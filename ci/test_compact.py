#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Created in the personal fork on 2026-10-28: verify native exports survive stripping and external/target files remain intact.
import ctypes
import hashlib
import os
from pathlib import Path
import platform
import subprocess
import tempfile
import unittest

from compact import compact_runtime


@unittest.skipUnless(platform.system() == 'Linux', 'Host ELF integration test')
class CompactTests(unittest.TestCase):
    def test_strip_keeps_exports_and_never_mutates_external_links_or_target_objects(self):
        with tempfile.TemporaryDirectory(prefix='ase-strip-test-') as directory:
            root = Path(directory)
            source, original = root / 'source.c', root / 'original.so'
            source.write_text('int exported_value(void) { return 42; }\n')
            subprocess.run(['cc', '-g', '-shared', '-fPIC', str(source), '-o', str(original)], check=True)
            before = hashlib.sha256(original.read_bytes()).hexdigest()
            sdk = root / 'sdk'
            sdk.mkdir()
            library = sdk / 'library.so'
            os.link(original, library)
            (sdk / 'external.so').symlink_to(original)
            header = bytearray(20)
            header[:6] = b'\x7fELF\x01\x01'
            header[16:18] = (2).to_bytes(2, 'little')
            header[18:20] = (243).to_bytes(2, 'little')
            target = sdk / 'riscv-target.elf'
            target.write_bytes(header)
            report = compact_runtime(sdk, root / 'report.json')
            self.assertEqual(report['status'], 'succeeded')
            self.assertGreater(report['saved_bytes'], 0)
            self.assertEqual([item['path'] for item in report['files']], ['library.so'])
            self.assertEqual(ctypes.CDLL(str(library)).exported_value(), 42)
            self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(), before)
            self.assertEqual(target.read_bytes(), header)
            self.assertTrue((sdk / 'external.so').is_symlink())
            self.assertEqual(library.stat().st_mode, original.stat().st_mode)


if __name__ == '__main__':
    unittest.main()
