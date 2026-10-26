#!/usr/bin/env bash
# Shared build policy for the Ubuntu, Fedora and Arch installers.

install_error() { echo "Installation: $*" >&2; return 1; }

select_build_jobs() {
    if [[ -n "${BUILD_JOBS:-}" ]]; then
        [[ "${BUILD_JOBS}" =~ ^[1-9][0-9]{0,5}$ ]] || {
            install_error "BUILD_JOBS must be a positive integer (at most six digits)."
            return 1
        }
    else
        local cpus memory jobs
        cpus=$(nproc)
        memory=$(available_build_memory_kib)
        # Reserve 1 GiB for other work, then budget 2 GiB per compiler job.
        # This is a conservative heuristic, not a peak-memory guarantee.
        jobs=$(( (memory - 1048576) / 2097152 ))
        (( jobs > 0 )) || jobs=1
        (( jobs <= cpus )) || jobs=${cpus}
        BUILD_JOBS=${jobs}
    fi
    export BUILD_JOBS
}

available_build_memory_kib() {
    python3 - <<'PY'
from pathlib import Path

info = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
available = int(info.get('MemAvailable', info['MemTotal']).split()[0]) * 1024
# Also respect container limits, including when the cgroup mount is namespaced.
roots = [(Path('/sys/fs/cgroup'), 'memory.max', 'memory.current'),
         (Path('/sys/fs/cgroup/memory'), 'memory.limit_in_bytes', 'memory.usage_in_bytes')]
for line in Path('/proc/self/cgroup').read_text().splitlines():
    _, controllers, group = line.split(':', 2)
    if not controllers:
        mount, limit_file, used_file = Path('/sys/fs/cgroup'), 'memory.max', 'memory.current'
    elif 'memory' in controllers.split(','):
        mount, limit_file, used_file = (Path('/sys/fs/cgroup/memory'),
                                       'memory.limit_in_bytes', 'memory.usage_in_bytes')
    else:
        continue
    # A parent cgroup can impose a limit even when the leaf says "max".
    if '..' not in Path(group).parts:
        node = mount / group.lstrip('/')
        while node != mount:
            roots.append((node, limit_file, used_file))
            node = node.parent
for root, limit_file, used_file in roots:
    try:
        limit = int((root / limit_file).read_text())
        used = int((root / used_file).read_text())
    except (OSError, ValueError):
        continue
    available = min(available, max(0, limit - used))
print(available // 1024)
PY
}

record_install_event() {
    [[ -n "${ASE_INSTALL_EVENT_LOG:-}" ]] || return 0
    python3 - "$@" <<'PY'
import json, os, sys, time

kind, stage_id, parent, label, *status = sys.argv[1:]
event = dict(kind=kind, stage_id=stage_id, parent=parent or None, label=label,
             monotonic_ns=time.monotonic_ns(), build_jobs=os.environ.get('BUILD_JOBS'))
if status:
    event['exit_code'] = int(status[0])
with open(os.environ['ASE_INSTALL_EVENT_LOG'], 'a', encoding='utf-8') as stream:
    stream.write(json.dumps(event) + '\n')
PY
}

run_install_stage() (
    local label="$1" started=${SECONDS}
    shift
    local stage_id="${BASHPID}" parent="${ASE_INSTALL_PARENT_STAGE:-}"
    record_install_event start "${stage_id}" "${parent}" "${label}"
    export ASE_INSTALL_PARENT_STAGE="${stage_id}"
    # An EXIT trap records failed stages without suppressing errexit inside
    # the command or function being measured. Nested stages remain separate.
    trap 'status=$?; record_install_event end "${stage_id}" "${parent}" "${label}" "${status}"; exit "${status}"' EXIT
    echo "${label}..."
    "$@"
    echo "${label}: completed in $((SECONDS - started))s."
)

# Verify both RV32/RV64 assembly and the C runtime before automatically reusing
# a toolchain. An executable GCC alone can be a partially installed toolchain.
toolchain_works() (
    local compiler="$1" prefix="${1%-gcc}" scratch arch abi
    [[ -x "${compiler}" && -x "${prefix}-objdump" ]] || return 1
    [[ "$("${compiler}" -dumpmachine 2>/dev/null)" == riscv*elf ]] || return 1
    scratch=$(mktemp -d) || return 1
    trap 'rm -rf -- "${scratch}"' EXIT
    printf '.text\n.globl _start\n_start:\n fadd.s f0,f0,f0\n fadd.d f0,f0,f0\n csrr a0,fcsr\n fence.i\n' > "${scratch}/check.s"
    "${compiler}" -march=rv32imafd_zicsr_zifencei -mabi=ilp32 -nostdlib \
        "${scratch}/check.s" -o "${scratch}/check.elf" >/dev/null 2>&1 || return 1
    printf '#include <stdio.h>\nint main(void) { return puts("ASE"); }\n' > "${scratch}/check.c"
    for arch in rv32imac rv64gc; do
        abi=ilp32
        [[ "${arch}" == rv64gc ]] && abi=lp64d
        "${compiler}" -march="${arch}" -mabi="${abi}" "${scratch}/check.c" \
            -o "${scratch}/check.elf" >/dev/null 2>&1 || return 1
        "${prefix}-objdump" -d "${scratch}/check.elf" >/dev/null 2>&1 || return 1
    done
)

find_toolchain_in() {
    local directory="$1" compiler
    [[ -n "${directory}" && "${directory}" != *$'\n'* ]] || return 1
    [[ ! -d "${directory}/bin" ]] || directory="${directory}/bin"
    for compiler in "${directory}"/riscv*-gcc; do
        if toolchain_works "${compiler}"; then
            SELECTED_TOOLCHAIN_BIN="$(cd "${directory}" && pwd)"
            SELECTED_TOOLCHAIN_PREFIX="${compiler##*/}"
            SELECTED_TOOLCHAIN_PREFIX="${SELECTED_TOOLCHAIN_PREFIX%-gcc}"
            export SELECTED_TOOLCHAIN_BIN SELECTED_TOOLCHAIN_PREFIX
            return 0
        fi
    done
    return 1
}

find_installed_toolchain() {
    local prefix compiler
    if [[ "${TOOLCHAIN_MODE:-auto}" != source && -n "${RISCV_TOOLCHAIN_PATH:-}" ]]; then
        find_toolchain_in "${RISCV_TOOLCHAIN_PATH}"
        return
    fi
    if find_toolchain_in "${ROOT_DIR}/riscv-toolchain/bin"; then
        return 0
    fi
    [[ "${TOOLCHAIN_MODE:-auto}" != source ]] || return 1
    local saved_directory
    if [[ -r "${ROOT_DIR}/toolchain.path" ]]; then
        IFS= read -r saved_directory < "${ROOT_DIR}/toolchain.path"
        if find_toolchain_in "${saved_directory}"; then
            return 0
        fi
    fi
    for prefix in riscv64-unknown-elf riscv-none-elf riscv64-elf riscv32-unknown-elf; do
        compiler=$(command -v "${prefix}-gcc") || continue
        if find_toolchain_in "$(dirname "${compiler}")"; then
            return 0
        fi
    done
    return 1
}

build_riscv_toolchain() (
    set -euo pipefail
    select_build_jobs
    local source_dir="${ROOT_DIR}/riscv-gnu-toolchain"
    local prefix="${ROOT_DIR}/riscv-toolchain"
    if [[ ! -d "${source_dir}" ]]; then
        git clone --depth 1 https://github.com/riscv-collab/riscv-gnu-toolchain.git "${source_dir}"
    fi
    [[ -x "${source_dir}/configure" ]] || {
        install_error "Incomplete toolchain checkout at ${source_dir}; inspect it before retrying."
        exit 1
    }
    cd "${source_dir}"
    if [[ -f .ase-install-prefix && "$(cat .ase-install-prefix)" != "${prefix}" ]]; then
        install_error "This build was configured for another prefix; use a separate checkout."
        exit 1
    fi
    if [[ ! -f Makefile || ! -f .ase-install-prefix ]]; then
        ./configure --prefix="${prefix}" --enable-multilib
        printf '%s\n' "${prefix}" > .ase-install-prefix
    fi
    # Upstream's default target builds AND installs newlib/GCC. Its submodules
    # are fetched on demand; recursively fetching every target wastes downloads.
    run_install_stage "Building the multilib toolchain (${BUILD_JOBS} jobs)" make -j "${BUILD_JOBS}"
    toolchain_works "${prefix}/bin/riscv64-unknown-elf-gcc" || {
        install_error "The built toolchain failed the RV32/RV64 compile-and-link checks."
        exit 1
    }
    echo "Build files retained at ${source_dir} for incremental retries."
)

build_gem5() (
    set -euo pipefail
    select_build_jobs
    local python python_config source_dir="${ROOT_DIR}/gem5" venv="${ROOT_DIR}/myenv"
    local -a options=()
    python=$(command -v "${GEM5_PYTHON:-python3.10}") || {
        install_error "Install Python 3.10 and its development files, or set GEM5_PYTHON and GEM5_PYTHON_CONFIG."
        exit 1
    }
    # Use the base interpreter's headers even when called from an active venv.
    python_config="${GEM5_PYTHON_CONFIG:-}"
    if [[ -z "${python_config}" ]]; then
        python_config=$("${python}" -c 'import os, sys; print(os.path.join(sys.base_prefix, "bin", "python%d.%d-config" % sys.version_info[:2]))')
    fi
    python_config=$(command -v "${python_config}") || {
        install_error "Cannot find the matching python-config for ${python}."
        exit 1
    }
    if [[ ! -d "${source_dir}" ]]; then
        git clone --depth 1 --branch "${GEM5_REQUIRED_BRANCH}" --single-branch \
            https://github.com/cad-polito-it/gem5.git "${source_dir}"
    fi
    [[ -f "${source_dir}/SConstruct" ]] || {
        install_error "Incomplete gem5 checkout at ${source_dir}; inspect it before retrying."
        exit 1
    }
    cd "${source_dir}"
    if [[ ! -x "${venv}/bin/python" ]]; then
        if command -v virtualenv >/dev/null 2>&1; then
            virtualenv -p "${python}" "${venv}"
        else
            "${python}" -m venv "${venv}"
        fi
    fi
    local version_code='import sys; print(sys.version_info[:2])'
    [[ "$("${venv}/bin/python" -c "${version_code}")" == "$("${python}" -c "${version_code}")" ]] || {
        install_error "Existing ${venv} uses a different Python; select the matching interpreter."
        exit 1
    }
    if [[ ! -f "${venv}/bin/scons" ]] ||
        ! "${venv}/bin/python" -c 'import importlib.metadata as m; assert m.version("scons") == "4.8.0"' >/dev/null 2>&1; then
        "${venv}/bin/python" -m pip install 'scons==4.8.0'
    fi
    if [[ -n "${GEM5_LINKER:-}" ]]; then
        case "${GEM5_LINKER}" in
            bfd|gold|lld|mold) options+=("--linker=${GEM5_LINKER}") ;;
            *) install_error "GEM5_LINKER must be bfd, gold, lld or mold."; exit 1 ;;
        esac
    fi
    [[ -z "${GEM5_BUILD_CACHE:-}" ]] || options+=("M5_BUILD_CACHE=${GEM5_BUILD_CACHE}")
    export PYTHON="${python}" PYTHON_CONFIG="${python_config}"
    export PATH="${venv}/bin:${PATH}"
    run_install_stage "Building gem5 (${BUILD_JOBS} jobs)" \
        "${venv}/bin/python" "${venv}/bin/scons" build/RISCV/gem5.opt -j "${BUILD_JOBS}" "${options[@]}"
    "${source_dir}/build/RISCV/gem5.opt" --help >/dev/null
)
