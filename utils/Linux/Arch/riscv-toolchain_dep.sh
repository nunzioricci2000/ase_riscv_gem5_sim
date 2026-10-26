#!/usr/bin/env bash
set -euo pipefail

##############################################################################

if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root" 
   exit 1
fi

##############################################################################

if [[ "${ASE_PACKAGE_INDEX_READY:-0}" != 1 ]]; then
    pacman -Syu --noconfirm
fi

# Install RISC-V toolchain dependencies for Arch Linux
pacman -S --needed --noconfirm autoconf automake curl python python-pip python-tomli libmpc mpfr gmp gawk base-devel bison flex texinfo gperf libtool patchutils bc zlib expat ninja git cmake glib2 libslirp

exit 0
