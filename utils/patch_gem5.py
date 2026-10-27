#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Created in the personal fork on 2026-10-27: apply runtime fixes without replacing local edits.
# Modified in the personal fork on 2026-10-27: independently apply and preflight the TimeBuffer initialization fix.
"""Apply the shared runtime patch once; reject incompatible source contexts."""
from pathlib import Path
import subprocess
import sys


def apply(source, patch=None):
    patches = [Path(patch)] if patch else [Path(__file__).with_name(name) for name in
                                         ("gem5-runtime.patch", "gem5-timebuffer.patch")]
    command = ["git", "apply", "--whitespace=error"]
    def check(path, *args):
        return subprocess.run(command + list(args) + [str(path)], cwd=source,
                              capture_output=True, text=True)
    pending = []
    for path in patches:
        if check(path, "--reverse", "--check").returncode == 0:
            print(f"{path.name} already applied")
            continue
        result = check(path, "--check")
        if result.returncode:
            raise RuntimeError(f"{path.name} conflicts with this source; local changes preserved:\n" + result.stderr)
        pending.append(path)
    for path in pending:
        subprocess.run(command + [str(path)], cwd=source, check=True)
        print(f"Applied {path.name}")


if __name__ == "__main__":
    apply(Path(sys.argv[1]).resolve())
