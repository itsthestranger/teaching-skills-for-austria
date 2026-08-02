"""Build breadth across all six shards (E12-09).

Run:  .venv/bin/python -m pytest data-pipeline/tests -q

Unlike ``test_build_dataset.py`` -- which builds the real Sek I Mathematik
shard from ``resources/`` and is skipped entirely when that gitignored
directory is absent -- these tests run against the **committed** fixtures in
``tests/fixtures/``, so build breadth stays covered in a fresh clone and in CI.

What they pin down is V-59: routing keys on the area **slug**, not on
``bereich_nummer``. Only SEK1.M numbers its Kompetenzbereiche, so before E12-09
``build_parts`` raised ``KeyError: None`` for the other five, and
``zusatzkompetenzen`` -- defined as "has no area number" -- would have
swallowed every competence of those shards had the KeyError not fired first.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

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
    have been written as a zusatzkompetenz, carrying a null ``bereich_nummer``
    and omitting the (possibly empty) ``anwendungsbereiche`` key.
    """
    dateien = _baue(spec_key, fixture)
    for dateiname, doc in dateien.items():
        if dateiname == "zusatz.json":
            continue
        for bereich in doc["kompetenzbereiche"]:
            for k in bereich["kompetenzen"]:
                assert "bereich_nummer" not in k, (dateiname, k["id"])
                assert "bereich_name" not in k, (dateiname, k["id"])
                assert "anwendungsbereiche" in k, (dateiname, k["id"])


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
