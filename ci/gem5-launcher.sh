#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# Created in the personal fork on 2026-10-27: relocatable engine entry point.
set -euo pipefail
bundle="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONHOME="$bundle/python"
export PYTHONNOUSERSITE=1
export PYTHONPATH="$bundle/gem5/configs"
export LD_LIBRARY_PATH="$bundle/python/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export DYLD_LIBRARY_PATH="$bundle/python/lib${DYLD_LIBRARY_PATH:+:$DYLD_LIBRARY_PATH}"
exec "$bundle/gem5/bin/gem5.opt" "$@"
