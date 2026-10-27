#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Created in the personal fork on 2026-10-27: reuse verified SDKs independently of Actions cache eviction.
"""Fetch an earlier source-paired SDK only when a component identity matches."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile


def api(route):
    return subprocess.check_output(['gh', 'api', route])


def matching(report, requested):
    return (report.get('status') == 'succeeded'
            and any(report.get('component_keys', {}).get(name) == key
                    for name, key in requested.items()))


def checksum(path):
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            sha.update(block)
    return sha.hexdigest()


def main():
    output, destination, target = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    repo = os.environ.get('GITHUB_REPOSITORY')
    if not repo or not os.environ.get('GH_TOKEN'):
        print('SDK reuse unavailable outside authenticated GitHub Actions')
        return
    requested = json.loads((output / 'component-keys.json').read_text())
    cache = Path(sys.argv[4])
    if all((cache / 'components' / name / key / 'manifest.json').is_file()
           for name, key in requested.items()):
        print('All components are present in the restored cache; no SDK download needed')
        return
    branch = os.environ.get('GITHUB_REF_NAME')
    indices = json.loads(api(f'repos/{repo}/actions/artifacts?name=engine-index-{target}&per_page=100'))['artifacts']
    for index in indices[:10]:
        run = index.get('workflow_run', {})
        if index['expired'] or run.get('head_branch') not in ('main', branch):
            continue
        if str(run.get('id')) == os.environ.get('GITHUB_RUN_ID'):
            continue
        with zipfile.ZipFile(io.BytesIO(api(f'repos/{repo}/actions/artifacts/{index["id"]}/zip'))) as archive:
            report = json.loads(archive.read('report.json'))
        if not matching(report, requested):
            continue
        artifacts = json.loads(api(f'repos/{repo}/actions/runs/{run["id"]}/artifacts?per_page=100'))['artifacts']
        artifact = next((a for a in artifacts if a['name'] == f'engine-{target}' and not a['expired']), None)
        if not artifact:
            continue
        name = f'ase-engine-{target}.tar.gz'
        expected = next((a for a in report['artifacts'] if a['name'] == name), None)
        if not expected:
            continue
        destination.mkdir(parents=True, exist_ok=True)
        download = destination / 'download.zip'
        with download.open('wb') as stream:
            subprocess.run(['gh', 'api', f'repos/{repo}/actions/artifacts/{artifact["id"]}/zip'], stdout=stream, check=True)
        try:
            with zipfile.ZipFile(download) as archive, archive.open(name) as source, (destination / name).open('wb') as binary:
                import shutil
                shutil.copyfileobj(source, binary, 1024 * 1024)
        finally:
            download.unlink(missing_ok=True)
        binary = destination / name
        if binary.stat().st_size != expected['bytes'] or checksum(binary) != expected['sha256']:
            binary.unlink()
            raise ValueError('Previous SDK failed checksum validation')
        record = dict(run_id=run['id'], artifact_id=artifact['id'], archive=name,
                      component_keys=report['component_keys'], sha256=expected['sha256'])
        (destination / 'reuse.json').write_text(json.dumps(record, indent=2))
        (output / 'artifact-reuse.json').write_text(json.dumps(record, indent=2))
        print(f'Verified previous SDK from run {run["id"]}; matching components: ' +
              ', '.join(n for n, k in requested.items() if report['component_keys'].get(n) == k))
        return
    print('No retained SDK has matching component inputs; use object/component cache or build')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, subprocess.CalledProcessError) as error:
        # A download outage or corrupt archive must fall back to building, never
        # turn an optional speedup into a dependency on retained GitHub artifacts.
        print(f'Previous SDK unavailable; building from verified sources instead: {error}', file=sys.stderr)
