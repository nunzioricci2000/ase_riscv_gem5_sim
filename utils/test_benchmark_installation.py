#!/usr/bin/env python3
"""Benchmark accounting tests; no real installs or network access."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parent.parent
RUNNER = ROOT/'utils/benchmark_installation.py'


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ase benchmark test ')
        self.base = Path(self.temp.name)
        self.repo = self.base/'repo'
        (self.repo/'utils').mkdir(parents=True)
        shutil.copy(ROOT/'utils/install_build.sh', self.repo/'utils/install_build.sh')
        self.report = self.base/'report.json'
        self.env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        self.env.pop('ASE_INSTALL_EVENT_LOG', None)
        self.env.pop('ASE_INSTALL_PARENT_STAGE', None)

    def tearDown(self):
        self.temp.cleanup()

    def installer(self, body):
        (self.repo/'utils/installation.sh').write_text(
            'set -euo pipefail\nexport BUILD_JOBS=2\n'
            'source utils/install_build.sh\n'
            'record_install_event configuration "" "" "$1"\n' + body)

    def command(self, *arguments):
        return [sys.executable, str(RUNNER), 'gem5', '--repo', str(self.repo),
                '--output', str(self.report), *arguments]

    def run_benchmark(self, *arguments, success=True):
        result = subprocess.run(self.command(*arguments), capture_output=True,
                                text=True, env=self.env, timeout=10)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(self.report.read_text()) if self.report.exists() else None

    def test_nested_stage_measurements_and_resources(self):
        self.installer('''inner() { run_install_stage compile sleep 0.08; }
run_install_stage install inner
''')
        report = self.run_benchmark('--runs', '2')
        self.assertEqual(report['summary']['successful_runs'], 2)
        self.assertEqual(len(report['summary']['groups']), 1)
        self.assertIn('utils/install_build.sh', report['metadata']['installer_sha256'])
        for run in report['runs']:
            self.assertEqual(run['status'], 'succeeded')
            self.assertEqual(run['build_jobs'], 2)
            self.assertEqual(run['event_errors'], [])
            stages = {stage['label']: stage for stage in run['stages']}
            self.assertEqual(stages['compile']['parent'], stages['install']['stage_id'])
            self.assertIsNone(stages['install']['parent'])
            self.assertGreaterEqual(stages['compile']['wall_seconds'], 0.08)
            self.assertGreater(run['wall_seconds'], stages['install']['wall_seconds'])
            self.assertGreater(run['peak_process_rss_kib'], 0)
            self.assertGreaterEqual(run['user_cpu_seconds'], 0)
            self.assertTrue(Path(run['log']).is_file())

    def test_failure_is_recorded_and_not_averaged(self):
        self.installer('''fail_build() { false; touch should-not-exist; }
run_install_stage build fail_build
''')
        report = self.run_benchmark('--runs', '3', success=False)
        self.assertFalse((self.repo/'should-not-exist').exists())
        self.assertEqual(len(report['runs']), 1)
        run = report['runs'][0]
        self.assertEqual(run['status'], 'failed')
        self.assertEqual(run['exit_code'], 1)
        self.assertEqual(run['stages'][0]['exit_code'], 1)
        self.assertGreater(run['stages'][0]['wall_seconds'], 0)
        self.assertEqual(report['summary']['groups'], [])

    def test_first_install_and_skip_are_not_averaged_together(self):
        self.installer('''if [[ -d tools/gem5 ]]; then
    record_install_event skipped "" "" gem5
else
    run_install_stage build sleep 0.02
    mkdir -p tools/gem5
fi
''')
        report = self.run_benchmark('--runs', '3')
        self.assertEqual(report['runs'][1]['skipped'], ['gem5'])
        self.assertEqual(sorted(group['runs'] for group in report['summary']['groups']), [1, 2])

    def test_timeout_stops_descendants_and_writes_partial_result(self):
        self.installer('''long_build() { sleep 60 & echo "$!" > child.pid; wait; }
run_install_stage build long_build
''')
        report = self.run_benchmark('--timeout', '0.4', success=False)
        self.assertEqual(report['runs'][0]['status'], 'timed_out')
        self.assertEqual(report['summary']['groups'], [])
        self.assertLess(report['runs'][0]['wall_seconds'], 3)
        self.assert_child_stopped()

    def assert_child_stopped(self):
        child = int((self.repo/'child.pid').read_text())
        status = Path(f'/proc/{child}/stat')
        if status.exists():
            self.assertIn(status.read_text().split()[2], ('Z', 'X'))

    def test_interrupt_stops_descendants_and_keeps_report(self):
        self.installer('''long_build() { sleep 60 & echo "$!" > child.pid; wait; }
run_install_stage build long_build
''')
        process = subprocess.Popen(self.command(), stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, env=self.env, text=True)
        try:
            deadline = time.monotonic() + 5
            while not (self.repo/'child.pid').exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue((self.repo/'child.pid').exists())
            process.send_signal(signal.SIGINT)
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 130, stdout+stderr)
            report = json.loads(self.report.read_text())
            self.assertEqual(report['runs'][0]['status'], 'interrupted')
            self.assert_child_stopped()
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()

    def test_empty_build_guard_does_not_delete_anything(self):
        self.installer('touch should-not-run\n')
        (self.repo/'tools/gem5').mkdir(parents=True)
        self.run_benchmark('--require-empty-builds', success=False)
        self.assertFalse((self.repo/'should-not-run').exists())
        self.assertTrue((self.repo/'tools/gem5').exists())
        self.assertFalse(self.report.exists())

    def test_older_installer_still_gets_total_measurement(self):
        (self.repo/'utils/installation.sh').write_text('echo legacy; sleep 0.05\n')
        report = self.run_benchmark()
        self.assertEqual(report['runs'][0]['stages'], [])
        self.assertGreaterEqual(report['runs'][0]['wall_seconds'], 0.05)
        self.assertIn('legacy', Path(report['runs'][0]['log']).read_text())

    def test_report_is_never_overwritten(self):
        self.installer('touch should-not-run\n')
        self.report.write_text('{"existing": true}\n')
        report = self.run_benchmark(success=False)
        self.assertEqual(report, {'existing': True})
        self.assertFalse((self.repo/'should-not-run').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
