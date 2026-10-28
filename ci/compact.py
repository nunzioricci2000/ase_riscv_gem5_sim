#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Created in the personal fork on 2026-10-28: remove host ELF debug information only from staged runtime copies.
"""Reduce runtime download size without rebuilding or changing cached components."""
from datetime import datetime, timezone
import json
import os
import platform
import stat
import subprocess
import time


def compact_runtime(bundle, output):
    started = time.monotonic()
    report = dict(started_at=datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
                  operation='strip --strip-debug', files=[], bytes_before=0, bytes_after=0)
    if platform.system() != 'Linux':
        report.update(status='not_applicable', reason='Only host ELF debug sections are removed')
    else:
        machine = {'x86_64': 62, 'aarch64': 183}.get(platform.machine())
        if machine is None:
            raise ValueError('Unsupported ELF host architecture')
        bundle = bundle.resolve()
        for path in sorted(bundle.rglob('*')):
            if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(bundle):
                continue
            with path.open('rb') as stream:
                header = stream.read(20)
            if len(header) != 20 or header[:4] != b'\x7fELF' or header[5] not in (1, 2):
                continue
            byteorder = 'little' if header[5] == 1 else 'big'
            kind = int.from_bytes(header[16:18], byteorder)
            arch = int.from_bytes(header[18:20], byteorder)
            # Preserve RISC-V target objects/libraries, static archives, scripts,
            # dynamic exports and ordinary symbols used in crash backtraces.
            if kind not in (2, 3) or arch != machine:
                continue
            before = path.stat()
            temporary = path.with_name(path.name + '.strip-partial')
            if temporary.exists() or temporary.is_symlink():
                raise ValueError(f'Refusing to overwrite {temporary}')
            try:
                subprocess.run(['strip', '--strip-debug', '-o', str(temporary), str(path)], check=True)
                temporary.chmod(stat.S_IMODE(before.st_mode))
                after = temporary.stat().st_size
                if after < before.st_size:
                    # Replacing a staged file also protects any external hard link.
                    os.replace(temporary, path)
                    report['files'].append(dict(path=str(path.relative_to(bundle)),
                                                before_bytes=before.st_size, after_bytes=after))
                else:
                    after = before.st_size
                report['bytes_before'] += before.st_size
                report['bytes_after'] += after
            finally:
                temporary.unlink(missing_ok=True)
        report['status'] = 'succeeded'
    report.update(finished_at=datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
                  wall_seconds=time.monotonic() - started,
                  saved_bytes=report['bytes_before'] - report['bytes_after'])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + '\n')
    return report
