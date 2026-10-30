# SPDX-License-Identifier: GPL-2.0-only
# Created in the personal fork on 2026-10-30: test upstream proposals using only disposable Git histories.
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT/'scripts/upstream_sync.py'
if not SCRIPT.exists():
    SCRIPT = Path(__file__).with_name('upstream_sync.py')
spec = importlib.util.spec_from_file_location('sync_under_test', SCRIPT)
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class UpstreamTests(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory(prefix='upstream-test-')
        self.addCleanup(work.cleanup)
        self.repo = Path(work.name)
        self.git('init')
        self.git('config','user.name','Test')
        self.git('config','user.email','test@example.invalid')
        self.write('app.py','original\n')
        self.write('README.md','original guide\n')
        self.git('add','.')
        self.git('commit','-m','base')
        self.git('branch','upstream')
        self.git('checkout','-b','personal')
        self.write('README.md','fork additions\n')
        self.git('commit','-am','fork documentation')

    def git(self,*args):
        return sync.git(self.repo,*args).stdout.strip()

    def write(self,name,text):
        (self.repo/name).write_text(text)

    def incoming(self,conflict=False):
        if conflict:
            self.write('app.py','personal code\n')
            self.git('commit','-am','personal functionality')
        self.git('checkout','upstream')
        self.write('app.py','new upstream functionality\n')
        self.write('README.md','new original guide\n')
        self.git('commit','-am','incoming')
        tip=self.git('rev-parse','HEAD')
        self.git('checkout','personal')
        return tip

    def test_clean_merge_keeps_features_and_fork_documentation(self):
        tip=self.incoming()
        text,blocked=sync.prepare(self.repo,'example/original',[tip])
        self.assertFalse(blocked)
        self.assertTrue(sync.ancestor(self.repo,tip,'HEAD'))
        self.assertEqual((self.repo/'app.py').read_text(),'new upstream functionality\n')
        self.assertEqual((self.repo/'README.md').read_text(),'fork additions\n')
        self.assertIn('README.md',text)
        self.assertIn('READY FOR TESTS',text)

    def test_conflicts_create_only_blocked_report_without_false_merge(self):
        tip=self.incoming(conflict=True)
        before=self.git('rev-parse','HEAD')
        text,blocked=sync.prepare(self.repo,'example/original',[tip])
        self.assertTrue(blocked)
        self.assertFalse(sync.ancestor(self.repo,tip,'HEAD'))
        self.assertEqual(self.git('diff','--name-only',before,'HEAD'),sync.REPORT)
        self.assertIn('BLOCKED',text)
        self.assertIn('app.py',text)
        self.assertEqual((self.repo/'app.py').read_text(),'personal code\n')

    def test_already_integrated_commit_is_identified(self):
        tip=self.incoming()
        sync.prepare(self.repo,'example/original',[tip])
        self.assertTrue(sync.ancestor(self.repo,tip,'HEAD'))

    def test_script_copies_remain_identical(self):
        other=ROOT.parent/'ci/upstream_sync.py'
        if other.exists():
            self.assertEqual(other.read_bytes(),SCRIPT.read_bytes())


if __name__=='__main__':
    unittest.main()
