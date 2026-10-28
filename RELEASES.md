<!-- SPDX-License-Identifier: GPL-2.0-only -->
<!-- Created in the personal fork on 2026-10-27: measured binary distribution and Gitflow. -->
<!-- Modified in the personal fork on 2026-10-27: use main/develop and original/ branch names. -->
<!-- Modified in the personal fork on 2026-10-27: document automatic builds on main pushes. -->
<!-- Modified in the personal fork on 2026-10-27: add direct artifact download instructions. -->
<!-- Modified in the personal fork on 2026-10-27: default component reuse and document diagnostics. -->
<!-- Modified in the personal fork on 2026-10-27: document runtime coverage and incremental build counters. -->
<!-- Modified in the personal fork on 2026-10-27: document complete SDK reuse and promotion after merging. -->
<!-- Modified in the personal fork on 2026-10-28: reduce Linux runtime archives by removing staged debug sections. -->
<!-- Modified in the personal fork on 2026-10-28: avoid duplicate cache uploads and expose their storage use. -->
<!-- Modified in the personal fork on 2026-10-28: inspect legacy artifact reports without downloading irrelevant SDKs. -->
<!-- Modified in the personal fork on 2026-10-28: use measured fast gzip for release archives. -->
# Engine packages and Gitflow

The build workflow produces **experimental engine SDKs**, not a cross-platform
ASE Studio desktop application. Each SDK contains this fork's RISCV `gem5.opt`,
the GNU bare-metal RV32/RV64 toolchain, Python 3.10, simulation configurations,
launch wrapper, smoke test, manifests and notices. GTK/WebKit and the Studio
frontend are not bundled. Set Studio's gem5 path to `SDK/bin/gem5` and its
toolchain path to `SDK/toolchain/bin` on a supported Studio host.

## Platforms

`ci/targets.json` is the explicit, extensible target inventory. It currently
builds Ubuntu 22.04/24.04 x86-64, Ubuntu 24.04 ARM64, Debian 12/13 x86-64,
Fedora 43 x86-64, Arch x86-64, and experimental macOS 15 Intel/Apple Silicon.
Linux builds use native-architecture containers, not CPU emulation. macOS uses
a case-sensitive APFS workspace because the toolchain sources require it.
The OS/architecture is the **host** running gem5/GCC; the compiled programs
target **RISC-V RV32/RV64** on every host.

Windows uses the Ubuntu 24.04 x86-64 SDK under **WSL2**. A Windows 2025 job
installs a WSL2 Ubuntu distribution and runs the SDK's compile/simulation test.
That job can fail if the runner cannot provision WSL2; the failure is retained,
not disguised as native Windows support. There is no `.exe` target. A WSL2
validation is added whenever Ubuntu 24.04 x86-64 is selected.

System shared libraries remain external. `packages.txt`, `environment.json`
and `runtime-links.txt` identify the build/runtime environment. These are
distribution-specific packages, **not universal static binaries**. WSL validation
installs the build image's package names conservatively; it does not yet measure
a minimal runtime installation. macOS depends on Homebrew libraries in the
matching architecture/prefix. Compilers and mutable package/image versions can
break an older gem5 fork; the first remote run is a compatibility experiment.
No target is certified before its actual build and smoke test succeed.

## Run and compare builds

Every push to `main` automatically starts **Build engine packages** for the
entire matrix. Download the resulting artifacts from that workflow run once
each target completes; pushing to `main` does not publish a GitHub Release.
For a controlled experiment, open **Actions → Build engine packages → Run workflow**.
Choose a branch, target IDs (`all`, `linux`, or comma-separated IDs), `full` or
`minimal` toolchain profile, compiler jobs, linker and whether to restore the
component and SCons caches. Reuse is enabled by default, including automatic
push builds. Python, the toolchain and gem5 have separate content identities:
source revision, component recipes, platform, compiler and installed libraries.
gem5 additionally includes its patches, Python identity, SCons and linker;
the toolchain includes its multilib profile. An unchanged component is restored
after verifying its archive checksum. Changed gem5 inputs fall back to SCons's
dependency/object cache. Completed components are saved even if a later build
stage fails. Cache eviction or a missing cache causes a normal source build.
Every package still undergoes the relocated compile/simulation smoke tests.
These compile/link RV32 and RV64 C programs and execute integer and floating-point
assembly. MinorCPU and O3 are tested with direct and cached memory, including
dependent FP operations, a store of 3.5 and final double-precision writeback of
4.5 before exit. A short C++ regression also checks optimized TimeBuffer
initialization before compiling gem5; it detects a startup crash exposed by
newer optimizing compilers. Passing these checks is not exhaustive ISA validation.

Before those tests, Linux packages remove debug sections from staged host ELF
executables/shared libraries with `strip --strip-debug`. Dynamic exports and
ordinary symbols remain; RISC-V target files and static archives are preserved.
`runtime-compaction.json` records timestamps,
per-file sizes and saved bytes. The exact sources and build recipes still ship
alongside binaries; rebuild without this packaging step for full source-level
debugging. macOS binaries are unchanged by this ELF-specific step.
Runtime and source archives use gzip level 1. On the local runtime sample,
level 1 took 8.3 seconds for 245 MB versus 126.1 seconds for 215 MB at level 9;
the per-target remote reports remain the authoritative release measurements.

Small `engine-index-TARGET` artifacts index successful SDKs for 14 days. When
an Actions cache has been evicted, the workflow can download a matching SDK,
verify its checksum and reuse only components with identical inputs. Lookup
accepts this repository's current branch and main, plus commits from this same
repository that GitHub confirms are ancestors of the current commit. Thus a
tested feature build can be reused after its merge into main. Fork PR artifacts
are excluded. Up to three older artifacts without an index can also be checked;
their embedded reports must contain matching component identities.
For those older artifacts, HTTP range requests read only the ZIP index and small
report first. A full SDK is downloaded only when it provides a missing component
or an exact complete package. A match for components already in cache is not
sufficient. Servers without range support fall back to full archive verification.
Missing/expired artifacts or failed downloads fall back to a source build; no extra cache
storage allowance or billing setting is enabled.
`cache-storage.json` inventories bytes and file counts for component archives and
SCons object namespaces. On Linux, completed toolchain/gem5 component archives
also remove host ELF debug sections from temporary verified copies before cache
upload. Live build files and SCons intermediate objects are untouched; target
RISC-V debugging information and GDB functionality remain. Compaction is recorded
once per component checksum and replaces the archive and its verified manifest.
The before/after archive sizes are recorded separately from raw binary savings.
<!-- Modified in the personal fork on 2026-10-28: compact completed cache components while retaining all intermediate object data. -->
<!-- Modified in the personal fork on 2026-10-28: retire replaced branch caches and record measured Arch storage savings. -->
The Arch check in run 40618058855 reduced the stored Actions cache from
3,945,134,044 to 2,464,319,305 bytes without compiling or linking gem5. The one-time
conversion took 51 seconds. After a successful cache save, the workflow confirms
the new cache exists and deletes only older copies for the same target, profile,
linker, branch and cache layout. It preserves newer concurrent saves and caches
from other branches/targets; a missing replacement never triggers deletion.
`cache-retention.json` records the removed keys and their sizes.
The workflow uploads a new Actions cache only when it
saved a newly built component or compiled/linked something. Exact SDK reuse and
repackaging do not upload duplicate caches that would evict other targets, except
to replace a previously oversized cache with its compacted version. Failed
or interrupted builds still retain new partial work. Cache eviction can still
force recompilation when no matching object cache survives; an SDK preserves
finished components, not every intermediate object needed for a changed source.
When the entire package identity also matches (components, configuration files,
build/package scripts, workflow files, notices and recorded job count), both
the binary and corresponding source archive are downloaded and checksum-verified.
The SDK is extracted at the relocated test path and the runtime checks run again;
source fetching, compilation and archiving are skipped explicitly in the report.
Dependency installation, transfer, checksum and runtime-test costs remain.
Disable cache for a source-build timing experiment.
The full profile is the default. Minimal omits GDB and restricts
multilib to RV32IMAC/ILP32 and RV64GC/LP64D; both preserve the assembly/runtime
smoke tests. Python is built without PGO/LTO. gem5 stays `opt` with pipeline
tracing enabled; switching to `fast` would invalidate that requirement.

Each matrix job has a 350-minute limit; up to nine execute concurrently,
subject to GitHub's available runner capacity.
Compilation is expensive. Normal feature/develop pushes run only offline
checks. Main/release/hotfix pushes and version tags build the entire matrix.
GitHub runner storage/concurrency limits still apply. Linux jobs free known
preinstalled SDK directories on the disposable runner; macOS jobs fail with a
clear preflight diagnostic when there is less than 20 GiB free. No local
installation/build directory is removed by these scripts.

For a baseline, disable cache, use `full` and `default` linker. Compare runs
with identical source lock, target, package inventory and jobs; change only
one variable. A restored cache is not proof that every object was reused.
SCons cache directories include the package-inventory fingerprint. Reports
record the image digest, compiler versions, recipes' hashes and cache setting;
container tags and distro repositories remain mutable, so this is not a claim
of byte-for-byte reproducibility.

Download `engine-TARGET` from the workflow run. It contains the binary archive,
matching **complete source snapshots** (including initialized toolchain
submodules and local gem5 patch), SHA256SUMS, stage logs and JSON/Markdown
reports. Failed builds retain diagnostics; incomplete archives use `.partial`
and are not release assets. Artifacts expire after 14 days; the combined report
is retained for 90 days. GitHub artifact downloads normally require login.

Open [the fork's package builds](https://github.com/nunzioricci2000/ase_riscv_gem5_sim/actions/workflows/build-release.yml),
select a run on `main`, then select `engine-TARGET` in **Artifacts** at the bottom
of the run page. Choose the host OS and architecture, extract the downloaded ZIP,
then extract its binary `.tar.gz`. A failed target may contain only diagnostics.
With GitHub CLI, replace `RUN_ID` with the number in that run's URL:

```sh
gh run download RUN_ID --repo nunzioricci2000/ase_riscv_gem5_sim \
  --name engine-ubuntu-24.04-x86_64 --dir downloaded-engine
```

`build-report` includes UTC start/end timestamps and monotonic wall durations
for image pull, dependencies, source fetch, Python configure/build, toolchain
configure/build, gem5 build, staging, relocation/simulation, source archiving
and binary archiving. The large toolchain source download has its own
`fetch-toolchain` phase after gem5 builds, so early gem5 failures avoid that cost.
`actions-jobs.json` adds job/step timestamps for runner
setup, checkout, cache and artifact upload. It is a snapshot taken during the
report job, so the report job's own final upload/end and a subsequent release
job are not yet present. Missing or cancelled targets appear explicitly.
No parallel-build aggregate RAM measurement or unmeasured speedup is claimed.
Failed phases include the last 4 KiB of their diagnostic log in both reports.
Component cache hits/misses and transfer times are recorded separately from
GitHub's outer cache restore. `gem5_work` counts actual compile/link actions and
cached outputs retrieved from the SCons build log, excluding configure probes.
These are different units, so they are not presented as a cache-hit percentage.
The Windows validation can also be rerun against
an existing Ubuntu artifact by setting `wsl_run_id` in the build workflow;
this mode skips compilation and only validates that run's Ubuntu SDK.

Local Linux invocation (requires Docker; performs real downloads/builds):

```sh
python3 ci/build.py --target ubuntu-22.04-x86_64 \
  --work /path/to/new-work --output /path/to/new-report --jobs 2
```

Source archives include the build recipes in `sources/project/ci` and all
editable component sources. To rebuild from snapshots, use the dependency and
configure/build commands in `ci/steps.sh`, pointing `sources` at those extracted
trees instead of running the `fetch` phase. Initialize local Git metadata for
the toolchain and its populated submodules (`git init` in each) because its
Makefile uses `.git` as a source-presence marker; no upstream source download
is needed. Unpack the included SCons tarball into the `ASE_WORK/scons` directory.
System build packages are still required. The source archive is not a VM image.

## Gitflow for this fork

The personal repository uses `main` for stable releases and `develop` for
integration. The original repository remains the `upstream` remote, whose
remote-tracking refs already have names such as `upstream/main`. Retained
copies in the personal repository use `original/main` and
`original/fix/new_env_setup`. These are snapshots, not automatically updated
mirrors; use `git fetch upstream` to refresh upstream's remote-tracking refs.
The original repository's branches are not renamed. The local `original/main`
preserves the former local upstream checkout, which can lag the remote snapshot.

| Branch | Purpose | Merge destination |
| --- | --- | --- |
| `main` | Stable releases; default branch | `develop` after release/hotfix |
| `develop` | Integration | start a `release/VERSION` branch |
| `feature/NAME`, `fix/NAME` | Development from `develop` | `develop` |
| `release/VERSION` | Stabilization from `develop` | `main`, then back into `develop` |
| `hotfix/VERSION` | Urgent fix from `main` | `main`, then back into `develop` |

`python3 ci/gitflow.py init` creates `develop` if absent and configures
local git-flow branch/prefix settings. It does not switch branches, commit,
push or rewrite history. Push the integration branch when ready. The CI
check rejects feature PRs directly into stable. GitHub branch protection must
require **Gitflow and regression checks** on `main` and `develop`,
require PRs, and prohibit force-push/deletion. Workflow YAML alone cannot
enforce remote protection or prevent direct pushes by administrators.

Release sequence:

1. Merge features into `develop`; create `release/X.Y.Z` and evaluate the
   matrix reports. Publish/merge Studio changes separately if relevant; these
   engine packages do not include the Studio submodule.
2. Merge release into `main`, then merge stable back into `develop`.
3. Tag the current stable tip `vX.Y.Z` (or `vX.Y.Z-rc.N` / `-beta.N`) and push
   the tag. A tag elsewhere is rejected before starting expensive builds.
4. Only when every selected build and WSL validation succeeds does the workflow
   create a **draft** GitHub Release with source/binary pairs and reports.
   Failed macOS builds also block the automatic draft; successful target
   artifacts remain available for evaluation. Draft creation is intentionally
   non-overwriting: a rerun against an existing release needs explicit handling.
5. Review [DISTRIBUTION.md](DISTRIBUTION.md), notices, source completeness and
   test evidence, then publish the draft. Successful CI does not certify every
   upstream asset or license. This initial workflow does not publish automatically.

Offline checks: `python3 -m unittest discover -s ci -p 'test_*.py' -v`,
`python3 utils/test_installation.py`, `python3 utils/test_benchmark_installation.py`.
