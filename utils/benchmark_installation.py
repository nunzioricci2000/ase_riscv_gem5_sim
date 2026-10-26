#!/usr/bin/env python3
"""Measure real installer invocations; never delete or reset installations."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import statistics
import subprocess
import sys
import tempfile
import time

SETTINGS = ('BUILD_JOBS', 'TOOLCHAIN_MODE', 'RISCV_TOOLCHAIN_PATH', 'GEM5_PYTHON',
            'GEM5_PYTHON_CONFIG', 'GEM5_LINKER', 'GEM5_BUILD_CACHE', 'CC', 'CXX',
            'MAKEFLAGS', 'CCACHE_DIR', 'XDG_CACHE_HOME')


def read_text(path):
    try:
        return Path(path).read_text(encoding='utf-8', errors='replace')
    except OSError:
        return None


def command_output(command, cwd=None):
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=5)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def initial_state(repo):
    tools = repo/'tools'
    return {
        'toolchain_sources_present': (tools/'riscv-gnu-toolchain').exists(),
        'toolchain_prefix_present': (tools/'riscv-toolchain').exists(),
        'saved_toolchain_selection': read_text(tools/'toolchain.path'),
        'gem5_sources_present': (tools/'gem5').exists(),
        'gem5_binary_present': (tools/'gem5/build/RISCV/gem5.opt').exists(),
        'gem5_venv_present': (tools/'myenv').exists(),
        'python310_build_present': (repo/'python310').exists(),
    }


def metadata(repo):
    # Hash the working files too: HEAD alone does not identify uncommitted fixes.
    paths = sorted((repo/'utils').rglob('*.sh'))
    paths += [repo/'setup_default', repo/'ase_studio_branches.json']
    hashes = {str(path.relative_to(repo)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in paths if path.is_file()}
    cpu_info = read_text('/proc/cpuinfo') or ''
    model = next((line.split(':', 1)[1].strip() for line in cpu_info.splitlines()
                  if line.startswith('model name')), None)
    return {
        'os_release': read_text('/etc/os-release'),
        'kernel': platform.release(), 'architecture': platform.machine(),
        'cpu_model': model, 'logical_cpus': os.cpu_count(),
        'available_cpus': command_output(['nproc']),
        'memory_before': read_text('/proc/meminfo'),
        'python': platform.python_version(),
        'git_commit': command_output(['git', 'rev-parse', 'HEAD'], repo),
        'git_changes': command_output(['git', 'status', '--short', '--untracked-files=no'], repo),
        'installer_sha256': hashes,
        'benchmark_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'settings': {key: os.environ.get(key) for key in SETTINGS},
    }


def stages_from_events(path):
    starts = {}
    stages, skipped, errors = [], [], []
    jobs = None
    for number, line in enumerate((read_text(path) or '').splitlines(), 1):
        try:
            event = json.loads(line)
            kind = event['kind']
            if event.get('build_jobs'):
                jobs = int(event['build_jobs'])
            if kind == 'start':
                starts[event['stage_id']] = event
            elif kind == 'end':
                start = starts.pop(event['stage_id'])
                stages.append(dict(label=start['label'], parent=start['parent'],
                                   stage_id=start['stage_id'], exit_code=event['exit_code'],
                                   wall_seconds=(event['monotonic_ns']-start['monotonic_ns'])/1e9))
            elif kind == 'skipped':
                skipped.append(event['label'])
        except (KeyError, ValueError, TypeError) as error:
            errors.append(f'Event line {number}: {error}')
    for start in starts.values():
        stages.append(dict(label=start['label'], parent=start['parent'],
                           stage_id=start['stage_id'], exit_code=None, wall_seconds=None))
    return dict(stages=stages, skipped=skipped, build_jobs=jobs, event_errors=errors)


def signal_group(pid, signum):
    try:
        os.killpg(pid, signum)
    except ProcessLookupError:
        pass


def measure(command, repo, environment, log, timeout):
    """wait4 reports this process tree's CPU use, without mixing previous runs."""
    started = time.monotonic()
    stopped = None
    reason = None
    usage = None
    # No human think-time in measurements. Provision noninteractive sudo/package
    # access in a disposable VM/container for dependency-install benchmarks.
    with log.open('xb') as output:
        try:
            process = subprocess.Popen(command, cwd=repo, env=environment,
                                       stdin=subprocess.DEVNULL, stdout=output,
                                       stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as error:
            output.write(str(error).encode())
            return dict(status='failed', exit_code=127,
                        wall_seconds=time.monotonic()-started, launch_error=str(error))
        while True:
            try:
                pid, status, usage_result = os.wait4(process.pid, os.WNOHANG)
                if pid:
                    usage = usage_result
                    process.returncode = (os.WEXITSTATUS(status) if os.WIFEXITED(status)
                                          else -os.WTERMSIG(status))
                    break
                now = time.monotonic()
                if timeout and now-started >= timeout and stopped is None:
                    reason, stopped = 'timed_out', now
                    signal_group(process.pid, signal.SIGTERM)
                if stopped is not None and now-stopped >= 5:
                    signal_group(process.pid, signal.SIGKILL)
                # Avoid quantizing quick reruns to 50 ms; long builds need less polling.
                time.sleep(0.001 if now-started < 5 else 0.05)
            except KeyboardInterrupt:
                reason, stopped = 'interrupted', time.monotonic()
                signal_group(process.pid, signal.SIGTERM)
        if stopped is not None:
            # The shell may exit before a child that ignored SIGTERM.
            signal_group(process.pid, signal.SIGKILL)
    return dict(status=reason or ('succeeded' if process.returncode == 0 else 'failed'),
                exit_code=process.returncode, wall_seconds=time.monotonic()-started,
                user_cpu_seconds=usage.ru_utime, system_cpu_seconds=usage.ru_stime,
                peak_process_rss_kib=usage.ru_maxrss)


def summary(runs):
    groups = defaultdict(list)
    for run in runs:
        if run['status'] != 'succeeded':
            continue
        profile = dict(initial_state=run['initial_state'], skipped=run['skipped'],
                       build_jobs=run['build_jobs'], stages=[s['label'] for s in run['stages']])
        groups[json.dumps(profile, sort_keys=True)].append(run['wall_seconds'])
    return dict(successful_runs=sum(r['status'] == 'succeeded' for r in runs),
                unsuccessful_runs=sum(r['status'] != 'succeeded' for r in runs),
                groups=[dict(profile=json.loads(profile), runs=len(times),
                             median_seconds=statistics.median(times),
                             min_seconds=min(times), max_seconds=max(times))
                        for profile, times in groups.items()])


def save_report(path, report):
    report['summary'] = summary(report['runs'])
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False,
                                     encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
        temporary = stream.name
    os.replace(temporary, path)


def positive_integer(value):
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError('must be at least 1')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('toolchain', 'gem5', 'ase-studio', 'all-ase'))
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parent.parent,
                        help='Checkout to benchmark (including an older installer for a baseline)')
    parser.add_argument('--runs', type=positive_integer, default=1,
                        help='Repeated invocations; later runs reuse the preceding installation')
    parser.add_argument('--output', type=Path, help='New JSON report; defaults to a unique file in /tmp')
    parser.add_argument('--label', default='', help='Description, e.g. ubuntu-22-fresh-vm')
    parser.add_argument('--require-empty-builds', action='store_true',
                        help='Refuse existing native source/build directories; never delete them')
    parser.add_argument('--timeout', type=float, default=0,
                        help='Maximum seconds per run; 0 means unlimited')
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    if not (repo/'utils/installation.sh').is_file():
        parser.error('The selected checkout has no utils/installation.sh')
    if args.timeout < 0 or not args.timeout < float('inf'):
        parser.error('--timeout must be a finite nonnegative number')
    if args.require_empty_builds:
        if args.runs != 1:
            parser.error('--require-empty-builds requires --runs 1; restore a fresh environment for each sample')
        existing = [key for key, value in initial_state(repo).items() if value]
        if existing:
            parser.error('Existing installation/build state: ' + ', '.join(existing))
    if args.output:
        report_path = args.output.resolve()
        try:
            report_path.open('x').close()
        except OSError as error:
            parser.error(f'Cannot create report: {error}')
    else:
        fd, name = tempfile.mkstemp(prefix='ase-install-benchmark-', suffix='.json')
        os.close(fd)
        report_path = Path(name)
    report = dict(schema_version=1, created_utc=datetime.now(timezone.utc).isoformat(),
                  label=args.label, command=args.command, repository=str(repo),
                  metadata=metadata(repo), runs=[],
                  notes=['Wall time includes subprocess startup and instrumentation.',
                         'Nested stage times overlap; do not sum them.',
                         'RSS is the maximum for a process, not aggregate parallel-build memory.',
                         'Empty build directories do not imply cold package/download/OS caches.',
                         'Dependency installation needs noninteractive package/sudo access.'])
    save_report(report_path, report)
    print(f'Report: {report_path}', flush=True)
    result_code = 0
    for index in range(1, args.runs+1):
        log = report_path.with_suffix(f'.run-{index:03d}.log')
        events = report_path.with_suffix(f'.run-{index:03d}.events.jsonl')
        if log.exists() or events.exists():
            parser.error(f'Refusing to overwrite run artifacts for {log}')
        events.touch(exist_ok=False)
        before = initial_state(repo)
        environment = os.environ.copy()
        environment.pop('ASE_INSTALL_PARENT_STAGE', None)
        environment['ASE_INSTALL_EVENT_LOG'] = str(events)
        environment['ASE_INSTALL_NONINTERACTIVE'] = '1'
        command = ['bash', str(repo/'utils/installation.sh'), args.command]
        print(f'Run {index}/{args.runs}: {args.command}; log: {log}', flush=True)
        run = measure(command, repo, environment, log, args.timeout)
        run.update(index=index, initial_state=before, log=str(log), events=str(events),
                   **stages_from_events(events))
        run['source_revisions_after'] = {
            component: command_output(['git', 'rev-parse', 'HEAD'], repo/'tools'/component)
            if (repo/'tools'/component/'.git').exists() else None
            for component in ('gem5', 'riscv-gnu-toolchain')}
        report['runs'].append(run)
        save_report(report_path, report)
        print(f"  {run['status']}: {run['wall_seconds']:.3f}s; skipped: {', '.join(run['skipped']) or 'none reported'}", flush=True)
        if run['status'] != 'succeeded':
            result_code = 130 if run['status'] == 'interrupted' else 1
            break
    for group in report['summary']['groups']:
        print(f"Comparable group ({group['runs']} successful runs): median {group['median_seconds']:.3f}s "
              f"[min {group['min_seconds']:.3f}, max {group['max_seconds']:.3f}]")
    return result_code


if __name__ == '__main__':
    sys.exit(main())
