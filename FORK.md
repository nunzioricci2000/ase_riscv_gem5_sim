<!-- SPDX-License-Identifier: GPL-2.0-only -->
<!-- Created in the personal fork on 2026-10-30: collect personal simulator changes and link original usage instead of reproducing it. -->
# Changes in the simulator fork

For the standard simulation workflow, setup files, creating a program and original
tool installation instructions, use the
[original simulator documentation](https://github.com/cad-polito-it/ase_riscv_gem5_sim#readme).
This page describes the behavior changed by the personal fork.

## Source installation with this fork

```bash
git clone --branch main --recurse-submodules https://github.com/nunzioricci2000/ase_riscv_gem5_sim.git
cd ase_riscv_gem5_sim
./utils/installation.sh
```

These commands select our repositories and recipes. For the standalone desktop
application, use the [Studio fork installer](https://github.com/nunzioricci2000/ase-studio#readme).
Its exact platform matching differs from the source installer's support for
Arch derivatives; do not substitute one distribution's binary SDK for another.

The installer recognizes Ubuntu, Fedora, Arch Linux, and Arch-based distributions
such as Omarchy through the `ID_LIKE` field in `/etc/os-release`.

The same build policy is used on all three distributions:

- Reuse an installed bare-metal RISC-V toolchain when it passes RV32 and RV64
  compile-and-link checks, including the C runtime and objdump. The installer
  checks the local installation, a previously selected installation, and `PATH`.
  A compiler-only package without a C runtime is not accepted automatically.
- Otherwise build the full multilib toolchain. Keep its checkout and intermediate
  files so an interrupted installation can resume; gem5 builds resume too.
- Use shallow source clones and let the toolchain fetch its submodules on demand.
- Choose build parallelism from available CPUs and memory (including cgroup
  limits): reserve 1 GiB, budget 2 GiB per job, and always use at least one job.
  This is a heuristic; use `BUILD_JOBS` to override it on memory-constrained hosts.
- Reuse gem5's virtual environment and pinned SCons installation. On Arch, pass
  the same job limit to the Python package build without changing system settings.
- Refresh package indexes once per installer run where possible. Ubuntu no
  longer upgrades unrelated packages; Arch retains its required full upgrade
  before installing dependencies, avoiding unsupported partial upgrades.
- Print elapsed time for each install/build stage.

Examples (settings apply only to that invocation):

```bash
# Override automatic parallelism on any supported distribution.
BUILD_JOBS=4 ./utils/installation.sh all-ase

# Reuse a complete toolchain already installed at a custom location.
RISCV_TOOLCHAIN_PATH=/opt/riscv/bin ./utils/installation.sh toolchain

# Build locally instead of selecting a system toolchain.
TOOLCHAIN_MODE=source ./utils/installation.sh toolchain

# Optional: use an installed linker and a persistent gem5 object cache.
GEM5_LINKER=lld GEM5_BUILD_CACHE="$HOME/.cache/ase-gem5" ./utils/installation.sh gem5
```

`TOOLCHAIN_MODE=source` still skips an already working local installation. Rerun
the same command after an interrupted build; do not delete the build directories.
Keeping build files uses more disk space, but avoids repeating compilation.
The installer does not fetch updates into existing source checkouts or discard
local changes. For intentional source changes, run the corresponding
`utils/Linux/<distribution>/*_install.sh` build script with `WORK_DIR`, `ROOT_DIR`,
and (for gem5) `GEM5_REQUIRED_BRANCH` set; it runs the incremental build even when
the installed binary already exists.

Python 3.10 remains the default for this gem5 fork. Advanced users can provide
`GEM5_PYTHON` and `GEM5_PYTHON_CONFIG` for another compatible installation with
development files. Interpreter compatibility must be verified with this fork.
The `opt` simulator variant and pipeline tracing remain enabled.

The selected toolchain directory and command prefix are saved in ignored `tools/toolchain.path`;
`setup_default` reads it while still allowing `RISCV_TOOLCHAIN_PATH` to override
the selection. Explicit ASE Studio settings also retain their precedence.
Installing ASE Studio selects its launcher in `setup_default`.

These changes reduce downloads and avoid repeated work; a clean gem5 and full
toolchain source build can still take substantial time. No paid services or
host-specific binaries are required. Run the installer regression tests with
`python3 utils/test_installation.py` (no downloads or package installation).

#### Benchmark installation time

The benchmark runs the actual installer and saves a JSON report, full output
logs, and stage events. It does not remove installations or reset caches.

```bash
python3 utils/benchmark_installation.py all-ase --output /tmp/ase-install.json

# Measure repeated invocations against the same installation.
python3 utils/benchmark_installation.py gem5 --runs 5 --label installed-rerun

# In a fresh disposable VM/checkout, measure a complete source installation.
TOOLCHAIN_MODE=source BUILD_JOBS=4 python3 utils/benchmark_installation.py all-ase \
  --require-empty-builds --label fresh-source --output /tmp/ase-fresh.json
```

For fresh-install comparisons, use separate Ubuntu, Fedora, and Arch VMs with
the same CPU/RAM allocation. Provision a normal user with noninteractive sudo
access in those disposable environments; the benchmark runs unattended, with
stdin closed, and enables noninteractive AUR package confirmation. Restore the
same VM snapshot before each sample, including package/download caches, and
hold build jobs and source revisions constant when comparing installer changes.
`--require-empty-builds` refuses existing source/build directories rather than
deleting them. It does not establish that system packages or caches are cold.
Use one run per fresh environment; subsequent invocations measure reuse.

Reports include total wall-clock seconds, nested stage durations and exit codes,
skipped components, CPU time, maximum process RSS, OS/CPU/memory information,
effective job count, build settings, and installer/source fingerprints. Nested
stage times overlap and must not be added together. RSS is the maximum for a
process, not the combined memory of all parallel compiler processes. Successful
runs with matching observed state and executed stages are grouped for median,
minimum, and maximum times. Failed, cancelled, and timed-out runs are retained
but excluded from those statistics; execution stops on the first unsuccessful
run. Timing includes instrumentation overhead.

`--timeout SECONDS` limits a run and terminates its process group. Ctrl+C saves
the partial result and stops the build. `--repo /path/to/checkout` can measure
another installer revision using the same harness; older revisions without
stage instrumentation still get total wall-clock/CPU measurements. Existing
reports are never overwritten. Run accounting tests with
`python3 utils/test_benchmark_installation.py`.


## Simulator corrections

The local gem5 patches preserve upstream notices and are applied by the fork's
build/install recipes:

- `utils/gem5-runtime.patch` records MinorCPU's initial register state and drains
  older instructions before a syscall exits, preserving final writebacks.
- `utils/gem5-timebuffer.patch` initializes TimeBuffer storage to prevent the
  optimized O3 startup failure encountered with newer compilers.
- `utils/gem5-fpreg.patch` preserves raw floating-point register bits on hosts
  such as macOS where a narrower integer conversion truncated them.
- `utils/gem5-cxx17.patch` addresses the older DRAMPower code's C++17 build
  compatibility. The build recipes also preserve the embedded Python environment.

The Studio fork consumes these traces for corrected register playback. Old traces
cannot reconstruct an initial state that was never recorded. The initial-register
extension is for MinorCPU; do not infer that O3 produces the same snapshot.
See [third-party provenance](THIRD_PARTY.md) for licensing boundaries and exact
engine inputs, and [release verification](RELEASES.md) for integer/FP coverage.

## Prebuilt SDKs and Studio integration

The engine workflow produces platform-specific SDKs and matching source archives.
Studio's independent workflow selects verified SDKs using its lockfile, so an
editor change does not require compiling the engine again. SDKs do not contain
the Studio GUI; the [Studio packages](https://github.com/nunzioricci2000/ase-studio/releases)
combine both components. Caches, manifests, reports and source rebuilds are
explained in [RELEASES.md](RELEASES.md).

The Studio feature package is **Abate**, based on original Studio **1.6.0**.
Its [version naming](https://github.com/nunzioricci2000/ase-studio/blob/main/VERSIONING.md)
is independent of engine SDK tags and of this repository's submodule pointer.

## Personal checkout workflow

The simulator's personal stable branch is `main`, with development integrated
on `develop`. Keep the original project as remote `upstream` and publish to
your own `origin`. References such as `upstream/main` already identify upstream
branches; retained copies in the personal repository use `original/`.
The relative Studio submodule URL
(`../ase-studio.git`) resolves to the Studio repository under the same GitHub
owner as the simulator fork. Publish the Studio commit before publishing a
simulator commit that pins it.

Launch the pinned Studio with `./ase-studio.sh`. To preview the independent
Monaco worktree, use:

```bash
ASE_STUDIO_HOST_ROOT="$PWD" ASE_STUDIO_PORT=8766 ../ase-studio-monaco/launch.sh
```

Studio validates runtime files without switching branches. App updates only
fast-forward from `origin`; commit or stash tracked local edits first. Upstream
changes are reviewed and integrated explicitly with Git. Personal program
directories, pipeline exports, results and the local Python environment are
excluded from new commits. Existing tracked examples remain versioned.

