"""E10-02..E10-05: the CI workflow must keep enforcing what it was created to enforce.

Deliberately stdlib-only string assertions rather than a YAML parse: `pyyaml` is not in
`requirements-dev.txt` (which is frozen at `jsonschema`, `pytest`, `python-docx`), and adding a
dev dependency to test a config file is a worse trade than checking the few load-bearing lines
directly. GitHub is the thing that parses this file; what this test protects is that nobody
quietly narrows what it *runs* -- the failure mode where CI stays green while covering half the
repository.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


@pytest.fixture(scope="module")
def workflow() -> str:
    assert WORKFLOW.is_file(), "the CI workflow is missing"
    return WORKFLOW.read_text(encoding="utf-8")


def test_runs_on_every_push(workflow: str) -> None:
    """E10-02's acceptance is 'on every push', not 'on pull requests only'."""
    on_block = workflow.split("on:", 1)[1].split("permissions:", 1)[0]
    assert "push:" in on_block
    assert "pull_request:" in on_block


def test_schema_validation_runs_without_strict(workflow: str) -> None:
    """Hard rules fail, soft rules report. `--strict` promotes soft findings to failures and
    would fail every build on the accepted SEK1.M zahlen.json size overage."""
    assert "python data-pipeline/validate_dataset.py" in workflow
    assert "validate_dataset.py --strict" not in workflow


def test_pytest_runs_repository_wide(workflow: str) -> None:
    """E10-04 requires the DOCX goldens to be included, and they only are if collection covers
    the whole repository -- the golden tests live in tests/, the parser tests in
    data-pipeline/tests/."""
    assert "python -m pytest -q\n" in workflow
    for narrowed in ("pytest -q tests/", "pytest -q data-pipeline/"):
        assert narrowed not in workflow, f"pytest invocation was narrowed to {narrowed!r}"


def test_collection_guard_names_both_roots(workflow: str) -> None:
    """The guard is the thing that notices a narrowed collection. It is worthless if it stops
    naming a suite from each root."""
    assert "tests/test_renderer_golden.py" in workflow
    assert "data-pipeline/tests/test_parse_lehrplan.py" in workflow


def test_fetcher_selftest_is_network_blackholed(workflow: str) -> None:
    """E10-05: 'passes in a network-isolated job'. A self-test that quietly reaches RIS on the
    runner would prove nothing about offline correctness."""
    assert "--self-test" in workflow
    assert "http://127.0.0.1:9" in workflow
    # Lowercase only. This test previously also demanded HTTP_PROXY/HTTPS_PROXY, which
    # made it *enforce* a workflow GitHub rejects outright ("'HTTP_PROXY' is already
    # defined" -- env keys are compared case-insensitively). What matters here is that
    # the proxy variables exist and point at a closed port, not their casing; casing is
    # pinned separately by test_proxy_blackhole_stays_lowercase_only.
    for var in ("http_proxy", "https_proxy"):
        assert f"{var}: http://127.0.0.1:9" in workflow


def test_python_version_is_pinned(workflow: str) -> None:
    """The goldens are byte-maps of python-docx output; an unpinned runner interpreter can turn
    a packaging difference into a phantom golden failure."""
    assert 'PYTHON_VERSION: "3.13"' in workflow
    assert "python-version: ${{ env.PYTHON_VERSION }}" in workflow


# ---------------------------------------------------------------------------
# Structural checks that GitHub would otherwise be the first to make.
#
# The module docstring's reasoning ("GitHub is the thing that parses this file")
# has one hole: GitHub only parses it *after* a push, and pushing is owner-only
# here. A malformed workflow therefore cannot be discovered locally at all -- it
# burns a push/CI cycle instead. These checks are still stdlib-only.
#
# Real failure, 2026-08-11: the fetcher job set both `http_proxy` and
# `HTTP_PROXY` (belt-and-braces for tools that read one or the other). GitHub
# compares `env:` keys **case-insensitively** and rejected the entire workflow:
#   "(Line: 154, Col: 11): 'HTTP_PROXY' is already defined"
# Nothing in the repo could have caught it; the whole run was Invalid workflow
# file, so every job was skipped.
# ---------------------------------------------------------------------------

def _env_blocks(text: str) -> list[tuple[int, list[tuple[str, int]]]]:
    """Return (start_line, [(key, line_no), ...]) for every `env:` mapping."""
    import re

    lines = text.split("\n")
    blocks: list[tuple[int, list[tuple[str, int]]]] = []
    index = 0
    while index < len(lines):
        opener = re.match(r"^(\s*)env:\s*(#.*)?$", lines[index])
        if not opener:
            index += 1
            continue
        indent = len(opener.group(1))
        keys: list[tuple[str, int]] = []
        cursor = index + 1
        while cursor < len(lines):
            line = lines[cursor]
            if not line.strip() or line.strip().startswith("#"):
                cursor += 1
                continue
            entry = re.match(r"^(\s+)([A-Za-z_][A-Za-z0-9_-]*):", line)
            if not entry or len(entry.group(1)) <= indent:
                break
            keys.append((entry.group(2), cursor + 1))
            cursor += 1
        blocks.append((index + 1, keys))
        index = cursor
    return blocks


def test_env_blocks_have_no_case_insensitive_duplicate_keys(workflow: str) -> None:
    """GitHub rejects the whole file for this, so every job is skipped."""
    import collections

    failures = []
    for start, keys in _env_blocks(workflow):
        seen = collections.defaultdict(list)
        for key, line_no in keys:
            seen[key.lower()].append(f"{key} (line {line_no})")
        for lowered, occurrences in seen.items():
            if len(occurrences) > 1:
                failures.append(
                    f"env: block at line {start} defines {lowered!r} more than once: "
                    + ", ".join(occurrences)
                    + " -- GitHub compares env keys case-insensitively and will reject "
                    "the workflow as 'Invalid workflow file'"
                )
    assert not failures, "\n".join(failures)


def test_the_env_block_scanner_actually_finds_the_blocks(workflow: str) -> None:
    """Canary: a scanner that silently matches nothing would pass everything."""
    blocks = _env_blocks(workflow)
    assert blocks, "no env: blocks found -- the scanner is broken, not the workflow"
    assert any(keys for _, keys in blocks), "every env: block parsed as empty"


def test_proxy_blackhole_stays_lowercase_only(workflow: str) -> None:
    """The fix for the 2026-08-11 failure, pinned so it cannot be undone.

    urllib.request.getproxies_environment() lower-cases every variable name
    before matching, so lowercase alone reaches the fetcher; adding the
    uppercase twins buys nothing and breaks the file.
    """
    for forbidden in ("HTTP_PROXY:", "HTTPS_PROXY:", "NO_PROXY:"):
        assert forbidden not in workflow, (
            f"{forbidden} collides case-insensitively with its lowercase twin; "
            "keep the lowercase form only"
        )
    for required in ("http_proxy:", "https_proxy:", "no_proxy:"):
        assert required in workflow, f"the proxy blackhole lost {required}"
