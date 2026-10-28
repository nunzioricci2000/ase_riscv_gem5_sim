#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Created in the personal fork on 2026-10-28: keep only the newly saved compatible target cache on the current branch.
"""Remove superseded caches only after confirming their replacement exists."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlencode


def superseded(records, key, prefix, ref):
    current = [item for item in records if item['key'] == key and item['ref'] == ref]
    if len(current) != 1 or current[0]['size_in_bytes'] <= 0 or not key.startswith(prefix):
        return []
    current = current[0]
    return [item for item in records if item['ref'] == ref and item['key'].startswith(prefix)
            and item['id'] != current['id'] and item['version'] == current['version']
            and datetime.fromisoformat(item['created_at'].replace('Z', '+00:00'))
            < datetime.fromisoformat(current['created_at'].replace('Z', '+00:00'))]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--key', required=True)
    parser.add_argument('--prefix', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    repo, ref = os.environ['GITHUB_REPOSITORY'], os.environ['GITHUB_REF']
    endpoint = f'repos/{repo}/actions/caches'
    query = urlencode(dict(key=args.prefix, ref=ref, per_page=100))
    pages = json.loads(subprocess.check_output(['gh', 'api', '--paginate', '--slurp', endpoint + '?' + query], text=True))
    records = [item for page in pages for item in page['actions_caches']]
    report = dict(started_at=datetime.now(timezone.utc).isoformat(), replacement_key=args.key, ref=ref, deleted=[])
    try:
        for item in superseded(records, args.key, args.prefix, ref):
            subprocess.run(['gh', 'api', '--method', 'DELETE', endpoint + '/' + str(item['id'])], check=True)
            report['deleted'].append(dict(id=item['id'], key=item['key'], bytes=item['size_in_bytes']))
    finally:
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        args.output.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
