#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Created in the personal fork on 2026-10-27: Gitflow checks preserving upstream main.
# Modified in the personal fork on 2026-10-27: use main/develop for personal branches.
import argparse
import os
import re
import subprocess

STABLE = "main"
DEVELOP = "develop"


def allowed_pull_request(base, head):
    if base == STABLE:
        return head.startswith(("release/", "hotfix/"))
    if base == DEVELOP:
        return head == STABLE or head.startswith(("feature/", "fix/", "release/", "hotfix/"))
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("check", "init", "verify-tag"))
    parser.add_argument("--tag", default=os.getenv("GITHUB_REF_NAME", ""))
    args = parser.parse_args()
    if args.command == "check":
        if os.getenv("GITHUB_EVENT_NAME") == "pull_request":
            base, head = os.environ["GITHUB_BASE_REF"], os.environ["GITHUB_HEAD_REF"]
            if not allowed_pull_request(base, head):
                raise SystemExit(f"Gitflow rejects {head} → {base}; see RELEASES.md")
    elif args.command == "verify-tag":
        if not re.fullmatch(r"v\d+\.\d+\.\d+(?:-(?:rc|beta)\.\d+)?", args.tag):
            raise SystemExit("Expected vMAJOR.MINOR.PATCH[-rc.N|-beta.N]")
        subprocess.run(["git", "fetch", "origin", STABLE], check=True)
        # Release only the stable tip, not an old ancestor or an arbitrary feature commit.
        tagged = subprocess.check_output(["git", "rev-parse", f"{args.tag}^{{commit}}"], text=True).strip()
        stable = subprocess.check_output(["git", "rev-parse", "FETCH_HEAD"], text=True).strip()
        if tagged != stable:
            raise SystemExit("Release tag must identify the current origin/main tip")
    else:
        subprocess.run(["git", "rev-parse", "--verify", STABLE], check=True)
        if subprocess.run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{DEVELOP}"]).returncode:
            subprocess.run(["git", "branch", DEVELOP, STABLE], check=True)
        settings = {"branch.master": STABLE, "branch.develop": DEVELOP,
                    "prefix.feature": "feature/", "prefix.release": "release/",
                    "prefix.hotfix": "hotfix/", "prefix.support": "support/",
                    "prefix.versiontag": "v"}
        for key, value in settings.items():
            subprocess.run(["git", "config", "--local", f"gitflow.{key}", value], check=True)
        print("Configured local Gitflow; no checkout, commit, push or history rewrite performed.")


if __name__ == "__main__":
    main()
