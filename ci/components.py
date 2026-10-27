#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Created in the personal fork on 2026-10-27: verified reuse of completed build components.
"""Cache components independently; SCons separately caches intermediate gem5 objects."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tarfile
import time


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def identity(component, repo, output, env):
    lock = json.loads((repo / 'ci/sources.lock.json').read_text())
    recipe = (repo / 'ci/steps.sh').read_text()
    phases = {'python': ['python-configure', 'python-build'],
              'toolchain': ['toolchain-configure', 'toolchain-build'],
              'gem5': ['gem5-build']}[component]
    fragments = [recipe.split('case "${1:?stage required}" in')[0]]
    for phase in phases:
        fragments.append(re.search(r'^' + phase + r'\)\n(.*?)^    ;;$', recipe, re.M | re.S)[1])
    environment = json.loads((output / 'environment.json').read_text())
    inputs = dict(schema=1, component=component, target=env['ASE_TARGET'],
                  source=lock[component], recipe=fragments,
                  packages=digest(output / 'packages.txt'),
                  compiler=environment['compiler'], cxx=environment.get('cxx'))
    if component == 'toolchain':
        inputs['profile'] = env['ASE_PROFILE']
    if component == 'gem5':
        inputs.update(python=identity('python', repo, output, env), scons=lock['scons_sha256'],
                      linker=env['GEM5_LINKER'],
                      patches={name: digest(repo / name) for name in
                               ('utils/patch_gem5.py', 'utils/gem5-runtime.patch')},
                      patch_recipe=(repo / 'ci/package.py').read_text().split(
                          'elif phase == "patch-gem5":')[1].split('elif phase == "stage":')[0])
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()


def extract(archive, destination):
    """Reject escaping paths/links even if a corrupt cache was restored."""
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            path = PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] != 'payload':
                raise ValueError('Unsafe cached path')
            if member.isdev() or member.isfifo():
                raise ValueError('Unsupported cached file type')
            if member.issym() or member.islnk():
                link = PurePosixPath(member.linkname)
                target = (destination / member.name).parent / member.linkname if member.issym() else destination / member.linkname
                if link.is_absolute() or not target.resolve().is_relative_to((destination / 'payload').resolve()):
                    raise ValueError('Unsafe cached link')
        tar.extractall(destination)


def restore(entry, destination):
    archive = entry / 'component.tar.gz'
    try:
        manifest = json.loads((entry / 'manifest.json').read_text())
        if digest(archive) != manifest['sha256']:
            return False
    except (FileNotFoundError, ValueError, KeyError):
        return False
    temporary = destination.with_name(destination.name + '.restore')
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True)
    try:
        extract(archive, temporary)
        if destination.exists():
            raise ValueError('Refusing to replace an existing component')
        (temporary / 'payload').replace(destination)
    finally:
        shutil.rmtree(temporary)
    return True


def save(entry, source):
    entry.mkdir(parents=True, exist_ok=True)
    archive = entry / 'component.tar.gz'
    temporary = entry / 'component.partial'
    with tarfile.open(temporary, 'w:gz', compresslevel=1) as tar:
        tar.add(source, arcname='payload')
    temporary.replace(archive)
    (entry / 'manifest.json').write_text(json.dumps({'sha256': digest(archive)}))


def main():
    action, component = sys.argv[1:]
    env = os.environ
    repo, work, output = (Path(env[k]) for k in ('ASE_REPO', 'ASE_WORK', 'ASE_OUTPUT'))
    cache = env.get('ASE_CACHE')
    if not cache:
        return 1 if action == 'restore' else 0
    key = identity(component, repo, output, env)
    entry = Path(cache) / 'components' / component / key
    destination = (work / 'sources/gem5/build/RISCV/gem5.opt' if component == 'gem5'
                   else work / 'prefix' / component)
    started = time.monotonic()
    if action == 'restore':
        destination.parent.mkdir(parents=True, exist_ok=True)
        hit = restore(entry, destination)
        status = 'hit' if hit else 'miss'
    elif action == 'save':
        save(entry, destination)
        # Keep one completed variant per target/component; SCons retains object reuse.
        for previous in entry.parent.iterdir():
            if previous != entry and previous.is_dir():
                shutil.rmtree(previous)
        hit, status = True, 'saved'
    else:
        raise ValueError(action)
    event = dict(component=component, key=key, action=action, status=status,
                 seconds=time.monotonic() - started)
    with (output / 'component-cache.jsonl').open('a') as stream:
        stream.write(json.dumps(event) + '\n')
    print(json.dumps(event), flush=True)
    return 0 if hit else 1


if __name__ == '__main__':
    sys.exit(main())
