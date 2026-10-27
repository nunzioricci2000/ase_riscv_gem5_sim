#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Created in the personal fork on 2026-10-27: check cache invalidation, corruption and safe restoration.
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('components', ROOT / 'ci/components.py')
components = importlib.util.module_from_spec(spec)
spec.loader.exec_module(components)


class ComponentTests(unittest.TestCase):
    def test_sdk_reuse_selects_only_matching_component(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sdk = root / 'ase-engine-test'
            (sdk / 'toolchain/bin').mkdir(parents=True)
            (sdk / 'toolchain/bin/gcc').write_text('compiler')
            (sdk / 'toolchain/bin/cc').symlink_to('gcc')
            (sdk / 'python').mkdir()
            (sdk / 'python/unrelated').write_text('different component')
            with tarfile.open(root / 'sdk.tar.gz', 'w:gz') as tar:
                tar.add(sdk, arcname=sdk.name)
            (root / 'reuse.json').write_text(json.dumps(dict(archive='sdk.tar.gz',
                component_keys={'toolchain': 'exact-inputs'})))
            self.assertFalse(components.restore_sdk(root, 'toolchain', 'other-inputs', root / 'bad', 'test'))
            self.assertTrue(components.restore_sdk(root, 'toolchain', 'exact-inputs', root / 'restored', 'test'))
            self.assertEqual((root / 'restored/bin/cc').read_text(), 'compiler')
            self.assertFalse((root / 'restored/unrelated').exists())

    def test_restore_preserves_executables_and_relative_links_and_rejects_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'
            source.mkdir()
            (source / 'compiler').write_text('binary')
            (source / 'compiler').chmod(0o755)
            (source / 'cc').symlink_to('compiler')
            entry = root / 'cache'
            components.save(entry, source)
            self.assertTrue(components.restore(entry, root / 'restored'))
            self.assertEqual((root / 'restored/cc').read_text(), 'binary')
            self.assertTrue((root / 'restored/compiler').stat().st_mode & 0o111)
            with (entry / 'component.tar.gz').open('ab') as stream:
                stream.write(b'corrupt')
            self.assertFalse(components.restore(entry, root / 'bad'))
            self.assertFalse((root / 'bad').exists())

    def test_restore_single_gem5_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'binary').write_bytes(b'gem5')
            components.save(root / 'cache', root / 'binary')
            self.assertTrue(components.restore(root / 'cache', root / 'restored'))
            self.assertEqual((root / 'restored').read_bytes(), b'gem5')

    def test_escaping_archive_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / 'bad.tar'
            for name, link in [('../escape', None), ('payload/link', '../../escape')]:
                with tarfile.open(archive, 'w') as tar:
                    info = tarfile.TarInfo(name)
                    if link:
                        info.type, info.linkname = tarfile.SYMTYPE, link
                    tar.addfile(info, io.BytesIO())
                with self.assertRaises(ValueError):
                    components.extract(archive, root / 'extract')
            self.assertFalse((root / 'escape').exists())

    def test_gem5_patch_does_not_invalidate_toolchain_or_python(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, output = root / 'repo', root / 'output'
            output.mkdir()
            shutil.copytree(ROOT / 'ci', repo / 'ci')
            (repo / 'utils').mkdir()
            for name in ('patch_gem5.py', 'gem5-runtime.patch'):
                shutil.copy2(ROOT / 'utils' / name, repo / 'utils' / name)
            (output / 'packages.txt').write_text('compiler 1.0')
            (output / 'environment.json').write_text(json.dumps({'compiler': 'gcc 1.0'}))
            env = dict(ASE_TARGET='linux-x64', ASE_PROFILE='full', GEM5_LINKER='default')
            def keys():
                return {c: components.identity(c, repo, output, env) for c in ('python', 'toolchain', 'gem5')}
            before = keys()
            (repo / 'utils/gem5-runtime.patch').write_text('different patch')
            after = keys()
            self.assertNotEqual(before['gem5'], after['gem5'])
            self.assertEqual(before['python'], after['python'])
            self.assertEqual(before['toolchain'], after['toolchain'])
            env['ASE_PROFILE'] = 'minimal'
            self.assertNotEqual(after['toolchain'], keys()['toolchain'])
            self.assertEqual(after['gem5'], keys()['gem5'])
            (output / 'packages.txt').write_text('compiler 2.0')
            self.assertTrue(all(after[c] != keys()[c] for c in after))


if __name__ == '__main__':
    unittest.main()
