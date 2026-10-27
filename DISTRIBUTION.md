# Distribution checklist

<!-- SPDX-License-Identifier: GPL-2.0-only -->
<!-- Created in the personal fork on 2026-10-27: redistribution guidance. -->

This is a practical release checklist, not a certification of every asset.
The project code is GPL-2.0-only; separately licensed components retain their
notices. Educational use is a purpose, not a restriction on GPL permissions.

Before distributing a source archive, executable, installer or bundled app:

1. Include LICENSE, THIRD_PARTY.md, required third-party license texts and
   warranty notices. Identify this as a modified personal fork and preserve
   original authorship. Check dated modification notices in modified GPL files.
   Review older fork changes too; do not invent historical dates or authors.
2. Supply the complete corresponding source for the exact distributed build,
   including local changes, interface files and build/install scripts. Include
   the preferred editable sources of bundled dependencies, not only minified
   JavaScript, generated files, lockfiles or a link to an upstream home page.
   For online binaries, offer the corresponding source alongside them with
   equivalent access (GPL v2 §3). Other distribution methods require one of
   the alternatives in §3; a written offer has specific three-year obligations.
3. Preserve dependency versions and provenance. Archive the source and notices
   needed for that release, even if an upstream URL later disappears. A clean
   dependency installation and a successful build help validate completeness;
   they do not by themselves satisfy source-distribution obligations.
4. Check third-party assets, including logos, images and fonts, for permission
   to redistribute. Code licensing does not automatically grant trademark
   rights. Resolve uncertain provenance or omit the affected asset from release.
5. Review anything actually bundled (including gem5, toolchains and runtimes)
   under its own license. Merely naming or downloading an external tool does
   not mean its entire licensing has been audited here.
6. Verify that the archive contains every required file and that documented
   build/install steps work from the supplied sources. Preserve recipients'
   rights to modify and redistribute; do not impose additional restrictions.

For the simulator, include the exact ASE Studio submodule revision and its
sources/notices; a GitHub source archive of the parent alone does not include
submodule contents. Publish a Studio commit before a parent commit pins it.
For Studio alone, include its own LICENSE, documentation and frontend notices.

References: [GPL v2](https://www.gnu.org/licenses/old-licenses/gpl-2.0.en.html),
[GNU FAQ](https://www.gnu.org/licenses/gpl-faq.html), and
[MPL/GPL integration](https://www.mozilla.org/en-US/MPL/2.0/combining-mpl-and-gpl/).
