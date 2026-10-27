#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Created in the personal fork on 2026-10-27: measured multi-platform builds.
# Modified in the personal fork on 2026-10-27: expose failures and component reuse; compile gem5 first.
# Modified in the personal fork on 2026-10-27: report actual gem5 compilation, linking and object cache retrievals.
# Modified in the personal fork on 2026-10-27: delay large toolchain downloads until gem5 has built.
"""Build the engine SDK, preserving failure reports; never publish from this script."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
PHASES = ("dependencies", "environment", "reuse", "fetch", "python-configure", "python-build",
          "gem5-build", "fetch-toolchain", "toolchain-configure", "toolchain-build", "stage", "smoke",
          "sources", "archive")


def utc():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def targets(selection):
    rows = json.loads((ROOT / "ci/targets.json").read_text())["targets"]
    if selection == "all":
        return rows
    if selection == "linux":
        return [row for row in rows if row["image"]]
    requested = selection.split(",")
    known = {row["id"] for row in rows}
    if not requested or len(set(requested)) != len(requested) or set(requested) - known:
        raise ValueError("Unknown or duplicated target; use all, linux, or comma-separated target IDs")
    return [row for row in rows if row["id"] in requested]


def gem5_work(log):
    """Count emitted SCons actions; configure probes are deliberately excluded."""
    result = dict(build_started=False, compile_actions=0, link_actions=0, cache_retrievals=0)
    active = False
    with log.open(errors="replace") as stream:
        for line in stream:
            if line.startswith("scons: Building targets"):
                active = result["build_started"] = True
                continue
            if line.startswith(("scons: done building", "scons: building terminated")):
                active = False
            if not active:
                continue
            if line.startswith("Retrieved ") and " from cache" in line:
                result["cache_retrievals"] += 1
            action = re.match(r"\s*\[\s*(CC|CXX|AS|LINK|SHLINK)\s*\]", line)
            if action:
                key = "link_actions" if action[1] in ("LINK", "SHLINK") else "compile_actions"
                result[key] += 1
    return result


class Recorder:
    def __init__(self, output, metadata):
        self.output = output
        output.mkdir(parents=True, exist_ok=True)
        if (output / "report.json").exists():
            raise ValueError("Refusing to overwrite an existing build report")
        self.start = time.monotonic()
        self.report = dict(schema_version=1, started_at=utc(), finished_at=None,
                           status="running", stages=[], **metadata)
        self.save()

    def save(self):
        write_json(self.output / "report.json", self.report)

    def run(self, name, command, env=None, timeout=18000):
        stage = dict(name=name, started_at=utc(), finished_at=None, status="running",
                     command=command, log=f"{len(self.report['stages']):02d}-{name}.log")
        self.report["stages"].append(stage)
        self.save()
        started = time.monotonic()
        print(f"[{stage['started_at']}] {name}", flush=True)
        process = None
        try:
            with (self.output / stage["log"]).open("wb") as log:
                process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                           env=env, start_new_session=True)
                try:
                    code = process.wait(timeout=timeout)
                except (subprocess.TimeoutExpired, KeyboardInterrupt):
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    # The parent can exit before a child that ignores SIGTERM.
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    raise
            stage.update(exit_code=code, status="succeeded" if code == 0 else "failed")
            if code:
                raise subprocess.CalledProcessError(code, command)
        except subprocess.TimeoutExpired:
            stage.update(status="timed_out", exit_code=process.returncode)
            raise
        except KeyboardInterrupt:
            stage.update(status="interrupted", exit_code=process.returncode if process else None)
            raise
        except OSError as error:
            stage.update(status="failed", error=str(error), exit_code=None)
            raise
        finally:
            stage.update(finished_at=utc(), wall_seconds=time.monotonic() - started)
            if stage['status'] != 'succeeded' and (self.output / stage['log']).exists():
                with (self.output / stage['log']).open('rb') as stream:
                    stream.seek(max(0, (self.output / stage['log']).stat().st_size - 4000))
                    stage['diagnostic'] = stream.read().decode(errors='replace')
                print(stage['diagnostic'], flush=True)
            self.save()

    def finish(self, status, error=None):
        self.report.update(status=status)
        cache_events = self.output / 'component-cache.jsonl'
        self.report['component_cache'] = [json.loads(line) for line in cache_events.read_text().splitlines()] if cache_events.exists() else []
        keys = self.output / 'component-keys.json'
        self.report['component_keys'] = json.loads(keys.read_text()) if keys.exists() else {}
        for stage in self.report['stages']:
            log = self.output / stage['log']
            if stage['name'] == 'gem5-build' and log.exists():
                self.report['gem5_work'] = gem5_work(log)
        if error:
            self.report["error"] = str(error)
        self.report["artifacts"] = [dict(name=p.name, bytes=p.stat().st_size, sha256=digest(p))
                                    for p in sorted(self.output.glob("*.tar.gz"))]
        self.report.update(finished_at=utc(), wall_seconds=time.monotonic() - self.start)
        self.save()
        lines = [f"# {self.report['target']['id']}: {status}", "",
                 f"UTC: {self.report['started_at']} → {self.report['finished_at']}", "",
                 "| Stage | Started UTC | Finished UTC | Seconds | Status |",
                 "| --- | --- | --- | ---: | --- |"]
        for stage in self.report["stages"]:
            lines.append(f"| {stage['name']} | {stage['started_at']} | {stage['finished_at']} | "
                         f"{stage['wall_seconds']:.3f} | {stage['status']} |")
        for stage in self.report['stages']:
            if stage.get('diagnostic'):
                lines += ['', f"Failure in {stage['name']} ({stage['log']}):", '', '```text',
                          stage['diagnostic'].replace('```', "'''"), '```']
        if self.report['component_cache']:
            lines += ['', 'Component reuse:'] + [
                f"- {e['component']}: {e['action']} {e['status']} ({e['seconds']:.2f}s)"
                for e in self.report['component_cache']]
        if self.report.get('gem5_work', {}).get('build_started'):
            work = self.report['gem5_work']
            lines += ['', f"gem5: {work['compile_actions']} compile actions, "
                      f"{work['link_actions']} link actions, {work['cache_retrievals']} cached outputs retrieved."]
        (self.output / "report.md").write_text("\n".join(lines) + "\n")
        (self.output / "SHA256SUMS").write_text("".join(
            f"{item['sha256']}  {item['name']}\n" for item in self.report["artifacts"]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", metavar="SELECTION")
    parser.add_argument("--target")
    parser.add_argument("--work", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--profile", choices=("full", "minimal"), default="full")
    parser.add_argument("--linker", choices=("default", "bfd", "gold", "lld", "mold"), default="default")
    parser.add_argument("--stage-timeout", type=int, default=18000)
    args = parser.parse_args(argv)
    if args.matrix:
        print(json.dumps({"include": targets(args.matrix)}))
        return 0
    if not args.target or not args.work or not args.output:
        parser.error("--target, --work and --output are required")
    if args.jobs < 1 or args.jobs > 64 or args.stage_timeout < 1:
        parser.error("jobs must be 1..64 and stage-timeout positive")
    selected = targets(args.target)
    if len(selected) != 1:
        parser.error("Select exactly one build target")
    target = selected[0]
    work, output = args.work.resolve(), args.output.resolve()
    if work.exists() and any(work.iterdir()):
        parser.error("Use a new empty work directory; existing builds are never deleted")
    if output.exists() and any(output.iterdir()):
        parser.error("Use a new empty output directory; existing artifacts are never overwritten")
    if output == work or work in output.parents or output in work.parents:
        parser.error("Work and output must be separate directories")
    lock = json.loads((ROOT / "ci/sources.lock.json").read_text())
    metadata = dict(target=target, sources=lock, host=platform.platform(), cpu_count=os.cpu_count(),
                    jobs=args.jobs, profile=args.profile, linker=args.linker,
                    cache_requested=bool(args.cache),
                    cache_restore=os.getenv("ASE_CACHE_RESTORED_KEY") or ("cold" if args.cache else "disabled"),
                    cache_exact_match=os.getenv("ASE_CACHE_HIT", "false"),
                    git_sha=os.getenv("GITHUB_SHA"), run_id=os.getenv("GITHUB_RUN_ID"),
                    run_attempt=os.getenv("GITHUB_RUN_ATTEMPT"),
                    recipe_sha256={str(p.relative_to(ROOT)): digest(p)
                                   for p in sorted((ROOT / "ci").glob("*")) if p.is_file()},
                    notes=["Phase durations are sequential; container setup is included.",
                           "Runner provisioning, checkout, cache and uploads are in actions-jobs.json.",
                           "No aggregate parallel-build RSS is claimed.",
                           "Mutable image/package versions are recorded; source commits are pinned."])
    rec = Recorder(output, metadata)
    status, error, container = "failed", None, None
    try:
        work.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.update(ASE_TARGET=target["id"], ASE_FAMILY=target["family"], ASE_ARCH=target["arch"],
                   BUILD_JOBS=str(args.jobs), ASE_PROFILE=args.profile, GEM5_LINKER=args.linker)
        if args.cache:
            args.cache = args.cache.resolve()
            args.cache.mkdir(parents=True, exist_ok=True)
        if target["image"]:
            container = f"ase-build-{os.getpid()}"
            rec.run("image-pull", ["docker", "pull", target["image"]], timeout=args.stage_timeout)
            rec.report["image_inspect"] = json.loads(subprocess.check_output(
                ["docker", "image", "inspect", target["image"]], text=True))
            command = ["docker", "run", "--detach", "--name", container,
                       "--mount", f"type=bind,src={ROOT},dst=/repo,readonly",
                       "--mount", f"type=bind,src={work},dst=/work",
                       "--mount", f"type=bind,src={output},dst=/output"]
            if args.cache:
                command += ["--mount", f"type=bind,src={args.cache},dst=/cache"]
            for key in ("ASE_TARGET", "ASE_FAMILY", "ASE_ARCH", "BUILD_JOBS", "ASE_PROFILE", "GEM5_LINKER"):
                command += ["--env", f"{key}={env[key]}"]
            command += ["--env", "ASE_REPO=/repo", "--env", "ASE_WORK=/work",
                        "--env", "ASE_OUTPUT=/output", "--env", f"ASE_CACHE={'/cache' if args.cache else ''}",
                        target["image"], "sleep", "infinity"]
            rec.run("container-start", command)
            prefix = ["docker", "exec", container, "bash", "/repo/ci/steps.sh"]
        else:
            if platform.system() != "Darwin":
                raise ValueError("macOS targets require a native macOS runner")
            env.update(ASE_REPO=str(ROOT), ASE_WORK=str(work), ASE_OUTPUT=str(output),
                       ASE_CACHE=str(args.cache or ""))
            prefix = ["bash", str(ROOT / "ci/steps.sh")]
        for phase in PHASES:
            if phase == 'reuse':
                if args.cache:
                    rec.run(phase, [sys.executable, str(ROOT / 'ci/reuse.py'), str(output),
                                   str(work / 'reuse'), target['id'], str(args.cache)], env, args.stage_timeout)
            else:
                rec.run(phase, prefix + [phase], env, args.stage_timeout)
        status = "succeeded"
    except subprocess.TimeoutExpired as exc:
        status, error = "timed_out", exc
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        error = exc
    except KeyboardInterrupt:
        status, error = "interrupted", "Build interrupted"
    finally:
        if container:
            # Only this run's disposable container is removed; host directories are retained.
            subprocess.run(["docker", "rm", "-f", container], check=False, capture_output=True)
        rec.finish(status, error)
    return 0 if status == "succeeded" else 1


if __name__ == "__main__":
    def interrupted(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    sys.exit(main())
