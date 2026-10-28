#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Modified in the personal fork on 2026-10-28: prove tzdata-only compatibility without discarding compiled components or SCons objects.
# Created in the personal fork on 2026-10-27: reuse verified SDKs independently of Actions cache eviction.
# Modified in the personal fork on 2026-10-27: prefer complete SDK/source pairs and support older unindexed artifacts.
# Modified in the personal fork on 2026-10-27: recover proven component identities from early cache reports.
# Modified in the personal fork on 2026-10-28: inspect legacy reports with partial downloads and request only missing components.
# Modified in the personal fork on 2026-10-28: refresh packaging from an existing source-paired SDK when every compiled component is unchanged.
# Modified in the personal fork on 2026-10-28: retry bounded GitHub transfers and continue past unavailable candidate artifacts.
"""Recover verified components or a complete SDK; always test the resulting binaries."""
import hashlib
from contextlib import nullcontext
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile

ANCESTORS = {}


def build_packages(data, target):
    """Only Debian-family timezone data is irrelevant to these compiled inputs."""
    if target.startswith(('debian-', 'ubuntu-')):
        return b''.join(line for line in data.splitlines(keepends=True)
                        if not line.startswith(b'tzdata\t'))
    return data


def compatible_report(archive, output, target):
    """Recompute old keys with current recipes; never trust package names alone."""
    report = json.loads(archive.read('report.json'))
    if (output is None or report.get('status') != 'succeeded'
            or report.get('target', {}).get('id') != target
            or 'packages.txt' not in archive.namelist()
            or not (output / 'environment.json').is_file()):
        return report
    if archive.getinfo('packages.txt').file_size > 2 * 1024 * 1024:
        raise ValueError('Package inventory is unexpectedly large')
    previous = archive.read('packages.txt')
    current = (output / 'packages.txt').read_bytes()
    if previous == current or build_packages(previous, target) != build_packages(current, target):
        return report
    environment = json.loads((output / 'environment.json').read_text())
    if not {'build_profile', 'gem5_linker'} <= environment.keys():
        return report
    from components import identity
    env = dict(ASE_TARGET=target, ASE_PROFILE=environment['build_profile'],
               GEM5_LINKER=environment['gem5_linker'])
    repo = Path(__file__).resolve().parent.parent
    previous_hash = hashlib.sha256(previous).hexdigest()
    current_hash = hashlib.sha256(current).hexdigest()
    keys = component_keys(report)
    translated = dict(keys)
    for component in ('python', 'toolchain', 'gem5'):
        expected = identity(component, repo, output, env, packages_hash=previous_hash)
        if keys.get(component) == expected:
            translated[component] = identity(component, repo, output, env)
    if translated == keys:
        return report
    return dict(report, component_keys=translated, original_component_keys=keys,
                package_compatibility=dict(ignored_packages=['tzdata'],
                                           previous_inventory_sha256=previous_hash,
                                           current_inventory_sha256=current_hash))


def migrate_object_cache(cache, record):
    """Retain signed SCons objects when only the timezone database changed."""
    compatibility = record.get('package_compatibility')
    if not compatibility:
        return
    previous = cache / 'objects' / compatibility['previous_inventory_sha256']
    current = cache / 'objects' / compatibility['current_inventory_sha256']
    if previous.is_dir() and not current.exists():
        previous.rename(current)
        compatibility['object_cache_migrated'] = True
        print('Retained SCons object namespace after verified tzdata-only change', flush=True)


def api(route, destination=None):
    """Retry transient transfer failures without accepting incomplete responses."""
    for attempt in range(3):
        try:
            # Reopen with wb on every attempt: never append to a partial download.
            with (destination.open('wb') if destination else nullcontext(subprocess.PIPE)) as stream:
                result = subprocess.run(['gh', 'api', route], stdout=stream,
                                        stderr=subprocess.PIPE, check=True,
                                        timeout=600 if destination else 60)
            return result.stdout
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            if attempt == 2:
                raise
            # Do not print redirect URLs or credentials from transport diagnostics.
            print(f'GitHub request failed ({type(error).__name__}); retry {attempt + 2}/3', flush=True)
            time.sleep(2 ** attempt)


def component_keys(report):
    if 'component_keys' in report:
        return report['component_keys']
    # Early incremental builds recorded identities in cache events only. A miss
    # does not prove which binary was installed; require a successful operation.
    keys = {}
    for event in report.get('component_cache', []):
        if (event.get('action'), event.get('status')) not in {
                ('save', 'saved'), ('restore', 'hit'), ('restore', 'artifact-hit')}:
            continue
        name, key = event['component'], event['key']
        if name in keys and keys[name] != key:
            raise ValueError(f'Ambiguous previous component identity: {name}')
        keys[name] = key
    return keys


def matching(report, requested, target):
    return (report.get('status') == 'succeeded'
            and report.get('target', {}).get('id') == target
            and any(component_keys(report).get(name) == key
                    for name, key in requested.items()))


def complete_match(report, requested, bundle_key):
    return (bool(bundle_key) and report.get('bundle_key') == bundle_key
            and component_keys(report) == requested)


def useful(report, requested, missing, bundle_key, target):
    return (matching(report, requested, target) and
            (component_keys(report) == requested or matching(report, missing, target)))


class RangeReader(io.RawIOBase):
    """Seek within an artifact ZIP without downloading its multi-gigabyte SDK."""
    def __init__(self, size, fetch):
        self.size, self.fetch, self.position, self.downloaded = size, fetch, 0, 0

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        position = offset + (0 if whence == 0 else self.position if whence == 1 else self.size)
        if position < 0:
            raise ValueError('Negative artifact offset')
        self.position = position
        return position

    def read(self, count=-1):
        count = self.size - self.position if count < 0 else min(count, self.size - self.position)
        if count <= 0:
            return b''
        if count > 2 * 1024 * 1024:
            raise ValueError('Artifact report or ZIP index is unexpectedly large')
        result = self.fetch(self.position, self.position + count - 1)
        if len(result) != count:
            raise ValueError('Incomplete artifact range')
        self.position += len(result)
        self.downloaded += len(result)
        return result


def inspect_legacy(repo, artifact, output=None, target=None):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    request = urllib.request.Request(
        f'https://api.github.com/repos/{repo}/actions/artifacts/{artifact["id"]}/zip',
        headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
                 'Accept': 'application/vnd.github+json'})
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=30):
            raise ValueError('Artifact API did not redirect')
    except urllib.error.HTTPError as response:
        if response.code != 302:
            raise ValueError(f'Artifact API returned HTTP {response.code}') from None
        url = response.headers['Location']
    if not url.startswith('https://'):
        raise ValueError('Artifact download must use HTTPS')

    def fetch(first, last):
        # The GitHub token is never forwarded to the signed storage URL.
        request = urllib.request.Request(url, headers={'Range': f'bytes={first}-{last}'})
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status != 206:
                raise ValueError('Artifact server does not support partial reads')
            header = response.headers.get('Content-Range', '')
            expected = f'bytes {first}-{last}/'
            if not header.startswith(expected):
                raise ValueError('Artifact server returned the wrong range')
            data = response.read(last - first + 2)
            if len(data) != last - first + 1:
                raise ValueError('Artifact range length mismatch')
            return data, int(header[len(expected):])
    _, size = fetch(0, 0)
    def span(first, last):
        data, total = fetch(first, last)
        if total != size:
            raise ValueError('Artifact size changed during inspection')
        return data
    reader = RangeReader(size, span)
    with zipfile.ZipFile(reader) as archive:
        if archive.getinfo('report.json').file_size > 2 * 1024 * 1024:
            raise ValueError('Artifact report is unexpectedly large')
        report = compatible_report(archive, output, target)
    print(f'Inspected legacy artifact {artifact["id"]}: {reader.downloaded + 1} downloaded bytes')
    return report


def checksum(path):
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            sha.update(block)
    return sha.hexdigest()


def unpack_verified(download, destination, target, requested, bundle_key, output=None):
    """Trust the report inside the downloaded artifact, then verify actual bytes."""
    with zipfile.ZipFile(download) as archive:
        report = compatible_report(archive, output, target)
        if not matching(report, requested, target):
            return None
        binary = f'ase-engine-{target}.tar.gz'
        sources = f'ase-engine-{target}-sources.tar.gz'
        entries = {item['name']: item for item in report['artifacts']}
        if not {binary, sources} <= entries.keys() or not {binary, sources} <= set(archive.namelist()):
            raise ValueError('Previous SDK does not have its corresponding source archive')
        whole = not report.get('package_compatibility') and complete_match(report, requested, bundle_key)
        refresh = not whole and component_keys(report) == requested
        selected = (binary, sources) if whole or refresh else (binary,)
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
        return dict(archive=binary, component_keys=component_keys(report),
                    sha256=entries[binary]['sha256'], whole_sdk=whole, refresh_sdk=refresh,
                    bundle_key=report.get('bundle_key'),
                    **({name: report[name] for name in ('package_compatibility', 'original_component_keys')}
                       if report.get('package_compatibility') else {}),
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
        except (ValueError, subprocess.SubprocessError):
            # A failed lookup proves nothing about ancestry. Another candidate
            # from this commit may succeed after the transient outage.
            return False
    return ANCESTORS[key]


def recover(repo, artifact, run_id, output, destination, target, requested, bundle_key, cache=None):
    destination.mkdir(parents=True, exist_ok=True)
    download = destination / 'download.zip'
    try:
        api(f'repos/{repo}/actions/artifacts/{artifact["id"]}/zip', download)
        record = unpack_verified(download, destination, target, requested, bundle_key, output)
    finally:
        download.unlink(missing_ok=True)
    if record is None:
        return False
    if cache is not None:
        migrate_object_cache(cache, record)
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
    missing = {name: key for name, key in requested.items()
               if not (cache / 'components' / name / key / 'manifest.json').is_file()}
    all_cached = not missing
    branch = os.environ.get('GITHUB_REF_NAME')
    indices = json.loads(api(f'repos/{repo}/actions/artifacts?name=engine-index-{target}&per_page=100'))['artifacts']
    candidates = []
    for index in indices[:10]:
        try:
            if not available(index, branch, repo):
                continue
            with zipfile.ZipFile(io.BytesIO(api(f'repos/{repo}/actions/artifacts/{index["id"]}/zip'))) as archive:
                report = compatible_report(archive, output, target)
            if not useful(report, requested, missing, bundle_key, target):
                continue
            whole = complete_match(report, requested, bundle_key)
            refresh = component_keys(report) == requested
            score = (whole, refresh, sum(component_keys(report).get(n) == k for n, k in missing.items()))
            candidates.append((score, index['workflow_run']['id']))
        except (OSError, ValueError, KeyError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
            print(f'Cannot inspect SDK index {index.get("id")}: {type(error).__name__}; trying other candidates')
    seen = set()
    for _, run_id in sorted(candidates, key=lambda c: c[0], reverse=True):
        try:
            artifacts = json.loads(api(f'repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100'))['artifacts']
            artifact = next((a for a in artifacts if a['name'] == f'engine-{target}' and not a['expired']), None)
            if artifact:
                seen.add(artifact['id'])
                if recover(repo, artifact, run_id, output, destination, target, requested, bundle_key, cache):
                    return
        except (OSError, ValueError, KeyError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
            print(f'Cannot recover SDK from run {run_id}: {type(error).__name__}; trying other candidates')
    if all_cached:
        print('No retained SDK with all matching components; use the restored component cache')
        return
    # Transitional support for builds made before small indexes were introduced.
    # Inspect metadata first; download only a source-paired SDK with useful inputs.
    legacy = json.loads(api(f'repos/{repo}/actions/artifacts?name=engine-{target}&per_page=100'))['artifacts']
    legacy = [a for a in legacy if a['id'] not in seen and available(a, branch, repo)]
    for artifact in legacy[:3]:
        try:
            report = inspect_legacy(repo, artifact, output, target)
            if not useful(report, requested, missing, bundle_key, target):
                continue
        except (OSError, ValueError, KeyError, zipfile.BadZipFile):
            print(f'Partial inspection unavailable for artifact {artifact["id"]}; checking the full archive')
        try:
            if recover(repo, artifact, artifact['workflow_run']['id'], output, destination,
                       target, requested, bundle_key, cache):
                return
        except (OSError, ValueError, KeyError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
            print(f'Cannot recover legacy SDK {artifact.get("id")}: {type(error).__name__}; trying other candidates')
    print('No retained SDK has matching inputs; use object/component cache or build')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
        print(f'Previous SDK unavailable; building from verified sources instead: {error}', file=sys.stderr)
