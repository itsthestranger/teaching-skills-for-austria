"""stichwort_index keyword routing (E12-12, FINDINGS V-67).

V-67: index.json carried per-part counts/sizes but nothing mapping a search
term to a part, so the plan's own worked example --
``finde_kompetenz(fach=M, stufe=K2, stichworte=["Bruch"])`` -- forced loading
every part of a shard to answer a single keyword lookup. ``build_index()`` now
also emits ``stichwort_index``: normalised term -> comma-joined part
filenames containing it (see ``build_dataset._baue_stichwort_index`` and its
neighbouring constants for the exact normalisation/dropping/capping rules and
the measurements that justify each threshold).

Like ``test_build_six_shards.py`` -- and unlike ``test_build_dataset.py``,
which needs the gitignored ``resources/`` directory -- these tests build from
the **committed** fixtures in ``tests/fixtures/``, so they run in a fresh
clone and in CI.
"""

from __future__ import annotations

import json
import logging
import sys
import unicodedata
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

#: Mirrors test_build_six_shards.FAKE_MANIFEST -- enough structure for
#: build_provenienz(); the real manifest is gitignored.
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

#: spec key -> fixture, covering all six shards and, with them, all four
#: anwendungsbereiche_bindung axes (kompetenz/SEK1.M, bereich/SEK1.D,
#: prosa/SEK1.E, stufe/PRIM.D+PRIM.SU, keine/PRIM.M).
SHARDS = [
    ("SEK1.M", "sek1_mathematik.xml"),
    ("SEK1.D", "sek1_deutsch.xml"),
    ("SEK1.E", "sek1_fremdsprache.xml"),
    ("PRIM.D", "prim_deutsch.xml"),
    ("PRIM.M", "prim_mathematik.xml"),
    ("PRIM.SU", "prim_sachunterricht.xml"),
]


def _baue(spec_key: str, fixture: str) -> tuple[P.SubjectSpec, dict[str, dict]]:
    spec = P.SUBJECT_SPECS[spec_key]
    result = P.parse_lehrplan(FIXTURES / fixture, spec)
    registry = B.collect_abbildungen_registry_eintraege(result)
    dateien = B.build_parts(result, spec, FAKE_MANIFEST, registry, modus="meta")
    return spec, dateien


# ---------------------------------------------------------------------------
# Build breadth: all six shards, all four binding axes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spec_key,fixture", SHARDS)
def test_stichwort_index_present_and_nonempty(spec_key, fixture):
    spec, dateien = _baue(spec_key, fixture)
    index = B.build_index(spec, dateien)
    assert "stichwort_index" in index
    assert index["stichwort_index"], f"{spec_key}: no terms survived filtering"


@pytest.mark.parametrize("spec_key,fixture", SHARDS)
def test_every_posting_names_a_real_part(spec_key, fixture):
    """Every filename in a posting must be one of this shard's actual parts
    -- not zusatz.json-only or a typo, and never an empty entry."""
    spec, dateien = _baue(spec_key, fixture)
    index = B.build_index(spec, dateien)
    for begriff, postings in index["stichwort_index"].items():
        dateinamen = postings.split(",")
        assert dateinamen, begriff
        for name in dateinamen:
            assert name, f"{begriff!r}: empty filename in postings {postings!r}"
            assert name in dateien, f"{begriff!r}: {name!r} is not a real part of {spec_key}"


@pytest.mark.parametrize("spec_key,fixture", SHARDS)
def test_postings_are_sorted_and_deduplicated(spec_key, fixture):
    spec, dateien = _baue(spec_key, fixture)
    index = B.build_index(spec, dateien)
    for begriff, postings in index["stichwort_index"].items():
        dateinamen = postings.split(",")
        assert dateinamen == sorted(dateinamen), begriff
        assert len(dateinamen) == len(set(dateinamen)), begriff


# ---------------------------------------------------------------------------
# Thresholds: min length, stopwords, the postings cap (requirements 2 and 3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spec_key,fixture", SHARDS)
def test_no_term_is_shorter_than_the_minimum(spec_key, fixture):
    spec, dateien = _baue(spec_key, fixture)
    index = B.build_index(spec, dateien)
    zu_kurz = [t for t in index["stichwort_index"] if len(t) < B.STICHWORT_MIN_LEN]
    assert zu_kurz == []


@pytest.mark.parametrize("spec_key,fixture", SHARDS)
def test_no_stopword_survives(spec_key, fixture):
    spec, dateien = _baue(spec_key, fixture)
    index = B.build_index(spec, dateien)
    getroffen = set(index["stichwort_index"]) & B.STICHWORT_STOPWORDS
    assert getroffen == set()


@pytest.mark.parametrize("spec_key,fixture", SHARDS)
def test_no_posting_exceeds_the_cap(spec_key, fixture):
    """Requirement 2/3: a term present in more parts than the cap allows is
    dropped entirely, never truncated -- so every surviving posting is short
    by construction."""
    spec, dateien = _baue(spec_key, fixture)
    index = B.build_index(spec, dateien)
    for begriff, postings in index["stichwort_index"].items():
        assert len(postings.split(",")) <= B.STICHWORT_MAX_DATEIEN, begriff


@pytest.mark.parametrize("spec_key,fixture", SHARDS)
def test_a_term_in_every_part_is_dropped(spec_key, fixture):
    """The literal requirement-3 acceptance case: construct a term that is
    guaranteed to be in every part (the shard's own fach name, casefolded --
    every part's meta.fach.name is identical) and confirm it never survives,
    however low a cap were passed."""
    spec, dateien = _baue(spec_key, fixture)
    index = B.build_index(spec, dateien)
    fach_name = next(iter(dateien.values()))["meta"]["fach"]["name"]
    for wort in fach_name.split():
        normalisiert = unicodedata.normalize("NFC", wort.strip(".,;:")).casefold()
        if len(normalisiert) >= B.STICHWORT_MIN_LEN:
            assert normalisiert not in index["stichwort_index"], (
                f"{spec_key}: {normalisiert!r} (from meta.fach.name, present in every part) "
                "should have been dropped as non-discriminating"
            )


# ---------------------------------------------------------------------------
# Normalisation: casefold, ABB-token stripping (V-53-style junk)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spec_key,fixture", SHARDS)
def test_every_term_is_casefolded(spec_key, fixture):
    spec, dateien = _baue(spec_key, fixture)
    index = B.build_index(spec, dateien)
    for begriff in index["stichwort_index"]:
        assert begriff == begriff.casefold(), begriff


def test_abb_image_tokens_never_leak_into_the_index():
    """SEK1.M's fixture text contains literal ⟦ABB:hauptdokument.imgNNis.png⟧
    markers (zahlen.json, variablen.json, figuren.json all reference images).
    Without stripping them first, tokenising would seed the index with
    "abb"/"hauptdokument"/"img1is"/"png"-style junk that is not curriculum
    vocabulary and, worse, would be near-universal across every part that
    happens to reference a figure."""
    spec, dateien = _baue("SEK1.M", "sek1_mathematik.xml")
    # Sanity: the fixture really does carry ABB tokens, or this test would
    # pass vacuously.
    traf_abb = any(
        "⟦ABB:" in a.get("text", "")
        for doc in dateien.values()
        for bereich in doc.get("kompetenzbereiche", [])
        for k in bereich["kompetenzen"]
        for a in k.get("anwendungsbereiche", [])
    )
    assert traf_abb, "fixture no longer contains an ABB marker -- test needs a new source"
    index = B.build_index(spec, dateien)
    for junk in ("abb", "img", "png", "hauptdokument"):
        assert junk not in index["stichwort_index"]
    # No kept term contains a digit either (an img-token remnant like
    # "img1is" would), since _WORT_RE only ever matches letters.
    assert not any(any(c.isdigit() for c in t) for t in index["stichwort_index"])


# ---------------------------------------------------------------------------
# The acceptance criterion: "Bruch" resolves to a small number of parts, and
# that part genuinely contains it (V-67's own worked example).
# ---------------------------------------------------------------------------


def test_bruch_resolves_to_a_small_number_of_sek1_m_parts():
    spec, dateien = _baue("SEK1.M", "sek1_mathematik.xml")
    index = B.build_index(spec, dateien)
    postings = index["stichwort_index"].get("bruch")
    assert postings is not None, "'bruch' did not survive indexing at all"
    dateinamen = postings.split(",")
    # "small number", not necessarily one -- see STICHWORT_MAX_DATEIEN's
    # comment for why cap=2 is chosen over the stricter cap=1.
    assert 1 <= len(dateinamen) <= B.STICHWORT_MAX_DATEIEN
    assert len(dateinamen) < len(dateien), "must not resolve to every part"


def test_bruch_postings_actually_contain_the_term():
    """The point of the whole feature: reading only the returned part(s)
    must actually find the term, with no false-positive routing."""
    spec, dateien = _baue("SEK1.M", "sek1_mathematik.xml")
    index = B.build_index(spec, dateien)
    postings = index["stichwort_index"]["bruch"]
    for dateiname in postings.split(","):
        payload = json.dumps(dateien[dateiname], ensure_ascii=False).casefold()
        assert "bruch" in payload, f"{dateiname} was named in bruch's postings but does not contain it"
    # And the parts *not* named must not silently also contain a standalone
    # "Bruch" token -- otherwise the index would be incomplete, not just capped.
    import re

    wort_re = re.compile(r"[^\W\d_]+")
    for dateiname, doc in dateien.items():
        if dateiname in postings.split(","):
            continue
        text = json.dumps(doc, ensure_ascii=False)
        text = P.ABBILDUNG_TOKEN_RE.sub(" ", text)
        gefunden = {unicodedata.normalize("NFC", w).casefold() for w in wort_re.findall(text)}
        assert "bruch" not in gefunden, f"{dateiname} contains 'bruch' but is missing from its postings"


# ---------------------------------------------------------------------------
# Determinism (requirement 4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spec_key,fixture", SHARDS)
def test_build_is_byte_identical_across_repeated_runs(spec_key, fixture):
    spec, dateien = _baue(spec_key, fixture)
    payload_a = B._dump(B.build_index(spec, dateien))
    payload_b = B._dump(B.build_index(spec, dateien))
    assert payload_a == payload_b


@pytest.mark.parametrize("spec_key,fixture", SHARDS)
def test_stichwort_index_keys_are_sorted(spec_key, fixture):
    spec, dateien = _baue(spec_key, fixture)
    index = B.build_index(spec, dateien)
    keys = list(index["stichwort_index"])
    assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# Compactness (requirement 2): the index must stay small relative to what it
# replaces -- loading every part.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spec_key,fixture", SHARDS)
def test_index_stays_far_smaller_than_loading_every_part(spec_key, fixture):
    """Not a byte-exact budget (that would pin fixture prose that may
    legitimately change) -- the structural guarantee V-67 asked for: index.json
    with stichwort_index must still cost much less than the alternative it
    replaces, loading every part."""
    spec, dateien = _baue(spec_key, fixture)
    index = B.build_index(spec, dateien)
    index_bytes = len(B._dump(index).encode("utf-8"))
    parts_bytes = sum(len(B._dump(doc).encode("utf-8")) for doc in dateien.values())
    assert index_bytes < parts_bytes / 2


@pytest.mark.parametrize("spec_key,fixture", SHARDS)
def test_no_kept_term_appears_in_every_single_part(spec_key, fixture):
    """Requirement 3, restated structurally: STICHWORT_MAX_DATEIEN < the
    shard's own part count for every shard under test, so a term present in
    literally all parts can never survive regardless of content."""
    spec, dateien = _baue(spec_key, fixture)
    assert B.STICHWORT_MAX_DATEIEN < len(dateien)
