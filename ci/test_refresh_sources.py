# SPDX-License-Identifier: GPL-2.0-only
# Created in the personal fork on 2026-10-28: ensure packaging refresh preserves exact vendor sources and replaces obsolete project recipes.
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

from package import refresh_source_archive


class RefreshSourceTests(unittest.TestCase):
    def test_vendor_bytes_links_modes_and_notices_survive_while_project_is_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / 'old.tar.gz'
            contents = {f'sources/{name}/LICENSE': (name + ' original notice').encode()
                        for name in ('gem5', 'python', 'toolchain', 'build-tools')}
            contents['sources/gem5/code with spaces.cc'] = b'exact locally patched source\n'
            contents['sources/project/obsolete.py'] = b'must be removed'
            with tarfile.open(old, 'w:gz') as archive:
                for name, data in contents.items():
                    item = tarfile.TarInfo(name)
                    item.size, item.mode = len(data), 0o755
                    archive.addfile(item, io.BytesIO(data))
                link = tarfile.TarInfo('sources/gem5/relative-link')
                link.type, link.linkname = tarfile.SYMTYPE, 'code with spaces.cc'
                archive.addfile(link)
            project = root / 'project'
            (project / '__pycache__').mkdir(parents=True)
            (project / '__pycache__/ignored.pyc').write_bytes(b'cache')
            (project / 'new.py').write_text('current recipe')
            destination = root / 'new.tar.gz'
            refresh_source_archive(old, destination, [(project, 'project')])
            with tarfile.open(destination) as archive:
                names = archive.getnames()
                self.assertNotIn('sources/project/obsolete.py', names)
                self.assertFalse(any('__pycache__' in name for name in names))
                self.assertEqual(archive.extractfile('sources/project/new.py').read(), b'current recipe')
                for name, data in contents.items():
                    if '/project/' not in name:
                        self.assertEqual(archive.extractfile(name).read(), data)
                        self.assertEqual(archive.getmember(name).mode, 0o755)
                self.assertEqual(archive.getmember('sources/gem5/relative-link').linkname, 'code with spaces.cc')

    def test_incomplete_vendor_snapshot_never_produces_an_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old, new = root / 'old.tar.gz', root / 'new.tar.gz'
            with tarfile.open(old, 'w:gz') as archive:
                item = tarfile.TarInfo('sources/gem5/only-one-component')
                archive.addfile(item, io.BytesIO())
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                refresh_source_archive(old, new, [])
            self.assertFalse(new.exists())
            self.assertFalse(list(root.glob('*.partial')))


if __name__ == '__main__':
    unittest.main()
