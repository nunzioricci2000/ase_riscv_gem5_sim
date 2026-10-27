#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# Created in the personal fork on 2026-10-27: isolated engine build stages.
# Modified in the personal fork on 2026-10-27: reuse components and fix portable SCons bootstrap.
set -euo pipefail
: "${ASE_REPO:?}" "${ASE_WORK:?}" "${ASE_OUTPUT:?}" "${ASE_FAMILY:?}" "${BUILD_JOBS:?}"
sources="$ASE_WORK/sources"
prefix="$ASE_WORK/prefix"
mkdir -p "$sources" "$prefix" "$ASE_OUTPUT"

if [[ "$ASE_FAMILY" == macos ]] && command -v brew >/dev/null; then
    brew_root=$(brew --prefix)
    export PATH="$brew_root/opt/make/libexec/gnubin:$brew_root/opt/gnu-sed/libexec/gnubin:$brew_root/opt/texinfo/bin:$brew_root/opt/bison/bin:$PATH"
    export CPPFLAGS="-I$brew_root/include"
    export LDFLAGS="-L$brew_root/lib"
    export PKG_CONFIG_PATH="$brew_root/lib/pkgconfig:$brew_root/opt/openssl@3/lib/pkgconfig"
    export CC=clang CXX=clang++
fi
export LD_LIBRARY_PATH="$prefix/python/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export DYLD_LIBRARY_PATH="$prefix/python/lib${DYLD_LIBRARY_PATH:+:$DYLD_LIBRARY_PATH}"
export PYTHONNOUSERSITE=1

lock_value() {
    python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d[sys.argv[2]][sys.argv[3]])' \
        "$ASE_REPO/ci/sources.lock.json" "$1" "$2"
}

checkout() {
    local component="$1" url revision
    url=$(lock_value "$component" url)
    revision=$(lock_value "$component" commit)
    git init "$sources/$component"
    git -C "$sources/$component" remote add origin "$url"
    git -C "$sources/$component" fetch --depth 1 origin "$revision"
    git -C "$sources/$component" checkout --detach FETCH_HEAD
    [[ "$(git -C "$sources/$component" rev-parse HEAD)" == "$revision" ]]
}

case "${1:?stage required}" in
dependencies)
    case "$ASE_FAMILY" in
    debian)
        export DEBIAN_FRONTEND=noninteractive
        apt-get update
        apt-get install -y --no-install-recommends build-essential git ca-certificates curl \
            autoconf automake autotools-dev libtool gawk bison flex texinfo patchutils bc gperf \
            libmpc-dev libmpfr-dev libgmp-dev zlib1g-dev libexpat1-dev libssl-dev libffi-dev \
            libbz2-dev liblzma-dev libsqlite3-dev libreadline-dev libncurses-dev \
            python3 python3-pip python3-venv pkg-config m4 libprotobuf-dev protobuf-compiler \
            libprotoc-dev libgoogle-perftools-dev libboost-all-dev libhdf5-dev libpng-dev libelf-dev
        ;;
    fedora)
        dnf install -y gcc gcc-c++ make git ca-certificates curl autoconf automake libtool \
            gawk bison flex texinfo patchutils bc gperf gmp-devel mpfr-devel libmpc-devel \
            zlib-devel expat-devel openssl-devel libffi-devel bzip2-devel xz-devel \
            sqlite-devel readline-devel ncurses-devel python3 python3-pip pkgconf-pkg-config \
            m4 protobuf-devel protobuf-compiler gperftools-devel boost-devel hdf5-devel \
            libpng-devel elfutils-libelf-devel which diffutils findutils patch
        ;;
    arch)
        pacman -Syu --needed --noconfirm base-devel git ca-certificates curl python python-pip \
            gmp mpfr libmpc zlib expat openssl libffi bzip2 xz sqlite readline ncurses \
            patchutils bc gperf pkgconf protobuf gperftools boost hdf5 libpng libelf
        ;;
    macos)
        brew install autoconf automake libtool gawk gnu-sed make bison flex texinfo \
            gmp mpfr libmpc openssl@3 libffi xz sqlite readline pkgconf protobuf boost
        ;;
    *) echo "Unsupported package family: $ASE_FAMILY" >&2; exit 2 ;;
    esac
    if [[ "$GEM5_LINKER" == lld || "$GEM5_LINKER" == mold ]]; then
        case "$ASE_FAMILY" in
            debian) apt-get install -y "$GEM5_LINKER" ;;
            fedora) dnf install -y "$GEM5_LINKER" ;;
            arch) pacman -S --needed --noconfirm "$GEM5_LINKER" ;;
            macos) brew install "$GEM5_LINKER" ;;
        esac
    fi
    ;;
environment)
    python3 "$ASE_REPO/ci/package.py" environment
    ;;
fetch)
    checkout python
    checkout toolchain
    checkout gem5
    # Only these projects are used by the newlib build; never fetch QEMU/LLVM/glibc.
    git -C "$sources/toolchain" submodule update --init --depth 1 gcc binutils newlib gdb
    python3 "$ASE_REPO/ci/package.py" patch-gem5
    # Fetch the pinned source directly: distro pip versions can misread its metadata.
    mkdir -p "$sources/build-tools"
    curl --fail --location --retry 3 \
        'https://files.pythonhosted.org/packages/ec/5c/cc835a17633de8b260ec1a6e527b5c57f4975cee5949f49e57ad4d5fab4b/scons-4.8.0.tar.gz' \
        --output "$sources/build-tools/scons-4.8.0.tar.gz"
    python3 - "$ASE_REPO/ci/sources.lock.json" "$sources/build-tools" <<'PY'
import hashlib, json, pathlib, sys
lock = json.load(open(sys.argv[1]))
source = pathlib.Path(sys.argv[2]) / ('scons-' + lock['scons'] + '.tar.gz')
if hashlib.sha256(source.read_bytes()).hexdigest() != lock['scons_sha256']:
    raise SystemExit('SCons source checksum mismatch')
PY
    mkdir "$ASE_WORK/scons"
    tar -xf "$sources"/build-tools/scons-*.tar.gz --strip-components=1 -C "$ASE_WORK/scons"
    ;;
python-configure)
    if python3 "$ASE_REPO/ci/components.py" restore python; then
        touch "$ASE_WORK/python-restored"
        exit 0
    fi
    mkdir "$ASE_WORK/python-build"
    cd "$ASE_WORK/python-build"
    options=(--prefix="$prefix/python" --enable-shared --with-ensurepip=no)
    [[ "$ASE_FAMILY" != macos ]] || options+=(--with-openssl="$brew_root/opt/openssl@3")
    # No PGO/LTO: record a reproducible baseline with lower build cost.
    "$sources/python/configure" "${options[@]}"
    ;;
python-build)
    [[ ! -f "$ASE_WORK/python-restored" ]] || exit 0
    make -C "$ASE_WORK/python-build" -j "$BUILD_JOBS"
    make -C "$ASE_WORK/python-build" install
    "$prefix/python/bin/python3.10" -c 'import ssl, ctypes, zlib; print(ssl.OPENSSL_VERSION)'
    python3 "$ASE_REPO/ci/components.py" save python
    ;;
toolchain-configure)
    if python3 "$ASE_REPO/ci/components.py" restore toolchain; then
        touch "$ASE_WORK/toolchain-restored"
        exit 0
    fi
    mkdir "$ASE_WORK/toolchain-build"
    cd "$ASE_WORK/toolchain-build"
    options=(--prefix="$prefix/toolchain" --enable-multilib)
    if [[ "$ASE_PROFILE" == minimal ]]; then
        options+=(--with-multilib-generator='rv32imac-ilp32--;rv64gc-lp64d--' --disable-gdb)
    fi
    if [[ "$ASE_FAMILY" == macos ]]; then
        options+=(--with-gmp="$brew_root" --with-mpfr="$brew_root" --with-mpc="$brew_root")
    fi
    "$sources/toolchain/configure" "${options[@]}"
    ;;
toolchain-build)
    [[ ! -f "$ASE_WORK/toolchain-restored" ]] || exit 0
    make -C "$ASE_WORK/toolchain-build" -j "$BUILD_JOBS" newlib
    python3 "$ASE_REPO/ci/components.py" save toolchain
    ;;
gem5-build)
    if python3 "$ASE_REPO/ci/components.py" restore gem5; then exit 0; fi
    export PYTHON_CONFIG="$prefix/python/bin/python3.10-config"
    export PYTHONPATH="$ASE_WORK/scons"
    # A nonempty array also works with nounset in macOS's system Bash 3.2.
    options=(build/RISCV/gem5.opt -j "$BUILD_JOBS")
    [[ "$GEM5_LINKER" == default ]] || options+=("--linker=$GEM5_LINKER")
    if [[ -n "${ASE_CACHE:-}" ]]; then
        # System package changes invalidate object reuse even with a fixed source lock.
        fingerprint=$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$ASE_OUTPUT/packages.txt")
        options+=("M5_BUILD_CACHE=$ASE_CACHE/objects/$fingerprint")
    fi
    cd "$sources/gem5"
    if PYTHONHOME="$prefix/python" "$prefix/python/bin/python3.10" -m SCons "${options[@]}"; then
        :
    else
        code=$?
        # Preserve the actual configure/linker error, not just SCons's summary.
        if [[ -f build/RISCV/gem5.build/scons_config.log ]]; then
            cp build/RISCV/gem5.build/scons_config.log "$ASE_OUTPUT/gem5-scons-config.log"
            tail -n 90 "$ASE_OUTPUT/gem5-scons-config.log"
        fi
        exit "$code"
    fi
    python3 "$ASE_REPO/ci/components.py" save gem5
    ;;
stage|smoke|sources|archive)
    python3 "$ASE_REPO/ci/package.py" "$1"
    ;;
*) echo "Unknown phase: $1" >&2; exit 2 ;;
esac
