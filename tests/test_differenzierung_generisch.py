"""E7-04 acceptance: the generic ``lehrplan_generisch`` differentiation axis, demonstrated on a
non-mathematics subject (Sachunterricht, ``PRIM.SU``).

These tests compare the fixture
``tests/fixtures/differenzierung_flow/prim_sachunterricht_sch3_wetter.differenzierung.json``
against the *real* public access layer in ``plugin/scripts/kompetenz.py`` (V-60/V-61/V-78/V-88
ground truth), not merely against strings that happen to occur in the file. Central point of this
task: ``PRIM.SU`` has ``anwendungsbereiche_bindung: "stufe"``, so the ten Anwendungsbereich items
for the anchored competence's Schulstufe are shared verbatim across every competence of that
Schulstufe, in all six Kompetenzbereiche -- a fixture that presents the full ten-item list as
precisifications of one Naturwissenschaftliche competence would misattribute stage-shared content,
the exact defect this task must not ship.
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
FIXTURE = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "differenzierung_flow"
    / "prim_sachunterricht_sch3_wetter.differenzierung.json"
)
RENDERER = REPO_ROOT / "plugin" / "skills" / "at-differenzierung" / "scripts" / "render_documents.py"
CHECKER = REPO_ROOT / "plugin" / "scripts" / "pruefe_verankerung.py"

sys.path.insert(0, str(REPO_ROOT / "plugin" / "scripts"))
import kompetenz  # noqa: E402  pylint: disable=wrong-import-position
import pruefe_verankerung  # noqa: E402  pylint: disable=wrong-import-position

KOMPETENZ_ID = "AT.LP23.PRIM.SU.NATURWISS.SCH3.01"


def _blocks(value: object) -> list[dict]:
    if isinstance(value, dict):
        found = [value] if isinstance(value.get("type"), str) else []
        for child in value.values():
            found.extend(_blocks(child))
        return found
    if isinstance(value, list):
        return [block for child in value for block in _blocks(child)]
    return []


def _source() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _blocks_and_anchor() -> tuple[list[dict], dict]:
    source = _source()
    blocks = _blocks(source)
    anchor = next(block for block in blocks if block.get("type") == "kompetenzbezug")
    return blocks, anchor


def _all_text(blocks: list[dict]) -> str:
    """Every reader-facing string on a flattened block list -- body text, labels (rendered
    as bold headers) and list items alike, so a claim hidden in a label or a
    ``quelle_hinweis`` cannot dodge a text-content assertion."""
    parts: list[str] = []
    for block in blocks:
        for key in ("text", "label", "quelle_hinweis"):
            value = block.get(key)
            if isinstance(value, str):
                parts.append(value)
        items = block.get("items")
        if isinstance(items, list):
            parts.extend(item for item in items if isinstance(item, str))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Fixture exists, is anchored on the right competence, passes the checker.
# ---------------------------------------------------------------------------


def test_fixture_exists_and_is_anchored_on_the_worked_example() -> None:
    blocks, anchor = _blocks_and_anchor()
    assert anchor["kompetenz_id"] == KOMPETENZ_ID
    record = kompetenz.kompetenz_nach_id(KOMPETENZ_ID)
    assert record["fach"] == "PRIM.SU"
    assert anchor["text"] == record["volltext"] == kompetenz.voller_wortlaut(record)
    assert anchor["quelle"] == record["provenienz"]


def test_pruefe_verankerung_accepts_the_fixture() -> None:
    verletzungen = pruefe_verankerung.pruefe_lesson(FIXTURE)
    assert verletzungen == [], verletzungen


def test_pruefe_verankerung_cli_exits_zero() -> None:
    result = subprocess.run(
        [sys.executable, str(CHECKER), str(FIXTURE)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


# ---------------------------------------------------------------------------
# Renders to DOCX with exit 0.
# ---------------------------------------------------------------------------


def test_fixture_renders_docx_in_one_command(tmp_path: Path) -> None:
    pytest.importorskip("docx", reason="python-docx is optional; DOCX flow test is skipped")
    result = subprocess.run(
        [sys.executable, str(RENDERER), str(FIXTURE), "--format", "docx", "--outdir", str(tmp_path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    source = _source()
    for doc in source["documents"]:
        doc_id = doc["id"]
        docx_path = tmp_path / f"{doc_id}.docx"
        assert docx_path.is_file(), f"{doc_id}.docx was not written"
        assert (tmp_path / f"{doc_id}.html").is_file(), f"{doc_id}.html was not written"
        with zipfile.ZipFile(docx_path) as document:
            assert "word/document.xml" in document.namelist()


# ---------------------------------------------------------------------------
# 4 documents with the right ids/audiences.
# ---------------------------------------------------------------------------


def test_fixture_carries_four_documents_with_correct_ids_and_audiences() -> None:
    source = _source()
    docs = {doc["id"]: doc for doc in source["documents"]}
    assert set(docs) == {
        "differenzierungsplan",
        "arbeitsblatt_grundlegend",
        "arbeitsblatt_erweitert",
        "arbeitsblatt_vertiefend",
    }
    assert docs["differenzierungsplan"]["audience"] == "teacher"
    for doc_id in ("arbeitsblatt_grundlegend", "arbeitsblatt_erweitert", "arbeitsblatt_vertiefend"):
        assert docs[doc_id]["audience"] == "student"
    for doc in source["documents"]:
        assert doc["sections"], f"{doc['id']} has no sections"


def test_kompetenzbezug_lives_only_in_shared_and_is_referenced_via_from_shared() -> None:
    """The kompetenzbezug (with its full ``quelle``) must live once, in ``shared`` -- never
    retyped into a second document. Every document that shows it does so via a
    ``from_shared`` block."""
    source = _source()
    shared_kompetenz_blocks = [
        v for v in source["shared"].values()
        if isinstance(v, dict) and v.get("type") == "kompetenzbezug"
    ]
    assert len(shared_kompetenz_blocks) == 1

    # No document may carry a second, independently-typed kompetenzbezug block --
    # only from_shared references back to the one in `shared`.
    for doc in source["documents"]:
        doc_blocks = _blocks(doc)
        assert not any(b.get("type") == "kompetenzbezug" for b in doc_blocks), (
            f"document {doc['id']!r} retypes a kompetenzbezug block instead of "
            "referencing it via from_shared"
        )
        from_shared_keys = {b["key"] for b in doc_blocks if b.get("type") == "from_shared"}
        assert "kompetenz" in from_shared_keys, f"document {doc['id']!r} never references the shared anchor"


# ---------------------------------------------------------------------------
# The three tier labels are read from the axis, not hardcoded.
# ---------------------------------------------------------------------------


def test_tier_labels_match_the_axis_niveaus_read_live_from_data() -> None:
    diff = kompetenz.finde_differenzierung(KOMPETENZ_ID)
    assert diff["achse"]["typ"] == "lehrplan_generisch"
    assert diff["achse"].get("gilt_ab_stufe") is None
    assert diff["niveaus"] == diff["achse"]["niveaus"]
    assert diff["niveaus"], "PRIM.SU must have effective niveaus at every stage -- no K1-style suppression"

    source = _source()
    docs = {doc["id"]: doc for doc in source["documents"]}
    tier_doc_ids = ("arbeitsblatt_grundlegend", "arbeitsblatt_erweitert", "arbeitsblatt_vertiefend")
    assert len(diff["niveaus"]) == len(tier_doc_ids)

    for expected_label, doc_id in zip(diff["niveaus"], tier_doc_ids):
        blocks = _blocks(docs[doc_id])
        label_block = next(
            (b for b in blocks if b.get("type") == "labeled" and b.get("label") == "Niveaustufe"),
            None,
        )
        assert label_block is not None, f"{doc_id} carries no Niveaustufe block"
        assert label_block["text"] == expected_label, (
            f"{doc_id}'s Niveaustufe {label_block['text']!r} does not match the live axis "
            f"label {expected_label!r} at this position"
        )


# ---------------------------------------------------------------------------
# enrichment_items is empty for this shard; no document text claims otherwise.
# ---------------------------------------------------------------------------


def test_enrichment_items_is_empty_and_no_document_claims_dataset_enrichment() -> None:
    diff = kompetenz.finde_differenzierung(KOMPETENZ_ID)
    assert diff["achse"].get("enrichment_quelle") != "allenfalls"
    assert diff["enrichment_items"] == []

    source = _source()
    full_text = _all_text(_blocks(source))
    # Nothing may claim a per-item Standard-AHS marker (V-60) -- that phrase is SEK1-only
    # prose and never applies to PRIM.SU.
    assert "Standard AHS" not in full_text
    assert "allenfalls" not in full_text.lower() or "kein" in full_text.lower()

    # The vertiefend document must say plainly that this is skill-authored depth, not a
    # dataset enrichment query.
    vertiefend = next(doc for doc in source["documents"] if doc["id"] == "arbeitsblatt_vertiefend")
    vertiefend_text = _all_text(_blocks(vertiefend))
    assert "kein Datensatz-Enrichment" in vertiefend_text or "skill-eigene" in vertiefend_text


def test_measured_enrichment_items_empty_across_all_prim_su_competences() -> None:
    """Ground truth backing the reference doc's blanket claim: 0/48, not just this one
    competence."""
    records = kompetenz.finde_kompetenz("PRIM.SU")
    assert len(records) == 48
    for record in records:
        diff = kompetenz.finde_differenzierung(record["id"])
        assert diff["enrichment_items"] == []
        assert diff["niveaus"], f"{record['id']} unexpectedly has empty niveaus"


# ---------------------------------------------------------------------------
# No Bildungsstandard is asserted anywhere.
# ---------------------------------------------------------------------------


def test_no_bildungsstandard_is_asserted() -> None:
    bist = kompetenz.finde_bildungsstandard_bezug(KOMPETENZ_ID)
    assert bist == {"abgedeckt": False, "grund": "keine BiSt verordnet"}

    source = _source()
    full_text = _all_text(_blocks(source))
    assert "abgedeckt" not in full_text or "False" in full_text or "keine BiSt verordnet" in full_text
    # No document may claim a Bildungsstandard descriptor count/coverage the way the SEK1.M
    # fixture legitimately does -- PRIM.SU has none.
    assert "Deskriptoren" not in full_text
    assert "M8-Bereich" not in full_text and "AT.BIST" not in full_text


# ---------------------------------------------------------------------------
# Every application item cited is real (set membership), and the material does not present
# the full stage list as competence-bound.
# ---------------------------------------------------------------------------


def test_cited_application_items_are_real_and_not_the_full_stage_list() -> None:
    real_items = {
        item["text"]: item
        for item in kompetenz.finde_anwendungsbereiche(KOMPETENZ_ID, nur_verbindlich=True)
    }
    assert len(real_items) == 10, "V-brief ground truth: 10 stage-shared items at SCH3"

    source = _source()
    blocks = _blocks(source)
    cited: set[str] = set()
    for block in blocks:
        if block.get("type") == "list" and isinstance(block.get("label"), str):
            if "verbindlich" in block["label"].lower() or "anwendungsbereich" in block["label"].lower():
                cited.update(i for i in block.get("items", []) if isinstance(i, str))

    assert cited, "fixture must cite at least one application item"
    # Every cited item must be a real, verbatim member of the stage list.
    assert cited <= set(real_items), f"fixture cites {cited - set(real_items)}, which is not real"
    # The material must select a genuine subset, not reproduce the full stage list --
    # presenting all ten as bound to this one competence is the exact defect this task
    # must not ship.
    assert len(cited) < len(real_items), (
        "fixture cites the entire stage-shared application-area list as if it were bound "
        "to this one competence"
    )


def _parse_hinweis_selected_and_excluded(hinweis_text: str) -> tuple[set[str], set[str]]:
    """Parse the two item sets ``anwendungsbereiche_hinweis`` itself names -- the ones it
    says were *selected* ("... sind für diese Einheit pädagogisch ausgewählt") and the
    worked examples it names among the *excluded* rest ("Die übrigen ... (u. a. '...', ...)").

    Deliberately parses the fixture's own prose rather than hardcoding a copy of the
    selection: a hardcoded list would pass unchanged if the actual selection silently
    drifted away from what the hinweis claims (smuggled-in item, dropped item, ...) --
    exactly the gap a coordinator mutation test found. Raises via assertion if the hinweis
    no longer follows this phrasing, so a rewrite that breaks the parseable structure fails
    loudly instead of silently returning an empty set that trivially satisfies subset checks.
    """
    selected_match = re.search(
        r"\(([^)]*)\)\s+sind für diese Einheit pädagogisch ausgewählt", hinweis_text
    )
    assert selected_match, (
        "anwendungsbereiche_hinweis must name the selected items in parentheses "
        "immediately before '... sind für diese Einheit pädagogisch ausgewählt'"
    )
    selected = set(re.findall(r"'([^']+)'", selected_match.group(1)))
    assert selected, "no quoted items found in the hinweis's 'ausgewählt' clause"

    excluded_match = re.search(r"Die übrigen \w+\s*\(u\. a\. ([^)]*)\)", hinweis_text)
    assert excluded_match, (
        "anwendungsbereiche_hinweis must name worked examples of the excluded rest after "
        "'Die übrigen <N> (u. a. ...)'"
    )
    excluded_examples = set(re.findall(r"'([^']+)'", excluded_match.group(1)))
    assert excluded_examples, "no quoted example items found in the hinweis's excluded clause"

    return selected, excluded_examples


def test_selection_matches_the_hinweis_exactly_and_never_contains_a_named_excluded_item() -> None:
    """Closes a real gap a coordinator mutation test found: set-membership alone (every cited
    item is real) and cardinality alone (fewer than all ten) both stay green if an official
    but wrong-Kompetenzbereich item is smuggled in for one that belongs, or if a genuinely
    relevant item is silently dropped. Pin the *actual* selection against what the fixture's
    own explanatory text claims was selected/excluded, so the two cannot drift apart.

    - MUT A (smuggle 'Kinderrechte und Diversität', an official but sozialwissenschaftlich
      item the hinweis explicitly names as excluded, into the selection): caught here twice
      over -- the selection no longer equals the hinweis-declared selected set, and it now
      intersects the hinweis-declared excluded examples.
    - MUT C (drop 'Stoffe und Veränderungen', leaving a single item): caught here -- the
      selection no longer equals the hinweis-declared selected set.
    """
    real_items = {
        item["text"] for item in kompetenz.finde_anwendungsbereiche(KOMPETENZ_ID, nur_verbindlich=True)
    }
    source = _source()
    hinweis_block = source["shared"]["anwendungsbereiche_hinweis"]
    assert hinweis_block["type"] == "labeled"
    hinweis_selected, hinweis_excluded_examples = _parse_hinweis_selected_and_excluded(
        hinweis_block["text"]
    )

    # The items the hinweis text itself names must be real (verbatim, official) and the two
    # named sets must not overlap -- otherwise the hinweis contradicts itself before we even
    # compare it to the actual selection block.
    assert hinweis_selected <= real_items
    assert hinweis_excluded_examples <= real_items
    assert hinweis_selected.isdisjoint(hinweis_excluded_examples)

    selection_block = source["shared"]["anwendungsbereiche_auswahl"]
    assert selection_block["type"] == "list"
    actual_selected = set(selection_block["items"])

    # 1. The selection equals exactly what the hinweis declares selected -- catches both a
    #    smuggled-in item (MUT A) and a silently dropped one (MUT C).
    assert actual_selected == hinweis_selected, (
        f"shared.anwendungsbereiche_auswahl {actual_selected!r} disagrees with what "
        f"anwendungsbereiche_hinweis names as selected {hinweis_selected!r}"
    )

    # 2. No item the hinweis names as belonging to the excluded rest may appear in the
    #    actual selection -- catches a smuggled-in item (MUT A) directly, and stays
    #    meaningful even if the fixture's prose or item choice is re-authored later.
    assert actual_selected.isdisjoint(hinweis_excluded_examples), (
        f"selection contains {actual_selected & hinweis_excluded_examples!r}, which the "
        "hinweis itself names as belonging to a different Kompetenzbereich"
    )

    # 3. The selection is a proper, non-empty subset of the ten real stage items, every
    #    member verbatim-official -- never empty, never the full stage-wide list.
    assert actual_selected, "selection must be non-empty"
    assert actual_selected <= real_items
    assert actual_selected < real_items


def test_stage_shared_binding_is_measured_and_stated_explicitly() -> None:
    """Ground truth backing the reference doc and fixture caveat: the same 10 items are
    returned for a *different* PRIM.SU competence at the same Schulstufe, in a different
    Kompetenzbereich -- proving the list is stage-wide, not competence-bound."""
    su = kompetenz.finde_kompetenz("PRIM.SU")
    sch3_other_bereich = next(
        k for k in su
        if k["stufe"] == "SCH3" and k["bereich_slug"] != "NATURWISS"
    )
    own_items = {
        i["text"] for i in kompetenz.finde_anwendungsbereiche(KOMPETENZ_ID, nur_verbindlich=True)
    }
    other_items = {
        i["text"]
        for i in kompetenz.finde_anwendungsbereiche(sch3_other_bereich["id"], nur_verbindlich=True)
    }
    assert own_items == other_items, (
        "expected PRIM.SU's stage-shared Anwendungsbereiche to be identical across "
        "Kompetenzbereiche at the same Schulstufe (anwendungsbereiche_bindung: 'stufe')"
    )

    # The fixture's own explanatory text must say so, not just happen to select a subset.
    source = _source()
    full_text = _all_text(_blocks(source))
    assert "stufenweit" in full_text
    assert "andere" in full_text.lower() or "übrigen" in full_text.lower()


def test_vorklasse_stuetzen_are_real_predecessor_competences() -> None:
    diff = kompetenz.finde_differenzierung(KOMPETENZ_ID)
    predecessor_ids = {v["id"] for v in diff["vorklasse_stuetzen"]}
    assert predecessor_ids == {
        "AT.LP23.PRIM.SU.NATURWISS.SCH2.01",
        "AT.LP23.PRIM.SU.NATURWISS.SCH2.02",
    }

    source = _source()
    full_text = _all_text(_blocks(source))
    for pid in predecessor_ids:
        assert pid in full_text
