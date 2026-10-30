#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Created in the personal fork on 2026-10-30: prepare auditable upstream integration PRs without executing incoming code or publishing releases.
"""Run only from the trusted default branch. All merges use a disposable clone."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

PROTECTED = ('.github', 'AGENTS.md', 'README.md', 'FORK.md', 'INSTALLATION.md',
             'DEVELOPING.md', 'VERSIONING.md', 'RELEASES.md', 'DISTRIBUTION.md',
             'FORK.json', 'FORK.json.license', '.gitmodules', 'ase_studio')
REPORT = 'UPSTREAM_INTEGRATION.md'


def command(args, cwd=None, check=True):
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if check and result.returncode:
        raise RuntimeError(f'{args[0]} failed: {result.stderr[-3000:]}')
    return result


def git(repo, *args, check=True):
    return command(['git', '-c', 'core.hooksPath=/dev/null', *args], cwd=repo, check=check)


def api(endpoint, data=None):
    args = ['gh', 'api', endpoint]
    if data is None:
        return json.loads(command(args).stdout)
    result = subprocess.run(args + ['--input', '-'], input=json.dumps(data), text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError('GitHub request failed: ' + result.stderr[-2000:])
    return json.loads(result.stdout)


def ancestor(repo, first, second):
    return git(repo, 'merge-base', '--is-ancestor', first, second, check=False).returncode == 0


def report_text(upstream, tips, commits, protected, conflicts):
    date = datetime.now(timezone.utc).date().isoformat()
    lines = ['<!-- SPDX-License-Identifier: GPL-2.0-only -->',
             f'<!-- Created in the personal fork on {date}: record a proposed upstream integration. -->',
             '# Upstream integration', '', 'Integration: ' + ('BLOCKED' if conflicts else 'READY FOR TESTS'), '',
             f'Original repository: https://github.com/{upstream}', '',
             'Revisions: ' + ', '.join(tips), '',
             'This is a draft. No automatic merge, SDK replacement or release is authorized.', '',
             '## Incoming commits', '', *['- ' + line for line in commits], '',
             '## Fork-owned paths retained', '', *['- `' + name + '`' for name in protected], '']
    if conflicts:
        lines += ['## Integration incomplete', '',
                  'This branch contains only this report. The merge was aborted; no incoming feature is claimed as integrated.',
                  'Resolve and test the actual upstream merge before removing the BLOCKED marker.', '',
                  *['- `' + name + '`' for name in conflicts]]
    else:
        lines += ['## Required review', '',
                  '- Review preserved documentation/workflow differences and update fork-only guidance where needed.',
                  '- Keep the upstream VERSION; review Abate revision and release sequence before a release.',
                  '- Run the ordinary pull-request checks and inspect functional changes.',
                  '- Keep the personal Studio submodule pin; update it only to a published, tested fork commit.']
    return '\n'.join(lines) + '\n'


def prepare(repo, upstream, tips):
    """Merge actual commits or leave a report-only branch; never record discarded conflicts as merged."""
    original = git(repo, 'rev-parse', 'HEAD').stdout.strip()
    incoming = []
    protected = set()
    for tip in tips:
        incoming += git(repo, 'log', '--format=%h %s', f'{original}..{tip}').stdout.splitlines()
        paths = git(repo, 'diff', '--name-only', f'{original}...{tip}').stdout.splitlines()
        protected.update(p for p in paths if any(p == rule or p.startswith(rule + '/') for rule in PROTECTED))
        # A changed upstream license needs review, not an automatically preserved or replaced license.
        if 'LICENSE' in paths:
            conflicts = ['LICENSE (upstream license change requires review)']
            break
        merged = git(repo, 'merge', '--no-commit', '--no-ff', tip, check=False)
        unmerged = git(repo, 'diff', '--name-only', '--diff-filter=U').stdout.splitlines()
        for path in sorted(protected):
            exists = git(repo, 'cat-file', '-e', f'{original}:{path}', check=False).returncode == 0
            if exists:
                git(repo, 'restore', '--source', original, '--staged', '--worktree', '--', path)
            else:
                git(repo, 'rm', '-f', '--ignore-unmatch', '--', path)
        conflicts = git(repo, 'diff', '--name-only', '--diff-filter=U').stdout.splitlines()
        if merged.returncode and not unmerged:
            conflicts = ['Merge failed: ' + merged.stderr[-1000:]]
        if conflicts:
            break
        git(repo, 'commit', '--no-verify', '-m', 'Integrate upstream ' + tip)
    if conflicts:
        git(repo, 'merge', '--abort', check=False)
        # This reset is confined to a disposable clone, never a user checkout or remote branch.
        git(repo, 'reset', '--hard', original)
    text = report_text(upstream, tips, list(dict.fromkeys(incoming)), sorted(protected), conflicts)
    (repo / REPORT).write_text(text)
    git(repo, 'add', REPORT)
    git(repo, 'commit', '--no-verify', '-m', 'Record upstream integration review' + (' (blocked)' if conflicts else ''))
    return text, bool(conflicts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstream', required=True)
    parser.add_argument('--fork', required=True)
    parser.add_argument('--base', default='develop', choices=['develop'])
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    for name in (args.upstream, args.fork):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', name):
            raise ValueError('Invalid repository name')
    expected = {'nunzioricci2000/ase-studio': 'cad-polito-it/ase-studio',
                'nunzioricci2000/ase_riscv_gem5_sim': 'cad-polito-it/ase_riscv_gem5_sim'}
    if expected.get(args.fork) != args.upstream:
        raise ValueError('Repository pair is not allowlisted')
    pulls = api(f'repos/{args.fork}/pulls?state=open&base=develop&per_page=100')
    if any(p['head']['ref'].startswith('feature/upstream-') for p in pulls):
        print('An upstream integration PR is already open; pending changes will be reconsidered after it closes.')
        return
    with tempfile.TemporaryDirectory(prefix='ase-upstream-') as directory:
        repo = Path(directory)
        git(repo, 'init')
        git(repo, 'config', 'user.name', 'ASE upstream sync')
        git(repo, 'config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com')
        git(repo, 'remote', 'add', 'origin', f'https://github.com/{args.fork}.git')
        git(repo, 'remote', 'add', 'upstream', f'https://github.com/{args.upstream}.git')
        git(repo, 'fetch', '--no-tags', 'origin', args.base)
        git(repo, 'checkout', '-b', 'integration', 'FETCH_HEAD')
        git(repo, 'fetch', '--no-tags', 'upstream', 'main')
        tips = [git(repo, 'rev-parse', 'FETCH_HEAD').stdout.strip()]
        releases = api(f'repos/{args.upstream}/releases?per_page=100')
        stable = sorted((r for r in releases if not r['draft'] and not r['prerelease']),
                        key=lambda r: r['published_at'], reverse=True)
        if stable:
            tag = stable[0]['tag_name']
            git(repo, 'check-ref-format', 'refs/tags/' + tag)
            git(repo, 'fetch', '--no-tags', 'upstream', 'refs/tags/' + tag)
            release = git(repo, 'rev-parse', 'FETCH_HEAD^{commit}').stdout.strip()
            if not ancestor(repo, release, tips[0]):
                tips.append(release)
        tips = [tip for tip in tips if not ancestor(repo, tip, 'HEAD')]
        if not tips:
            print('No upstream changes to integrate.')
            return
        branch = 'feature/upstream-' + hashlib.sha256(' '.join(tips).encode()).hexdigest()[:16]
        old = api(f'repos/{args.fork}/pulls?state=all&head={args.fork.split("/")[0]}:{branch}&per_page=100')
        if old:
            print('This proposal was already submitted; preserving the previous review decision.')
            return
        # Recover a push that succeeded before a transient PR-creation failure.
        existing = git(repo, 'ls-remote', '--heads', 'origin', 'refs/heads/' + branch).stdout.strip()
        if existing:
            git(repo, 'fetch', '--no-tags', 'origin', 'refs/heads/' + branch)
            body = git(repo, 'show', 'FETCH_HEAD:' + REPORT).stdout
            if not all(tip in body for tip in tips):
                raise RuntimeError('Existing proposal branch has unexpected provenance; preserving it')
            blocked = 'Integration: BLOCKED' in body
        else:
            git(repo, 'branch', '-m', branch)
            body, blocked = prepare(repo, args.upstream, tips)
        if args.dry_run:
            print(body)
            return
        # Credentials are used only for the push, never to execute incoming project code.
        if not existing:
            git(repo, '-c', 'credential.helper=', '-c', 'credential.helper=!gh auth git-credential',
                'push', 'origin', f'HEAD:refs/heads/{branch}')
        pr = api(f'repos/{args.fork}/pulls', {'base': args.base, 'head': branch, 'draft': True,
                 'title': ('Resolve upstream integration conflicts' if blocked else 'Integrate upstream updates') + ' (' + tips[0][:7] + ')',
                 'body': body})
        print(pr['html_url'])


if __name__ == '__main__':
    main()
