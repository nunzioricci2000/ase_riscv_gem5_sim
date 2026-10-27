#!/usr/bin/env bash
set -euo pipefail

WORK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT_DIR="${WORK_DIR}/tools"
UTILS_DIR="${WORK_DIR}/utils"
OS="$(uname -s)"
ARCH="$(uname -m)"
ASE_STUDIO_REPOSITORY="${ASE_STUDIO_REPOSITORY:-}"
BRANCH_CONFIG="${WORK_DIR}/ase_studio_branches.json"
if [[ ! -f "${BRANCH_CONFIG}" ]]; then
    echo "Missing ASE Studio branch configuration: ${BRANCH_CONFIG}" >&2
    exit 1
fi
GEM5_REQUIRED_BRANCH="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["gem5"])' "${BRANCH_CONFIG}")"
export GEM5_REQUIRED_BRANCH
export WORK_DIR ROOT_DIR UTILS_DIR OS ARCH
source "${UTILS_DIR}/install_build.sh"

usage() {
    cat <<'EOF'
Usage: ./utils/installation.sh COMMAND

Commands:
  toolchain   Install only the RISC-V GNU toolchain
  gem5        Install only the gem5 simulator
  ase-studio  Install ASE Studio and its native GTK launcher
  labinf      Use preinstalled LabInf tools and create ASE Studio launchers
  all-ase     Install toolchain, gem5, and ASE Studio

Environment:
  BUILD_JOBS=N                 Override CPU/memory-aware build parallelism
  TOOLCHAIN_MODE=auto|source    Reuse a working toolchain (default: auto)
  RISCV_TOOLCHAIN_PATH=DIR     Reuse this toolchain (RV32/RV64 C runtime required)
  GEM5_PYTHON=COMMAND          Python for gem5 (default: python3.10)
  GEM5_PYTHON_CONFIG=COMMAND   Matching python-config command
  GEM5_LINKER=bfd|gold|lld|mold Optional linker; must already be installed
  GEM5_BUILD_CACHE=DIR         Optional persistent SCons object cache
EOF
}

choose_command() {
    echo "Choose what to install:"
    select choice in \
        "All with ASE Studio (recommended)" \
        "ASE Studio only" \
        "Configure a LabInf checkout (no tool installation)" \
        "RISC-V toolchain only" \
        "gem5 only" \
        "Cancel"; do
        case "${REPLY}" in
            1) CHOSEN_COMMAND="all-ase"; return ;;
            2) CHOSEN_COMMAND="ase-studio"; return ;;
            3) CHOSEN_COMMAND="labinf"; return ;;
            4) CHOSEN_COMMAND="toolchain"; return ;;
            5) CHOSEN_COMMAND="gem5"; return ;;
            6) exit 0 ;;
            *) echo "Enter a number from 1 to 6." >&2 ;;
        esac
    done
}

detect_distribution() {
    local ID="" ID_LIKE="" VERSION_ID=""
    if [[ "${OS}" != "Linux" ]]; then
        echo "Unsupported operating system: ${OS}" >&2
        exit 1
    fi
    if [[ -r /etc/os-release ]]; then
        # shellcheck disable=SC1091
        source /etc/os-release
        DISTRO="${ID:-}"
        VERSION="${VERSION_ID:-}"
    elif command -v lsb_release >/dev/null 2>&1; then
        DISTRO="$(lsb_release -is)"
        VERSION="$(lsb_release -rs)"
    else
        echo "Could not determine the Linux distribution." >&2
        exit 1
    fi
    case "${DISTRO,,}" in
        ubuntu) DISTRO="Ubuntu" ;;
        fedora) DISTRO="Fedora" ;;
        arch|manjarolinux|manjaro) DISTRO="Arch" ;;
        *)
            # Arch derivatives (such as Omarchy) declare their base in ID_LIKE.
            # Match complete words, since ID_LIKE can contain several IDs.
            if [[ " ${ID_LIKE,,} " =~ [[:space:]]arch[[:space:]] ]]; then
                DISTRO="Arch"
            else
                echo "Unsupported Linux distribution: ${DISTRO}" >&2
                exit 1
            fi
            ;;
    esac
    MAJOR="${VERSION%%.*}"
    MINOR="${VERSION#*.}"
    export DISTRO MAJOR MINOR
}

component_target_exists() {
    case "$1" in
        toolchain) find_installed_toolchain ;;
        gem5)
            [[ -x "${ROOT_DIR}/gem5/build/RISCV/gem5.opt" ]] &&
                "${ROOT_DIR}/gem5/build/RISCV/gem5.opt" --help >/dev/null 2>&1
            ;;
        *) return 1 ;;
    esac
}

install_native_component() {
    local component="$1"
    local script_name="${component}"
    [[ "${component}" == "toolchain" ]] && script_name="riscv-toolchain"
    if component_target_exists "${component}"; then
        record_install_event skipped "" "" "${component}"
        echo "${component} is already installed; skipping."
        return
    fi
    if [[ "${component}" == toolchain && "${TOOLCHAIN_MODE}" != source && -n "${RISCV_TOOLCHAIN_PATH:-}" &&
          "${RISCV_TOOLCHAIN_PATH%/}" != "${ROOT_DIR}/riscv-toolchain" &&
          "${RISCV_TOOLCHAIN_PATH%/}" != "${ROOT_DIR}/riscv-toolchain/bin" ]]; then
        install_error "RISCV_TOOLCHAIN_PATH failed validation; provide an RV32/RV64 toolchain with its C runtime, or use TOOLCHAIN_MODE=source."
        exit 1
    fi
    local base="${UTILS_DIR}/${OS}/${DISTRO}/${script_name}"
    if [[ ! -f "${base}_dep.sh" || ! -f "${base}_install.sh" ]]; then
        echo "No ${component} installer is available for ${DISTRO}." >&2
        exit 1
    fi
    run_install_stage "Installing ${component} dependencies" sudo -E bash "${base}_dep.sh"
    # Dependencies may refresh package indexes; later stages in this run reuse them.
    export ASE_PACKAGE_INDEX_READY=1
    run_install_stage "Installing ${component}" bash "${base}_install.sh"
    component_target_exists "${component}" || {
        install_error "${component} did not pass its post-install check."
        exit 1
    }
}

install_ase_studio_dependencies() {
    case "${DISTRO}" in
        Ubuntu)
            [[ "${ASE_PACKAGE_INDEX_READY:-0}" == 1 ]] || sudo apt-get update
            sudo apt-get install -y git python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1
            ;;
        Fedora)
            local manager="dnf"
            command -v dnf5 >/dev/null 2>&1 && manager="dnf5"
            sudo "${manager}" install -y git python3-gobject gtk3 webkit2gtk4.1
            ;;
        Arch)
            local sync=-Syu
            [[ "${ASE_PACKAGE_INDEX_READY:-0}" != 1 ]] || sync=-S
            sudo pacman "${sync}" --needed --noconfirm git python-gobject gtk3 webkit2gtk-4.1
            ;;
    esac
}

install_ase_studio() {
    if ! command -v git >/dev/null 2>&1 ||
        ! python3 -c 'import gi; gi.require_version("Gtk", "3.0"); gi.require_version("WebKit2", "4.1")' 2>/dev/null; then
        install_ase_studio_dependencies
    fi
    if [[ ! -f "${WORK_DIR}/ase_studio/install.sh" ]]; then
        if [[ -f "${WORK_DIR}/.gitmodules" ]]; then
            git -C "${WORK_DIR}" submodule update --init --recursive ase_studio
        else
            if [[ -z "${ASE_STUDIO_REPOSITORY}" ]]; then
                echo "Set ASE_STUDIO_REPOSITORY to your Studio fork URL when installing without .gitmodules." >&2
                return 1
            fi
            git clone "${ASE_STUDIO_REPOSITORY}" "${WORK_DIR}/ase_studio"
        fi
    else
        echo "Using the existing ASE Studio checkout."
    fi
    bash "${WORK_DIR}/ase_studio/install.sh"
}

set_setup_export() {
    local key="$1"
    local line="$2"
    local setup="${WORK_DIR}/setup_default"
    if grep -q "^export ${key}=" "${setup}"; then
        sed -i "s|^export ${key}=.*|${line}|" "${setup}"
    else
        printf '\n%s\n' "${line}" >> "${setup}"
    fi
}

update_setup_default() {
    local frontend="$1"
    if [[ -n "${SELECTED_TOOLCHAIN_BIN:-}" ]]; then
        # Keep the tracked defaults portable; save this installation's selection
        # as data, not executable shell code, in the ignored tools directory.
        local selection_file
        selection_file=$(mktemp "${ROOT_DIR}/.toolchain.XXXXXX")
        printf '%s\n%s\n' "${SELECTED_TOOLCHAIN_BIN}" "${SELECTED_TOOLCHAIN_PREFIX}" > "${selection_file}"
        mv -f "${selection_file}" "${ROOT_DIR}/toolchain.path"
    fi
    if [[ "${frontend}" == "ase" ]]; then
        set_setup_export PIPELINE_VISUALIZER 'export PIPELINE_VISUALIZER="${WORK_DIR}/ase-studio.sh"'
    fi
}

configure_labinf() {
    local labinf_setup="${WORK_DIR}/setup_default.labinf"
    local studio_installer="${WORK_DIR}/ase_studio/install.sh"
    if [[ ! -f "${labinf_setup}" ]]; then
        echo "Missing LabInf configuration: ${labinf_setup}" >&2
        exit 1
    fi

    if ! (
        cd "${WORK_DIR}"
        set +u
        # shellcheck disable=SC1091
        source "${labinf_setup}"
        [[ -x "${CC}" ]]
        [[ -x "${OBJDUMP}" ]]
        [[ -x "${GEM5_INSTALLATION_PATH}" ]]
    ); then
        echo "The paths copied from setup_default.labinf do not point to all required LabInf tools." >&2
        echo "Ask the LabInf administrator to verify the shared RISC-V and gem5 installations." >&2
        exit 1
    fi
    install -m 0644 "${labinf_setup}" "${WORK_DIR}/setup_default"

    if [[ ! -f "${studio_installer}" ]]; then
        if [[ -f "${WORK_DIR}/.gitmodules" ]]; then
            git -C "${WORK_DIR}" submodule update --init --recursive ase_studio
        else
            echo "ASE Studio is missing and this checkout has no submodule configuration." >&2
            exit 1
        fi
    fi
    bash "${studio_installer}" --launcher-only
    if [[ -f "${WORK_DIR}/.ase-studio-env.json" ]]; then
        echo "Note: existing values in .ase-studio-env.json override setup_default; review them in ASE Studio Settings."
    fi
}

command="${1:-}"
if [[ -z "${command}" ]]; then
    if [[ -t 0 ]]; then
        CHOSEN_COMMAND=""
        choose_command
        command="${CHOSEN_COMMAND}"
    else
        usage
        exit 2
    fi
fi
case "${command}" in
    toolchain|gem5|ase-studio|labinf|all-ase) ;;
    -h|--help|help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
esac

if [[ "${command}" == "labinf" ]]; then
    configure_labinf
    echo "LabInf configuration completed successfully."
    exit 0
fi

TOOLCHAIN_MODE="${TOOLCHAIN_MODE:-auto}"
case "${TOOLCHAIN_MODE}" in
    auto|source) ;;
    *) install_error "TOOLCHAIN_MODE must be auto or source."; exit 2 ;;
esac
export TOOLCHAIN_MODE
unset SELECTED_TOOLCHAIN_BIN SELECTED_TOOLCHAIN_PREFIX
select_build_jobs
# Do not trust a refresh marker inherited from an earlier invocation.
export ASE_PACKAGE_INDEX_READY=0
echo "Build parallelism: ${BUILD_JOBS} jobs (override with BUILD_JOBS)."
record_install_event configuration "" "" "${command}"
mkdir -p "${ROOT_DIR}"
detect_distribution
case "${command}" in
    toolchain) install_native_component toolchain; update_setup_default none ;;
    gem5) install_native_component gem5; update_setup_default none ;;
    ase-studio) run_install_stage "Installing ASE Studio" install_ase_studio; update_setup_default ase ;;
    all-ase)
        install_native_component toolchain
        install_native_component gem5
        run_install_stage "Installing ASE Studio" install_ase_studio
        update_setup_default ase
        ;;
esac

echo "Installation completed successfully."
