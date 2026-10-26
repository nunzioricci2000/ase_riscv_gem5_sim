#!/usr/bin/env bash
set -euo pipefail

##############################################################################

if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root" 
   exit 1
fi

##############################################################################

if [[ "${ASE_PACKAGE_INDEX_READY:-0}" != 1 ]]; then
    apt-get update
fi

apt-get install autoconf automake autotools-dev curl python3 python3-pip python3-tomli libmpc-dev libmpfr-dev libgmp-dev gawk build-essential bison flex texinfo gperf libtool patchutils bc zlib1g-dev libexpat-dev ninja-build git cmake libglib2.0-dev libslirp-dev -y

exit 0
