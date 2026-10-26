#!/bin/bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/install_build.sh"

##############################################################################

if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root" 
   exit 1
fi

##############################################################################

if [[ "${ASE_PACKAGE_INDEX_READY:-0}" != 1 ]]; then
    pacman -Syu --noconfirm
fi

# Install gem5 dependencies for Arch Linux
pacman -S --needed --noconfirm base-devel git m4 zlib protobuf gperftools python boost pkg-config python-virtualenv hdf5 capstone libpng libelf
# Explicit interpreter overrides are supplied with their own development files.
if [[ -z "${GEM5_PYTHON:-}" ]] &&
    { ! command -v python3.10 >/dev/null || ! command -v python3.10-config >/dev/null; }; then
    select_build_jobs
    build_user="${SUDO_USER:-$(logname)}"
    if [[ "${build_user}" == root ]]; then
        echo "Run the installer with sudo from your normal user account." >&2
        exit 1
    fi
    aur_dir="${WORK_DIR}/python310"
    if [[ ! -d "${aur_dir}" ]]; then
        runuser -u "${build_user}" -- git clone --depth 1 https://aur.archlinux.org/python310.git "${aur_dir}"
    fi
    # Command-line makepkg variables override makepkg.conf without editing it.
    # Existing package archives are reused by makepkg on a retry.
    runuser -u "${build_user}" -- bash -c \
        'set -e; cd "$1"; options=(-si --needed "MAKEFLAGS=-j$2");
         [[ "${3:-0}" != 1 ]] || options+=(--noconfirm);
         exec makepkg "${options[@]}"' bash "${aur_dir}" "${BUILD_JOBS}" "${ASE_INSTALL_NONINTERACTIVE:-0}"
fi

command -v "${GEM5_PYTHON:-python3.10}" >/dev/null

exit 0
