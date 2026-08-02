"""Build breadth across all six shards (E12-09, E12-10).

Run:  .venv/bin/python -m pytest data-pipeline/tests -q

Unlike ``test_build_dataset.py`` -- which builds the real Sek I Mathematik
shard from ``resources/`` and is skipped entirely when that gitignored
directory is absent -- these tests run against the **committed** fixtures in
``tests/fixtures/``, so build breadth stays covered in a fresh clone and in CI.

Two bugs are pinned down here, both invisible while SEK1.M was the only
registered spec:

* **V-59 (E12-09)** -- routing keys on the area **slug**, not on
  ``bereich_nummer``. Only SEK1.M numbers its Kompetenzbereiche, so
  ``build_parts`` raised ``KeyError: None`` for the other five, and
  ``zusatzkompetenzen`` -- defined as "has no area number" -- would have
  swallowed every competence of those shards had the crash not fired first.
* **V-64 (E12-10)** -- ``art`` alone decides ``digitale_technologien``. The old
  partition also treated ``kompetenz_id is None`` as digital, which is true of
  every item under the coarse binding axes, so all 54 SEK1.D + 37 PRIM.D + 40
  PRIM.SU items would have shipped as digital-technology suggestions. Those
  items now live in ``meta.anwendungsbereiche_bloecke`` and are never pushed
  onto a competence record.
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
import parse_lehrplan as P  # noqa: E402

logging.getLogger("parse_lehrplan").setLevel(logging.CRITICAL)
logging.getLogger("build_dataset").setLevel(logging.CRITICAL)

FIXTURES = _HERE / "fixtures"

#: spec key -> (fixture, expected competences, expected areas, expected
#: zusatzkompetenzen). Counts are the frozen ERWARTET_* values (V-70); the
#: zusatz column is the E12-09 acceptance criterion: 2 for SEK1.M (the
#: GZ-integrative pair, FINDINGS V-57) and 0 everywhere else.
SHARDS = [
    ("SEK1.M", "sek1_mathematik.xml", 42, 4, 2),
    ("SEK1.D", "sek1_deutsch.xml", 40, 4, 0),
    ("SEK1.E", "sek1_fremdsprache.xml", 37, 4, 0),
    ("PRIM.D", "prim_deutsch.xml", 40, 4, 0),
    ("PRIM.M", "prim_mathematik.xml", 40, 4, 0),
    ("PRIM.SU", "prim_sachunterricht.xml", 48, 6, 0),
]

#: Enough manifest for build_provenienz(); the real file is gitignored. Values
#: are structurally shaped like the live entries, not copied from them -- these
#: tests assert routing, never provenance content.
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


def _baue(spec_key: str, fixture: str) -> dict[str, dict]:
    spec = P.SUBJECT_SPECS[spec_key]
    result = P.parse_lehrplan(FIXTURES / fixture, spec)
    registry = B.collect_abbildungen_registry_eintraege(result)
    return B.build_parts(result, spec, FAKE_MANIFEST, registry, modus="meta")


@pytest.mark.parametrize("spec_key,fixture,n_komp,n_bereiche,n_zusatz", SHARDS)
def test_builds_without_keyerror(spec_key, fixture, n_komp, n_bereiche, n_zusatz):
    """The headline E12-09 criterion: all six build at all."""
    dateien = _baue(spec_key, fixture)
    # one part per Kompetenzbereich, plus zusatz.json
    assert len(dateien) == n_bereiche + 1
    assert "zusatz.json" in dateien


@pytest.mark.parametrize("spec_key,fixture,n_komp,n_bereiche,n_zusatz", SHARDS)
def test_zusatzkompetenzen_means_no_official_area(spec_key, fixture, n_komp, n_bereiche, n_zusatz):
    """2 for SEK1.M, 0 for the other five -- on identity, not on a null number."""
    dateien = _baue(spec_key, fixture)
    assert len(dateien["zusatz.json"]["zusatzkompetenzen"]) == n_zusatz


@pytest.mark.parametrize("spec_key,fixture,n_komp,n_bereiche,n_zusatz", SHARDS)
def test_no_competence_is_lost_or_duplicated(spec_key, fixture, n_komp, n_bereiche, n_zusatz):
    """Routing must partition the competences, not drop or copy any."""
    dateien = _baue(spec_key, fixture)
    ids: list[str] = []
    for doc in dateien.values():
        for bereich in doc.get("kompetenzbereiche", []):
            ids += [k["id"] for k in bereich["kompetenzen"]]
        ids += [k["id"] for k in doc.get("zusatzkompetenzen", [])]
    assert len(ids) == n_komp
    assert len(set(ids)) == n_komp


@pytest.mark.parametrize("spec_key,fixture,n_komp,n_bereiche,n_zusatz", SHARDS)
def test_area_records_omit_bereich_nummer(spec_key, fixture, n_komp, n_bereiche, n_zusatz):
    """A competence under a real area never carries area attribution.

    This is the regression that the old ``ist_zusatz = bereich_nummer is None``
    test would have caused for the five unnumbered shards: every record would
    have been written as a zusatzkompetenz, carrying a null ``bereich_nummer``.

    The ``anwendungsbereiche`` key follows the binding axis (E12-10): under
    ``bindung: kompetenz`` every area record carries it, possibly empty, because
    the source really does attach items per competence. Under the coarse axes
    the key is absent -- those items live in ``meta.anwendungsbereiche_bloecke``,
    and an empty per-competence array would imply an attribution the regulation
    never makes.
    """
    dateien = _baue(spec_key, fixture)
    spec = P.SUBJECT_SPECS[spec_key]
    erwartet_key = spec.anwendungsbereiche_bindung == "kompetenz"
    for dateiname, doc in dateien.items():
        if dateiname == "zusatz.json":
            continue
        for bereich in doc["kompetenzbereiche"]:
            for k in bereich["kompetenzen"]:
                assert "bereich_nummer" not in k, (dateiname, k["id"])
                assert "bereich_name" not in k, (dateiname, k["id"])
                assert ("anwendungsbereiche" in k) == erwartet_key, (dateiname, k["id"])


@pytest.mark.parametrize("spec_key,fixture,n_komp,n_bereiche,n_zusatz", SHARDS)
def test_part_filenames_follow_the_area_slugs(spec_key, fixture, n_komp, n_bereiche, n_zusatz):
    dateien = _baue(spec_key, fixture)
    spec = P.SUBJECT_SPECS[spec_key]
    for dateiname, doc in dateien.items():
        if dateiname == "zusatz.json":
            continue
        slug = doc["kompetenzbereiche"][0]["slug"]
        assert dateiname == f"{slug.lower()}.json"
        # Every shipped area code is a frozen one (decision D2).
        assert slug in spec.bereich_slugs.values()


@pytest.mark.parametrize("spec_key,fixture,n_komp,n_bereiche,n_zusatz", SHARDS)
def test_combine_parts_round_trips(spec_key, fixture, n_komp, n_bereiche, n_zusatz):
    """combine_parts sorts areas; with every nummer None that must not raise.

    ``(True, None) < (True, None)`` compares None to None and raises
    TypeError, which is what the old two-element sort key did for all five
    unnumbered shards.
    """
    dateien = _baue(spec_key, fixture)
    gesamt = B.combine_parts(dateien)
    assert len(gesamt["kompetenzbereiche"]) == n_bereiche
    n = sum(len(b["kompetenzen"]) for b in gesamt["kompetenzbereiche"])
    assert n + len(gesamt["zusatzkompetenzen"]) == n_komp
    # Serialisable, and the index agrees with the parts it describes.
    index = B.build_index(P.SUBJECT_SPECS[spec_key], dateien)
    json.dumps(index, ensure_ascii=False)
    assert len(index["teile"]) == len(dateien)


@pytest.mark.parametrize("spec_key,fixture,n_komp,n_bereiche,n_zusatz", SHARDS)
def test_report_counts_agree_with_what_was_built(spec_key, fixture, n_komp, n_bereiche, n_zusatz):
    """zaehle() and build_parts() must share one identity test, not two."""
    spec = P.SUBJECT_SPECS[spec_key]
    result = P.parse_lehrplan(FIXTURES / fixture, spec)
    zahlen = B.zaehle(result)
    dateien = _baue(spec_key, fixture)
    assert zahlen["zusatzkompetenzen"] == len(dateien["zusatz.json"]["zusatzkompetenzen"])
    assert zahlen["zusatzkompetenzen"] == n_zusatz
    assert zahlen["kompetenzen_gesamt"] == n_komp
    assert zahlen["kompetenzbereiche"] == n_bereiche


# ---------------------------------------------------------------------------
# E12-10: meta.anwendungsbereiche_bloecke and the item partition (V-64)
# ---------------------------------------------------------------------------

SCHEMA_PATH = _DATA_PIPELINE / "schema" / "kompetenzen.schema.json"

#: spec key -> (fixture, total application items, expected block entries).
#: Blocks exist only under the two coarse binding axes; SEK1.M nests its items
#: under competences and SEK1.E/PRIM.M have no items at all.
ITEMS = [
    ("SEK1.M", "sek1_mathematik.xml", 237, 0),
    ("SEK1.D", "sek1_deutsch.xml", 54, 16),
    ("SEK1.E", "sek1_fremdsprache.xml", 0, 0),
    ("PRIM.D", "prim_deutsch.xml", 37, 4),
    ("PRIM.M", "prim_mathematik.xml", 0, 0),
    ("PRIM.SU", "prim_sachunterricht.xml", 40, 4),
]


def _alle_item_ids(gesamt: dict) -> list[str]:
    """Every application item id reachable in a recombined document."""
    ids: list[str] = []
    for bereich in gesamt["kompetenzbereiche"]:
        for k in bereich["kompetenzen"]:
            ids += [i["id"] for i in k.get("anwendungsbereiche", [])]
    for k in gesamt["zusatzkompetenzen"]:
        ids += [i["id"] for i in k.get("anwendungsbereiche", [])]
    ids += [i["id"] for i in gesamt["digitale_technologien_vorschlaege"]]
    for eintrag in gesamt["meta"].get("anwendungsbereiche_bloecke", {}).values():
        ids += [i["id"] for i in eintrag["items"]]
    return ids


@pytest.mark.parametrize("spec_key,fixture,n_items,n_bloecke", ITEMS)
def test_every_item_survives_recombination_exactly_once(spec_key, fixture, n_items, n_bloecke):
    """The headline E12-10 criterion.

    Both failure modes are real: under ``bindung: stufe`` the identical block is
    repeated in every area file, so a naive merge would multiply PRIM.D's 37
    items by 4; under ``bindung: bereich`` the files hold disjoint areas, so a
    plain school-year key would drop three of SEK1.D's four areas per year.
    """
    dateien = _baue(spec_key, fixture)
    ids = _alle_item_ids(B.combine_parts(dateien))
    assert len(ids) == n_items
    assert len(set(ids)) == n_items


@pytest.mark.parametrize("spec_key,fixture,n_items,n_bloecke", ITEMS)
def test_no_praezisierung_ships_as_a_digital_suggestion(spec_key, fixture, n_items, n_bloecke):
    """V-64: ``art`` alone decides, never ``kompetenz_id is None``.

    Before E12-10 all 54 SEK1.D + 37 PRIM.D + 40 PRIM.SU items would have shipped
    as digital-technology suggestions; none of the 131 carries that art.
    """
    dateien = _baue(spec_key, fixture)
    dt = dateien["zusatz.json"]["digitale_technologien_vorschlaege"]
    assert [i for i in dt if i["art"] != "digitale_technologien"] == []


@pytest.mark.parametrize("spec_key,fixture,n_items,n_bloecke", ITEMS)
def test_block_container_matches_the_binding_axis(spec_key, fixture, n_items, n_bloecke):
    dateien = _baue(spec_key, fixture)
    gesamt = B.combine_parts(dateien)
    bloecke = gesamt["meta"].get("anwendungsbereiche_bloecke", {})
    assert len(bloecke) == n_bloecke
    bindung = P.SUBJECT_SPECS[spec_key].anwendungsbereiche_bindung
    if bindung not in ("bereich", "stufe"):
        # Nothing coarse-attached exists, so the key must be absent entirely --
        # not present-and-empty, which would imply the axis applies here.
        assert "anwendungsbereiche_bloecke" not in gesamt["meta"]
    for eintrag in bloecke.values():
        assert eintrag["bindung"] == bindung
        if bindung == "bereich":
            # A recombined document must not depend on "the area is implied by
            # the file it came from".
            assert eintrag["bereich_name"]
            assert eintrag["bereich_slug"]
        else:
            assert "bereich_name" not in eintrag
            assert "bereich_slug" not in eintrag


@pytest.mark.parametrize("spec_key,fixture,n_items,n_bloecke", ITEMS)
def test_coarse_items_are_never_pushed_onto_a_competence(spec_key, fixture, n_items, n_bloecke):
    """No competence record may carry an invented link.

    Under ``bindung: bereich``/``stufe`` the regulation attaches items to an area
    or a school year across all competences; asserting a per-competence link is
    precisely the misattribution the verbatim discipline exists to prevent.
    """
    if P.SUBJECT_SPECS[spec_key].anwendungsbereiche_bindung == "kompetenz":
        pytest.skip("bindung: kompetenz genuinely does attach items per competence")
    dateien = _baue(spec_key, fixture)
    for dateiname, doc in dateien.items():
        for bereich in doc.get("kompetenzbereiche", []):
            for k in bereich["kompetenzen"]:
                assert "anwendungsbereiche" not in k, (dateiname, k["id"])
        for k in doc.get("zusatzkompetenzen", []):
            assert "anwendungsbereiche" not in k, (dateiname, k["id"])


def test_stufe_blocks_are_repeated_verbatim_in_every_area_part():
    """Plan section 5 B1: a skill loading one area file sees all of that year's
    items without reading a second file (decision of 2026-07-29)."""
    dateien = _baue("PRIM.D", "prim_deutsch.xml")
    area_parts = {n: d for n, d in dateien.items() if n != "zusatz.json"}
    assert len(area_parts) == 4
    referenz = None
    for name, doc in area_parts.items():
        bloecke = doc["meta"]["anwendungsbereiche_bloecke"]
        assert sorted(bloecke) == ["SCH1", "SCH2", "SCH3", "SCH4"], name
        if referenz is None:
            referenz = bloecke
        assert bloecke == referenz, f"{name} differs from the other area parts"
    # ... and zusatz.json carries none of it: it holds no Kompetenzbereich.
    assert "anwendungsbereiche_bloecke" not in dateien["zusatz.json"]["meta"]


def test_bereich_blocks_are_area_specific_and_keyed_without_collision():
    """SEK1.D has 16 blocks, four per class year -- one per area.

    Measured 2026-08-02: a plain school-year key collides four ways, so the key
    is ``<SLUG>.<STUFE>``. Each area part carries only its own four blocks.
    """
    dateien = _baue("SEK1.D", "sek1_deutsch.xml")
    area_parts = {n: d for n, d in dateien.items() if n != "zusatz.json"}
    assert len(area_parts) == 4
    gesehen: set[str] = set()
    for name, doc in area_parts.items():
        bloecke = doc["meta"]["anwendungsbereiche_bloecke"]
        assert len(bloecke) == 4, name
        slug = doc["kompetenzbereiche"][0]["slug"]
        assert sorted(bloecke) == sorted(f"{slug}.K{n}" for n in (1, 2, 3, 4)), name
        assert all(e["bereich_slug"] == slug for e in bloecke.values()), name
        assert not (gesehen & set(bloecke)), f"{name} repeats another area's keys"
        gesehen |= set(bloecke)
    assert len(gesehen) == 16


def test_combine_parts_rejects_conflicting_block_entries():
    """Same key, different content must fail loudly rather than pick a winner."""
    dateien = _baue("PRIM.D", "prim_deutsch.xml")
    namen = [n for n in dateien if n != "zusatz.json"]
    kaputt = json.loads(json.dumps(dateien[namen[0]]))
    kaputt["meta"]["anwendungsbereiche_bloecke"]["SCH1"]["items"] = []
    with pytest.raises(B.BuildError, match="different content"):
        B.combine_parts({**dateien, namen[0]: kaputt})


@pytest.mark.parametrize("spec_key,fixture,n_items,n_bloecke", ITEMS)
def test_every_part_validates_against_the_schema(spec_key, fixture, n_items, n_bloecke):
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    for dateiname, doc in _baue(spec_key, fixture).items():
        fehler = [f"{list(e.path)}: {e.message}" for e in validator.iter_errors(doc)]
        assert fehler == [], f"{spec_key}/{dateiname}: {fehler[:3]}"
