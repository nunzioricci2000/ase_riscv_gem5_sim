#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Created in the personal fork on 2026-10-27: reuse verified SDKs independently of Actions cache eviction.
# Modified in the personal fork on 2026-10-27: prefer complete SDK/source pairs and support older unindexed artifacts.
"""Recover verified components or a complete SDK; always test the resulting binaries."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ANCESTORS = {}


def api(route):
    return subprocess.check_output(['gh', 'api', route])


def matching(report, requested, target):
    return (report.get('status') == 'succeeded'
            and report.get('target', {}).get('id') == target
            and any(report.get('component_keys', {}).get(name) == key
                    for name, key in requested.items()))


def complete_match(report, requested, bundle_key):
    return (bool(bundle_key) and report.get('bundle_key') == bundle_key
            and report.get('component_keys') == requested)


def checksum(path):
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            sha.update(block)
    return sha.hexdigest()


def unpack_verified(download, destination, target, requested, bundle_key):
    """Trust the report inside the downloaded artifact, then verify actual bytes."""
    with zipfile.ZipFile(download) as archive:
        report = json.loads(archive.read('report.json'))
        if not matching(report, requested, target):
            return None
        binary = f'ase-engine-{target}.tar.gz'
        sources = f'ase-engine-{target}-sources.tar.gz'
        entries = {item['name']: item for item in report['artifacts']}
        if not {binary, sources} <= entries.keys() or not {binary, sources} <= set(archive.namelist()):
            raise ValueError('Previous SDK does not have its corresponding source archive')
        whole = complete_match(report, requested, bundle_key)
        selected = (binary, sources) if whole else (binary,)
        destination.mkdir(parents=True, exist_ok=True)
        for name in selected:
            temporary = destination / (name + '.partial')
            try:
                with archive.open(name) as source, temporary.open('wb') as stream:
                    shutil.copyfileobj(source, stream, 1024 * 1024)
                if temporary.stat().st_size != entries[name]['bytes'] or checksum(temporary) != entries[name]['sha256']:
                    raise ValueError(f'Previous SDK checksum mismatch: {name}')
                temporary.replace(destination / name)
            finally:
                temporary.unlink(missing_ok=True)
        return dict(archive=binary, component_keys=report['component_keys'],
                    sha256=entries[binary]['sha256'], whole_sdk=whole,
                    bundle_key=report.get('bundle_key'),
                    archives={name: entries[name] for name in selected})


def available(artifact, branch, repo=None):
    run = artifact.get('workflow_run', {})
    if artifact['expired'] or str(run.get('id')) == os.environ.get('GITHUB_RUN_ID'):
        return False
    if not run.get('repository_id') or run.get('head_repository_id') != run['repository_id']:
        return False
    if run.get('head_branch') in ('main', branch):
        return True
    # Promote tested feature artifacts only after their exact commit was merged.
    # Fork PR artifacts cannot qualify through this path.
    head, current = run.get('head_sha'), os.environ.get('GITHUB_SHA')
    if not repo or not head or not current:
        return False
    key = (repo, head, current)
    if key not in ANCESTORS:
        try:
            comparison = json.loads(api(f'repos/{repo}/compare/{head}...{current}'))
            ANCESTORS[key] = (comparison.get('status') in ('ahead', 'identical')
                              and comparison.get('merge_base_commit', {}).get('sha') == head)
        except (ValueError, subprocess.CalledProcessError):
            ANCESTORS[key] = False
    return ANCESTORS[key]


def recover(repo, artifact, run_id, output, destination, target, requested, bundle_key):
    destination.mkdir(parents=True, exist_ok=True)
    download = destination / 'download.zip'
    try:
        with download.open('wb') as stream:
            subprocess.run(['gh', 'api', f'repos/{repo}/actions/artifacts/{artifact["id"]}/zip'], stdout=stream, check=True)
        record = unpack_verified(download, destination, target, requested, bundle_key)
    finally:
        download.unlink(missing_ok=True)
    if record is None:
        return False
    record.update(run_id=run_id, artifact_id=artifact['id'])
    (destination / 'reuse.json').write_text(json.dumps(record, indent=2))
    (output / 'artifact-reuse.json').write_text(json.dumps(record, indent=2))
    print(f'Verified SDK from run {run_id}; whole SDK reuse: {record["whole_sdk"]}; matching components: ' +
          ', '.join(n for n, k in requested.items() if record['component_keys'].get(n) == k))
    return True


def main():
    output, destination, target = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    repo = os.environ.get('GITHUB_REPOSITORY')
    if not repo or not os.environ.get('GH_TOKEN'):
        print('SDK reuse unavailable outside authenticated GitHub Actions')
        return
    requested = json.loads((output / 'component-keys.json').read_text())
    bundle_key = (output / 'bundle-key.txt').read_text().strip()
    cache = Path(sys.argv[4])
    all_cached = all((cache / 'components' / name / key / 'manifest.json').is_file()
                     for name, key in requested.items())
    branch = os.environ.get('GITHUB_REF_NAME')
    indices = json.loads(api(f'repos/{repo}/actions/artifacts?name=engine-index-{target}&per_page=100'))['artifacts']
    candidates = []
    for index in indices[:10]:
        if not available(index, branch, repo):
            continue
        with zipfile.ZipFile(io.BytesIO(api(f'repos/{repo}/actions/artifacts/{index["id"]}/zip'))) as archive:
            report = json.loads(archive.read('report.json'))
        if not matching(report, requested, target):
            continue
        whole = complete_match(report, requested, bundle_key)
        if whole or not all_cached:
            score = (whole, sum(report['component_keys'].get(n) == k for n, k in requested.items()))
            candidates.append((score, index['workflow_run']['id']))
    seen = set()
    for _, run_id in sorted(candidates, key=lambda c: c[0], reverse=True):
        artifacts = json.loads(api(f'repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100'))['artifacts']
        artifact = next((a for a in artifacts if a['name'] == f'engine-{target}' and not a['expired']), None)
        if artifact:
            seen.add(artifact['id'])
            if recover(repo, artifact, run_id, output, destination, target, requested, bundle_key):
                return
    if all_cached:
        print('No identical complete SDK; all components are already in the restored cache')
        return
    # Transitional support for builds made before small indexes were introduced.
    # Only three candidates are downloaded; mismatched inputs are never relabelled.
    legacy = json.loads(api(f'repos/{repo}/actions/artifacts?name=engine-{target}&per_page=100'))['artifacts']
    legacy = [a for a in legacy if a['id'] not in seen and available(a, branch, repo)]
    for artifact in legacy[:3]:
        if recover(repo, artifact, artifact['workflow_run']['id'], output, destination,
                   target, requested, bundle_key):
            return
    print('No retained SDK has matching inputs; use object/component cache or build')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, subprocess.CalledProcessError) as error:
        print(f'Previous SDK unavailable; building from verified sources instead: {error}', file=sys.stderr)
