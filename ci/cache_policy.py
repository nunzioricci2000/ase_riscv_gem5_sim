#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Created in the personal fork on 2026-10-28: avoid uploading duplicate caches and expose storage pressure.
# Modified in the personal fork on 2026-10-28: compact completed host binaries in component caches without touching SCons objects.
"""Save new compilation work; do not evict other targets by duplicating a cache hit."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import tempfile
import time

from build import gem5_work
from compact import compact_runtime
from components import restore, save as save_component


def decision(output):
    path = output / 'report.json'
    if not path.exists():
        return True, 'No build report: conservatively preserve possible partial work'
    report = json.loads(path.read_text())
    events = output / 'component-cache.jsonl'
    records = [json.loads(line) for line in events.read_text().splitlines()] if events.exists() else report.get('component_cache', [])
    if any(item.get('action') == 'save' and item.get('status') == 'saved' for item in records):
        return True, 'A newly built component was saved'
    work = report.get('gem5_work', {})
    for log in output.glob('*-gem5-build.log'):
        measured = gem5_work(log)
        if measured['compile_actions'] or measured['link_actions']:
            work = measured
            break
    if work.get('compile_actions', 0) or work.get('link_actions', 0):
        return True, 'SCons performed compilation or linking, including partial work'
    if report.get('status') == 'running':
        return True, 'Interrupted report: conservatively preserve possible partial work'
    return False, 'No new compiled output; the existing cache already contains this work'


def inventory(cache):
    result = {}
    if not cache.exists():
        return result
    for directory, _, names in os.walk(cache, followlinks=False):
        for name in names:
            path = Path(directory) / name
            if path.is_symlink():
                continue
            relative = path.relative_to(cache)
            group = '/'.join(relative.parts[:2]) if len(relative.parts) > 2 else relative.parts[0]
            row = result.setdefault(group, dict(files=0, bytes=0))
            row['files'] += 1
            row['bytes'] += path.stat().st_size
    return result


def compact_components(cache, output):
    """Shrink verified completed components; leave live builds and object caches intact."""
    results = []
    if platform.system() != 'Linux':
        return results
    for component in ('toolchain', 'gem5'):
        for manifest_path in sorted((cache / 'components' / component).glob('*/manifest.json')):
            if manifest_path.is_symlink() or not manifest_path.resolve().is_relative_to(cache.resolve()):
                continue
            manifest = json.loads(manifest_path.read_text())
            if manifest.get('host_debug_compacted'):
                continue
            entry = manifest_path.parent
            archive = entry / 'component.tar.gz'
            before = archive.stat().st_size
            with tempfile.TemporaryDirectory(prefix='ase-component-compact-', dir=cache.parent) as directory:
                work = Path(directory)
                payload = work / 'staged/payload'
                payload.parent.mkdir()
                if not restore(entry, payload):
                    raise ValueError(f'Cannot compact a corrupt cached {component}')
                measured = compact_runtime(payload.parent, output / f'cache-compaction-{component}.json')
                save_component(entry, payload)
            manifest = json.loads(manifest_path.read_text())
            manifest['host_debug_compacted'] = True
            manifest_path.write_text(json.dumps(manifest) + '\n')
            results.append(dict(component=component, archive_bytes_before=before,
                                archive_bytes_after=archive.stat().st_size,
                                host_debug_bytes_removed=measured['saved_bytes']))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cache', type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    timestamp = datetime.now(timezone.utc).isoformat(timespec='milliseconds')
    args.output.mkdir(parents=True, exist_ok=True)
    save, reason = decision(args.output)
    before = inventory(args.cache)
    compacted = compact_components(args.cache, args.output)
    if compacted and not save:
        save, reason = True, 'Replace an oversized cache with compacted completed host binaries'
    report = dict(started_at=timestamp, save=save, reason=reason, groups=inventory(args.cache),
                  groups_before=before, component_compaction=compacted)
    report.update(finished_at=datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
                  wall_seconds=time.monotonic() - started)
    (args.output / 'cache-storage.json').write_text(json.dumps(report, indent=2) + '\n')
    if os.getenv('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
            stream.write('save=' + str(save).lower() + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
