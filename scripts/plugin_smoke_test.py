#!/usr/bin/env python3
"""E10-06: plugin smoke test on a fresh environment.

Mitigates the risk V-32 names: ``python-docx`` is a *runtime* dependency of the
plugin's .docx renderer (decision E5-11 kept upstream's ``pip install`` after
vendoring was investigated and rejected -- ``python-docx`` -> ``lxml`` -> 7
compiled ``.so`` files bound to CPython version x arch x libc). A smoke test
that passes because the invoking shell already has ``python-docx`` installed
proves nothing about that risk; this script goes out of its way to prove the
opposite -- that a venv which provably does NOT have the package before this
script runs, does have it afterwards, and that everything downstream (the
.docx deliverable itself) is produced by *that* interpreter, not the one
running this script.

Six phases, run in this order:

  1. fresh-venv-dependency-install (REAL)   -- prove the fresh-environment
     delivery story for python-docx actually works.
  2. validate-manifests            (REAL, requires the Claude Code CLI)
  3. marketplace-add               (REAL, requires the Claude Code CLI)
  4. install                       (REAL, requires the Claude Code CLI)
  5. planning-flow                 (PROXY -- see below)
  6. differentiation-flow          (PROXY -- see below)

Phases 2-4 need the real ``claude`` binary on PATH. It is not installed in
this repository's own dev/CI Python environment (it is a separate Node/native
tool), so this script auto-detects it: if missing, those phases are recorded
as **PROXY-SKIPPED**, never silently reported as passed. Pass ``--require-cli``
(the dedicated CI job does) to turn a missing/broken CLI into a hard failure
instead of a silent skip -- that job exists specifically to prove the CLI
steps run, not merely that this script tolerates their absence.

Phases 5-6 are **honest proxies**, not the real thing, and are labelled as
such in every place they are reported. The real "planning flow" / "differen-
tiation flow" is a live, conversational Claude Code session that reads
SKILL.md, asks the teacher clarifying questions, and authors a lesson.json
from scratch -- that requires a non-deterministic, authenticated model call
and cannot be part of an offline, deterministic CI smoke test (see "what to
build" point 3 in the E10-06 brief). What CAN run deterministically and
offline is the mechanical backend that flow depends on and is gated on
(SKILL.md Schritt 4): ``plugin/scripts/pruefe_verankerung.py`` validating a
committed fixture against the live access layer, followed by the same
``render_documents.py`` each skill actually ships, run with the interpreter
this script just fresh-installed python-docx into. That is the closest
honest proxy, not a fabricated pass.

Deterministic and offline by construction: every phase after the one
explicitly-labelled bootstrap step (building a local wheel cache from
``requirements-dev.txt``, exactly the same network use every existing CI job
already makes via ``pip install -r requirements-dev.txt``) runs with the
outbound proxy variables pointed at a closed port, the same blackhole trick
``fetch_ris_resources.py --self-test`` uses in CI -- an accidental network
call fails fast and loudly instead of quietly succeeding.

Usage:
    python scripts/plugin_smoke_test.py
    python scripts/plugin_smoke_test.py --require-cli --json
    python scripts/plugin_smoke_test.py --keep --work-dir /tmp/smoke
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import venv
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = REPO_ROOT / "requirements-dev.txt"

PLUGIN_DIR = REPO_ROOT / "plugin"
PLUGIN_MANIFEST = PLUGIN_DIR / ".claude-plugin" / "plugin.json"
MARKETPLACE_MANIFEST = PLUGIN_DIR / ".claude-plugin" / "marketplace.json"

PRUEFE_VERANKERUNG = PLUGIN_DIR / "scripts" / "pruefe_verankerung.py"

PLANUNG_RENDERER = PLUGIN_DIR / "skills" / "at-unterrichtsplanung" / "scripts" / "render_documents.py"
PLANUNG_FIXTURE = (
    REPO_ROOT / "tests" / "fixtures" / "planning_flow" / "sek1_mathematik_k2_bruchzahlen.lesson.json"
)
PLANUNG_DOC_IDS = ("unterrichtsplanung", "schueler_material", "beobachtungsbogen")

DIFFERENZIERUNG_RENDERER = PLUGIN_DIR / "skills" / "at-differenzierung" / "scripts" / "render_documents.py"
DIFFERENZIERUNG_FIXTURE = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "differenzierung_flow"
    / "sek1_mathematik_k2_bruchrechnen.differenzierung.json"
)
DIFFERENZIERUNG_DOC_IDS = ("differenzierungsplan", "arbeitsblatt_unter", "arbeitsblatt_auf", "arbeitsblatt_ueber")

MARKETPLACE_NAME = "teaching-skills-austria"
PLUGIN_ID = f"{MARKETPLACE_NAME}@{MARKETPLACE_NAME}"

# Same blackhole trick as the fetcher-selftest CI job: point every proxy
# variable at a closed local port so an accidental outbound call fails fast
# instead of quietly succeeding on a machine that happens to have network.
BLACKHOLE_PROXY_ENV = {
    "http_proxy": "http://127.0.0.1:9",
    "https_proxy": "http://127.0.0.1:9",
    "HTTP_PROXY": "http://127.0.0.1:9",
    "HTTPS_PROXY": "http://127.0.0.1:9",
    "no_proxy": "",
    "NO_PROXY": "",
}

REAL = "real"
PROXY = "proxy"
BOOTSTRAP = "bootstrap"


@dataclass
class StepResult:
    name: str
    kind: str  # REAL / PROXY / BOOTSTRAP
    ok: bool
    skipped: bool = False
    detail: str = ""
    log: str = field(default="", repr=False)

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "ok": self.ok,
            "skipped": self.skipped,
            "detail": self.detail,
        }


def _run(cmd: list[str], cwd: Path | None = None, env: dict | None = None, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(part) for part in cmd],
        cwd=str(cwd) if cwd else None,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _offline_env(extra: dict | None = None) -> dict:
    env = dict(os.environ)
    env.update(BLACKHOLE_PROXY_ENV)
    if extra:
        env.update(extra)
    return env


# ---------------------------------------------------------------------------
# Phase 1: fresh-venv dependency install -- the V-32 mitigation itself.
# ---------------------------------------------------------------------------


def phase_fresh_venv(work_dir: Path, wheelhouse: Path | None = None) -> tuple[StepResult, Path | None]:
    name = "fresh-venv-dependency-install"
    wheelhouse = wheelhouse or (work_dir / "wheelhouse")
    venv_dir = work_dir / "fresh_venv"

    # Bootstrap (network allowed): build a local wheel cache from the frozen
    # requirements file with whatever interpreter is running this script.
    # This is the same network use every existing CI job already makes via
    # `pip install -r requirements-dev.txt`; it is not part of the offline
    # guarantee below, and is labelled BOOTSTRAP rather than REAL/PROXY.
    # Reused across runs when the caller passes an existing --wheelhouse (the
    # test suite does, to avoid rebuilding it on every invocation); a fresh
    # temp work dir gets a fresh one built here.
    if not (wheelhouse.is_dir() and any(wheelhouse.iterdir())):
        build = _run([sys.executable, "-m", "pip", "wheel", "-r", str(REQUIREMENTS), "-w", str(wheelhouse), "-q"])
        if build.returncode != 0:
            return StepResult(name, REAL, ok=False, detail="could not build local wheelhouse", log=build.stderr), None

    venv.EnvBuilder(with_pip=True, clear=True).create(venv_dir)
    venv_python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    pre = _run([str(venv_python), "-c", "import docx"])
    if pre.returncode == 0:
        return (
            StepResult(
                name,
                REAL,
                ok=False,
                detail="python-docx was already importable in the freshly created venv, "
                "before this script installed anything -- the fresh-environment "
                "guarantee is void (something leaked in from outside the venv)",
            ),
            None,
        )

    # The genuinely offline, deterministic half: install into the fresh venv
    # from the local wheelhouse only, with the network blackholed so a
    # `--no-index` bug (falling through to the real index) fails loudly.
    install = _run(
        [str(venv_python), "-m", "pip", "install", "--no-index", "--find-links", str(wheelhouse), "-r", str(REQUIREMENTS), "-q"],
        env=_offline_env(),
    )
    if install.returncode != 0:
        return StepResult(name, REAL, ok=False, detail="offline install into the fresh venv failed", log=install.stderr), None

    post = _run([str(venv_python), "-c", "import docx; print(docx.__file__)"])
    if post.returncode != 0:
        return (
            StepResult(name, REAL, ok=False, detail="install exited 0 but python-docx is still not importable", log=post.stderr),
            None,
        )
    if str(venv_dir) not in post.stdout:
        return (
            StepResult(
                name,
                REAL,
                ok=False,
                detail=f"python-docx resolved outside the fresh venv ({post.stdout.strip()!r}) -- not proof of a fresh install",
            ),
            None,
        )

    return (
        StepResult(name, REAL, ok=True, detail="python-docx: not importable before install, importable from the fresh venv after"),
        venv_python,
    )


# ---------------------------------------------------------------------------
# Phases 2-4: the real Claude Code CLI chain.
# ---------------------------------------------------------------------------


def _claude_available() -> str | None:
    return shutil.which("claude")


def phase_validate_manifests(work_dir: Path) -> StepResult:
    name = "validate-manifests"
    claude = _claude_available()
    if not claude:
        return StepResult(name, REAL, ok=True, skipped=True, detail="claude CLI not on PATH -- see --require-cli")

    cfg = work_dir / "config_validate"
    env = _offline_env({"CLAUDE_CONFIG_DIR": str(cfg)})
    for manifest in (PLUGIN_MANIFEST, MARKETPLACE_MANIFEST):
        result = _run([claude, "plugin", "validate", "--strict", str(manifest)], env=env)
        if result.returncode != 0:
            return StepResult(name, REAL, ok=False, detail=f"validate --strict failed for {manifest}", log=result.stdout + result.stderr)
    return StepResult(name, REAL, ok=True, detail="plugin.json and marketplace.json both pass --strict")


def phase_marketplace_add(work_dir: Path) -> StepResult:
    name = "marketplace-add"
    claude = _claude_available()
    if not claude:
        return StepResult(name, REAL, ok=True, skipped=True, detail="claude CLI not on PATH -- see --require-cli")

    # A fresh CLAUDE_CONFIG_DIR (isolated from the operator's real ~/.claude) and a
    # throwaway project directory as cwd: `--scope local` writes to
    # <cwd>/.claude/settings.local.json, and this script must never leave that
    # behind in the actual repository checkout.
    cfg = work_dir / "config_marketplace"
    proj = work_dir / "marketplace_project"
    proj.mkdir(parents=True, exist_ok=True)
    env = _offline_env({"CLAUDE_CONFIG_DIR": str(cfg)})

    result = _run([claude, "plugin", "marketplace", "add", str(PLUGIN_DIR), "--scope", "local"], cwd=proj, env=env)
    if result.returncode != 0:
        return StepResult(name, REAL, ok=False, detail="marketplace add failed", log=result.stdout + result.stderr)
    return StepResult(name, REAL, ok=True, detail=result.stdout.strip())


def phase_install(work_dir: Path) -> StepResult:
    name = "install"
    claude = _claude_available()
    if not claude:
        return StepResult(name, REAL, ok=True, skipped=True, detail="claude CLI not on PATH -- see --require-cli")

    # Fresh config + project dir again, and re-run marketplace add here too:
    # `install` needs the marketplace registered in the *same* CLAUDE_CONFIG_DIR,
    # and phase_marketplace_add's own directories are torn down independently.
    cfg = work_dir / "config_install"
    proj = work_dir / "install_project"
    proj.mkdir(parents=True, exist_ok=True)
    env = _offline_env({"CLAUDE_CONFIG_DIR": str(cfg)})

    add = _run([claude, "plugin", "marketplace", "add", str(PLUGIN_DIR), "--scope", "local"], cwd=proj, env=env)
    if add.returncode != 0:
        return StepResult(name, REAL, ok=False, detail="prerequisite marketplace add failed", log=add.stdout + add.stderr)

    install = _run([claude, "plugin", "install", PLUGIN_ID, "--scope", "local"], cwd=proj, env=env)
    if install.returncode != 0:
        return StepResult(name, REAL, ok=False, detail="install failed", log=install.stdout + install.stderr)

    listing = _run([claude, "plugin", "list"], cwd=proj, env=env)
    if listing.returncode != 0 or PLUGIN_ID not in listing.stdout or "enabled" not in listing.stdout.lower():
        return StepResult(name, REAL, ok=False, detail="plugin list does not show the plugin enabled", log=listing.stdout)
    return StepResult(name, REAL, ok=True, detail=f"{PLUGIN_ID} installed and enabled (scope: local)")


# ---------------------------------------------------------------------------
# Phases 5-6: planning / differentiation flow proxies.
# ---------------------------------------------------------------------------


def phase_flow(
    work_dir: Path,
    fresh_python: Path | None,
    label: str,
    fixture: Path,
    renderer: Path,
    doc_ids: tuple[str, ...],
) -> StepResult:
    if fresh_python is None:
        return StepResult(
            label,
            PROXY,
            ok=False,
            detail="fresh-venv-dependency-install did not produce a usable interpreter; cannot "
            "prove the deliverable renders in a fresh environment",
        )

    check = _run([sys.executable, str(PRUEFE_VERANKERUNG), str(fixture)], env=_offline_env())
    if check.returncode != 0:
        return StepResult(label, PROXY, ok=False, detail="pruefe_verankerung.py rejected the fixture", log=check.stdout + check.stderr)

    outdir = work_dir / f"{label}_out"
    render = _run(
        [str(fresh_python), str(renderer), str(fixture), "--format", "both", "--outdir", str(outdir)],
        env=_offline_env(),
    )
    if render.returncode != 0:
        return StepResult(label, PROXY, ok=False, detail="render_documents.py failed", log=render.stdout + render.stderr)

    missing: list[str] = []
    for doc_id in doc_ids:
        docx_path = outdir / f"{doc_id}.docx"
        html_path = outdir / f"{doc_id}.html"
        if not docx_path.is_file():
            missing.append(f"{docx_path.name} (docx)")
            continue
        if not html_path.is_file():
            missing.append(f"{html_path.name} (html)")
        with zipfile.ZipFile(docx_path) as archive:
            if "word/document.xml" not in archive.namelist():
                missing.append(f"{docx_path.name}: not a valid docx package")

    if missing:
        return StepResult(label, PROXY, ok=False, detail=f"missing/invalid outputs: {missing}")
    return StepResult(
        label,
        PROXY,
        ok=True,
        detail=f"pruefe_verankerung clean; {len(doc_ids)} document(s) rendered docx+html by the fresh venv's interpreter",
    )


# ---------------------------------------------------------------------------


def run_all(work_dir: Path, require_cli: bool, wheelhouse: Path | None = None) -> list[StepResult]:
    results: list[StepResult] = []

    fresh_result, fresh_python = phase_fresh_venv(work_dir, wheelhouse=wheelhouse)
    results.append(fresh_result)

    results.append(phase_validate_manifests(work_dir))
    results.append(phase_marketplace_add(work_dir))
    results.append(phase_install(work_dir))

    results.append(
        phase_flow(work_dir, fresh_python, "planning-flow", PLANUNG_FIXTURE, PLANUNG_RENDERER, PLANUNG_DOC_IDS)
    )
    results.append(
        phase_flow(
            work_dir,
            fresh_python,
            "differentiation-flow",
            DIFFERENZIERUNG_FIXTURE,
            DIFFERENZIERUNG_RENDERER,
            DIFFERENZIERUNG_DOC_IDS,
        )
    )

    return results


def _overall_ok(results: list[StepResult], require_cli: bool) -> bool:
    for result in results:
        if result.skipped:
            if require_cli:
                return False
            continue
        if not result.ok:
            return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--work-dir", default=None, help="directory to build the fresh venv/config in (default: a new temp dir)")
    parser.add_argument("--keep", action="store_true", help="do not delete --work-dir afterwards (debugging)")
    parser.add_argument(
        "--require-cli",
        action="store_true",
        help="treat a missing/unusable claude CLI as a failure instead of a PROXY-SKIPPED pass "
        "(the dedicated CI job sets this: that job's entire point is to prove the CLI steps run)",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable JSON report on stdout instead of the human-readable summary")
    parser.add_argument(
        "--wheelhouse",
        default=None,
        help="reuse (or populate, if empty/missing) this directory as the local wheel cache instead "
        "of building a fresh one per run -- avoids rebuilding it across repeated invocations; the "
        "install into the fresh venv still runs --no-index against it",
    )
    args = parser.parse_args()

    work_dir = Path(args.work_dir) if args.work_dir else Path(tempfile.mkdtemp(prefix="plugin_smoke_"))
    work_dir.mkdir(parents=True, exist_ok=True)
    wheelhouse = Path(args.wheelhouse) if args.wheelhouse else None
    if wheelhouse:
        wheelhouse.mkdir(parents=True, exist_ok=True)

    try:
        results = run_all(work_dir, args.require_cli, wheelhouse=wheelhouse)
    finally:
        if not args.keep:
            shutil.rmtree(work_dir, ignore_errors=True)

    overall_ok = _overall_ok(results, args.require_cli)

    if args.json:
        print(json.dumps({"ok": overall_ok, "require_cli": args.require_cli, "steps": [r.to_json() for r in results]}, indent=2))
    else:
        width = max(len(r.name) for r in results)
        for r in results:
            if r.skipped:
                status = "PROXY-SKIPPED"
            elif r.ok:
                status = "PASS"
            else:
                status = "FAIL"
            print(f"[{status:>13}] ({r.kind:>9}) {r.name.ljust(width)}  {r.detail}")
            if not r.ok and not r.skipped and r.log:
                for line in r.log.strip().splitlines()[-20:]:
                    print(f"    {line}")
        print()
        if overall_ok:
            print("plugin smoke test: OK" + (" (some CLI steps proxy-skipped -- see above)" if any(r.skipped for r in results) else ""))
        else:
            print("plugin smoke test: FAILED")

    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
