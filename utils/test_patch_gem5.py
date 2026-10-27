# SPDX-License-Identifier: GPL-2.0-only
# Created in the personal fork on 2026-10-27: verify safe and idempotent patch application.
from pathlib import Path
import tempfile
import unittest
from patch_gem5 import apply


class PatchTests(unittest.TestCase):
    def test_applies_once_and_preserves_unrelated_edits(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'source'
            source.write_text('old\n')
            other = root / 'user-edit'
            other.write_text('keep me\n')
            patch = root / 'change.patch'
            patch.write_text('diff --git a/source b/source\n--- a/source\n+++ b/source\n@@ -1 +1 @@\n-old\n+new\n')
            apply(root, patch)
            apply(root, patch)
            self.assertEqual(source.read_text(), 'new\n')
            self.assertEqual(other.read_text(), 'keep me\n')
            source.write_text('conflicting user edit\n')
            with self.assertRaises(RuntimeError):
                apply(root, patch)
            self.assertEqual(source.read_text(), 'conflicting user edit\n')


if __name__ == '__main__':
    unittest.main()
