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
    for var in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        assert f"{var}:" in workflow


def test_python_version_is_pinned(workflow: str) -> None:
    """The goldens are byte-maps of python-docx output; an unpinned runner interpreter can turn
    a packaging difference into a phantom golden failure."""
    assert 'PYTHON_VERSION: "3.13"' in workflow
    assert "python-version: ${{ env.PYTHON_VERSION }}" in workflow
