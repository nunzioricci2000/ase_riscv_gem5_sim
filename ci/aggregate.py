#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Created in the personal fork on 2026-10-27: aggregate complete and missing build reports.
# Modified in the personal fork on 2026-10-27: surface failure diagnostics and component cache outcomes.
# Modified in the personal fork on 2026-10-27: distinguish compilation work from cached outputs.
# Modified in the personal fork on 2026-10-27: expose complete SDK reuse and explicitly skipped phases.
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def aggregate(root, expected, jobs=None):
    expected = list(expected)
    if any(row["id"] == "ubuntu-24.04-x86_64" for row in expected):
        expected.append(dict(id="windows-wsl2-x86_64", experimental=True))
    found = {}
    for path in root.rglob("report.json"):
        if path.parent.name.startswith('engine-index-'):
            continue  # Lookup copies; the source-paired engine artifact is authoritative.
        report = json.loads(path.read_text())
        target = report["target"]["id"]
        if target in found:
            raise ValueError(f"Duplicate report for {target}")
        if report["status"] == "succeeded" and target != "windows-wsl2-x86_64":
            expected_names = {f"ase-engine-{target}.tar.gz", f"ase-engine-{target}-sources.tar.gz"}
            entries = report.get("artifacts", [])
            valid = {item["name"] for item in entries} == expected_names
            for item in entries:
                file = path.parent / item["name"]
                if item["name"] not in expected_names or not file.is_file():
                    valid = False
                    continue
                sha = hashlib.sha256()
                with file.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        sha.update(block)
                valid &= file.stat().st_size == item["bytes"] and sha.hexdigest() == item["sha256"]
            if not valid:
                report.update(status="invalid_artifacts", error="Source/binary pair missing or checksum mismatch")
        if report["status"] == "running":
            report.update(status="incomplete", error="Build ended without finalizing its report")
        found[target] = report
    unexpected = set(found) - {row["id"] for row in expected}
    if unexpected:
        raise ValueError(f"Unexpected targets: {sorted(unexpected)}")
    reports = [found.get(row["id"], dict(target=row, status="missing",
                error="No report uploaded; inspect job setup, cancellation or runner timeout", stages=[]))
               for row in expected]
    return dict(schema_version=1, generated_at=datetime.now(timezone.utc).isoformat(),
                all_succeeded=bool(reports) and all(r["status"] == "succeeded" for r in reports),
                targets=reports, actions_jobs=jobs,
                notes=["Missing reports are failures, not silently omitted successes.",
                       "Wall time and stage times exclude runner queue/setup and artifact upload.",
                       "Compare identical revisions, profile, target, package inventory and cache mode.",
                       "Windows uses the Linux Ubuntu 24.04 x86-64 artifact under WSL2; native Windows is unsupported.",
                       "macOS is experimental; a successful compile is not full GUI/platform certification."])


def markdown(report):
    lines = ["# Engine build report", "", f"Generated UTC: {report['generated_at']}", "",
             "| Target | Result | Started UTC | Finished UTC | Build seconds | Cache restore |",
             "| --- | --- | --- | --- | ---: | --- |"]
    for row in report["targets"]:
        lines.append(f"| {row['target']['id']} | {row['status']} | {row.get('started_at', '—')} | "
                     f"{row.get('finished_at', '—')} | {row.get('wall_seconds', 0):.3f} | "
                     f"{row.get('cache_restore', 'unknown')} |")
    for row in report["targets"]:
        lines += ["", f"## {row['target']['id']}", "",
                  "| Phase | Started UTC | Finished UTC | Seconds | Result |",
                  "| --- | --- | --- | ---: | --- |"]
        for stage in row["stages"]:
            lines.append(f"| {stage['name']} | {stage['started_at']} | {stage.get('finished_at', '—')} | "
                         f"{stage.get('wall_seconds', 0):.3f} | {stage['status']} |")
        if row.get('error'):
            lines += ['', 'Error: ' + row['error'].replace('\n', ' ')]
        for stage in row['stages']:
            if stage.get('diagnostic') or stage.get('error'):
                lines += ['', f"Diagnostic ({stage['name']}):", '', '```text',
                          (stage.get('diagnostic') or stage['error']).replace('```', "'''"), '```']
        for event in row.get('component_cache', []):
            lines += [f"- Cache {event['component']}: {event['action']} {event['status']} ({event['seconds']:.2f}s)"]
        if row.get('gem5_work', {}).get('build_started'):
            work = row['gem5_work']
            lines += ['', f"gem5: {work['compile_actions']} compile actions, "
                      f"{work['link_actions']} link actions, {work['cache_retrievals']} cached outputs retrieved."]
        if row.get('skipped_phases'):
            donor = row.get('artifact_reuse', {}).get('run_id', 'unknown')
            lines += ['', f"SDK/source pair reused from run {donor}; runtime tests executed again.",
                      'Skipped: ' + ', '.join(row['skipped_phases'])]
        for artifact in row.get("artifacts", []):
            lines += ["", f"`{artifact['name']}`: {artifact['bytes']} bytes; SHA256 `{artifact['sha256']}`"]
    lines += ["", "## Interpretation", ""] + [f"- {note}" for note in report["notes"]]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--jobs", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    jobs = json.loads(args.jobs.read_text()) if args.jobs and args.jobs.exists() else None
    report = aggregate(args.artifacts, json.loads(args.plan.read_text())["include"], jobs)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "build-report.json").write_text(json.dumps(report, indent=2) + "\n")
    (args.output / "build-report.md").write_text(markdown(report))
    (args.output / "SHA256SUMS").write_text("".join(
        f"{artifact['sha256']}  {artifact['name']}\n" for target in report["targets"]
        if target["status"] == "succeeded" for artifact in target.get("artifacts", [])))
    # A report is useful even when builds fail; the release gate reads all_succeeded.


if __name__ == "__main__":
    main()
