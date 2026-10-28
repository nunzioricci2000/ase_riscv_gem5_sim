# SPDX-License-Identifier: GPL-2.0-only
# Created in the personal fork on 2026-10-28: preserve missing replacements, other branches and concurrent newer cache saves.
import unittest

from retain_cache import superseded


class RetentionTests(unittest.TestCase):
    def test_only_older_compatible_caches_on_this_branch_are_removed(self):
        def item(number, **extra):
            return dict(id=number, key=f'target-{number}', ref='refs/heads/feature/test', version='same-paths',
                        created_at=f'2026-10-28T01:00:0{number}Z', size_in_bytes=100, **extra)
        old, current, newer = (item(i) for i in (1, 2, 3))
        other_branch = dict(old, id=4, ref='refs/heads/main')
        other_target = dict(old, id=5, key='another-target-1')
        other_layout = dict(old, id=6, version='different-paths')
        records = [old, current, newer, other_branch, other_target, other_layout]
        self.assertEqual(superseded(records, 'target-2', 'target-', current['ref']), [old])
        self.assertEqual(superseded(records, 'missing', 'target-', current['ref']), [])
        self.assertEqual(superseded([old, dict(current, size_in_bytes=0)], 'target-2', 'target-', current['ref']), [])


if __name__ == '__main__':
    unittest.main()
