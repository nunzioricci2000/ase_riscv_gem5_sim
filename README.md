<!-- Modified in the personal fork on 2026-10-27: clarify licensing and redistribution requirements. -->
<!-- Modified in the personal fork on 2026-10-27: link measured binary build and Gitflow workflow. -->
<!-- Modified in the personal fork on 2026-10-27: reserve main/develop for the personal fork. -->
# Architetture dei Sistemi di Elaborazione@Politecnico di Torino: SIMULATING A RISC-V CPU WITH GEM5

This README provides an environment for simulating a program on a parametrizable RISC-V CPU and visualize the pipeline. You can see the flow in the Figure below.


![flow](.images/gem5_workflow.png "Simulation flow")

## Table of contest
- [Architetture dei Sistemi di Elaborazione@Politecnico di Torino: SIMULATING A RISC-V CPU WITH GEM5](#architetture-dei-sistemi-di-elaborazionepolitecnico-di-torino-simulating-a-risc-v-cpu-with-gem5)
  - [Table of contest](#table-of-contest)
  - [Setup the environment](#setup-the-environment)
    - [Prerequisites](#prerequisites)
    - [Installing a Risc-V toolchain, the cross-compiler](#installing-a-risc-v-toolchain-the-cross-compiler)
  - [HOWTO - Simulate a Program](#howto---simulate-a-program)
  - [HOWTO - Visualize the Pipeline with Konata](#howto---visualize-the-pipeline-with-konata)
  - [Contributors](#contributors)

## Setup the environment 
First of all, you need to clone the repository with the following command, for SSH:
```
$ git clone --recurse-submodules git@github.com:nunzioricci2000/ase_riscv_gem5_sim.git
```
For HTTPS:
```
$ git clone --recurse-submodules https://github.com/nunzioricci2000/ase_riscv_gem5_sim.git
```

### Prerequisites
In order to simulate a program, you need the following two core tools:
- A Risc-V cross compiler
- An architectural simulator (gem5)

The pipeline visualizer is provided by ASE Studio (GTK/WebKit frontend).

An important file for the simulation flow is the [```setup_default```](./setup_default).
In this file you need to specify you installation paths for different tools.
For example:
```
export CC="/usr/bin/riscv64-linux-gnu-gcc-10"
export GEM5_INSTALLATION_PATH="/mnt/d/gem5_simulator/build/RISCV/gem5.opt"
export GEM5_SRC="/mnt/d/gem5_simulator/gem5/"
```
The ```CC``` is the cross compiler, and it is installed in ```/usr/bin```. ```GEM5_INSTALLATION_PATH``` is the complete path to the gem5 executable (or an executable wrapper that forwards its arguments), while the simulator source is at ```/mnt/d/gem5_simulator/gem5```.

In the repository, you have different ```setup_default``` files, each one for a specific configuration (LABINF, VM, or your native installation). You can choose the one that fits your needs. For a LABINF workstation, configure the preinstalled tools and create the ASE Studio desktop shortcut with:
```bash
$ ./utils/installation.sh labinf
```
This copies `setup_default.labinf` to `setup_default`, verifies the shared compiler and gem5 paths, and creates the launcher without reinstalling the toolchain or gem5.

### Installation 

Experimental precompiled engine packages, the platform matrix, timestamped
build reports and the fork's Gitflow release process are described in
[RELEASES.md](RELEASES.md). These packages contain gem5 and the RISC-V toolchain;
ASE Studio's desktop frontend remains a separate installation.

In the repository, you can find a script named [```installation.sh```](./utils/installation.sh) (in the utils folder) that can help you to download the cross-compiler, the gem5 simulator and generate the ```setup_default``` file. You can run it with the following command:

```bash
$ ./utils/installation.sh
```
Use `./utils/installation.sh labinf` instead on LABINF systems where the required tools are already installed.

The standard installation will install the cross-compiler and gem5 in a default folder named ```./tools/```.

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

Check the following installation guidelines for each tool for the necessary dependencies and requirements before running the ```installation.sh``` script.
#### Installing a Risc-V toolchain, the cross-compiler

You can compile from scratch the toolchain and the necessary dependencies for Risc-V following [these instructions](https://github.com/riscv-collab/riscv-gnu-toolchain).


#### Installing Gem5, the Architectural Simulator

Start by cloning gem5 from this repository:
```
$ git clone --branch stable https://github.com/cad-polito-it/gem5
```

To install Gem5 and the necessary dependencies, you can follow the README of that repo as well as these [instructions](https://www.gem5.org/documentation/general_docs/building).

Just remember that you need the following Gem5 characteristics to install:
- ISA = RISCV.
- variant = opt.

## HOWTO - Simulate a Program

To simulate a program, run the `simulate.sh` script with the desired program as an argument, and the desired configuration file:  
```bash
./simulate.sh -i ./programs/sanity_test/ --setup ./setup_default
```

This will produce an ELF (Executable and Linkable Format) file in the `programs/sanity_test/` directory.
Afterward, the ELF is passed to the Architectural Simulator, and program-related statistics (```stats.txt```) and trace (```trace.out```)are dumped in ```./results/sanity_test/```

You can execute the script in interactive mode:
```bash
./simulate.sh -setup ./setup_default
```

## HOWTO - Add a new program
For adding a new program, you can follow the steps below:
1. Copy an existing folder in the `programs/` directory, e.g., `programs/program_1/` and rename it to `programs/program_2/`.
2. Modify the source code (assembly or c files) in the `program_2/` folder.
3. Modify the `Makefile` in the `program_2/` folder if necessary (add new source files). In the following line (line 23):
    ```makefile
    ASM = ./program2.s # Removed ./program1.s
    ```

## ASE Studio 

ASE Studio is a lightweight teaching IDE distributed in the `ase_studio`
submodule. It uses GTK WebKit and the existing RISC-V compiler/gem5
configuration in `setup_default`. When cloning this
repository, initialize the submodule as well:

```bash
git clone --recurse-submodules https://github.com/nunzioricci2000/ase_riscv_gem5_sim.git
cd ase_riscv_gem5_sim
git submodule update --init --recursive
```

On Ubuntu or Debian, install the native GUI dependencies and the per-user
application launcher, then start Studio:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1
./ase_studio/install.sh
./ase-studio.sh
```

## Contributors
- Francesco Angione (francesco.angione@polito.it)
- Nicola di Gruttola giardino (nicola.digruttola@polito.it)
- Behnam Farnaghinejad (behnam.farnaghinejad@polito.it)
- Gabriele Filipponi (gabriele.filipponi@polito.it)
- Giorgio Insinga (giorgio.insinga@polito.it)
- Annachiara Ruospo (annachiara.ruospo@polito.it)
- Antonio Porsia (antonio.porsia@polito.it)

Feel free to contribute with issues and pull requests or contact us!

## Personal fork workflow

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

## Redistribution and license compliance

The project code is **GPL-2.0-only**, except for components with their own
license notices. You may redistribute and modify it, including commercially,
subject to the applicable license conditions. Preserve upstream attribution
and identify changes made in this personal fork. No upstream endorsement is implied.

See [distribution requirements](DISTRIBUTION.md), [third-party components](THIRD_PARTY.md)
and [contributor instructions](AGENTS.md). Keep all required license notices
and provide corresponding source when distributing built artifacts.
