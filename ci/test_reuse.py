#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Created in the personal fork on 2026-10-27: verify binary/source integrity and complete-versus-component reuse.
# Modified in the personal fork on 2026-10-27: validate migration from early component-cache reports.
# Modified in the personal fork on 2026-10-28: avoid irrelevant SDK downloads and exercise sparse ZIP report reads.
# Modified in the personal fork on 2026-10-28: require both source/binary archives for packaging-only refreshes.
# Modified in the personal fork on 2026-10-28: exercise transient API failures, partial downloads and alternate SDK candidates.
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location('reuse', Path(__file__).with_name('reuse.py'))
reuse = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reuse)


class ReuseTests(unittest.TestCase):
    def test_metadata_transfer_recovers_after_transient_error(self):
        failure = subprocess.CalledProcessError(1, ['gh', 'api', 'route'])
        success = subprocess.CompletedProcess([], 0, stdout=b'{"valid":true}')
        with patch.object(reuse.subprocess, 'run', side_effect=[failure, success]) as run, \
                patch.object(reuse.time, 'sleep') as sleep:
            self.assertEqual(reuse.api('route'), success.stdout)
            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args.kwargs['timeout'], 60)
            sleep.assert_called_once_with(1)

    def test_repeated_api_timeouts_have_a_bounded_retry_count(self):
        with patch.object(reuse.subprocess, 'run', side_effect=subprocess.TimeoutExpired('gh', 60)) as run, \
                patch.object(reuse.time, 'sleep') as sleep:
            with self.assertRaises(subprocess.TimeoutExpired):
                reuse.api('route')
            self.assertEqual(run.call_count, 3)
            self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])

    def test_retry_discards_partial_archive_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'download.zip'
            attempts = []
            def transfer(command, **kwargs):
                attempts.append(command)
                kwargs['stdout'].write(b'partial bytes' if len(attempts) == 1 else b'complete')
                if len(attempts) == 1:
                    raise subprocess.CalledProcessError(1, command)
                return subprocess.CompletedProcess(command, 0)
            with patch.object(reuse.subprocess, 'run', side_effect=transfer) as run, \
                    patch.object(reuse.time, 'sleep'):
                reuse.api('route', target)
            self.assertEqual(target.read_bytes(), b'complete')
            self.assertEqual(run.call_args.kwargs['timeout'], 600)

    def check_alternate_candidate(self, failed_index=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            keys = {'gem5': 'g', 'python': 'p'}
            (root / 'component-keys.json').write_text(json.dumps(keys))
            (root / 'bundle-key.txt').write_text('same\n')
            payload = self.artifact(root).read_bytes()
            indices = [dict(id=i, expired=False, workflow_run=dict(id=i + 10, head_branch='main',
                       repository_id=1, head_repository_id=1)) for i in (1, 2)]
            def api(route):
                if '?name=engine-index-test' in route:
                    return json.dumps({'artifacts': indices}).encode()
                if '/artifacts/1/zip' in route:
                    if failed_index:
                        raise subprocess.CalledProcessError(1, ['gh', 'api', route])
                    return payload
                if '/artifacts/2/zip' in route:
                    return payload
                for run_id in (11, 12):
                    if f'/runs/{run_id}/artifacts?' in route:
                        return json.dumps({'artifacts': [dict(id=run_id * 10, name='engine-test', expired=False)]}).encode()
                self.fail('Unexpected API request: ' + route)
            responses = [True] if failed_index else [subprocess.CalledProcessError(1, ['gh', 'api']), True]
            with patch.dict(os.environ, GITHUB_REPOSITORY='owner/repo', GH_TOKEN='test',
                            GITHUB_REF_NAME='main', GITHUB_RUN_ID='123'), \
                    patch.object(reuse.sys, 'argv', ['reuse.py', str(root), str(root / 'out'), 'test', str(root / 'cache')]), \
                    patch.object(reuse, 'api', side_effect=api), \
                    patch.object(reuse, 'recover', side_effect=responses) as recover:
                reuse.main()
            self.assertEqual(recover.call_args.args[2], 12)
            self.assertEqual(recover.call_count, len(responses))

    def test_unavailable_index_does_not_hide_a_valid_sdk(self):
        self.check_alternate_candidate(failed_index=True)

    def test_failed_download_does_not_hide_an_alternate_sdk(self):
        self.check_alternate_candidate()

    def test_failed_ancestry_lookup_is_not_cached_as_a_negative_result(self):
        artifact = dict(id=1, expired=False, workflow_run=dict(id=120, head_branch='feature/test',
                        head_sha='a' * 40, repository_id=1, head_repository_id=1))
        reuse.ANCESTORS.clear()
        success = json.dumps(dict(status='ahead', merge_base_commit={'sha': 'a' * 40})).encode()
        with patch.dict(os.environ, GITHUB_RUN_ID='123', GITHUB_SHA='b' * 40), \
                patch.object(reuse, 'api', side_effect=[subprocess.TimeoutExpired('gh', 60), success]):
            self.assertFalse(reuse.available(artifact, 'main', 'owner/repo'))
            self.assertFalse(reuse.ANCESTORS)
            self.assertTrue(reuse.available(artifact, 'main', 'owner/repo'))

    def test_sparse_zip_lookup_skips_the_binary_payload(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('sdk.tar.gz', b'x' * (4 * 1024 * 1024))
            archive.writestr('report.json', '{"status":"succeeded"}')
        content = stream.getvalue()
        reader = reuse.RangeReader(len(content), lambda first, last: content[first:last + 1])
        with zipfile.ZipFile(reader) as archive:
            self.assertEqual(json.loads(archive.read('report.json')), {'status': 'succeeded'})
        self.assertLess(reader.downloaded, 4096)

    def test_unchanged_cached_components_do_not_justify_downloading_an_old_sdk(self):
        requested = {'gem5': 'new-gem5', 'python': 'same-python'}
        old = dict(status='succeeded', target={'id': 'test'},
                   component_keys={'gem5': 'old-gem5', 'python': 'same-python'}, bundle_key='old')
        self.assertFalse(reuse.useful(old, requested, {'gem5': 'new-gem5'}, 'new', 'test'))
        self.assertTrue(reuse.useful(old, requested, {'python': 'same-python'}, 'new', 'test'))
        exact = dict(old, component_keys=requested, bundle_key='new')
        self.assertTrue(reuse.useful(exact, requested, {}, 'new', 'test'))
        self.assertTrue(reuse.useful(exact, requested, {}, 'changed-packaging', 'test'))
        self.assertFalse(reuse.useful(dict(exact, status='failed'), requested, {}, 'new', 'test'))

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

    def test_packaging_changes_reuse_the_verified_source_pair_when_all_components_match(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = reuse.unpack_verified(self.artifact(root), root / 'out', 'test',
                                           {'gem5': 'g', 'python': 'p'}, 'changed-recipe')
            self.assertFalse(record['whole_sdk'])
            self.assertTrue(record['refresh_sdk'])
            self.assertTrue((root / 'out/ase-engine-test.tar.gz').exists())
            self.assertTrue((root / 'out/ase-engine-test-sources.tar.gz').exists())

    def test_changed_component_prevents_packaging_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = reuse.unpack_verified(self.artifact(root), root / 'out', 'test',
                                           {'gem5': 'changed', 'python': 'p'}, 'changed-recipe')
            self.assertFalse(record['whole_sdk'])
            self.assertFalse(record['refresh_sdk'])
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
