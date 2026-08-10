"""E7-05 acceptance: ``niveau_spalte`` tiers and origin separation in the **rendered output**.

The sibling tiering tests (E7-03/E7-04) assert what the *fixtures* say and that rendering exits
0. That is not this task's acceptance criterion, which is "present in docx output": a fixture can
carry a perfectly-formed ``niveau_spalte`` while the emitter drops it, and a renderer regression
that collapsed three tiers into one cell, or rendered teacher material with the official label,
would leave every existing test green.

So every assertion below is made against the bytes the renderer actually wrote --
``word/document.xml`` inside the emitted ``.docx`` package, and the emitted ``.html`` -- and the
expected labels/colours are read from ``lesson_common`` rather than retyped, so a deliberate
palette change updates the tests with the code while a *dropped* accent still fails.

Both worked examples are covered, because they exercise the two different axes: SEK1.M
(``standard_standardplus``, tiers unter/auf/über) and PRIM.SU (``lehrplan_generisch``, tiers
grundlegend/erweitert/vertiefend, whose labels are **not** in ``NIVEAU_KINDS`` and therefore take
``resolve_niveau_kind``'s custom-label path -- they must still render as their own text, not be
dropped).
"""
from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "plugin" / "skills" / "at-differenzierung"
RENDERER = SKILL_DIR / "scripts" / "render_documents.py"
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "differenzierung_flow"
MATHE_FIXTURE = FIXTURE_DIR / "sek1_mathematik_k2_bruchrechnen.differenzierung.json"
SU_FIXTURE = FIXTURE_DIR / "prim_sachunterricht_sch3_wetter.differenzierung.json"

sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "plugin" / "scripts"))
import kompetenz  # noqa: E402  pylint: disable=wrong-import-position
import lesson_common  # noqa: E402  pylint: disable=wrong-import-position

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}

# The `docs/` material embedded in the maths fixture's Unter-Stufe worksheet, and the
# ingestion tree it must be traceable to. Both are real: the file is the E6-05 docs
# fixture, and `finde_lernaufgaben` is the function a skill run would have called.
DOCS_ROOT = REPO_ROOT / "tests" / "fixtures" / "docs_ingestion"
DOCS_PFAD = "mathematik/K2/bruchrechnen.md"


# ---------------------------------------------------------------------------
# Rendering helpers -- one render per fixture, reused by every test in the module.
# ---------------------------------------------------------------------------


def _render(fixture: Path, outdir: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(RENDERER), str(fixture), "--format", "docx", "--outdir", str(outdir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.fixture(scope="module")
def mathe_render(tmp_path_factory: pytest.TempPathFactory) -> Path:
    pytest.importorskip("docx", reason="python-docx is optional; DOCX output test is skipped")
    outdir = tmp_path_factory.mktemp("mathe")
    _render(MATHE_FIXTURE, outdir)
    return outdir


@pytest.fixture(scope="module")
def su_render(tmp_path_factory: pytest.TempPathFactory) -> Path:
    pytest.importorskip("docx", reason="python-docx is optional; DOCX output test is skipped")
    outdir = tmp_path_factory.mktemp("su")
    _render(SU_FIXTURE, outdir)
    return outdir


def _document_xml(docx_path: Path) -> str:
    with zipfile.ZipFile(docx_path) as package:
        return package.read("word/document.xml").decode("utf-8")


def _cell_text(cell: ET.Element) -> str:
    return "".join(node.text or "" for node in cell.iter(f"{{{W}}}t"))


def _cell_border_colors(cell: ET.Element) -> dict[str, str]:
    """The `w:tcBorders` colours actually written for one table cell, edge -> hex."""
    borders = cell.find(f".//{{{W}}}tcBorders")
    if borders is None:
        return {}
    found = {}
    for edge in borders:
        color = edge.get(f"{{{W}}}color")
        if color and color.lower() != "auto":
            found[edge.tag.split("}")[1]] = color.upper()
    return found


def _tables(xml: str) -> list[ET.Element]:
    return list(ET.fromstring(xml).iter(f"{{{W}}}tbl"))


def _tier_table(xml: str, expected_cols: int) -> ET.Element:
    """The one table whose single row has `expected_cols` cells -- the niveau_spalte."""
    candidates = [
        table
        for table in _tables(xml)
        if len(table.findall("w:tr", NS)) == 1
        and len(table.findall("w:tr", NS)[0].findall("w:tc", NS)) == expected_cols
    ]
    assert len(candidates) == 1, (
        f"expected exactly one {expected_cols}-column single-row table (the niveau_spalte), "
        f"found {len(candidates)}"
    )
    return candidates[0]


def _expected_tiers(fixture: Path) -> list[tuple[str, str]]:
    """(display text, accent hex) per tier, resolved through the shipped renderer helper
    from the fixture's own labels -- never retyped here."""
    data = json.loads(fixture.read_text(encoding="utf-8"))

    def find(value: object) -> dict | None:
        if isinstance(value, dict):
            if value.get("type") == "niveau_spalte":
                return value
            for child in value.values():
                hit = find(child)
                if hit is not None:
                    return hit
        elif isinstance(value, list):
            for child in value:
                hit = find(child)
                if hit is not None:
                    return hit
        return None

    block = find(data)
    assert block is not None, f"{fixture.name} carries no niveau_spalte block"
    tiers = []
    for niveau in block["niveaus"]:
        display, _slug, accent = lesson_common.resolve_niveau_kind(niveau.get("label"))
        tiers.append((display, accent.lstrip("#").upper()))
    return tiers


# ---------------------------------------------------------------------------
# niveau_spalte -- the tiers survive into the docx as separate, marked columns.
# ---------------------------------------------------------------------------


def test_mathe_plan_renders_three_tier_columns_in_one_table(mathe_render: Path) -> None:
    xml = _document_xml(mathe_render / "differenzierungsplan.docx")
    expected = _expected_tiers(MATHE_FIXTURE)
    assert len(expected) == 3

    row = _tier_table(xml, 3).findall("w:tr", NS)[0]
    cells = row.findall("w:tc", NS)
    for cell, (display, _accent) in zip(cells, expected):
        assert display.upper() in _cell_text(cell), (
            f"tier {display!r} is not the heading of its own column"
        )


def test_mathe_tier_columns_carry_three_distinct_accent_borders(mathe_render: Path) -> None:
    """The colour is a second signal on top of the label text. Three tiers that all render
    the same accent (or none) would mean the emitter dropped the per-tier distinction."""
    xml = _document_xml(mathe_render / "differenzierungsplan.docx")
    expected = _expected_tiers(MATHE_FIXTURE)

    row = _tier_table(xml, 3).findall("w:tr", NS)[0]
    seen = []
    for cell, (display, accent) in zip(row.findall("w:tc", NS), expected):
        borders = _cell_border_colors(cell)
        assert borders.get("left") == accent, (
            f"tier {display!r} lost its accent border: wrote {borders!r}, expected left={accent}"
        )
        seen.append(borders["left"])
    assert len(set(seen)) == 3, f"tier accents are not distinct: {seen}"


def test_tier_order_in_the_docx_matches_the_axis_order(mathe_render: Path) -> None:
    """Reading order carries meaning here (below -> at -> above); a renderer that emitted the
    cells in dict or sorted order would still pass a mere membership check."""
    xml = _document_xml(mathe_render / "differenzierungsplan.docx")
    expected = [display.upper() for display, _ in _expected_tiers(MATHE_FIXTURE)]

    row = _tier_table(xml, 3).findall("w:tr", NS)[0]
    positions = []
    for cell in row.findall("w:tc", NS):
        text = _cell_text(cell)
        positions.append(next((d for d in expected if d in text), None))
    assert positions == expected, f"tier columns are out of order: {positions}"


def test_su_plan_renders_generic_axis_tiers_as_their_own_labels(su_render: Path) -> None:
    """PRIM.SU's labels (grundlegend/erweitert/vertiefend) are not in NIVEAU_KINDS, so they
    take resolve_niveau_kind's custom-label path. They must render as their own text with the
    neutral accent -- never be dropped, and never be relabelled into the Sek-I vocabulary."""
    xml = _document_xml(su_render / "differenzierungsplan.docx")
    expected = _expected_tiers(SU_FIXTURE)
    assert len(expected) == 3

    axis = kompetenz.finde_differenzierung("AT.LP23.PRIM.SU.NATURWISS.SCH3.01")["achse"]
    assert [display for display, _ in expected] == axis["niveaus"], (
        "the rendered tier labels must be the axis' own niveaus, read live from the data"
    )

    row = _tier_table(xml, 3).findall("w:tr", NS)[0]
    for cell, (display, accent) in zip(row.findall("w:tc", NS), expected):
        assert display.upper() in _cell_text(cell)
        assert _cell_border_colors(cell).get("left") == accent

    for foreign in ("UNTER DEM NIVEAU", "AUF DEM NIVEAU", "ÜBER DEM NIVEAU"):
        assert foreign not in xml, (
            f"the Sek-I tier vocabulary {foreign!r} leaked into the PRIM.SU document"
        )


# ---------------------------------------------------------------------------
# Origin separation -- official RIS content vs teacher-supplied `docs/` material.
# ---------------------------------------------------------------------------


def test_official_and_docs_material_render_with_different_labels_and_accents(
    mathe_render: Path,
) -> None:
    amtlich_label = lesson_common.HERKUNFT_LABEL[True]
    docs_label = lesson_common.HERKUNFT_LABEL[False]
    amtlich_accent = lesson_common.HERKUNFT_ACCENT[True].lstrip("#").upper()
    docs_accent = lesson_common.HERKUNFT_ACCENT[False].lstrip("#").upper()
    assert amtlich_label != docs_label and amtlich_accent != docs_accent

    ueber = _document_xml(mathe_render / "arbeitsblatt_ueber.docx")
    unter = _document_xml(mathe_render / "arbeitsblatt_unter.docx")

    # The official branch, in the worksheet that quotes an `allenfalls` item.
    assert amtlich_label in ueber
    # The teacher-supplied branch, in the worksheet that embeds `docs/` material.
    assert docs_label in unter
    assert amtlich_label not in unter, (
        "teacher material must never be presented under the official-source label"
    )

    def accent_of(xml: str, label: str) -> str:
        for table in _tables(xml):
            for row in table.findall("w:tr", NS):
                for cell in row.findall("w:tc", NS):
                    if label in _cell_text(cell):
                        return _cell_border_colors(cell).get("left", "")
        return ""

    assert accent_of(ueber, amtlich_label) == amtlich_accent
    assert accent_of(unter, docs_label) == docs_accent


def test_the_two_origins_stay_distinguishable_without_colour(mathe_render: Path) -> None:
    """B+W print is the delivery format for a worksheet. The icon and the label text must
    carry the distinction on their own, with no reliance on the accent hue."""
    ueber = _document_xml(mathe_render / "arbeitsblatt_ueber.docx")
    unter = _document_xml(mathe_render / "arbeitsblatt_unter.docx")

    assert lesson_common.HERKUNFT_ICON[True] in ueber
    assert lesson_common.HERKUNFT_ICON[False] in unter
    assert lesson_common.HERKUNFT_ICON[True] != lesson_common.HERKUNFT_ICON[False]
    assert lesson_common.HERKUNFT_LABEL[False] in unter


def test_official_block_cites_its_source_and_docs_block_never_does(mathe_render: Path) -> None:
    """`Quelle:` is the legal citation line, emitted only for `amtlich is True`; teacher
    material gets `Herkunft:` instead. Swapping those would dress `docs/` content as law."""
    ueber = _document_xml(mathe_render / "arbeitsblatt_ueber.docx")
    unter = _document_xml(mathe_render / "arbeitsblatt_unter.docx")

    source = json.loads(MATHE_FIXTURE.read_text(encoding="utf-8"))

    def herkunft_blocks(value: object) -> list[dict]:
        if isinstance(value, dict):
            found = [value] if value.get("type") == "herkunftsblock" else []
            for child in value.values():
                found.extend(herkunft_blocks(child))
            return found
        if isinstance(value, list):
            return [b for child in value for b in herkunft_blocks(child)]
        return []

    blocks = herkunft_blocks(source)
    amtliche = [b for b in blocks if b.get("amtlich") is True]
    docs = [b for b in blocks if b.get("amtlich") is not True]
    assert amtliche and docs, "the fixture must exercise both origin branches"

    for block in amtliche:
        citation = lesson_common.kompetenz_citation(block.get("quelle"))
        assert citation, "an official origin block must carry a citable quelle"
        assert f"Quelle: {citation}" in ueber

    docs_block = next(b for b in docs if b.get("quelle_hinweis", "").startswith("Bruchrechnen"))
    assert f"Herkunft: {docs_block['quelle_hinweis']}" in unter
    assert "Quelle:" not in _docs_cell(unter, lesson_common.HERKUNFT_LABEL[False]), (
        "the teacher-material block must not carry a legal citation line"
    )


def _docs_cell(xml: str, label: str) -> str:
    for table in _tables(xml):
        for row in table.findall("w:tr", NS):
            for cell in row.findall("w:tc", NS):
                text = _cell_text(cell)
                if label in text:
                    return text
    return ""


def test_embedded_docs_material_is_traceable_to_the_real_ingestion_result() -> None:
    """The embedded teacher material is not invented prose: `finde_lernaufgaben` over the
    shipped docs fixture tree returns exactly this file, and the block's `quelle_hinweis`
    follows the documented `<titel> (<pfad>)` form built from that result."""
    treffer = kompetenz.finde_lernaufgaben(fach="M", stufe="K2", docs_root=str(DOCS_ROOT))
    eintrag = next(t for t in treffer if t["pfad"] == DOCS_PFAD)
    assert eintrag["amtlich"] is False and eintrag["herkunft"] == "docs"

    source = json.loads(MATHE_FIXTURE.read_text(encoding="utf-8"))
    unter = next(d for d in source["documents"] if d["id"] == "arbeitsblatt_unter")
    block = next(
        b
        for section in unter["sections"]
        for b in section["blocks"]
        if b.get("type") == "herkunftsblock"
    )
    assert block["amtlich"] is False
    assert block["quelle_hinweis"] == f"{eintrag['titel']} ({eintrag['pfad']})"

    # The quoted body line is the docs file's own text, not a paraphrase of it.
    quoted = [b.get("text", "") for b in block["blocks"] if b.get("type") == "paragraph"]
    assert any(line and line in eintrag["text"] for line in quoted), (
        "the embedded paragraph is not present in the ingested docs text"
    )


def test_docs_material_does_not_reach_the_official_anchoring_path() -> None:
    """Teacher material carries no official IDs, so the anchoring checker must stay silent
    about it -- and must still be the thing that would catch an invented official item."""
    import pruefe_verankerung

    assert pruefe_verankerung.pruefe_lesson(MATHE_FIXTURE) == []

    broken = json.loads(MATHE_FIXTURE.read_text(encoding="utf-8"))
    unter = next(d for d in broken["documents"] if d["id"] == "arbeitsblatt_unter")
    section = next(s for s in unter["sections"] if any(
        b.get("type") == "herkunftsblock" for b in s["blocks"]))
    section["blocks"][0]["blocks"].append({
        "type": "list",
        "label": "Verbindliche Anwendungsbereiche",
        "items": ["Erfundenes verbindliches Item, das in keiner Verordnung steht;"],
    })
    verletzungen = pruefe_verankerung.pruefe_daten(broken)
    assert any(
        v.regel == pruefe_verankerung.REGEL_ERFUNDENES_VERBINDLICHES_ITEM for v in verletzungen
    ), "an invented binding item inside a docs block escaped the checker"
