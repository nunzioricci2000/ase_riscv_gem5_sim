#!/usr/bin/env python3
"""Offline installer regressions. All builds/package operations use test doubles."""
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parent.parent
DISTROS = ('Arch', 'Ubuntu', 'Fedora')

# A single executable supplies command doubles, logging exact argument boundaries.
DOUBLE = r'''#!PYTHON
import json, os, pathlib, subprocess, sys
p = pathlib.Path
name = p(sys.argv[0]).name
args = sys.argv[1:]
root = p(os.environ['ROOT_DIR'])
with open(os.environ['TEST_LOG'], 'a') as log:
    log.write(json.dumps([name, args]) + '\n')
if name == 'git':
    assert args[0] == 'clone', args
    dest = p(args[-1]); dest.mkdir(parents=True)
    if 'riscv-gnu-toolchain' in args[-2]:
        (dest/'configure').symlink_to(p(os.environ['TEST_BIN'])/'configure')
    else:
        (dest/'SConstruct').touch()
elif name == 'configure':
    p('Makefile').touch()
elif name == 'make':
    if os.environ.get('FAIL_BUILD') == '1':
        sys.exit(7)
    target = root/'riscv-toolchain/bin'; target.mkdir(parents=True, exist_ok=True)
    for suffix in ('gcc', 'objdump'):
        path = target/f'riscv64-unknown-elf-{suffix}'
        if not path.exists(): path.symlink_to(p(os.environ['TEST_BIN'])/f'fake-{suffix}')
elif name.endswith('gcc'):
    if args == ['-dumpmachine']:
        print('riscv64-unknown-elf')
    elif os.environ.get('FAIL_COMPILER') == '1':
        sys.exit(1)
    else:
        p(args[args.index('-o')+1]).write_bytes(b'ELF')
elif name.endswith('objdump'):
    sys.exit(1 if os.environ.get('FAIL_OBJDUMP') == '1' else 0)
elif name == 'virtualenv':
    dest = p(args[-1])/'bin'; dest.mkdir(parents=True)
    (dest/'python').symlink_to(p(os.environ['TEST_BIN'])/'venv-python')
    (dest/'scons').touch()
elif name in ('venv-python', 'python'):
    if args[:2] == ['-c', 'import importlib.metadata as m; assert m.version("scons") == "4.8.0"']:
        sys.exit(0 if (root/'myenv/ready').exists() else 1)
    if args[:2] == ['-m', 'pip']:
        (root/'myenv/ready').touch()
    elif args and args[0].endswith('/scons'):
        if os.environ.get('FAIL_BUILD') == '1': sys.exit(7)
        target = root/'gem5/build/RISCV'; target.mkdir(parents=True, exist_ok=True)
        binary = target/'gem5.opt'
        binary.write_text('#!/bin/sh\n[ "$1" = --help ]\n'); binary.chmod(0o755)
    else:
        sys.exit(subprocess.call([os.environ['TEST_PYTHON'], *args]))
elif name == 'sudo':
    # Deliberately never run a package manager or dependency script.
    with open(os.environ['TEST_LOG'], 'a') as log:
        log.write(json.dumps(['sudo-context', [os.environ.get('ASE_PACKAGE_INDEX_READY')]]) + '\n')
elif name in ('pacman', 'apt-get', 'apt', 'dnf', 'dnf5', 'add-apt-repository'):
    pass
elif name == 'apt-cache':
    sys.exit(0 if os.environ.get('PYTHON_PACKAGE_AVAILABLE', '1') == '1' else 1)
elif name == 'runuser':
    if any('makepkg' in arg for arg in args):
        target = p(os.environ['TEST_BIN'])/'python3.10'
        target.write_text('#!/bin/sh\nexit 0\n'); target.chmod(0o755)
elif name == 'python3':
    if any('import gi' in arg for arg in args): sys.exit(1)
    sys.exit(subprocess.call([os.environ['TEST_PYTHON'], *args]))
else:
    raise RuntimeError(name)
'''


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ase installer test ')
        self.base = Path(self.temp.name)
        self.repo = self.base/'project'
        self.repo.mkdir()
        shutil.copytree(REPO/'utils', self.repo/'utils')
        shutil.copy(REPO/'setup_default', self.repo/'setup_default')
        shutil.copy(REPO/'ase_studio_branches.json', self.repo/'ase_studio_branches.json')
        self.bin = self.base/'bin'; self.bin.mkdir()
        self.log = self.base/'calls.jsonl'
        self.env = {k: v for k, v in os.environ.items() if k not in (
            'RISCV_TOOLCHAIN_PATH', 'TOOLCHAIN_MODE', 'GEM5_LINKER', 'GEM5_BUILD_CACHE',
            'GEM5_PYTHON', 'GEM5_PYTHON_CONFIG', 'SELECTED_TOOLCHAIN_BIN')}
        self.env.update(PATH=f'{self.bin}:{os.environ["PATH"]}',
                        ROOT_DIR=str(self.repo/'tools'), WORK_DIR=str(self.repo),
                        UTILS_DIR=str(self.repo/'utils'), GEM5_REQUIRED_BRANCH='stable',
                        GEM5_PYTHON=sys.executable, GEM5_PYTHON_CONFIG='/bin/true',
                        TEST_PYTHON=sys.executable, TEST_BIN=str(self.bin),
                        TEST_LOG=str(self.log), BUILD_JOBS='3', PYTHONDONTWRITEBYTECODE='1')
        body = DOUBLE.replace('#!PYTHON', f'#!{sys.executable}', 1)
        for command in ('git', 'configure', 'make', 'fake-gcc', 'fake-objdump',
                        'virtualenv', 'venv-python', 'sudo', 'pacman', 'apt-get', 'apt',
                        'dnf', 'dnf5', 'apt-cache', 'add-apt-repository', 'runuser'):
            path = self.bin/command; path.write_text(body); path.chmod(0o755)

    def tearDown(self):
        self.temp.cleanup()

    def run_bash(self, code, *, success=True, **env):
        proc = subprocess.run(['bash', '-c', code], cwd=self.repo,
                              env={**self.env, **env}, capture_output=True, text=True)
        if success:
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        else:
            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc

    def calls(self, name):
        if not self.log.exists(): return []
        return [args for command, args in map(json.loads, self.log.read_text().splitlines())
                if command == name]

    def test_jobs_matrix(self):
        for cpus, memory, expected in ((1, 64*1048576, 1), (8, 32*1048576, 8),
                                       (32, 5*1048576, 2), (8, 512*1024, 1)):
            with self.subTest(cpus=cpus, memory=memory):
                proc = self.run_bash(f'''source utils/install_build.sh
nproc() {{ echo {cpus}; }}
available_build_memory_kib() {{ echo {memory}; }}
select_build_jobs
echo "$BUILD_JOBS"''', BUILD_JOBS='')
                self.assertEqual(proc.stdout.strip(), str(expected))
        proc = self.run_bash('source utils/install_build.sh; select_build_jobs; echo "$BUILD_JOBS"')
        self.assertEqual(proc.stdout.strip(), '3')
        for value in ('0', '-1', '01', 'hello', '9999999', '2; exit 0'):
            with self.subTest(value=value):
                self.run_bash('set -e; source utils/install_build.sh; select_build_jobs',
                              success=False, BUILD_JOBS=value)

    def test_memory_limits_include_parent_cgroups(self):
        procfs = self.base/'proc'; (procfs/'self').mkdir(parents=True)
        (procfs/'meminfo').write_text('MemTotal: 33554432 kB\nMemAvailable: 16777216 kB\n')
        cgroup = self.base/'cgroup'; (cgroup/'parent/child').mkdir(parents=True)
        common = self.repo/'utils/install_build.sh'
        common.write_text(common.read_text().replace('/proc/', str(procfs)+'/')
                          .replace('/sys/fs/cgroup', str(cgroup)))
        (procfs/'self/cgroup').write_text('0::/parent/child\n')
        (cgroup/'parent/child/memory.max').write_text('max')
        (cgroup/'parent/child/memory.current').write_text('0')
        (cgroup/'parent/memory.max').write_text(str(4*1024**3))
        (cgroup/'parent/memory.current').write_text(str(1024**3))
        result = self.run_bash('source utils/install_build.sh; available_build_memory_kib')
        self.assertEqual(int(result.stdout), 3*1024**2)
        # Legacy cgroup v1 also caps available memory.
        (procfs/'self/cgroup').write_text('5:memory:/test\n')
        (cgroup/'memory/test').mkdir(parents=True)
        (cgroup/'memory/test/memory.limit_in_bytes').write_text(str(2*1024**3))
        (cgroup/'memory/test/memory.usage_in_bytes').write_text(str(1024**3))
        result = self.run_bash('source utils/install_build.sh; available_build_memory_kib')
        self.assertEqual(int(result.stdout), 1024**2)

    def test_all_source_wrappers_resume_after_failure(self):
        for distro in DISTROS:
            with self.subTest(distro=distro):
                root = self.base/distro
                script = f'bash utils/Linux/{distro}/riscv-toolchain_install.sh'
                self.run_bash(script, success=False, ROOT_DIR=str(root), FAIL_BUILD='1')
                self.assertTrue((root/'riscv-gnu-toolchain/Makefile').exists())
                self.run_bash(script, ROOT_DIR=str(root))
                self.assertTrue((root/'riscv-toolchain/bin/riscv64-unknown-elf-gcc').exists())
                self.assertTrue((root/'riscv-gnu-toolchain').exists())
        self.assertEqual(len(self.calls('git')), 3)
        self.assertTrue(all('--depth' in call and '--recursive' not in call for call in self.calls('git')))
        self.assertEqual(len(self.calls('configure')), 3)
        self.assertEqual(self.calls('make'), [['-j', '3']]*6)
        self.assertTrue(all('--enable-multilib' in call for call in self.calls('configure')))

    def test_all_gem5_wrappers_reuse_environment(self):
        for distro in DISTROS:
            with self.subTest(distro=distro):
                root = str(self.base/distro)
                script = f'bash utils/Linux/{distro}/gem5_install.sh'
                self.run_bash(script, success=False, ROOT_DIR=root, FAIL_BUILD='1')
                self.run_bash(script, ROOT_DIR=root, GEM5_LINKER='lld',
                              GEM5_BUILD_CACHE=str(self.base/'object cache'))
        self.assertEqual(len(self.calls('git')), 3)
        self.assertEqual(len(self.calls('virtualenv')), 3)
        python_calls = self.calls('python')
        self.assertEqual(len([x for x in python_calls if x[:2] == ['-m', 'pip']]), 3)
        builds = [x for x in python_calls if x and x[0].endswith('/scons')]
        self.assertEqual(len(builds), 6)
        self.assertTrue(all('build/RISCV/gem5.opt' in x for x in builds))
        self.assertTrue(all('--linker=lld' in x for x in builds[1::2]))

    def test_partial_toolchain_is_rejected(self):
        compiler = self.bin/'riscv64-elf-gcc'; compiler.symlink_to(self.bin/'fake-gcc')
        code = f'source utils/install_build.sh; toolchain_works "{compiler}"'
        self.run_bash(code, success=False)  # Missing objdump.
        (self.bin/'riscv64-elf-objdump').symlink_to(self.bin/'fake-objdump')
        self.run_bash(code, success=False, FAIL_COMPILER='1')
        self.run_bash(code, success=False, FAIL_OBJDUMP='1')
        self.run_bash(code)

    def set_distro(self, distro):
        release = self.base/'os-release'
        release.write_text(f'ID={distro.lower()}\nVERSION_ID=22.04\n')
        path = self.repo/'utils/installation.sh'
        path.write_text((REPO/'utils/installation.sh').read_text().replace('/etc/os-release', shlex.quote(str(release))))

    def test_existing_external_toolchain_avoids_build_and_sudo(self):
        for distro in DISTROS:
            with self.subTest(distro=distro):
                self.set_distro(distro)
                external = self.base/f'{distro} external'; external.mkdir()
                for suffix in ('gcc', 'objdump'):
                    (external/f'riscv64-elf-{suffix}').symlink_to(self.bin/f'fake-{suffix}')
                self.run_bash('bash utils/installation.sh toolchain', RISCV_TOOLCHAIN_PATH=str(external))
                self.assertEqual((self.repo/'tools/toolchain.path').read_text().splitlines(),
                                 [str(external), 'riscv64-elf'])
                proc = self.run_bash('source setup_default >/dev/null; printf "%s" "$CC"',
                                     RISCV_TOOLCHAIN_PATH='', PYTHONPATH='')
                self.assertEqual(proc.stdout, str(external/'riscv64-elf-gcc'))
        self.assertEqual(self.calls('sudo'), [])
        self.assertEqual(self.calls('make'), [])
        self.assertEqual(self.calls('git'), [])

    def test_main_source_retry_then_skip_on_all_distros(self):
        for distro in DISTROS:
            with self.subTest(distro=distro):
                self.set_distro(distro)
                root = self.repo/'tools'
                if root.exists(): shutil.rmtree(root)
                self.run_bash('bash utils/installation.sh toolchain', success=False,
                              TOOLCHAIN_MODE='source', FAIL_BUILD='1')
                self.assertFalse((root/'toolchain.path').exists())
                self.run_bash('bash utils/installation.sh toolchain', TOOLCHAIN_MODE='source')
                counts = len(self.calls('make')), len(self.calls('sudo'))
                self.run_bash('bash utils/installation.sh toolchain', TOOLCHAIN_MODE='source')
                self.assertEqual(counts, (len(self.calls('make')), len(self.calls('sudo'))))

    def test_all_ase_reuses_refresh_and_preserves_selection(self):
        python = self.bin/'python3'
        python.write_text(DOUBLE.replace('#!PYTHON', f'#!{sys.executable}', 1))
        python.chmod(0o755)
        studio = self.repo/'ase_studio'; studio.mkdir()
        (studio/'install.sh').write_text('#!/bin/sh\nexit 0\n')
        for distro in DISTROS:
            with self.subTest(distro=distro):
                self.set_distro(distro)
                root = self.repo/'tools'
                if root.exists(): shutil.rmtree(root)
                self.log.write_text('')
                self.run_bash('bash utils/installation.sh all-ase', TOOLCHAIN_MODE='source',
                              ASE_PACKAGE_INDEX_READY='1')
                self.assertEqual(self.calls('sudo-context')[:2], [['0'], ['1']])
                sudo_calls = self.calls('sudo')
                self.assertEqual(sum('update' in call or '-Syu' in call for call in sudo_calls), 0)
                selection = (root/'toolchain.path').read_text()
                self.run_bash('bash utils/installation.sh gem5')
                self.assertEqual((root/'toolchain.path').read_text(), selection)
                self.assertEqual(len(self.calls('make')), 1)
                self.assertEqual(self.calls('sudo'), sudo_calls)

    def test_saved_prefix_wins_over_another_executable_in_same_directory(self):
        root = self.repo/'tools'; root.mkdir()
        for prefix in ('riscv-none-elf', 'riscv64-elf'):
            for suffix in ('gcc', 'objdump'):
                (self.bin/f'{prefix}-{suffix}').symlink_to(self.bin/f'fake-{suffix}')
        (root/'toolchain.path').write_text(f'{self.bin}\nriscv64-elf\n')
        proc = self.run_bash('source setup_default >/dev/null; printf "%s" "$CC"', PYTHONPATH='')
        self.assertEqual(proc.stdout, str(self.bin/'riscv64-elf-gcc'))

    def test_default_local_path_does_not_prevent_resuming(self):
        self.set_distro('Ubuntu')
        self.run_bash('bash utils/installation.sh toolchain',
                      RISCV_TOOLCHAIN_PATH=str(self.repo/'tools/riscv-toolchain/bin'))
        self.assertEqual(len(self.calls('make')), 1)

    def test_python_dependencies_and_parallel_arch_build(self):
        for distro in DISTROS:
            path = self.repo/f'utils/Linux/{distro}/gem5_dep.sh'
            path.write_text(path.read_text().replace('$EUID', '0'))
        self.run_bash('bash utils/Linux/Ubuntu/gem5_dep.sh', GEM5_PYTHON='',
                      PYTHON_PACKAGE_AVAILABLE='0')
        self.assertEqual(len(self.calls('add-apt-repository')), 1)
        self.assertIn(['install', '-y', 'python3.10', 'python3.10-dev', 'python3.10-venv'],
                      self.calls('apt-get'))
        self.run_bash('bash utils/Linux/Fedora/gem5_dep.sh', GEM5_PYTHON='')
        self.assertIn(['install', '-y', 'python3.10', 'python3.10-devel'], self.calls('dnf5'))
        self.run_bash('''command() {
    if [[ "$1" == -v && "$2" == python3.10 && ! -f "$TEST_BIN/python3.10" ]]; then
        return 1
    fi
    builtin command "$@"
}
export -f command
bash utils/Linux/Arch/gem5_dep.sh''', GEM5_PYTHON='', SUDO_USER='testuser')
        builds = [call for call in self.calls('runuser') if any('makepkg' in arg for arg in call)]
        self.assertEqual(len(builds), 1)
        self.assertIn('MAKEFLAGS=-j$2', ' '.join(builds[0]))
        self.assertEqual(builds[0][-2:], ['3', '0'])

    def test_explicit_bad_external_path_fails_without_installation(self):
        self.set_distro('Ubuntu')
        self.run_bash('bash utils/installation.sh toolchain', success=False,
                      RISCV_TOOLCHAIN_PATH=str(self.base/'missing'))
        self.assertEqual(self.calls('sudo'), [])
        self.assertEqual(self.calls('git'), [])

    def test_package_policy_without_root_or_real_package_managers(self):
        for distro in DISTROS:
            for component in ('gem5', 'riscv-toolchain'):
                with self.subTest(distro=distro, component=component):
                    path = self.repo/f'utils/Linux/{distro}/{component}_dep.sh'
                    # Only remove the privilege guard in this disposable fixture.
                    path.write_text(path.read_text().replace('$EUID', '0'))
                    # Partial installation directories must not block dependencies.
                    (self.repo/'tools/gem5').mkdir(parents=True, exist_ok=True)
                    (self.repo/'tools/riscv-toolchain').mkdir(exist_ok=True)
                    script = f'bash utils/Linux/{distro}/{component}_dep.sh'
                    self.run_bash(script, ASE_PACKAGE_INDEX_READY='0')
                    self.run_bash(script, ASE_PACKAGE_INDEX_READY='1')
        apt_calls = self.calls('apt') + self.calls('apt-get')
        self.assertFalse(any('upgrade' in call for call in apt_calls))
        self.assertEqual(sum(call == ['update'] for call in apt_calls), 2)
        self.assertEqual(sum('-Syu' in call for call in self.calls('pacman')), 2)
        self.assertFalse(any('clang-format' in ' '.join(call) for call in apt_calls))

    def test_invalid_settings_fail_before_installation(self):
        self.set_distro('Ubuntu')
        for env in ({'BUILD_JOBS': '0'}, {'TOOLCHAIN_MODE': 'unknown'}):
            proc = self.run_bash('bash utils/installation.sh toolchain', success=False, **env)
            self.assertIn(f'{next(iter(env))} must be', proc.stderr)
        self.assertEqual(self.calls('sudo'), [])
        self.assertEqual(self.calls('git'), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
