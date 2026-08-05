"""Focused acceptance test for the Sek I mathematics planning-flow example.

These tests compare the fixture against the *real* public access layer in
``plugin/scripts/kompetenz.py`` -- predecessor, binding vs. optional
(``allenfalls``) application items, and cross-cutting themes -- rather than
only asserting that labels and IDs occur somewhere in the text. A fixture
that drifts from what the API actually returns (a fabricated theme, an
application item that isn't really binding, a predecessor ID the API
doesn't recognise) must fail one of these tests.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "planning_flow" / "sek1_mathematik_k2_bruchzahlen.lesson.json"
RENDERER = REPO_ROOT / "plugin" / "skills" / "at-unterrichtsplanung" / "scripts" / "render_documents.py"
SKILL = REPO_ROOT / "plugin" / "skills" / "at-unterrichtsplanung" / "SKILL.md"

sys.path.insert(0, str(REPO_ROOT / "plugin" / "scripts"))
import kompetenz  # noqa: E402  pylint: disable=wrong-import-position


def _blocks(value: object) -> list[dict]:
    if isinstance(value, dict):
        found = [value] if isinstance(value.get("type"), str) else []
        for child in value.values():
            found.extend(_blocks(child))
        return found
    if isinstance(value, list):
        return [block for child in value for block in _blocks(child)]
    return []


def _fixture_blocks_and_anchor() -> tuple[list[dict], dict]:
    source = json.loads(FIXTURE.read_text(encoding="utf-8"))
    blocks = _blocks(source)
    anchor = next(block for block in blocks if block.get("type") == "kompetenzbezug")
    return blocks, anchor


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
    blocks, anchor = _fixture_blocks_and_anchor()
    record = kompetenz.kompetenz_nach_id(anchor["kompetenz_id"])
    assert anchor["text"] == record["volltext"]
    assert anchor["quelle"] == record["provenienz"]
    assert record["fach"] == "SEK1.M"

    real_predecessors = kompetenz.finde_progression(record["id"], "zurueck")
    assert real_predecessors
    predecessor_ids = {p["id"] for p in real_predecessors}

    bist = kompetenz.finde_bildungsstandard_bezug(record["id"])
    assert bist["abgedeckt"] is True
    assert len(bist["zuordnungen"]) == 4
    assert len(bist["deskriptoren"]) == 12

    labels = {block.get("label") for block in blocks if block.get("type") in {"labeled", "list"}}
    assert "Verbindliche Anwendungsbereiche" in labels
    assert "Optionale Erweiterung (allenfalls, nicht verpflichtend)" in labels

    # The narrative must name a predecessor competence the API actually
    # returns for this competence -- not merely an ID that occurs somewhere,
    # and not one the fixture invented from memory.
    mentioned_ids = {
        match
        for block in blocks
        for match in re.findall(r"AT\.LP23\.SEK1\.M\.ZAHLEN\.K\d\.\d\d", block.get("text", ""))
        if match != record["id"]
    }
    assert mentioned_ids, "fixture must name at least one predecessor competence"
    assert mentioned_ids <= predecessor_ids, (
        f"fixture names {mentioned_ids - predecessor_ids}, which finde_progression "
        f"(zurueck) does not return for {record['id']}"
    )


def test_sek1_mathematik_flow_application_items_match_api_binding_split() -> None:
    blocks, anchor = _fixture_blocks_and_anchor()
    kompetenz_id = anchor["kompetenz_id"]

    real_binding = {
        item["text"]
        for item in kompetenz.finde_anwendungsbereiche(kompetenz_id, nur_verbindlich=True)
    }
    real_optional = {
        item["text"]
        for item in kompetenz.finde_anwendungsbereiche(kompetenz_id, nur_verbindlich=False)
    }

    binding_block = next(
        block
        for block in blocks
        if block.get("type") == "list" and block.get("label") == "Verbindliche Anwendungsbereiche"
    )
    fixture_binding = set(binding_block["items"])
    assert fixture_binding, "fixture must actually list at least one binding item"

    # Every item shown as binding must be a real binding item for this
    # competence, and none of them may secretly be an optional (allenfalls)
    # item smuggled into the binding section.
    assert fixture_binding <= real_binding, (
        f"fixture claims {fixture_binding - real_binding} as binding, "
        "but the API does not return it under nur_verbindlich=True"
    )
    assert fixture_binding.isdisjoint(real_optional), (
        f"fixture lists {fixture_binding & real_optional} as binding, "
        "but the API marks it optional (allenfalls)"
    )

    optional_block = next(
        block
        for block in blocks
        if block.get("label") == "Optionale Erweiterung (allenfalls, nicht verpflichtend)"
    )
    optional_text = optional_block.get("text", "")
    if real_optional:
        assert "keine verknüpfte optionale Präzisierung" not in optional_text, (
            "API returns optional items for this competence, but the fixture "
            "claims there are none -- a source-dependent empty case must "
            "actually be empty in the source, never merely convenient"
        )
    else:
        assert "keine verknüpfte optionale Präzisierung" in optional_text


def test_sek1_mathematik_flow_theme_tag_matches_api_exactly() -> None:
    blocks, anchor = _fixture_blocks_and_anchor()
    kompetenz_id = anchor["kompetenz_id"]
    real_themes = kompetenz.finde_uebergreifende_themen(kompetenz_id=kompetenz_id)

    theme_blocks = [block for block in blocks if block.get("type") == "uebergreifende_themen_tag"]

    if real_themes:
        assert len(theme_blocks) == 1
        assert theme_blocks[0]["themen"] == real_themes, (
            f"fixture tags {theme_blocks[0]['themen']} but the API returns "
            f"{real_themes} for {kompetenz_id}"
        )
    else:
        # The API ties no cross-cutting theme to this competence. The
        # fixture must neither invent one nor smuggle in a theme that
        # belongs to a sibling competence -- omitting the block is the only
        # option the source supports.
        assert theme_blocks == [], (
            f"API returns no uebergreifende_themen for {kompetenz_id}, but the "
            f"fixture still carries a uebergreifende_themen_tag block"
        )


def test_sek1_mathematik_flow_integer_claim_is_backed_by_real_evidence() -> None:
    """The lesson narrates a K1->K2 delta that (for this competence) includes
    whole/integer numbers ("ganze Zahlen"). If the narrative makes that
    claim, the activities and the exit ticket must contain a genuine
    integer, and the claim must be anchored on a real binding application
    item -- not only nonnegative fractions/decimals dressed up as a wider
    claim than the lesson actually teaches and assesses.
    """
    blocks, anchor = _fixture_blocks_and_anchor()
    kompetenz_id = anchor["kompetenz_id"]

    consolidation = next(
        (
            block
            for block in blocks
            if block.get("type") == "paragraph" and "neu ist" in block.get("text", "")
        ),
        None,
    )
    assert consolidation is not None, "fixture must state what is newly taught (Spiralprinzip)"
    if "ganze" not in consolidation["text"] and "ganzen" not in consolidation["text"]:
        pytest.skip("fixture no longer claims integer ('ganze Zahlen') work; nothing to reconcile")

    # Tokenise numbers so a decimal ("0,75") or a fraction ("2/3") is never
    # mistaken for a bare integer -- the fraction alternative must be tried
    # before the bare-integer one, since Python's re alternation takes the
    # first alternative that matches at all, not the longest.
    number_token = re.compile(r"\d+/\d+|-?\d+(?:[,.]\d+)?")
    integer_token = re.compile(r"-?\d+\Z")

    def _has_genuine_integer(text: str) -> bool:
        return any(integer_token.fullmatch(tok) for tok in number_token.findall(text))

    exit_ticket = next(
        block
        for block in blocks
        if block.get("type") == "callout" and block.get("label") == "Exit-Ticket"
    )
    assert _has_genuine_integer(exit_ticket["text"]), (
        "narrative claims integer comparison as newly taught, but the exit "
        "ticket contains no whole integer to assess it"
    )

    activity_blocks = [
        block
        for block in blocks
        if block.get("type") == "list" and block.get("label") is None
    ]
    assert any(
        _has_genuine_integer(item)
        for block in activity_blocks
        for item in block.get("items", [])
    ), (
        "narrative claims integer comparison as newly taught, but no "
        "activity contains a whole integer"
    )

    # The claim must be backed by a real, binding application-area item for
    # this exact competence -- not invented from memory.
    real_binding_texts = {
        item["text"]
        for item in kompetenz.finde_anwendungsbereiche(kompetenz_id, nur_verbindlich=True)
    }
    assert any(
        "ganzer Zahlen" in text or "ganze Zahlen" in text for text in real_binding_texts
    ), "no real binding application item for this competence covers 'ganze Zahlen'"


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
