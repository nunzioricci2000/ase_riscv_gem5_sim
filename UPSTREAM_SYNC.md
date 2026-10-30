<!-- SPDX-License-Identifier: GPL-2.0-only -->
<!-- Modified in the personal fork on 2026-10-30: explain explicit CI dispatch for token-created proposals. -->
<!-- Created in the personal fork on 2026-10-30: document scheduled upstream proposals and their review boundary. -->
# Upstream integration proposals

`Propose upstream integration` runs every six hours from the personal repository's
main branch, or by manual dispatch on that branch. It checks the original main
branch and the most recently published stable release, if any. The original
projects currently use main without GitHub Releases. Experimental branches are
excluded. GitHub may delay scheduled runs or disable them after repository inactivity;
review the Actions page if proposals stop appearing.

The workflow uses a disposable clone and never executes incoming project code.
It opens one draft `feature/upstream-*` pull request toward develop. When one is
already open, newer changes wait until it closes. The proposal identity is stable:
reruns do not duplicate it or reopen a previously rejected proposal. Remote branches
are never force-pushed and existing human edits are not overwritten.

A successful proposal contains the real merge and an `UPSTREAM_INTEGRATION.md`
review report. Fork README/documentation, assistant rules, workflows, feature-package
metadata and the personal Studio submodule configuration/pin are retained. The report
lists upstream changes to those retained paths for manual review. Upstream code and
VERSION are integrated, but require regression tests and review of release metadata.
A changed upstream LICENSE requires explicit review.

For unresolved conflicts, the merge is aborted and the draft contains only a report.
It explicitly says `Integration: BLOCKED`; the normal Gitflow check rejects it. Merge
the actual upstream changes, resolve the conflicts and update the report before it
can pass. Never remove the marker just to bypass a failed integration. These drafts
do not claim that an automatic agent has adapted conflicted functionality.

Enable **Allow GitHub Actions to create and approve pull requests** in repository
Actions settings. The workflow requests only contents and pull-request write access;
it never approves or merges a PR. Events created with GITHUB_TOKEN do not trigger
ordinary push/PR workflows. After reviewing the proposal, dispatch `ci.yml` manually
on its branch, or close and reopen the PR from your own account to trigger PR checks.
Do not treat an absent check as a passing check. No personal access token is stored
and no privileged pull_request_target workflow executes incoming code. Normal tests
run with read permissions and without signing secrets.

Merging upstream proposals does not itself publish a release. Follow the existing
Gitflow release process, package verification and signing gates. Publish a tested
Studio fork commit before changing the simulator's submodule pin to it.
