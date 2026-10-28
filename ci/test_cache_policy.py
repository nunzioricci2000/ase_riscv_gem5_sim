# SPDX-License-Identifier: GPL-2.0-only
# Created in the personal fork on 2026-10-28: preserve partial compilation while avoiding duplicate cache uploads.
# Modified in the personal fork on 2026-10-28: verify compacted cache execution, checksums and preservation of originals and objects.
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import tempfile
import unittest

from cache_policy import compact_components, decision, inventory
from components import restore, save


class CachePolicyTests(unittest.TestCase):
    @unittest.skipUnless(platform.system() == 'Linux', 'Host ELF integration check')
    def test_compacted_component_runs_and_keeps_originals_and_intermediate_objects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, binary = root / 'main.c', root / 'binary'
            source.write_text('int main(void) { return 0; }\n')
            subprocess.run(['cc', '-g', str(source), '-o', str(binary)], check=True)
            digest = hashlib.sha256(binary.read_bytes()).hexdigest()
            cache = root / 'cache'
            entry = cache / 'components/gem5/test-key'
            save(entry, binary)
            objects = cache / 'objects/active/object'
            objects.parent.mkdir(parents=True)
            objects.write_bytes(b'intermediate debug information')
            result = compact_components(cache, root / 'reports')
            self.assertGreater(result[0]['host_debug_bytes_removed'], 0)
            self.assertEqual(hashlib.sha256(binary.read_bytes()).hexdigest(), digest)
            self.assertEqual(objects.read_bytes(), b'intermediate debug information')
            self.assertTrue(restore(entry, root / 'restored'))
            subprocess.run([str(root / 'restored')], check=True)
            self.assertLess((root / 'restored').stat().st_size, binary.stat().st_size)
            self.assertEqual(compact_components(cache, root / 'reports'), [])

    def test_repackaging_and_exact_sdk_reuse_do_not_upload_an_unchanged_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            for state in ({'component_cache': [{'action': 'restore', 'status': 'hit'}]},
                          {'artifact_reuse': {'whole_sdk': True}},
                          {'gem5_work': {'compile_actions': 0, 'link_actions': 0, 'cache_retrievals': 4000}}):
                (output / 'report.json').write_text(json.dumps(dict(status='succeeded', **state)))
                self.assertFalse(decision(output)[0])

    def test_failed_build_preserves_completed_components_and_partial_objects(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / 'report.json').write_text(json.dumps(dict(status='failed')))
            self.assertFalse(decision(output)[0])
            events = output / 'component-cache.jsonl'
            events.write_text(json.dumps(dict(action='save', status='saved')) + '\n')
            self.assertTrue(decision(output)[0])
            events.unlink()
            (output / '06-gem5-build.log').write_text('scons: Building targets ...\n [CXX] code.cc -> code.o\nscons: building terminated because of errors.\n')
            self.assertTrue(decision(output)[0])

    def test_missing_or_interrupted_reports_keep_possible_partial_work(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            self.assertTrue(decision(output)[0])
            (output / 'report.json').write_text('{"status":"running"}')
            self.assertTrue(decision(output)[0])

    def test_storage_inventory_does_not_follow_links_outside_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / 'cache'
            (cache / 'components/python').mkdir(parents=True)
            (cache / 'components/python/payload').write_bytes(b'123')
            (cache / 'outside').symlink_to(root, target_is_directory=True)
            self.assertEqual(inventory(cache), {'components/python': {'files': 1, 'bytes': 3}})


if __name__ == '__main__':
    unittest.main()
