#!/usr/bin/env bash
# Run the test suite the way CI sees the repository: against a fresh clone, which
# contains only *tracked* files.
#
# Why this exists. The local-only working documents (`teaching-skills-austria-plan.md`,
# `FINDINGS.md`, `BACKLOG.md`, `CLAUDE.md`, `AGENTS.md`, `handover.md`) are gitignored by
# decision -- nothing ships them. A test that reads one passes locally and fails on every
# runner, and because pushing is owner-only, that gap is invisible until it costs a full
# push/CI cycle. It cost one on 2026-08-11:
#
#     tests/test_differenzierung_skill.py::test_frontmatter_is_plan_section_6_5_verbatim
#     FileNotFoundError: .../teaching-skills-austria-plan.md
#
# Run this before asking the owner to push. It needs no network and touches nothing in the
# working tree -- the clone goes to a temporary directory and is removed afterwards.
#
# Usage:  scripts/ci_clone_check.sh [extra pytest args...]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-$REPO_ROOT/.venv/bin/python}"

if [[ ! -x "$PYTHON" ]]; then
    echo "error: no interpreter at $PYTHON (set PYTHON=... to override)" >&2
    exit 2
fi

CLONE="$(mktemp -d -t ci-clone-check-XXXXXX)"
cleanup() { rm -rf "$CLONE"; }
trap cleanup EXIT

git -C "$REPO_ROOT" clone --quiet . "$CLONE"

# Uncommitted work is invisible to `git clone`, which is the point for gitignored files but
# not for edits still in the working tree. Warn rather than silently test something stale.
if ! git -C "$REPO_ROOT" diff --quiet || ! git -C "$REPO_ROOT" diff --cached --quiet; then
    echo "note: uncommitted changes are NOT in the clone; commit them for a faithful check" >&2
fi

echo "running the suite against a tracked-files-only clone of $(git -C "$REPO_ROOT" rev-parse --short HEAD)"
cd "$CLONE"
"$PYTHON" -m pytest -q "$@"
