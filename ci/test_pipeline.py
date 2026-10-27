#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Created in the personal fork on 2026-10-27: failure accounting and packaging regressions.
# Modified in the personal fork on 2026-10-27: check unprefixed personal branch routes.
# Modified in the personal fork on 2026-10-27: ignore lookup indexes when verifying distributable artifacts.
# Modified in the personal fork on 2026-10-27: reject misleading compilation counts from configure probes.
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "ci" / f"{name}.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


build, package, aggregate, gitflow = [module(name) for name in ("build", "package", "aggregate", "gitflow")]


class PipelineTests(unittest.TestCase):
    def test_gem5_work_counts_actions_without_configure_probes(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'gem5.log'
            log.write_text(" [ CXX] configure probe\nscons: Building targets ...\n"
                           "Retrieved `build/RISCV/one.o' from cache\n"
                           " [ CXX] changed.cc -> changed.o\n [ CC] helper.c -> helper.o\n"
                           " [ LINK] -> gem5.opt\nscons: done building targets.\n [ CXX] diagnostic tail\n")
            self.assertEqual(build.gem5_work(log), dict(build_started=True, compile_actions=2,
                                                       link_actions=1, cache_retrievals=1))
            log.write_text('gem5 component restored from cache\n')
            self.assertEqual(build.gem5_work(log), dict(build_started=False, compile_actions=0,
                                                       link_actions=0, cache_retrievals=0))

    def test_target_selection_is_closed_and_preserves_architecture(self):
        rows = build.targets("all")
        self.assertEqual(len({r["id"] for r in rows}), len(rows))
        self.assertTrue(any(r["arch"] == "aarch64" for r in rows))
        self.assertTrue(all(r["image"] for r in build.targets("linux")))
        for bad in ("windows-native", "x; touch /tmp/unwanted", "all,linux", "", "arch-x86_64,arch-x86_64"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                build.targets(bad)

    def test_failure_report_preserves_timestamps_exit_and_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            rec = build.Recorder(out, {"target": {"id": "test"}})
            with self.assertRaises(subprocess.CalledProcessError):
                rec.run("failure", [sys.executable, "-c", "print('diagnostic'); raise SystemExit(7)"])
            rec.finish("failed")
            report = json.loads((out / "report.json").read_text())
            stage = report["stages"][0]
            self.assertEqual(stage["exit_code"], 7)
            self.assertEqual(stage["status"], "failed")
            self.assertLessEqual(stage["started_at"], stage["finished_at"])
            self.assertGreater(stage["wall_seconds"], 0)
            self.assertIn("diagnostic", (out / stage["log"]).read_text())
            self.assertIn("failed", (out / "report.md").read_text())
            with self.assertRaises(ValueError):
                build.Recorder(out, {})

    def test_timeout_is_not_a_success(self):
        with tempfile.TemporaryDirectory() as directory:
            rec = build.Recorder(Path(directory), {"target": {"id": "test"}})
            with self.assertRaises(subprocess.TimeoutExpired):
                rec.run("timeout", [sys.executable, "-c", "import time; time.sleep(60)"], timeout=0.1)
            rec.finish("failed")
            self.assertEqual(rec.report["stages"][0]["status"], "timed_out")

    def test_launch_failure_is_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            rec = build.Recorder(Path(directory), {"target": {"id": "test"}})
            with self.assertRaises(OSError):
                rec.run("missing", [str(Path(directory) / "absent")])
            self.assertEqual(rec.report["stages"][0]["status"], "failed")

    def test_missing_cancelled_targets_block_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "report.json").write_text(json.dumps(dict(target={"id": "one"}, status="succeeded", stages=[])))
            result = aggregate.aggregate(root, [{"id": "one"}, {"id": "two"}])
            self.assertFalse(result["all_succeeded"])
            self.assertEqual(result["targets"][1]["status"], "missing")
            self.assertIn("two", aggregate.markdown(result))

    def test_wsl_validation_required_when_ubuntu_artifact_is_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            result = aggregate.aggregate(Path(directory), [{"id": "ubuntu-24.04-x86_64"}])
            self.assertEqual(result["targets"][-1]["target"]["id"], "windows-wsl2-x86_64")
            self.assertFalse(result["all_succeeded"])

    def test_release_gate_checks_both_archives_and_actual_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = []
            for name in ("ase-engine-one.tar.gz", "ase-engine-one-sources.tar.gz"):
                (root / name).write_bytes(b"archive")
                artifacts.append(dict(name=name, bytes=7, sha256=hashlib.sha256(b"archive").hexdigest()))
            (root / "report.json").write_text(json.dumps(dict(target={"id": "one"},
                status="succeeded", stages=[], artifacts=artifacts)))
            (root / 'engine-index-one').mkdir()
            (root / 'engine-index-one/report.json').write_bytes((root / 'report.json').read_bytes())
            self.assertTrue(aggregate.aggregate(root, [{"id": "one"}])["all_succeeded"])
            (root / "ase-engine-one-sources.tar.gz").write_bytes(b"damaged")
            report = aggregate.aggregate(root, [{"id": "one"}])
            self.assertFalse(report["all_succeeded"])
            self.assertEqual(report["targets"][0]["status"], "invalid_artifacts")

    def test_abandoned_report_remains_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "report.json").write_text(json.dumps(dict(target={"id": "one"},
                status="running", stages=[dict(name="build", started_at="2026-10-27T00:00:00Z", status="running")])))
            report = aggregate.aggregate(root, [{"id": "one"}])
            self.assertFalse(report["all_succeeded"])
            self.assertEqual(report["targets"][0]["status"], "incomplete")
            self.assertIn("build", aggregate.markdown(report))

    def test_source_archive_keeps_patches_not_build_or_private_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "repo"
            subprocess.run(["git", "init", "-q", str(source)], check=True)
            (source / "LICENSE").write_text("original notice\n")
            (source / "code.c").write_text("original\n")
            subprocess.run(["git", "-C", str(source), "add", "LICENSE", "code.c"], check=True)
            (source / "code.c").write_text("original\nlocal patch\n")
            (source / "private.txt").write_text("must not be distributed")
            archive = root / "sources.tar.gz"
            package.source_archive(archive, {"test": source}, [])
            with tarfile.open(archive) as tar:
                self.assertEqual(set(tar.getnames()), {"sources/test/LICENSE", "sources/test/code.c"})
                self.assertIn(b"local patch", tar.extractfile("sources/test/code.c").read())
            self.assertFalse((root / "sources.tar.partial").exists())

    def test_external_symlinks_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ok").write_text("ok")
            (root / "relative").symlink_to("ok")
            package.validate_links(root)
            (root / "bad").symlink_to("/usr/lib")
            with self.assertRaises(ValueError):
                package.validate_links(root)

    def test_gitflow_routes(self):
        for head in ("release/1.2.3", "hotfix/1.2.4"):
            self.assertTrue(gitflow.allowed_pull_request("main", head))
        for head in ("feature/build", "fix/install", "main", "release/1.2.3"):
            self.assertTrue(gitflow.allowed_pull_request("develop", head))
        self.assertFalse(gitflow.allowed_pull_request("main", "feature/build"))
        self.assertFalse(gitflow.allowed_pull_request("original/main", "release/1.2.3"))

    def test_sources_pinned_and_scons_archive_verified(self):
        lock = json.loads((ROOT / "ci/sources.lock.json").read_text())
        for name in ("python", "toolchain", "gem5"):
            self.assertRegex(lock[name]["commit"], r"^[a-f0-9]{40}$")
        self.assertRegex(lock["scons_sha256"], r"^[a-f0-9]{64}$")


if __name__ == "__main__":
    unittest.main()
