# Third-party components and provenance

<!-- SPDX-License-Identifier: GPL-2.0-only -->
<!-- Created in the personal fork on 2026-10-27: record licensing boundaries. -->
<!-- Modified in the personal fork on 2026-10-27: document pinned engine build components. -->
<!-- Modified in the personal fork on 2026-10-27: document embedded Python build environment patch. -->
<!-- Modified in the personal fork on 2026-10-27: document TimeBuffer initialization fix. -->

- **ASE Studio** is a separate GPL-2.0-only repository at `ase_studio/`.
  Include its LICENSE and THIRD_PARTY.md and its exact pinned source revision.
- **gem5-derived configuration files** in `gem5/` retain their per-file
  copyright and license notices, including BSD-style notices. Preserve these;
  the repository's GPL license does not replace them.
- **External tools** (gem5, RISC-V toolchains and Konata) have independent
  upstream licenses. Install scripts are not a complete inventory of the
  licenses of their outputs. Audit the exact versions if bundling those tools.
- **Images and educational materials** require a provenance review before
  redistribution where permission is not explicit. Do not assume the code
  license covers university marks, third-party illustrations or personal labs.

This inventory identifies known boundaries, not an exhaustive asset audit.
See DISTRIBUTION.md before preparing a release.

## Experimental engine SDK pipeline

`ci/sources.lock.json` pins exact revisions, not moving branches:

- gem5 `6169bf94dc3f24b05303d2b4dbfbe765c0a04ac0`: its BSD-style LICENSE and
  per-file/third-party notices remain in force. The protobuf link-flags patch
  preserves its upstream notice and is included in the source snapshot.
  The SCons environment patch forwards PYTHONHOME and DYLD_LIBRARY_PATH to
  embedded-Python probes and build helpers, preserving the original BSD notice.
  `utils/gem5-runtime.patch` fixes MinorCPU entry register state and syscall
  draining; it retains the target files’ BSD-style terms. Full ARM notices
  are reproduced in `utils/gem5-runtime.patch.license` and in the patched sources.
  `utils/gem5-timebuffer.patch` explicitly initializes TimeBuffer slots so
  optimizing compilers cannot discard their intended zero initialization.
  It preserves the Michigan BSD-style notice, also reproduced in the adjacent
  `.license` file. Both patches are supplied with the corresponding sources.
- RISC-V toolchain `33eb59addcd65b8fd71f69fb42ccd2ea31bcbaf1`: the wrapper's
  LICENSE is not a substitute for its submodules' licenses. GCC
  `6afcc4f6da931eb93f3ab001a0dd9650ea71d1ea` and binutils
  `6ce87bbc521cf46eaee9a1f7ef61cee2cdfb3e32` include COPYING3; applicable
  runtime exceptions and individual notices must also be preserved. Newlib
  `8ba4275b83ec27529f67e0d477611fa6d8d6e6bd` has multiple licenses documented
  in COPYING.NEWLIB and its files. GDB's version is fixed by the parent gitlink.
  These are separate executables/libraries in an aggregate SDK, not code
  relicensed or linked into the GPL-2.0-only project. Do not label the SDK's
  entire contents GPL-2.0-only.
- CPython 3.10.19 `f08d3c437bc5f41973ddd11f4cfc3d9fe04010f7`: preserve its
  composite PSF license/history and embedded component notices. No pip runtime
  is installed; ensurepip is excluded from the binary SDK.
- SCons 4.8.0: MIT; source tarball SHA256 is fixed in the lock. This is a build
  tool, included as source for rebuilds, not installed in the runtime SDK.

The pipeline carries complete tracked working sources (including initialized
submodules and patches) alongside binaries and collects upstream LICENSE,
COPYING, NOTICE, COPYRIGHT and AUTHORS files with component-relative paths.
Original inline notices remain in the corresponding sources. System shared
libraries are not copied into the SDK; their installed versions are inventoried.
This is an inventory of the selected components, not a completed release audit.
No university logos, teaching images or generated Studio JavaScript are added
to the engine SDK. Review the actual output and all notices before publication.
