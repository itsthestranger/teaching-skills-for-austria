"""Focused acceptance test for the Sek I mathematics planning-flow example."""
from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "planning_flow" / "sek1_mathematik_k2_bruchzahlen.lesson.json"
RENDERER = REPO_ROOT / "plugin" / "skills" / "at-unterrichtsplanung" / "scripts" / "render_documents.py"
SKILL = REPO_ROOT / "plugin" / "skills" / "at-unterrichtsplanung" / "SKILL.md"


def _blocks(value: object) -> list[dict]:
    if isinstance(value, dict):
        found = [value] if isinstance(value.get("type"), str) else []
        for child in value.values():
            found.extend(_blocks(child))
        return found
    if isinstance(value, list):
        return [block for child in value for block in _blocks(child)]
    return []


def test_skill_prescribes_bounded_clarification_and_one_turn_rendering() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    for required in (
        "höchstens **zwei** gezielte Fragen",
        "`finde_progression(id, \"zurueck\")`",
        "`finde_anwendungsbereiche(id, nur_verbindlich=True)`",
        "`finde_anwendungsbereiche(id, nur_verbindlich=False)`",
        "`finde_lehrstoff(id)`",
        "`finde_bildungsstandard_bezug(id)`",
        "`finde_uebergreifende_themen(kompetenz_id=id)`",
        "in **einer** Antwort",
        "scripts/render_documents.py",
    ):
        assert required in skill


def test_sek1_mathematik_flow_fixture_is_officially_anchored_and_spiral() -> None:
    source = json.loads(FIXTURE.read_text(encoding="utf-8"))
    blocks = _blocks(source)
    anchor = next(block for block in blocks if block.get("type") == "kompetenzbezug")

    sys.path.insert(0, str(REPO_ROOT / "plugin" / "scripts"))
    import kompetenz  # pylint: disable=import-outside-toplevel

    record = kompetenz.kompetenz_nach_id(anchor["kompetenz_id"])
    assert anchor["text"] == record["volltext"]
    assert anchor["quelle"] == record["provenienz"]
    assert record["fach"] == "SEK1.M"
    assert kompetenz.finde_progression(record["id"], "zurueck")
    bist = kompetenz.finde_bildungsstandard_bezug(record["id"])
    assert bist["abgedeckt"] is True
    assert len(bist["zuordnungen"]) == 4
    assert len(bist["deskriptoren"]) == 12

    labels = {block.get("label") for block in blocks if block.get("type") in {"labeled", "list"}}
    assert "Verbindliche Anwendungsbereiche" in labels
    assert "Optionale Erweiterung (allenfalls, nicht verpflichtend)" in labels
    assert any(block.get("type") == "uebergreifende_themen_tag" for block in blocks)
    assert any("AT.LP23.SEK1.M.ZAHLEN.K1.01" in block.get("text", "") for block in blocks)


def test_sek1_mathematik_flow_fixture_renders_docx_in_one_command(tmp_path: Path) -> None:
    pytest.importorskip("docx", reason="python-docx is optional; DOCX flow test is skipped")
    result = subprocess.run(
        [sys.executable, str(RENDERER), str(FIXTURE), "--format", "docx", "--outdir", str(tmp_path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    docx_path = tmp_path / "unterrichtsplanung.docx"
    assert docx_path.is_file()
    assert (tmp_path / "unterrichtsplanung.html").is_file()
    with zipfile.ZipFile(docx_path) as document:
        assert "word/document.xml" in document.namelist()
