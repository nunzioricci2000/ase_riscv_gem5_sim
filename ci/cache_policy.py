#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Created in the personal fork on 2026-10-28: avoid uploading duplicate caches and expose storage pressure.
"""Save new compilation work; do not evict other targets by duplicating a cache hit."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

from build import gem5_work


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cache', type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    timestamp = datetime.now(timezone.utc).isoformat(timespec='milliseconds')
    save, reason = decision(args.output)
    report = dict(started_at=timestamp, save=save, reason=reason, groups=inventory(args.cache))
    report.update(finished_at=datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
                  wall_seconds=time.monotonic() - started)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'cache-storage.json').write_text(json.dumps(report, indent=2) + '\n')
    if os.getenv('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
            stream.write('save=' + str(save).lower() + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
