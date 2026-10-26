#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root" >&2
    exit 1
fi

if [[ "${ASE_PACKAGE_INDEX_READY:-0}" != 1 ]]; then
    apt-get update
fi

# Only build/runtime dependencies. SCons is installed in the build environment;
# formatter, documentation and type-checker packages are not needed to compile.
apt-get install -y build-essential git m4 zlib1g-dev libprotobuf-dev \
    protobuf-compiler libprotoc-dev libgoogle-perftools-dev libboost-all-dev \
    pkg-config libhdf5-dev libcapstone-dev libpng-dev libelf-dev python3-virtualenv

if [[ -z "${GEM5_PYTHON:-}" ]]; then
    if ! apt-cache show python3.10-dev >/dev/null 2>&1; then
        apt-get install -y software-properties-common
        add-apt-repository --no-update -y ppa:deadsnakes/ppa
        apt-get update
    fi
    apt-get install -y python3.10 python3.10-dev python3.10-venv
fi
