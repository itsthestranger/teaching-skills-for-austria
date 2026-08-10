"""E10-09: the source-truth fidelity guard, and proof that it is not vacuous.

A verifier that reports "clean" is worthless until it has been shown to fail on the defects it
exists to catch. This project has shipped four independent silent-loss mechanisms, every one of
them with the suite green, so each is reproduced here as a mutation and the guard must reject it:

* V-58  -- a competence stem lost from the shipped text
* V-69  -- a ``<symbol>``-wrapped word dropped by the extractor
* V-80  -- ``<gdash/>`` eaten, shipping ``(Un)Gleichungen`` for ``(Un-)Gleichungen``
* V-80  -- a Bildungsstandards area description dropped entirely

The mutations are applied to in-memory copies of the shipped records, never to the files.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "data-pipeline" / "verify_source_fidelity.py"
FIXTURES = REPO_ROOT / "data-pipeline" / "tests" / "fixtures"

sys.path.insert(0, str(REPO_ROOT / "data-pipeline"))
sys.path.insert(0, str(REPO_ROOT / "plugin" / "scripts"))
import kompetenz  # noqa: E402  pylint: disable=wrong-import-position
import verify_source_fidelity as V  # noqa: E402  pylint: disable=wrong-import-position


@pytest.fixture(scope="module")
def sek1_m_blocks() -> list[str]:
    return V.source_blocks(FIXTURES / "sek1_mathematik.xml")


@pytest.fixture(scope="module")
def bist_blocks() -> list[str]:
    return V.source_blocks(FIXTURES / "bildungsstandards_anl1.xml")


# ---------------------------------------------------------------------------
# Independence -- the whole point of the task.
# ---------------------------------------------------------------------------


def test_shares_no_code_with_the_production_parsers() -> None:
    """"Must not reuse the production parser's element-walking helpers" is the task's own
    constraint: a check that shares `element_text` inherits its blind spots and proves nothing.
    Asserted structurally against the import list, not by reading the file."""
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    forbidden = {"parse_lehrplan", "parse_bildungsstandards", "build_dataset", "abbildungen",
                 "kompetenz", "validate_dataset"}
    assert not (imported & forbidden), f"the verifier imports pipeline code: {imported & forbidden}"


# ---------------------------------------------------------------------------
# Coverage -- the acceptance criterion is "all 247 competences and all 268 descriptors".
# ---------------------------------------------------------------------------


def test_covers_every_competence_the_public_api_enumerates() -> None:
    api_ids = {
        record["id"]
        for shard in V.SHARD_SOURCES
        for record in kompetenz.finde_kompetenz(fach=shard)
    }
    assert len(api_ids) == 247, f"expected the 247 shipped competences, got {len(api_ids)}"

    checked = {
        record.record_id
        for shard in V.SHARD_SOURCES
        for record in V.competence_records(shard)
    }
    assert not api_ids - checked, f"competences never checked: {sorted(api_ids - checked)[:5]}"


def test_checks_both_stammsatz_and_text_for_every_competence() -> None:
    """`stammsatz` is where V-58's silent loss happened, so checking only `text` would leave the
    original defect class uncovered."""
    api_ids = {
        record["id"]
        for shard in V.SHARD_SOURCES
        for record in kompetenz.finde_kompetenz(fach=shard)
    }
    fields: dict[str, set[str]] = {}
    for shard in V.SHARD_SOURCES:
        for record in V.competence_records(shard):
            fields.setdefault(record.record_id, set()).add(record.field_name)

    missing = [rid for rid in api_ids if {"stammsatz", "text"} - fields.get(rid, set())]
    assert not missing, f"competences not checked on both fields: {missing[:5]}"


def test_covers_every_shipped_descriptor() -> None:
    shipped = set()
    for path in (REPO_ROOT / "plugin" / "data" / "bildungsstandards").glob("*.json"):
        if path.name == "crosswalk.json":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        shipped.update(d["id"] for d in data["deskriptoren"])
    assert len(shipped) == 268, f"expected 268 descriptors, got {len(shipped)}"

    checked = {r.record_id for r in V.descriptor_records()}
    assert not shipped - checked, f"descriptors never checked: {sorted(shipped - checked)[:5]}"


def test_the_m8_composed_area_name_is_pinned_even_though_it_is_not_verbatim() -> None:
    """M8's `name` is the project's composition of two axes and occurs nowhere in the source as
    one string, so the verifier checks the axes instead. The composition rule itself still needs
    a guard, or a change to it would go unnoticed."""
    data = json.loads((REPO_ROOT / "plugin" / "data" / "bildungsstandards" / "m8.json")
                      .read_text(encoding="utf-8"))
    bereiche = data["kompetenzbereiche"]
    assert len(bereiche) == 16, "M8 is 4 Handlungs- x 4 Inhaltsbereiche (V-80)"
    for bereich in bereiche:
        assert bereich["name"] == f"{bereich['handlungsbereich']} – {bereich['inhaltsbereich']}"


# ---------------------------------------------------------------------------
# The guard is clean on the shipped data.
# ---------------------------------------------------------------------------


def test_shipped_data_has_no_divergence_from_the_source() -> None:
    divergences, checked, unavailable, modes = V.run("fixtures")
    assert not unavailable, f"a committed fixture is missing: {unavailable}"
    assert sum(checked.values()) > 1200, "suspiciously few strings checked"
    assert divergences == [], [d.to_dict() for d in divergences[:3]]


def test_cli_exits_zero_and_reports_the_count() -> None:
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=REPO_ROOT,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "No divergence" in result.stdout


# ---------------------------------------------------------------------------
# Non-vacuity -- each historical silent-loss mechanism, reproduced.
# ---------------------------------------------------------------------------


def _one_competence(shard: str, field_name: str = "text") -> V.Record:
    return next(r for r in V.competence_records(shard) if r.field_name == field_name)


def test_a_dropped_word_is_rejected(sek1_m_blocks: list[str]) -> None:
    record = _one_competence("SEK1.M")
    words = record.text.split()
    assert len(words) > 4
    mutated = V.Record(record.record_id, record.shard, record.field_name,
                       " ".join(words[:2] + words[3:]))

    assert V.verify([record], sek1_m_blocks) == [], "the unmutated record should be clean"
    assert V.verify([mutated], sek1_m_blocks), "a dropped word was not caught"


def test_v58_a_lost_stem_is_rejected(sek1_m_blocks: list[str]) -> None:
    record = _one_competence("SEK1.M", "stammsatz")
    truncated = record.text.split(" ", 1)[1] if " " in record.text else record.text
    mutated = V.Record(record.record_id, record.shard, "stammsatz",
                       truncated + " und zusätzlich etwas, das nirgends steht")
    assert V.verify([mutated], sek1_m_blocks), "a corrupted stem was not caught"


def test_v69_a_dropped_symbol_word_is_rejected(sek1_m_blocks: list[str]) -> None:
    """`<symbol stellen="3">Die</symbol>Schülerinnen` -- dropping the symbol's word yields a
    stem that still reads plausibly, which is exactly why it shipped."""
    record = _one_competence("SEK1.M", "stammsatz")
    assert record.text.startswith("Die "), record.text
    mutated = V.Record(record.record_id, record.shard, "stammsatz", record.text[4:])
    assert V.verify([mutated], sek1_m_blocks), "a dropped <symbol> word was not caught"


def test_v80_an_eaten_gdash_is_rejected(bist_blocks: list[str]) -> None:
    """The `<gdash/>` case verbatim: `(Un-)Gleichungen` shipped as `(Un)Gleichungen`."""
    hits = [r for r in V.descriptor_records() if "(Un-)Gleichungen" in r.text]
    assert hits, "the (Un-)Gleichungen descriptor is no longer in the shipped data"

    for record in hits:
        assert V.verify([record], bist_blocks) == [], "the real descriptor must be clean"
        mutated = V.Record(record.record_id, record.shard, record.field_name,
                           record.text.replace("(Un-)Gleichungen", "(Un)Gleichungen"))
        assert V.verify([mutated], bist_blocks), "an eaten <gdash/> hyphen was not caught"


def test_v80_a_dropped_area_description_is_rejected(bist_blocks: list[str]) -> None:
    """The fourth mechanism: D8's area descriptions, silently dropped by an early draft. They
    are only caught if they are in scope at all."""
    descriptions = [r for r in V.descriptor_records() if r.field_name == "bereich.beschreibung"]
    assert descriptions, "area descriptions are not in the verifier's scope"

    record = descriptions[0]
    mutated = V.Record(record.record_id, record.shard, record.field_name,
                       record.text + " Zusatz, der in keiner Verordnung steht.")
    assert V.verify([mutated], bist_blocks), "a corrupted area description was not caught"


def test_a_footnote_marker_left_in_the_text_is_rejected(sek1_m_blocks: list[str]) -> None:
    """`<super>` markers are removed from the quotable text. A record that kept one would be
    quoting something the regulation does not say at that position."""
    record = _one_competence("SEK1.M")
    mutated = V.Record(record.record_id, record.shard, record.field_name, record.text + "12")
    assert V.verify([mutated], sek1_m_blocks), "a stray footnote marker was not caught"


# ---------------------------------------------------------------------------
# The normalisation must not be wide enough to absorb a real edit.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "left,right,should_be_equal",
    [
        ("a  b", "a b", True),
        ("Ge­setz", "Gesetz", True),
        ("a b", "a b", True),
        ("A–B", "A-B", False),
        ("„Wort“", '"Wort"', False),
        ("(Un-)Gleichungen", "(Un)Gleichungen", False),
        ("1/2", "1/3", False),
        ("a b c", "a c", False),
    ],
)
def test_normalisation_absorbs_only_invisible_differences(left: str, right: str,
                                                          should_be_equal: bool) -> None:
    assert (V.normalise(left) == V.normalise(right)) is should_be_equal


def test_the_flattener_applies_its_documented_element_rules() -> None:
    """Every rule below is a defect this project actually shipped. If the namespace handling
    regresses, none of them fire and the flattener degenerates to "concatenate all text" --
    which still finds most strings, so only a targeted check notices."""
    xml = (
        '<risdok xmlns="http://ris.bka.gv.at/schema/1.0">'
        '<listelem><symbol stellen="1">–</symbol>Der Bulletpunkt.</listelem>'
        '<listelem><symbol stellen="3">Die</symbol>Schülerinnen können.</listelem>'
        '<listelem>Mit Marker<super>4, 7</super> weiter.</listelem>'
        '<listelem>(Un<gdash/>)Gleichungen</listelem>'
        '<listelem>Formel <img src="/x/hauptdokument.img9is.png"/> Ende.</listelem>'
        "</risdok>"
    )
    path = Path(pytest.importorskip("tempfile").mkdtemp()) / "probe.xml"
    path.write_text(xml, encoding="utf-8")
    flat = V.haystack(path)

    assert "– Der Bulletpunkt" not in flat and "Der Bulletpunkt." in flat  # bullet dropped
    assert "Die Schülerinnen können." in flat                             # V-69 boundary
    assert "Mit Marker weiter." in flat and "4, 7" not in flat            # <super> removed
    assert "(Un-)Gleichungen" in flat                                     # V-80 gdash
    assert "⟦ABB:hauptdokument.img9is.png⟧" in flat                       # image token


# ---------------------------------------------------------------------------
# Match strength -- which mode each record class is held to, and what the weaker
# mode does not catch. Both are asserted, so neither can drift unnoticed.
# ---------------------------------------------------------------------------


def test_every_curriculum_record_is_held_to_whole_block_equality(sek1_m_blocks: list[str]) -> None:
    """Containment alone cannot catch a truncation: drop a leading word and the remainder is
    still a substring. Curriculum records all *equal* a source block, so they are checked that
    way -- and this test fails if any of them silently drops to the weaker mode."""
    modes = V.match_modes(V.competence_records("SEK1.M"), sek1_m_blocks)
    assert modes["bounded"] == 0 and modes["failed"] == 0, modes
    assert modes["exact"] == len(V.competence_records("SEK1.M"))


def test_a_trailing_truncation_of_a_competence_is_rejected(sek1_m_blocks: list[str]) -> None:
    record = _one_competence("SEK1.M")
    words = record.text.split()
    mutated = V.Record(record.record_id, record.shard, record.field_name, " ".join(words[:-1]))
    divergences = V.verify([mutated], sek1_m_blocks, require_exact=True)
    assert divergences, "a trailing truncation was not caught"
    assert divergences[0].reason == "not-a-whole-source-block"


def test_a_leading_truncation_of_a_descriptor_is_rejected(bist_blocks: list[str]) -> None:
    """The Bildungsstandards path allows a record to sit inside a block, so it needs its own
    defence against leading truncation: only a label or the record's own stem may precede it."""
    record = next(r for r in V.descriptor_records()
                  if r.field_name == "text" and len(r.text.split()) > 4)
    assert V.verify([record], bist_blocks) == []

    words = record.text.split()
    mutated = V.Record(record.record_id, record.shard, record.field_name, " ".join(words[1:]),
                       stem=record.stem)
    assert V.verify([mutated], bist_blocks), "a leading truncation of a descriptor was not caught"


def test_the_bounded_mode_does_not_catch_a_trailing_truncation() -> None:
    """A known and deliberate limit, pinned so it is not mistaken for coverage: inside a shared
    block, a shipped title legitimately precedes other text, so a dropped *trailing* word cannot
    be distinguished from that. Curriculum data does not use this path; Bildungsstandards does.
    Widening it needs per-record source offsets, which the parser does not record.
    """
    block = "Kompetenzen: Die Schülerinnen und Schüler können etwas tun."
    assert V._is_bounded("Die Schülerinnen und Schüler können etwas tun.", block)
    # trailing truncation -- not caught, by design
    assert V._is_bounded("Die Schülerinnen und Schüler können etwas", block)
    # leading truncation -- caught
    assert not V._is_bounded("Schülerinnen und Schüler können etwas tun.", block)
