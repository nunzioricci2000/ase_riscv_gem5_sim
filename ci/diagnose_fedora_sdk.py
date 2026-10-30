#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Created in the personal fork on 2026-10-28: inspect a previous Fedora SDK against changed system packages without changing production reuse rules.
# Modified in the personal fork on 2026-10-28: distinguish a PAM runtime plugin from linker development inputs and check whether PAM is used.
"""Isolated diagnostic: verify old SDK bytes, package inputs and actual ELF closures."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import zipfile

from components import identity, restore_bundle
from reuse import api, component_keys, unpack_verified

TARGET = 'fedora-43-x86_64'
ARTIFACT = 12790270382
REVISION = '30313eeaebb4e95c59f8a99b5bf10bbf3779b670'
CHANGED = {'libblkid', 'libfdisk', 'liblastlog2', 'libmount', 'libsmartcols', 'libuuid',
           'openssh', 'openssh-clients', 'util-linux', 'util-linux-core'}


def capture(*args, env=None):
    return subprocess.check_output(args, text=True, env=env).strip()


def write(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n')


def packages(text):
    result = {}
    for line in text.splitlines():
        name, version, release = line.rsplit('-', 2)
        assert name not in result, 'Ambiguous package architecture: ' + name
        result[name] = (version, release)
    return result


def prepare(output, work):
    repo = os.environ['GITHUB_REPOSITORY']
    assert repo == 'nunzioricci2000/ase_riscv_gem5_sim'
    work.mkdir(parents=True, exist_ok=True)
    download = work / 'download.zip'
    try:
        api(f'repos/{repo}/actions/artifacts/{ARTIFACT}/zip', download)
        with zipfile.ZipFile(download) as archive:
            report = json.loads(archive.read('report.json'))
            assert report['status'] == 'succeeded' and report['git_sha'] == REVISION
            assert report['target']['id'] == TARGET
            previous = archive.read('packages.txt')
            keys = component_keys(report)
            env = dict(ASE_TARGET=TARGET, ASE_PROFILE='full', GEM5_LINKER='default')
            root = Path(__file__).resolve().parent.parent
            expected = {name: identity(name, root, output, env,
                        packages_hash=hashlib.sha256(previous).hexdigest())
                        for name in ('python', 'toolchain', 'gem5')}
            assert keys == expected, 'The difference is not confined to the package inventory'
            before = packages(previous.decode())
            after = packages((output / 'packages.txt').read_text())
            changed = {name for name in before.keys() | after.keys() if before.get(name) != after.get(name)}
            assert changed == CHANGED, sorted(changed)
            (output / 'previous-packages.txt').write_bytes(previous)
            write(output / 'previous-report.json', report)
        # Keep old identities: this diagnostic does not claim current-input equivalence.
        record = unpack_verified(download, work, TARGET, keys, 'dependency-diagnostic')
        assert record and record['refresh_sdk']
        write(work / 'reuse.json', record)
        write(output / 'verified-previous-sdk.json', record)
    finally:
        download.unlink(missing_ok=True)


def native_elf(path):
    with path.open('rb') as stream:
        header = stream.read(64)
    return (len(header) == 64 and header[:6] == b'\x7fELF\x02\x01'
            and struct.unpack_from('<H', header, 18)[0] == 62
            and struct.unpack_from('<H', header, 16)[0] in (2, 3))


def inspect(output, work):
    record = json.loads((work / 'reuse.json').read_text())
    sdk = Path('/work/previous-sdk') / ('ase-engine-' + TARGET)
    restore_bundle(work, None, sdk, refresh_keys=record['component_keys'])
    env = dict(os.environ, LD_LIBRARY_PATH=str(sdk / 'python/lib'))
    owner_cache = {}
    def owner(path):
        path = str(Path(path).resolve())
        if path not in owner_cache:
            owner_cache[path] = capture('rpm', '-qf', '--qf', '%{NAME}\n', path).splitlines()
        return owner_cache[path]
    def linked(path):
        result = subprocess.run(['ldd', str(path)], capture_output=True, text=True, env=env)
        text = result.stdout + result.stderr
        assert 'not found' not in text, str(path) + ': ' + text
        assert result.returncode == 0 or any(s in text for s in ('not a dynamic executable', 'statically linked')), text
        paths = set(re.findall(r'(?:=>\s+|^\s*)(/[^\n]*?)\s+\(0x', text, re.M))
        return {p: owner(p) for p in sorted(paths) if not Path(p).resolve().is_relative_to(sdk)}
    sdk_links = {}
    for path in sdk.rglob('*'):
        if path.is_file() and not path.is_symlink() and native_elf(path):
            sdk_links[str(path.relative_to(sdk))] = linked(path)
    commands = ('cc c++ gcc g++ as ld ar ranlib nm objcopy objdump strip make gawk bison flex m4 gperf bc '
                'perl python3 bash sh pkg-config git curl tar gzip xz patch makeinfo texi2any automake '
                'autoconf libtoolize install find sort sed grep awk cut head tail uname tr readlink realpath '
                'mkdir rm cp ln touch date stat dd expr getconf od cmp diff wc cat basename dirname '
                'sleep test env nproc').split()
    build_tools, missing = {}, []
    for name in commands:
        path = shutil.which(name)
        if path is None:
            missing.append(name)
            continue
        path = Path(path).resolve()
        build_tools[name] = dict(path=str(path), owners=owner(path),
                                libraries=linked(path) if native_elf(path) else {})
    development, runtime_plugins = {}, {}
    for name in sorted(CHANGED):
        paths = capture('rpm', '-ql', name).splitlines()
        development[name] = [p for p in paths if '/include/' in p or
                             p.endswith(('.h', '.hh', '.hpp', '.pc', '.a', '.la')) or
                             (p.endswith('.so') and str(Path(p).parent) in
                              ('/usr/lib64', '/usr/lib', '/lib64', '/lib'))]
        runtime_plugins[name] = [p for p in paths if p.endswith('.so') and p not in development[name]]
    used = set()
    for libraries in sdk_links.values():
        used.update(p for providers in libraries.values() for p in providers)
    for tool in build_tools.values():
        used.update(tool['owners'])
        used.update(p for providers in tool['libraries'].values() for p in providers)
    affected = sorted(CHANGED & used)
    if 'pam' in used:
        affected = sorted(set(affected) | {name for name, paths in runtime_plugins.items()
                          if any('/security/pam_' in p for p in paths)})
    report = dict(changed_packages=sorted(CHANGED), native_sdk_files=len(sdk_links),
                  sdk_library_closures=sdk_links, build_tools=build_tools, missing_optional_tools=missing,
                  runtime_plugins_in_changed_packages=runtime_plugins,
                  development_files_in_changed_packages=development, changed_packages_used=affected,
                  status='succeeded' if not affected and not any(development.values()) else 'failed')
    write(output / 'dependency-compatibility.json', report)
    print(json.dumps({k: v for k, v in report.items() if k not in ('sdk_library_closures', 'build_tools')}, indent=2))
    assert report['status'] == 'succeeded', 'Changed packages reach a checked build/runtime input'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['prepare', 'inspect'])
    parser.add_argument('output', type=Path)
    parser.add_argument('work', type=Path)
    args = parser.parse_args()
    (prepare if args.mode == 'prepare' else inspect)(args.output, args.work)


if __name__ == '__main__':
    main()
