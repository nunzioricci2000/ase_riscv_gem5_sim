#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Created in the personal fork on 2026-10-27: apply runtime fixes without replacing local edits.
"""Apply the shared runtime patch once; reject incompatible source contexts."""
from pathlib import Path
import subprocess
import sys


def apply(source, patch=None):
    patch = Path(patch) if patch else Path(__file__).with_name("gem5-runtime.patch")
    command = ["git", "apply", "--whitespace=error"]
    def check(*args):
        return subprocess.run(command + list(args) + [str(patch)], cwd=source,
                              capture_output=True, text=True)
    if check("--reverse", "--check").returncode == 0:
        print("gem5 runtime fixes already applied")
        return
    result = check("--check")
    if result.returncode:
        raise RuntimeError("gem5 runtime patch conflicts with this source; local changes preserved:\n" + result.stderr)
    subprocess.run(command + [str(patch)], cwd=source, check=True)
    print("Applied gem5 entry-register and syscall-drain fixes")


if __name__ == "__main__":
    apply(Path(sys.argv[1]).resolve())
