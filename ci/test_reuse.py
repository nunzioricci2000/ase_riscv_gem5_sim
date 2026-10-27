#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Created in the personal fork on 2026-10-27: verify binary/source integrity and complete-versus-component reuse.
# Modified in the personal fork on 2026-10-27: validate migration from early component-cache reports.
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location('reuse', Path(__file__).with_name('reuse.py'))
reuse = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reuse)


class ReuseTests(unittest.TestCase):
    def artifact(self, root, bundle_key='same', corrupt=False, omit_sources=False, target='test', events=None):
        files = {'ase-engine-test.tar.gz': b'binary', 'ase-engine-test-sources.tar.gz': b'complete sources'}
        report = dict(status='succeeded', target={'id': target}, component_keys={'gem5': 'g', 'python': 'p'},
                      bundle_key=bundle_key, artifacts=[dict(name=name, bytes=len(data),
                      sha256=hashlib.sha256(data).hexdigest()) for name, data in files.items()])
        if events is not None:
            report.pop('component_keys')
            report.pop('bundle_key')
            report['component_cache'] = events
        path = root / 'download.zip'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('report.json', json.dumps(report))
            for name, data in files.items():
                if omit_sources and '-sources' in name:
                    continue
                if corrupt and '-sources' in name:
                    data = b'corrupted sources'
                archive.writestr(name, data)
        return path

    def test_early_reports_recover_only_successfully_saved_or_restored_components(self):
        events = [dict(component='gem5', key='g', action='restore', status='miss'),
                  dict(component='gem5', key='g', action='save', status='saved'),
                  dict(component='python', key='p', action='restore', status='hit'),
                  dict(component='toolchain', key='t', action='restore', status='miss')]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = reuse.unpack_verified(self.artifact(root, events=events), root / 'out', 'test',
                                           {'gem5': 'g', 'python': 'p', 'toolchain': 't'}, 'same')
            self.assertEqual(record['component_keys'], {'gem5': 'g', 'python': 'p'})
            self.assertFalse(record['whole_sdk'])
            for incomplete in ([], [events[0]], [events[-1]]):
                self.assertIsNone(reuse.unpack_verified(self.artifact(root, events=incomplete),
                                  root / 'unused', 'test', {'gem5': 'g', 'python': 'p'}, 'same'))
            self.assertFalse((root / 'unused').exists())

    def test_ambiguous_legacy_component_identity_is_rejected(self):
        events = [dict(component='gem5', key=key, action='save', status='saved') for key in ('g', 'other')]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, 'Ambiguous'):
                reuse.unpack_verified(self.artifact(root, events=events), root / 'out', 'test',
                                      {'gem5': 'g'}, 'same')
            self.assertFalse((root / 'out').exists())

    def test_exact_sdk_requires_both_verified_archives(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = reuse.unpack_verified(self.artifact(root), root / 'out', 'test',
                                           {'gem5': 'g', 'python': 'p'}, 'same')
            self.assertTrue(record['whole_sdk'])
            self.assertEqual(set(record['archives']), {'ase-engine-test.tar.gz', 'ase-engine-test-sources.tar.gz'})
            self.assertEqual((root / 'out/ase-engine-test-sources.tar.gz').read_bytes(), b'complete sources')

    def test_packaging_changes_allow_component_reuse_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = reuse.unpack_verified(self.artifact(root), root / 'out', 'test',
                                           {'gem5': 'g', 'python': 'p'}, 'changed-recipe')
            self.assertFalse(record['whole_sdk'])
            self.assertTrue((root / 'out/ase-engine-test.tar.gz').exists())
            self.assertFalse((root / 'out/ase-engine-test-sources.tar.gz').exists())

    def test_corrupt_or_missing_sources_cannot_be_whole_sdk_hits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for options in ({'corrupt': True}, {'omit_sources': True}):
                with self.subTest(options=options), self.assertRaises(ValueError):
                    reuse.unpack_verified(self.artifact(root, **options), root / 'out', 'test',
                                          {'gem5': 'g', 'python': 'p'}, 'same')
            self.assertFalse((root / 'out/ase-engine-test-sources.tar.gz').exists())
            self.assertFalse(list((root / 'out').glob('*.partial')))

    def test_mismatched_target_or_all_changed_components_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.artifact(root)
            self.assertIsNone(reuse.unpack_verified(path, root / 'out', 'other', {'gem5': 'g'}, 'same'))
            self.assertIsNone(reuse.unpack_verified(path, root / 'out', 'test', {'gem5': 'changed'}, 'same'))
            self.assertFalse((root / 'out').exists())

    def test_expired_unrelated_and_current_run_artifacts_are_excluded(self):
        with patch.dict('os.environ', GITHUB_RUN_ID='123'):
            good = dict(expired=False, workflow_run={'id': 122, 'head_branch': 'feature/test',
                                                    'repository_id': 1, 'head_repository_id': 1})
            self.assertTrue(reuse.available(good, 'feature/test'))
            self.assertFalse(reuse.available(good, 'different-branch'))
            self.assertFalse(reuse.available(dict(good, expired=True), 'feature/test'))
            self.assertFalse(reuse.available(dict(good, workflow_run={'id': 123, 'head_branch': 'main'}), 'feature/test'))

    def test_feature_artifact_is_promoted_only_from_merged_same_repository_commit(self):
        run = dict(id=120, head_branch='feature/old', head_sha='a' * 40,
                   repository_id=1, head_repository_id=1)
        artifact = dict(expired=False, workflow_run=run)
        reuse.ANCESTORS.clear()
        response = json.dumps(dict(status='ahead', merge_base_commit={'sha': 'a' * 40})).encode()
        with patch.dict('os.environ', GITHUB_RUN_ID='123', GITHUB_SHA='b' * 40), \
                patch.object(reuse, 'api', return_value=response) as api:
            self.assertTrue(reuse.available(artifact, 'main', 'owner/repo'))
            self.assertEqual(api.call_count, 1)
            self.assertFalse(reuse.available(dict(artifact, workflow_run=dict(run, head_repository_id=2)),
                                             'main', 'owner/repo'))
        reuse.ANCESTORS.clear()
        with patch.dict('os.environ', GITHUB_SHA='b' * 40), patch.object(reuse, 'api',
                return_value=json.dumps(dict(status='diverged', merge_base_commit={'sha': 'c' * 40})).encode()):
            self.assertFalse(reuse.available(artifact, 'main', 'owner/repo'))


if __name__ == '__main__':
    unittest.main()
