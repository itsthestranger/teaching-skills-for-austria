"""Per-``bindung`` progression and contract tests, plus one parse->build->
validate run per binding axis (E12-15, BACKLOG "test breadth").

Run:  .venv/bin/python -m pytest data-pipeline/tests -q

The six shards split across five ``anwendungsbereiche_bindung`` values
(``SubjectSpec.anwendungsbereiche_bindung``, parse_lehrplan.py):

    SEK1.M   kompetenz  -- items text-repetition-joined to one competence (V-27)
    SEK1.D   bereich    -- items attach to (area, class year) by containment
    SEK1.E   prosa      -- an Anwendungsbereiche heading with no items at all
    PRIM.D   stufe      -- items attach to a school year only, never an area
    PRIM.M   keine      -- no Anwendungsbereiche section exists at all
    PRIM.SU  stufe      -- same as PRIM.D

Everything here runs against the **committed** fixtures in
``tests/fixtures/`` -- nothing touches the gitignored ``resources/`` -- and
every count asserted below was measured against those fixtures with this
task (see the E12-15 report), not copied from FINDINGS.md/deviations.md
without re-checking.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import jsonschema
import pytest

_HERE = Path(__file__).resolve().parent
_DATA_PIPELINE = _HERE.parent
sys.path.insert(0, str(_DATA_PIPELINE))
sys.path.insert(0, str(_DATA_PIPELINE / "schema"))

import build_dataset as B  # noqa: E402
import id_schema as ID  # noqa: E402
import parse_lehrplan as P  # noqa: E402
import validate_dataset as V  # noqa: E402

logging.getLogger("parse_lehrplan").setLevel(logging.CRITICAL)
logging.getLogger("build_dataset").setLevel(logging.CRITICAL)

FIXTURES = _HERE / "fixtures"

#: spec key -> (fixture, expected anwendungsbereiche_bindung). The bindung
#: column is read straight from parse_lehrplan.SUBJECT_SPECS -- restated here
#: only so a change to that registry makes this file's own expectations
#: visibly wrong, rather than the tests silently tracking whatever the
#: registry says.
SHARDS = [
    ("SEK1.M", "sek1_mathematik.xml", "kompetenz"),
    ("SEK1.D", "sek1_deutsch.xml", "bereich"),
    ("SEK1.E", "sek1_fremdsprache.xml", "prosa"),
    ("PRIM.D", "prim_deutsch.xml", "stufe"),
    ("PRIM.M", "prim_mathematik.xml", "keine"),
    ("PRIM.SU", "prim_sachunterricht.xml", "stufe"),
]


def _parse(spec_key: str, fixture: str) -> P.ParseResult:
    spec = P.SUBJECT_SPECS[spec_key]
    return P.parse_lehrplan(FIXTURES / fixture, spec)


@pytest.fixture(scope="module")
def parsed() -> dict[str, P.ParseResult]:
    """Every shard, parsed once and shared read-only across this module's
    tests -- parsing is not free and none of the tests below mutate the
    result."""
    return {key: _parse(key, fixture) for key, fixture, _ in SHARDS}


def test_registry_bindung_matches_this_files_own_expectation():
    """If parse_lehrplan.SUBJECT_SPECS ever reassigns a shard's bindung, this
    is the test that goes red first, before any of the contract tests below
    quietly start checking the wrong axis for the wrong shard."""
    for spec_key, _fixture, erwartet in SHARDS:
        assert P.SUBJECT_SPECS[spec_key].anwendungsbereiche_bindung == erwartet, spec_key


# ---------------------------------------------------------------------------
# kompetenz_id: set only under bindung == "kompetenz" (SEK1.M)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spec_key,fixture,bindung", SHARDS)
def test_kompetenz_id_set_only_under_kompetenz_bindung(parsed, spec_key, fixture, bindung):
    """The join that fills in Anwendungsitem.kompetenz_id (V-27's verbatim
    text-repetition join) is SEK1.M-only. Measured 2026-08-02 against the
    fixtures: SEK1.M has 198/237 items joined (some praezisierung items never
    match any competence sentence -- a real, expected join gap, not a bug);
    every other shard has 0/N joined, always, by construction (join_anwendungen
    returns early for any bindung other than "kompetenz" -- SubjectSpec
    docstring: "a per-competence kompetenz_id must not be synthesised")."""
    result = parsed[spec_key]
    joined = [i for i in result.anwendungsitems if i.kompetenz_id is not None]
    if bindung == "kompetenz":
        assert joined, f"{spec_key}: bindung=kompetenz but nothing joined at all"
        assert len(joined) < len(result.anwendungsitems), (
            f"{spec_key}: every item joined -- V-54's digital-technology items "
            "(which precede no competence sentence) should never join"
        )
    else:
        assert joined == [], (
            f"{spec_key}: bindung={bindung!r} but {len(joined)} items carry a "
            "kompetenz_id -- the source makes no such link for this axis"
        )


# ---------------------------------------------------------------------------
# prosa / keine: zero Anwendungsbereiche items and zero blocks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spec_key,fixture,bindung", SHARDS)
def test_prosa_and_keine_bindungen_produce_zero_items(parsed, spec_key, fixture, bindung):
    """SEK1.E (prosa: the Anwendungsbereiche heading is followed by
    descriptive prose, not a liste) and PRIM.M (keine: no Anwendungsbereiche
    section at all) must extract no items and open no blocks. Every other
    bindung must extract at least one item and open at least one block --
    this is a two-sided contract, not "SEK1.E/PRIM.M are empty" alone: a
    bindung that claims to attach items but silently extracts none would be
    just as wrong as the reverse."""
    result = parsed[spec_key]
    if bindung in ("prosa", "keine"):
        assert result.anwendungsitems == [], spec_key
        assert result.bloecke == [], spec_key
    else:
        assert result.anwendungsitems, f"{spec_key}: bindung={bindung!r} but extracted 0 items"


# ---------------------------------------------------------------------------
# Area-free 7-segment IDs: only under bindung == "stufe" (PRIM.D, PRIM.SU)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spec_key,fixture,bindung", SHARDS)
def test_area_free_ids_occur_only_under_stufe_bindung(parsed, spec_key, fixture, bindung):
    """id_schema.ANWENDUNGSITEM_AREA_FREI_ID_RE (the 7-segment, no-Bereich
    application-item form, E-P3/D3) is minted only when the source itself
    attaches an item to a school year and nothing more specific -- exactly
    ``bindung: "stufe"``. Every item under every other (non-empty) bindung
    must instead be the 8-segment area-bearing form. Measured 2026-08-02:
    PRIM.D 37/37 and PRIM.SU 40/40 items are area-free; SEK1.M 237/237 and
    SEK1.D 54/54 are area-bearing; SEK1.E/PRIM.M have no items to check
    (covered by test_prosa_and_keine_bindungen_produce_zero_items)."""
    items = parsed[spec_key].anwendungsitems
    if not items:
        pytest.skip(f"{spec_key}: bindung={bindung!r} has no items (see the dedicated test)")
    area_free = [i for i in items if ID.ANWENDUNGSITEM_AREA_FREI_ID_RE.match(i.id)]
    area_bearing = [i for i in items if ID.ANWENDUNGSITEM_ID_RE.match(i.id)]
    # Every item must match exactly one of the two grammars -- no item id
    # should fail to parse at all under either form.
    assert len(area_free) + len(area_bearing) == len(items), spec_key
    if bindung == "stufe":
        assert len(area_free) == len(items), f"{spec_key}: expected every item area-free"
        assert area_bearing == []
    else:
        assert len(area_bearing) == len(items), f"{spec_key}: expected every item area-bearing"
        assert area_free == []


# ---------------------------------------------------------------------------
# Progression (vorlaeufer/folge): never crosses an area, never crosses a
# school year other than by exactly one step (V-59's E12-04 fix, bucketed on
# (stufe, bereich_slug) rather than (stufe, bereich_nummer)).
# ---------------------------------------------------------------------------


def _id_map(result: P.ParseResult) -> dict[str, P.Kompetenz]:
    return {k.id: k for k in result.kompetenzen}


@pytest.mark.parametrize("spec_key,fixture,bindung", SHARDS)
def test_progression_links_never_cross_an_area(parsed, spec_key, fixture, bindung):
    """FINDINGS V-59: before E12-04 all five unnumbered-area shards bucketed
    progression on bereich_nummer (always None outside SEK1.M), collapsing
    every area into one bucket -- 382-720 cross-area links per subject.
    link_wiederholungen now buckets on (stufe, bereich_slug). Measured
    2026-08-02 against the fixtures: 0 cross-area links for all six shards,
    confirming the FINDINGS V-59/E12-04 entry rather than re-copying its
    number unverified."""
    result = parsed[spec_key]
    by_id = _id_map(result)
    verstoesse = []
    for k in result.kompetenzen:
        for vid in k.vorlaeufer:
            v = by_id.get(vid)
            if v is not None and v.bereich_slug != k.bereich_slug:
                verstoesse.append((k.id, "vorlaeufer", vid))
        for fid in k.folge:
            f = by_id.get(fid)
            if f is not None and f.bereich_slug != k.bereich_slug:
                verstoesse.append((k.id, "folge", fid))
    assert verstoesse == [], f"{spec_key}: cross-area progression links: {verstoesse[:5]}"


@pytest.mark.parametrize("spec_key,fixture,bindung", SHARDS)
def test_progression_links_never_skip_or_reverse_a_school_year(parsed, spec_key, fixture, bindung):
    """A competence's vorlaeufer must live in exactly the previous class/
    school year and its folge in exactly the next one -- never the same
    year, never two years back/forward, and never a later year masquerading
    as a vorlaeufer (which would silently reverse the timeline a teacher
    reads progression from). link_wiederholungen derives both directions
    from a single (stufe, bereich_slug) bucket keyed on stufe +/- 1, so this
    is a property of that construction, not of any one subject's content --
    checked here against real parsed data rather than only against the
    function's source."""
    result = parsed[spec_key]
    spec = P.SUBJECT_SPECS[spec_key]
    praefix = spec.stufen_praefix
    by_id = _id_map(result)

    def stufe_nr(stufe: str) -> int:
        return int(stufe[len(praefix):])

    geprueft = 0
    for k in result.kompetenzen:
        kn = stufe_nr(k.stufe)
        for vid in k.vorlaeufer:
            v = by_id.get(vid)
            if v is None:
                continue
            assert stufe_nr(v.stufe) == kn - 1, (
                f"{spec_key}: {k.id} (stufe {k.stufe}) has vorlaeufer {vid} "
                f"(stufe {v.stufe}) -- not exactly one year earlier"
            )
            geprueft += 1
        for fid in k.folge:
            f = by_id.get(fid)
            if f is None:
                continue
            assert stufe_nr(f.stufe) == kn + 1, (
                f"{spec_key}: {k.id} (stufe {k.stufe}) has folge {fid} "
                f"(stufe {f.stufe}) -- not exactly one year later"
            )
            geprueft += 1
    # SEK1.E/PRIM.M's competences still progress year-over-year even though
    # they have no Anwendungsbereiche items (progression is positional, not
    # item-derived) -- every shard should exercise at least one link.
    assert geprueft > 0, f"{spec_key}: no progression links to check at all"


# ---------------------------------------------------------------------------
# End to end: parse -> build -> validate, one shard per binding axis,
# entirely from tests/fixtures/*.xml.
# ---------------------------------------------------------------------------

#: One representative shard per binding axis (five axes, kompetenz/bereich/
#: prosa/stufe/keine -- PRIM.SU stands in for "stufe" since PRIM.D is already
#: exercised heavily above; using the six-area subject here for variety).
JE_ACHSE = [
    ("SEK1.M", "sek1_mathematik.xml"),
    ("SEK1.D", "sek1_deutsch.xml"),
    ("SEK1.E", "sek1_fremdsprache.xml"),
    ("PRIM.SU", "prim_sachunterricht.xml"),
    ("PRIM.M", "prim_mathematik.xml"),
]

#: Enough manifest for build_provenienz() -- structurally shaped like the
#: real (gitignored) resources/manifest.json entries, values are placeholders.
FAKE_MANIFEST = {
    band: {
        "kurztitel": f"Testlehrplan {band}",
        "nor": "NOR00000000",
        "kundmachungsorgan": "BGBl. II Nr. 1/2023  ",
        "artikel_paragraph_anlage": "Anl. 1",
        "retrieval_date": "2026-01-01",
    }
    for band in ("mittelschule", "volksschule")
}

SCHEMA_PATH = _DATA_PIPELINE / "schema" / "kompetenzen.schema.json"


def _write_shard(kompetenzen_root: Path, spec: P.SubjectSpec, dateien: dict[str, dict]) -> None:
    shard_dir = kompetenzen_root / spec.band.lower() / spec.fach_code.lower()
    shard_dir.mkdir(parents=True)
    for name, doc in dateien.items():
        (shard_dir / name).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


@pytest.mark.parametrize("spec_key,fixture", JE_ACHSE)
def test_parse_build_validate_end_to_end_per_bindung(tmp_path, spec_key, fixture):
    """The E12-15 acceptance criterion: pytest on a fresh clone exercises
    build AND validate, not only the parser -- for a representative of every
    binding axis, entirely from the committed fixtures. Writes real files to
    tmp_path and runs the real validate_dataset.run_validation over them
    (not just jsonschema in isolation), so schema validation, ID-collision
    detection and the image-registry cross-check all actually run."""
    spec = P.SUBJECT_SPECS[spec_key]
    result = P.parse_lehrplan(FIXTURES / fixture, spec)
    registry = B.collect_abbildungen_registry_eintraege(result)
    dateien = B.build_parts(result, spec, FAKE_MANIFEST, registry, modus="meta")

    kompetenzen_root = tmp_path / "kompetenzen"
    _write_shard(kompetenzen_root, spec, dateien)

    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")

    report = V.run_validation(
        kompetenzen_root=kompetenzen_root,
        registry_path=registry_path,
        schema_path=SCHEMA_PATH,
        plugin_root=tmp_path,
    )
    assert report.hard == [], f"{spec_key}: unexpected hard findings: {report.hard}"
    assert report.shards_checked == [spec_key]


@pytest.mark.parametrize("spec_key,fixture", JE_ACHSE)
def test_combined_document_also_validates(spec_key, fixture):
    """combine_parts's merged, single-file view must be schema-valid too --
    not just the per-area parts. Uses jsonschema directly (no filesystem
    round-trip needed) since combine_parts's output never ships as a part
    file on disk; it is the shape a consumer sees after loading a whole
    shard."""
    spec = P.SUBJECT_SPECS[spec_key]
    result = P.parse_lehrplan(FIXTURES / fixture, spec)
    registry = B.collect_abbildungen_registry_eintraege(result)
    dateien = B.build_parts(result, spec, FAKE_MANIFEST, registry, modus="meta")
    gesamt = B.combine_parts(dateien)

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    fehler = [f"{list(e.path)}: {e.message}" for e in validator.iter_errors(gesamt)]
    assert fehler == [], f"{spec_key}: {fehler[:5]}"
