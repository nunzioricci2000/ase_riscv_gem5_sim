#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Modified in the personal fork on 2026-10-27: apply the shared gem5 register and syscall fixes.
# Modified in the personal fork on 2026-10-27: include shared patch tooling in rebuild sources.
# Modified in the personal fork on 2026-10-27: test FP execution on Minor/O3 and ship TimeBuffer fix sources.
# Modified in the personal fork on 2026-10-27: restore and retest exact SDK/source pairs without rebuilding.
# Modified in the personal fork on 2026-10-27: distribute the DRAMPower comparator patch and BSD notices.
# Modified in the personal fork on 2026-10-28: compact staged host ELF files before relocation/runtime checks.
# Modified in the personal fork on 2026-10-28: use fast gzip for runtime/source archives after measuring compression tradeoffs.
# Created in the personal fork on 2026-10-27: source-complete engine SDK packaging.
"""Called inside the target build environment by steps.sh."""
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile


def run(*args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, **kwargs)


def capture(*args):
    return subprocess.check_output([str(x) for x in args], text=True).strip()


def tracked_files(repo):
    """Export initialized submodules too, including working patches; exclude build output."""
    listing = subprocess.check_output(["git", "-c", f"safe.directory={repo}", "-C", str(repo),
                                       "ls-files", "--stage", "-z"])
    for entry in listing.split(b"\0"):
        if not entry:
            continue
        fields, name = entry.split(b"\t", 1)
        relative = Path(os.fsdecode(name))
        path = repo / relative
        if fields.startswith(b"160000 "):
            if (path / ".git").exists():
                for child in tracked_files(path):
                    yield relative / child
        elif path.exists() or path.is_symlink():
            yield relative


def source_archive(path, repositories, extras):
    temporary = path.with_suffix(".partial")
    destination = path
    def keep_source(member):
        if ".git" in Path(member.name).parts or "__pycache__" in Path(member.name).parts or member.name.endswith(".pyc"):
            return None
        return member
    with tarfile.open(temporary, "w:gz", compresslevel=1) as archive:
        for name, repo in repositories.items():
            for relative in tracked_files(repo):
                archive.add(repo / relative, arcname=f"sources/{name}/{relative}", recursive=False)
        for path, name in extras:
            archive.add(path, arcname=f"sources/{name}", filter=keep_source)
    temporary.replace(destination)


def validate_links(root):
    for path in root.rglob("*"):
        if path.is_symlink():
            if os.path.isabs(os.readlink(path)) or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError(f"Non-relocatable symlink: {path}")
            if not path.exists():
                raise ValueError(f"Broken symlink: {path}")


def smoke(bundle, output):
    """Run from a relocated SDK, not from the build prefix; no source tree is needed."""
    output.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    for key in ("PYTHONHOME", "PYTHONPATH", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
        env.pop(key, None)
    gcc = bundle / "toolchain/bin/riscv64-unknown-elf-gcc"
    objdump = bundle / "toolchain/bin/riscv64-unknown-elf-objdump"
    cfile = output / "runtime.c"
    cfile.write_text('#include <stdio.h>\nint main(void) { return puts("ASE"); }\n')
    for arch, abi in (("rv32imac", "ilp32"), ("rv64gc", "lp64d")):
        elf = output / f"{arch}.elf"
        run(gcc, f"-march={arch}", f"-mabi={abi}", cfile, "-o", elf, env=env)
        run(objdump, "-d", elf, stdout=subprocess.DEVNULL, env=env)
    elf = output / "smoke.elf"
    run(gcc, "-march=rv32imafd_zicsr_zifencei", "-mabi=ilp32", "-nostdlib",
        bundle / "tests/smoke.s", "-o", elf, env=env)
    simulator = bundle / "bin/gem5"
    run(simulator, "--help", env=env, stdout=subprocess.DEVNULL)
    trace = output / "pipeline.log"
    with (output / "simulation.log").open("w") as log:
        run(simulator, "--debug-flags=MinorGUI,Exec", f"--debug-file={trace}",
            f"--outdir={output / 'm5out'}", bundle / "configs/riscv_in_order_hen_patt.py",
            "--cpu-type=MinorCPU", "--caches", "--cmd", elf,
            "--abs-max-tick=100000000", env=env, cwd=output, timeout=120,
            stdout=log, stderr=subprocess.STDOUT)
    if not trace.is_file() or not trace.stat().st_size:
        raise RuntimeError("Simulation did not produce a pipeline trace")
    trace_text = trace.read_text()
    if "ASE_INITIAL_REGISTERS_BEGIN thread=0" not in trace_text:
        raise RuntimeError("Simulation did not record the initial register state")
    if not re.search(r"div\s+x7,\s*x5,\s*x6\s+:.*\bD=0x0*7\b", trace_text):
        raise RuntimeError("Simulation exited before the final division wrote back 63 / 9 = 7")
    if "exiting with last active thread context" not in (output / "simulation.log").read_text():
        raise RuntimeError("Smoke program did not exit normally (possibly hit the tick limit)")
    fp_elf = output / "smoke-fp.elf"
    run(gcc, "-march=rv32imafd_zicsr_zifencei", "-mabi=ilp32", "-nostdlib",
        bundle / "tests/smoke-fp.s", "-o", fp_elf, env=env)
    checked = ["rv32imac-ilp32-link", "rv64gc-lp64d-link", "minor-final-integer-writeback"]
    for cpu, script in (("minor", "riscv_in_order_hen_patt.py"), ("o3", "riscv_o3_custom.py")):
        for memory in ("direct", "cache"):
            name = f"{cpu}-{memory}-fp"
            trace = output / f"{name}.trace"
            log_path = output / f"{name}.log"
            outdir = output / f"{name}-m5out"
            options = (["--cpu-type=MinorCPU", "--caches"] if cpu == "minor"
                       else ["--directory", outdir])
            with log_path.open("w") as log:
                run(simulator, "--debug-flags=MinorGUI,Exec", f"--debug-file={trace}",
                    f"--outdir={outdir}", bundle / "configs" / script,
                    "--cmd", fp_elf, "--abs-max-tick=100000000", f"--ase-memory-mode={memory}",
                    *options, env=env, cwd=output, timeout=120, stdout=log, stderr=subprocess.STDOUT)
            text = trace.read_text()
            if not re.search(r"fsw\s+f3,\s*24\(x5\).*\bD=0x0*40600000\b", text):
                raise RuntimeError(f"{name}: dependent FP operations did not store 3.5")
            if not re.search(r"fdiv_d\s+f6,\s*f4,\s*f5.*\bD=0x4012000000000000\b", text):
                raise RuntimeError(f"{name}: final FP division did not write back 4.5")
            if "exiting with last active thread context" not in log_path.read_text():
                raise RuntimeError(f"{name}: simulation did not exit normally")
            if cpu == "minor" and "ASE_INITIAL_REGISTERS_BEGIN thread=0" not in text:
                raise RuntimeError(f"{name}: initial register snapshot missing")
            checked.append(name)
    (output / "verified-runtime.json").write_text(json.dumps(checked, indent=2) + "\n")


def main():
    repo = Path(os.environ["ASE_REPO"])
    work = Path(os.environ["ASE_WORK"])
    output = Path(os.environ["ASE_OUTPUT"])
    sources, prefix = work / "sources", work / "prefix"
    target = os.environ["ASE_TARGET"]
    bundle = work / "relocated sdk" / f"ase-engine-{target}"
    phase = sys.argv[1]
    if phase == "environment":
        actual = {"arm64": "aarch64", "AMD64": "x86_64"}.get(platform.machine(), platform.machine())
        if actual != os.environ["ASE_ARCH"]:
            raise RuntimeError(f"Expected {os.environ['ASE_ARCH']}, got {actual}; no emulated builds")
        family = os.environ["ASE_FAMILY"]
        commands = {"debian": ["dpkg-query", "-W"], "fedora": ["rpm", "-qa"],
                    "arch": ["pacman", "-Q"], "macos": ["brew", "list", "--versions"]}
        (output / "packages.txt").write_text("\n".join(sorted(capture(*commands[family]).splitlines())) + "\n")
        # GCC's source tree requires a case-sensitive filesystem on macOS.
        probe = work / "case-sensitive-check"
        probe.write_text("probe")
        try:
            if probe.with_name("CASE-SENSITIVE-CHECK").exists():
                raise RuntimeError("Use a case-sensitive APFS volume for the macOS build")
        finally:
            probe.unlink()
        data = dict(platform=platform.platform(), machine=actual, cpu_count=os.cpu_count(),
                    disk_free_bytes=shutil.disk_usage(work).free,
                    memory=Path("/proc/meminfo").read_text() if Path("/proc/meminfo").exists() else capture("sysctl", "hw.memsize"),
                    compiler=capture(os.getenv("CC", "cc"), "--version"),
                    cxx=capture(os.getenv("CXX", "c++"), "--version"),
                    os_release=Path("/etc/os-release").read_text() if Path("/etc/os-release").exists() else None)
        if data["disk_free_bytes"] < 20 * 1024 ** 3:
            raise RuntimeError("At least 20 GiB free space is needed for the full source/build/package experiment")
        (output / "environment.json").write_text(json.dumps(data, indent=2) + "\n")
    elif phase == "patch-gem5":
        run(sys.executable, repo / "utils/patch_gem5.py", sources / "gem5")
        path = sources / "gem5/src/proto/SConsopts"
        content = path.read_text()
        old = "conf.CheckPkgConfig('protobuf', '--cflags', '--libs-only-L')"
        new = "conf.CheckPkgConfig('protobuf', '--cflags', '--libs')"
        if content.count(old) != 1:
            raise RuntimeError("Pinned gem5 protobuf patch context changed")
        # Preserve the original BSD notice; do not relabel upstream code GPL.
        path.write_text(content.replace(old, new).replace("Import('*')",
            "# Modified in the personal fork on 2026-10-27: retain protobuf transitive link flags.\nImport('*')", 1))
        path = sources / 'gem5/site_scons/gem5_scons/defaults.py'
        content = path.read_text()
        old = '            "LD_LIBRARY_PATH",\n'
        if content.count(old) != 1:
            raise RuntimeError('Pinned gem5 Python environment patch context changed')
        path.write_text(content.replace(old, old +
            '            "DYLD_LIBRARY_PATH",\n            "PYTHONHOME",\n').replace(
                'import os\n', '# Modified in the personal fork on 2026-10-27: preserve the embedded Python runtime environment.\nimport os\n', 1))
    elif phase == "stage":
        bundle.mkdir(parents=True)
        shutil.copytree(prefix / "toolchain", bundle / "toolchain", symlinks=True)
        shutil.copytree(prefix / "python", bundle / "python", symlinks=True,
                        ignore=shutil.ignore_patterns("__pycache__", "ensurepip"))
        (bundle / "gem5/bin").mkdir(parents=True)
        shutil.copy2(sources / "gem5/build/RISCV/gem5.opt", bundle / "gem5/bin/gem5.opt")
        shutil.copytree(sources / "gem5/configs", bundle / "gem5/configs",
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(repo / "gem5", bundle / "configs", ignore=shutil.ignore_patterns("__pycache__"))
        (bundle / "bin").mkdir()
        shutil.copy2(repo / "ci/gem5-launcher.sh", bundle / "bin/gem5")
        (bundle / "bin/gem5").chmod(0o755)
        from compact import compact_runtime
        compact_runtime(bundle, output / 'runtime-compaction.json')
        (bundle / "tests").mkdir()
        shutil.copy2(repo / "ci/smoke.s", bundle / "tests/smoke.s")
        shutil.copy2(repo / "ci/smoke-fp.s", bundle / "tests/smoke-fp.s")
        shutil.copy2(repo / "ci/package.py", bundle / "tests/package.py")
        for name in ("LICENSE", "THIRD_PARTY.md", "DISTRIBUTION.md"):
            shutil.copy2(repo / name, bundle / name)
        shutil.copy2(output / "packages.txt", bundle / "packages.txt")
        shutil.copy2(output / "environment.json", bundle / "environment.json")
        # Collect all upstream license/notice files, with paths preserving provenance.
        for component in ("python", "gem5", "toolchain"):
            for relative in tracked_files(sources / component):
                if relative.name.lower().startswith(("license", "copying", "notice", "copyright", "authors")):
                    src = sources / component / relative
                    if src.is_file():
                        dest = bundle / "licenses" / component / relative
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dest)
        for name in ("gem5-runtime.patch.license", "gem5-timebuffer.patch.license", "gem5-cxx17.patch.license"):
            destination = bundle / "licenses/gem5" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(repo / "utils" / name, destination)
        manifest = dict(target=target, sources=json.loads((repo / "ci/sources.lock.json").read_text()),
                        profile=os.environ["ASE_PROFILE"], jobs=int(os.environ["BUILD_JOBS"]),
                        linker=os.environ["GEM5_LINKER"], gui_included=False, archive_compression='gzip level 1',
                        runtime_dependencies="System libraries listed in packages.txt and runtime-links.txt",
                        source_archive=f"ase-engine-{target}-sources.tar.gz")
        (bundle / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        (bundle / "manifest.json.license").write_text("SPDX-License-Identifier: GPL-2.0-only\n")
        shutil.copy2(output / 'runtime-compaction.json', bundle / 'runtime-compaction.json')
        (bundle / 'runtime-compaction.json.license').write_text('SPDX-License-Identifier: GPL-2.0-only\n')
        (bundle / "README.txt").write_text(
            "ASE engine SDK — personal fork, experimental until tested on your platform.\n"
            "This contains gem5.opt, a bare-metal RV32/RV64 toolchain and Python 3.10.\n"
            "Extract on the matching distribution/architecture. System shared libraries\n"
            "remain required: see packages.txt and runtime-links.txt. This is not a\n"
            "universal static binary or a native Windows executable. Windows uses WSL2.\n"
            "Run bin/gem5 --help. In ASE Studio Settings select bin/gem5 as gem5 and\n"
            "toolchain/bin as the RISC-V toolchain. The GTK GUI is installed separately.\n"
            "Keep the matching sources archive and notices with any redistribution.\n"
            "Test: ASE_REPO=. ASE_WORK=unused ASE_OUTPUT=smoke ASE_TARGET=unused "
            "python3 tests/package.py test-bundle /absolute/path/to/this/sdk\n")
        validate_links(bundle)
        # Hide the original prefix so smoke tests cannot accidentally use its libraries.
        prefix.rename(work / "original-prefix-not-for-runtime")
    elif phase == "restore-sdk":
        from components import restore_bundle
        record = restore_bundle(work / 'reuse', (output / 'bundle-key.txt').read_text().strip(), bundle)
        for name in record['archives']:
            shutil.copy2(work / 'reuse' / name, output / name)
    elif phase in ("smoke", "test-bundle"):
        if phase == "test-bundle":
            bundle = Path(sys.argv[2]).resolve()
        smoke(bundle, (output / "smoke").resolve())
        binaries = [bundle / "gem5/bin/gem5.opt", bundle / "toolchain/bin/riscv64-unknown-elf-gcc"]
        with (output / "runtime-links.txt").open("w") as log:
            for binary in binaries:
                run(*(["otool", "-L"] if platform.system() == "Darwin" else ["ldd"]), binary,
                    stdout=log, stderr=subprocess.STDOUT,
                    env=dict(os.environ, LD_LIBRARY_PATH=str(bundle / "python/lib")))
        shutil.copy2(output / "runtime-links.txt", bundle / "runtime-links.txt")
    elif phase == "sources":
        extras = [(repo / "ci", "project/ci"), (repo / "gem5", "project/gem5"),
                  (repo / ".github/workflows", "project/.github/workflows")]
        extras += [(repo / name, f"project/{name}") for name in ("LICENSE", "THIRD_PARTY.md", "DISTRIBUTION.md", "RELEASES.md")]
        extras += [(repo / 'utils' / name, f'project/utils/{name}') for name in
                   ('patch_gem5.py', 'gem5-runtime.patch', 'gem5-runtime.patch.license',
                    'gem5-timebuffer.patch', 'gem5-timebuffer.patch.license',
                    'gem5-cxx17.patch', 'gem5-cxx17.patch.license')]
        extras += [(p, f"build-tools/{p.name}") for p in (sources / "build-tools").iterdir()]
        source_archive(output / f"ase-engine-{target}-sources.tar.gz",
                       {name: sources / name for name in ("gem5", "python", "toolchain")}, extras)
        revisions = {name: capture("git", "-C", sources / name, "rev-parse", "HEAD")
                     for name in ("gem5", "python", "toolchain")}
        revisions["toolchain_submodules"] = capture("git", "-C", sources / "toolchain", "submodule", "status")
        (output / "source-revisions.json").write_text(json.dumps(revisions, indent=2) + "\n")
    elif phase == "archive":
        temporary = output / f"ase-engine-{target}.tar.partial"
        with tarfile.open(temporary, "w:gz", compresslevel=1) as archive:
            archive.add(bundle, arcname=bundle.name)
        temporary.replace(output / f"ase-engine-{target}.tar.gz")
    else:
        raise ValueError(f"Unknown phase: {phase}")


if __name__ == "__main__":
    main()
