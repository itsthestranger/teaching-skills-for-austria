"""E10-06: pin the plugin smoke test's contract.

Mostly stdlib-only string/structure assertions against the script source, in the
style of ``tests/test_ci_workflow.py`` -- what matters is that nobody quietly
narrows what the smoke test actually proves (e.g. silently dropping the
fresh-venv check, or running the CLI steps against the real repo checkout
instead of an isolated project dir). A handful of the tests below actually
execute the script, because its whole point -- proving a fresh venv doesn't
already have ``python-docx`` -- is not something a source-string assertion can
establish on its own.

The full six-phase run (which needs the real Claude Code CLI) is gated on the
CLI's presence, exactly like this repository's existing ``RESOURCES_XML.exists()``
gates: it runs here whenever ``claude`` happens to be on PATH (this dev box has
it), and skips cleanly -- not falsely -- everywhere else, including the plain
``tests`` CI job, which never installs the CLI.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "plugin_smoke_test.py"
PLANUNG_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "planning_flow" / "sek1_mathematik_k2_bruchzahlen.lesson.json"
DIFFERENZIERUNG_FIXTURE = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "differenzierung_flow"
    / "sek1_mathematik_k2_bruchrechnen.differenzierung.json"
)

CLAUDE_ON_PATH = shutil.which("claude") is not None


@pytest.fixture(scope="module")
def source() -> str:
    assert SCRIPT.is_file(), "the plugin smoke test script is missing"
    return SCRIPT.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Structural / contract tests (source-string, no execution).
# ---------------------------------------------------------------------------


def test_covers_all_four_backlog_steps_plus_the_fresh_venv_check(source: str) -> None:
    """E10-06's acceptance names four things: validate --strict, marketplace add,
    install, one planning + one differentiation flow. The script must invoke the
    real CLI for the first three and must not silently drop any of them."""
    assert '"plugin", "validate", "--strict"' in source
    assert '"plugin", "marketplace", "add"' in source
    assert '"plugin", "install"' in source
    assert "PLANUNG_FIXTURE" in source and "DIFFERENZIERUNG_FIXTURE" in source


def test_fresh_venv_check_is_a_real_before_after_assertion(source: str) -> None:
    """V-32's whole point: a smoke test that never proves the venv started
    *without* python-docx proves nothing about the fresh-environment risk."""
    assert 'import docx"' in source or "'import docx'" in source
    assert "pre.returncode == 0" in source  # fails the phase if docx is importable BEFORE install
    assert "fresh-environment" in source


def test_offline_phases_use_the_blackhole_proxy_convention(source: str) -> None:
    """Same trick as the fetcher-selftest CI job: proxy vars pointed at a closed
    port, so an accidental network call fails instead of silently succeeding."""
    assert "127.0.0.1:9" in source
    for var in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        assert f'"{var}"' in source


def test_offline_install_step_never_reaches_the_real_index(source: str) -> None:
    """The one bootstrap step that may use the network (building a local
    wheelhouse) must be clearly separated from the actual fresh-venv install,
    which must be `--no-index` and use only the local wheelhouse."""
    assert "--no-index" in source
    assert "--find-links" in source
    assert "wheelhouse" in source


def test_marketplace_and_install_never_run_against_the_real_repo_checkout(source: str) -> None:
    """`--scope local` writes <cwd>/.claude/settings.local.json. Running these
    commands with REPO_ROOT as cwd would leave that file behind in the actual
    project checkout -- everything must run in a throwaway project dir instead."""
    assert 'cwd=REPO_ROOT' not in source
    assert 'cwd=proj' in source
    assert "isolated from the operator's real ~/.claude" in source or "CLAUDE_CONFIG_DIR" in source


def test_flow_phases_are_labelled_proxy_not_real(source: str) -> None:
    """The planning/differentiation "flow" steps do not invoke a live Claude
    Code session (non-deterministic, needs auth, needs network) -- they must be
    labelled PROXY everywhere, never silently reported as the real thing."""
    assert 'phase_flow(work_dir, fresh_python, "planning-flow"' in source
    assert 'phase_flow(' in source and 'DIFFERENZIERUNG_FIXTURE' in source
    assert "def phase_flow(" in source
    # the function body must tag its own result PROXY, not REAL
    body = source.split("def phase_flow(", 1)[1].split("\ndef ", 1)[0]
    assert "REAL" not in body
    assert "PROXY" in body


def test_missing_cli_is_reported_as_proxy_skipped_not_silently_passed(source: str) -> None:
    assert "PROXY-SKIPPED" in source
    assert "skipped=True" in source


def test_require_cli_flag_exists_to_promote_skip_to_failure(source: str) -> None:
    assert "--require-cli" in source


def test_wheelhouse_flag_still_runs_the_install_no_index(source: str) -> None:
    """--wheelhouse lets callers reuse a pre-built wheel cache across repeated
    invocations; it must not become a shortcut that skips the actual
    --no-index install into the fresh venv."""
    assert "--wheelhouse" in source
    assert "wheelhouse.is_dir()" in source


def test_flow_doc_ids_match_the_committed_fixtures() -> None:
    """A silent drift between the script's expected doc-id tuples and what the
    fixtures actually carry would make the flow phases report false green (they
    would just find fewer files and might not notice) -- pin them against the
    real fixture content directly."""
    planung = json.loads(PLANUNG_FIXTURE.read_text(encoding="utf-8"))
    differenzierung = json.loads(DIFFERENZIERUNG_FIXTURE.read_text(encoding="utf-8"))

    planung_ids = tuple(doc["id"] for doc in planung["documents"])
    differenzierung_ids = tuple(doc["id"] for doc in differenzierung["documents"])

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import plugin_smoke_test as smoke  # noqa: E402  pylint: disable=wrong-import-position

    assert smoke.PLANUNG_DOC_IDS == planung_ids
    assert smoke.DIFFERENZIERUNG_DOC_IDS == differenzierung_ids


# ---------------------------------------------------------------------------
# Functional tests: these actually execute the script.
#
# All of them pass --wheelhouse pointed at one shared, session-scoped
# directory: without it, every invocation below would separately `pip wheel`
# the whole frozen dependency set (~6s each), which the script's own
# --wheelhouse flag exists to avoid. The offline, --no-index install into
# each test's own fresh venv is unaffected -- reusing the wheelhouse is not
# the same as skipping the install it feeds.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def shared_wheelhouse(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("smoke_wheelhouse")


def test_require_cli_promotes_a_missing_cli_to_failure(tmp_path: Path, shared_wheelhouse: Path) -> None:
    """Deterministic regardless of whether this environment happens to have the
    Claude Code CLI installed: PATH is stripped down so `claude` cannot resolve,
    then the flag's effect is checked both ways."""
    import os

    stripped_env = dict(os.environ)
    stripped_env["PATH"] = "/usr/bin:/bin"

    lenient = subprocess.run(
        [sys.executable, str(SCRIPT), "--work-dir", str(tmp_path / "a"), "--wheelhouse", str(shared_wheelhouse)],
        cwd=REPO_ROOT, env=stripped_env, capture_output=True, text=True, timeout=120,
    )
    assert lenient.returncode == 0, lenient.stdout + lenient.stderr
    assert "PROXY-SKIPPED" in lenient.stdout

    strict = subprocess.run(
        [sys.executable, str(SCRIPT), "--require-cli", "--work-dir", str(tmp_path / "b"), "--wheelhouse", str(shared_wheelhouse)],
        cwd=REPO_ROOT, env=stripped_env, capture_output=True, text=True, timeout=120,
    )
    assert strict.returncode != 0, "with --require-cli, a missing CLI must fail the run"
    assert "FAILED" in strict.stdout


def test_json_report_shape(tmp_path: Path, shared_wheelhouse: Path) -> None:
    import os

    stripped_env = dict(os.environ)
    stripped_env["PATH"] = "/usr/bin:/bin"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--json", "--work-dir", str(tmp_path), "--wheelhouse", str(shared_wheelhouse)],
        cwd=REPO_ROOT, env=stripped_env, capture_output=True, text=True, timeout=120,
    )
    report = json.loads(result.stdout)
    assert set(report) == {"ok", "require_cli", "steps"}
    names = {step["name"] for step in report["steps"]}
    assert names == {
        "fresh-venv-dependency-install",
        "validate-manifests",
        "marketplace-add",
        "install",
        "planning-flow",
        "differentiation-flow",
    }
    for step in report["steps"]:
        assert set(step) == {"name", "kind", "ok", "skipped", "detail"}


def test_work_dir_is_cleaned_up_unless_keep_is_passed(tmp_path: Path, shared_wheelhouse: Path) -> None:
    import os

    stripped_env = dict(os.environ)
    stripped_env["PATH"] = "/usr/bin:/bin"
    work_dir = tmp_path / "cleaned"

    subprocess.run(
        [sys.executable, str(SCRIPT), "--work-dir", str(work_dir), "--wheelhouse", str(shared_wheelhouse)],
        cwd=REPO_ROOT, env=stripped_env, capture_output=True, text=True, timeout=120,
    )
    assert not work_dir.exists(), "work dir must be removed when --keep is not passed"

    work_dir_kept = tmp_path / "kept"
    subprocess.run(
        [sys.executable, str(SCRIPT), "--work-dir", str(work_dir_kept), "--keep", "--wheelhouse", str(shared_wheelhouse)],
        cwd=REPO_ROOT, env=stripped_env, capture_output=True, text=True, timeout=120,
    )
    assert work_dir_kept.exists(), "work dir must survive when --keep is passed"


def test_never_writes_into_the_real_repo_claude_dir(tmp_path: Path, shared_wheelhouse: Path) -> None:
    """The exact regression this test guards against was hit while building this
    script: an early manual run with an unscoped cwd left a real
    .claude/settings.local.json inside the actual project checkout."""
    import os

    before = (REPO_ROOT / ".claude").exists()
    stripped_env = dict(os.environ)
    stripped_env["PATH"] = "/usr/bin:/bin"
    subprocess.run(
        [sys.executable, str(SCRIPT), "--work-dir", str(tmp_path), "--wheelhouse", str(shared_wheelhouse)],
        cwd=REPO_ROOT, env=stripped_env, capture_output=True, text=True, timeout=120,
    )
    after = (REPO_ROOT / ".claude").exists()
    assert before == after, "the smoke test must not create/modify a .claude/ dir in the real repo"


@pytest.mark.skipif(not CLAUDE_ON_PATH, reason="claude CLI not installed in this environment")
def test_full_chain_passes_for_real_when_the_cli_is_present(tmp_path: Path, shared_wheelhouse: Path) -> None:
    """When the real Claude Code CLI is available (this dev box; the dedicated
    CI job once wired up), all six phases must actually PASS -- none of them
    PROXY-SKIPPED -- and none of the flow phases may fall back to the
    "fresh-venv did not produce a usable interpreter" failure path."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--require-cli", "--work-dir", str(tmp_path), "--wheelhouse", str(shared_wheelhouse)],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PROXY-SKIPPED" not in result.stdout
    assert result.stdout.count("[         PASS]") == 6, result.stdout
