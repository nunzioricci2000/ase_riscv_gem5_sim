<!-- Modified in the personal fork on 2026-10-27: clarify licensing and redistribution requirements. -->
<!-- Modified in the personal fork on 2026-10-27: link measured binary build and Gitflow workflow. -->
<!-- Modified in the personal fork on 2026-10-27: reserve main/develop for the personal fork. -->
<!-- Modified in the personal fork on 2026-10-28: distinguish downloadable desktop applications from engine-only SDK packages. -->
<!-- Modified in the personal fork on 2026-10-30: replace the copied upstream guide with a fork-only overview and links to original documentation. -->
# RISC-V gem5 simulator · personal fork

This repository contains Nunzio's changes to
[cad-polito-it/ase_riscv_gem5_sim](https://github.com/cad-polito-it/ase_riscv_gem5_sim).
For the course environment, standard setup, simulation commands and creating
programs, use the **[original documentation](https://github.com/cad-polito-it/ase_riscv_gem5_sim#readme)**.
Local documentation covers only additions, corrections and different behavior.

For the desktop application, start with **[ASE Studio di Nunzio · Abate](https://github.com/nunzioricci2000/ase-studio#readme)**:
its README starts with the standalone installer. Studio is an independent
repository included here as the `ase_studio` submodule.

## What this fork changes

- **Installation and incremental builds:** reuse verified local toolchains,
  resume interrupted builds, choose parallelism from available resources and
  measure installation stages.
- **gem5 corrections:** reliable final/initial register traces, O3 TimeBuffer
  initialization, floating-point bit preservation and build compatibility fixes.
- **Prebuilt engine SDKs:** platform-specific binary/source pairs with checksums,
  component caches and runtime verification. These contain the engine, not the GUI.
- **Personal Studio integration:** the Abate editor/package additions, explicit
  checkout selection and a pinned Studio submodule revision.

[Detailed fork changes and source installation](FORK.md) ·
[SDK build/release workflow](RELEASES.md) ·
[Personal fork issues](https://github.com/nunzioricci2000/ase_riscv_gem5_sim/issues).

## Contributors

- Francesco Angione (francesco.angione@polito.it)
- Nicola di Gruttola giardino (nicola.digruttola@polito.it)
- Behnam Farnaghinejad (behnam.farnaghinejad@polito.it)
- Gabriele Filipponi (gabriele.filipponi@polito.it)
- Giorgio Insinga (giorgio.insinga@polito.it)
- Annachiara Ruospo (annachiara.ruospo@polito.it)
- Antonio Porsia (antonio.porsia@polito.it)

These original-project attributions are retained. This personal fork is not
presented as endorsed by the original authors or Politecnico di Torino.

## License and redistribution

The project code is **GPL-2.0-only**, except for components with their own
license notices. You may redistribute and modify it, including commercially,
subject to the applicable license conditions. Preserve upstream attribution
and identify changes made in this personal fork. The software is provided
without warranty; see [LICENSE](LICENSE).

See [distribution requirements](DISTRIBUTION.md), [third-party components](THIRD_PARTY.md)
and [contributor instructions](AGENTS.md). Keep all required license notices
and provide corresponding source when distributing built artifacts.

[Scheduled upstream integration proposals](UPSTREAM_SYNC.md).
