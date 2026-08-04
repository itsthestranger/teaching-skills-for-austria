"""Contract-conformance tests for ``plugin/scripts/kompetenz.py`` (E4-08).

**Purpose.** ``test_kompetenz_access.py`` (E4-01..07) proves the access
layer against the *shipped* dataset -- it is evidence that today's B1
implementation produces the right answers for the real six shards. This
module proves something narrower and more durable: that the module's
*public contract* -- the promise a skill author or a future B2 (SQLite)
implementer can rely on -- holds against a small, synthetic, hand-built
shard tree that exercises every distinct branch the plan's own binding/
axis vocabulary describes. None of the record IDs, subject names or
competence text below are real regulation text; they exist only to give
each branch a deterministic, easy-to-read input.

Unlike the sibling module, every test here runs against
``data-pipeline/tests/fixtures/kompetenz_mini/`` via the
``_fixture_root`` autouse fixture below, which monkeypatches
``kompetenz.KOMPETENZEN_ROOT`` for the duration of each test. Nothing in
this module reads ``plugin/data/kompetenzen/`` -- if it did, a shipped-data
change could make one of these tests pass or fail for the wrong reason,
which would defeat the point of a contract fixture. Redirecting
``KOMPETENZEN_ROOT`` and changing nothing else is itself the concrete
proof of the B1->B2 non-breaking promise for the file-backed half of the
system: if a future implementation swaps the directory-of-JSON-parts
storage for SQLite while keeping ``kompetenz.py``'s public surface
unchanged, this exact module should still be re-runnable (perhaps with the
monkeypatch target renamed) and still pass.

================================================================================
THE CONTRACT -- what a caller (a skill, a future B2 implementer) may rely on
================================================================================

**Public surface.** Exactly these names are the contract. Anything
underscore-prefixed (``_shard_verzeichnis``, ``_datei_laden``, ``_parse_id``,
``_anreichern``, ...) is a private implementation detail of the B1 storage
strategy and may change shape, be renamed or disappear in a B2 migration
without notice:

- ``finde_kompetenz(fach, stufe=None, kompetenzbereich=None, code=None,
  stichworte=None) -> list[dict]``
- ``finde_progression(kompetenz_id, richtung) -> list[dict]``
- ``finde_anwendungsbereiche(kompetenz_id=None, nur_verbindlich=None, *,
  fach=None, stufe=None, bereich=None) -> list[dict]``
- ``finde_lehrstoff(kompetenz_id=None, *, fach=None, stufe=None,
  bereich=None) -> {"quelle": str, "items": list[str]}``
- ``finde_lernaufgaben(fach=None, stufe=None, kompetenz_id=None,
  docs_root=None) -> list[dict]``
- ``finde_bildungsstandard_bezug(kompetenz_id) -> dict``
- ``finde_uebergreifende_themen(fach=None, kompetenz_id=None, thema=None)
  -> list`` (exactly one of the three keyword args)
- ``finde_differenzierung(kompetenz_id) -> {"achse", "niveaus",
  "enrichment_items", "vorklasse_stuetzen", "docs_material"}``
- ``finde_typische_fehlvorstellungen(kompetenz_id) -> list`` (always ``[]``
  today -- E9 is unimplemented by design)
- ``kompetenz_nach_id(kompetenz_id) -> dict`` (not one of the plan's nine,
  but every ``finde_*`` above is built on it and several tests below call it
  directly)
- ``voller_wortlaut(kompetenz: dict) -> str``
- ``stichwort_abdeckung(fach, begriff) -> dict`` (an E4-02 introspection
  helper, not one of the nine, but public and load-bearing for V-73 --
  callers must not read an empty ``finde_kompetenz`` result as "absent from
  the curriculum" without first checking this)
- Exception hierarchy: ``KompetenzFehler(Exception)``,
  ``UnbekannterFachSchluessel(KompetenzFehler, ValueError)``,
  ``KompetenzNichtGefunden(KompetenzFehler, LookupError)``. A caller that
  only wants to catch "this module misbehaved" can catch
  ``KompetenzFehler`` alone and get both concrete cases.
- ``ALLE_FAECHER`` / ``GUELTIGE_FAECHER``: the frozen six-shard registry.

**Shape guarantees every ``Kompetenz`` dict carries** (whether returned by
``finde_kompetenz``, ``kompetenz_nach_id``, ``finde_progression`` or nested
inside ``finde_differenzierung``'s ``vorklasse_stuetzen``): ``id``, ``fach``,
``stufe``, ``bereich_slug``, ``bereich_name``, ``bereich_nummer`` (may be
``None``), ``stammsatz``, ``text``, ``volltext`` (== ``stammsatz`` + ``" "``
+ ``text``, the only faithful quotation -- never cite ``text`` alone),
``provenienz`` (a dict copy, never the loaded document's own dict object).

**Dispatch is always data-driven, never a hardcoded subject name.** Every
function that branches on shard shape reads ``meta.anwendungsbereiche_bindung``
(``kompetenz`` | ``bereich`` | ``stufe`` | ``prosa`` | ``keine``),
``meta.lehrstoff_quelle`` (``aus_anwendungsbereichen`` | ``eigen_ausgewiesen``),
``meta.bildungsstandard_bezug`` (``verordnet`` | ``keine_verordnung``) or
``meta.differenzierungs_achse`` (free-form, dispatched on the presence of
specific keys such as ``enrichment_quelle: "allenfalls"``, never on
"is this SEK1.M"). This module's fixture deliberately uses none of the six
real subject codes/names, so any test here passing is proof the dispatch
reads data, not a subject string.

**Defined-empty is not an error.** ``prosa`` and ``keine`` bindings, a
structural Kompetenzbereich with zero competences, a ``bereich``-bound
(area, year) pair with no block at all -- every one of these returns ``[]``
(or an equivalent empty/false shape) from the legacy competence-ID call
path. **Asymmetry, pinned below:** the *coordinate* call path
(``fach``/``stufe``/``bereich`` keywords) raises ``ValueError`` instead when
the exact block it was told to address does not exist, because a coordinate
call is an explicit claim ("this block exists") whereas a competence-ID call
only ever reports what its own competence happens to have.

**Keyword search is competence-description-only and honest about it.**
``finde_kompetenz(..., stichworte=[...])`` returns ``[]`` when the term
occurs only in an Anwendungsbereiche/Lehrstoff item, never a curriculum
presence/absence claim. ``stichwort_abdeckung`` is the honest tool for that
case and returns one of four ``suchstatus`` values --
``keine_indexkandidaten``, ``kandidaten_ohne_texttreffer``,
``kompetenztreffer``, ``nur_lehrstofftreffer`` -- all four exercised below.

**Out of contract (must never be pinned as a promise):** the on-disk
directory layout, JSON key ordering, any underscore-prefixed function,
``KOMPETENZEN_ROOT`` itself (this module's whole reason to monkeypatch it),
and file names/counts inside a shard (``index.json``'s ``teile`` is a
routing hint, not something a caller should enumerate directly).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
_FIXTURE_ROOT = _HERE / "fixtures" / "kompetenz_mini"
sys.path.insert(0, str(_REPO_ROOT / "plugin" / "scripts"))

import kompetenz as K  # noqa: E402


@pytest.fixture(autouse=True)
def _fixture_root(monkeypatch):
    """Point the module at the mini fixture, never the shipped dataset.

    This is the one seam every test in this module relies on. It is also
    the concrete demonstration of the migration promise this task exists
    to pin: every public function below is reached exclusively through
    this one redirected root, with no other code change.
    """
    monkeypatch.setattr(K, "KOMPETENZEN_ROOT", _FIXTURE_ROOT)


#: The five ``anwendungsbereiche_bindung`` values, each carried by exactly
#: one fixture shard -- restated here, not imported, so a change to the
#: fixture's own meta makes this file's expectation visibly wrong.
SHARDS = [
    ("SEK1.M", "kompetenz"),
    ("SEK1.D", "bereich"),
    ("SEK1.E", "prosa"),
    ("PRIM.D", "stufe"),
    ("PRIM.M", "keine"),
    ("PRIM.SU", "stufe"),
]

ERWARTETE_ANZAHL = {
    "SEK1.M": 3,  # ALPHA.K1.01, ALPHA.K2.01, zusatzkompetenz BETA.K3.01
    "SEK1.D": 3,  # GAMMA.K1.01, GAMMA.K1.02, GAMMA.K2.01 (DELTA has none)
    "SEK1.E": 1,  # EPSILON.K1.01
    "PRIM.D": 3,  # ZETA.SCH1.01, ZETA.SCH2.01, ETA.SCH1.01
    "PRIM.M": 1,  # THETA.SCH1.01
    "PRIM.SU": 1,  # IOTA.SCH1.01
}


def test_alle_faecher_deckt_die_fixtur_ab():
    assert set(K.ALLE_FAECHER) == {s for s, _b in SHARDS}


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


def test_exception_hierarchy_ist_wie_dokumentiert():
    assert issubclass(K.UnbekannterFachSchluessel, K.KompetenzFehler)
    assert issubclass(K.UnbekannterFachSchluessel, ValueError)
    assert issubclass(K.KompetenzNichtGefunden, K.KompetenzFehler)
    assert issubclass(K.KompetenzNichtGefunden, LookupError)

    with pytest.raises(K.KompetenzFehler):
        K.finde_kompetenz("NICHT.EXISTENT")
    with pytest.raises(K.KompetenzFehler):
        K.kompetenz_nach_id("AT.LP23.SEK1.M.ALPHA.K9.99")


# ---------------------------------------------------------------------------
# voller_wortlaut -- pure function, no shard access
# ---------------------------------------------------------------------------


def test_voller_wortlaut_joins_stammsatz_und_text():
    assert (
        K.voller_wortlaut({"stammsatz": "Die Schülerinnen und Schüler können", "text": "rechnen."})
        == "Die Schülerinnen und Schüler können rechnen."
    )


def test_voller_wortlaut_ohne_stammsatz_gibt_nur_text():
    assert K.voller_wortlaut({"text": "rechnen."}) == "rechnen."
    assert K.voller_wortlaut({"stammsatz": "", "text": "rechnen."}) == "rechnen."


def test_voller_wortlaut_leeres_dict_gibt_leeren_string():
    assert K.voller_wortlaut({}) == ""


# ---------------------------------------------------------------------------
# kompetenz_nach_id -- routes via the ID's own Bereich segment, then zusatz
# ---------------------------------------------------------------------------


def test_kompetenz_nach_id_routiert_ueber_bereich_slug():
    k = K.kompetenz_nach_id("AT.LP23.SEK1.M.ALPHA.K1.01")
    assert k["fach"] == "SEK1.M"
    assert k["bereich_slug"] == "ALPHA"
    assert k["volltext"] == "Die Schülerinnen und Schüler können alpha eins bruch bearbeiten."
    assert k["provenienz"]["quelle"] == "RIS Bundesrecht konsolidiert"


def test_kompetenz_nach_id_findet_zusatzkompetenz_ueber_zusatz_datei():
    """BETA is not a real Kompetenzbereich file -- routing must fall
    through to zusatz.json exactly as it does for SEK1.M's real
    GZINTEGRATIV competences (V-57)."""
    k = K.kompetenz_nach_id("AT.LP23.SEK1.M.BETA.K3.01")
    assert k["bereich_nummer"] is None
    assert k["bereich_name"] == "Beta Zusatzbereich"
    # Slug is derived from the ID itself, never invented (V-57's own fix).
    assert k["bereich_slug"] == "BETA"


def test_kompetenz_nach_id_unknown_id_raises_kompetenz_nicht_gefunden():
    with pytest.raises(K.KompetenzNichtGefunden):
        K.kompetenz_nach_id("AT.LP23.SEK1.M.ALPHA.K9.99")


def test_kompetenz_nach_id_lehnt_anwendungsitem_id_ab():
    with pytest.raises(K.KompetenzFehler, match="Anwendungsitem"):
        K.kompetenz_nach_id("AT.LP23.SEK1.M.AB.ALPHA.K1.01")


# ---------------------------------------------------------------------------
# finde_kompetenz
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fach,_bindung", SHARDS)
def test_finde_kompetenz_gegen_alle_fixtur_shards(fach, _bindung):
    ergebnisse = K.finde_kompetenz(fach)
    assert len(ergebnisse) == ERWARTETE_ANZAHL[fach]
    for k in ergebnisse:
        assert k["fach"] == fach
        assert k["stammsatz"]
        assert k["volltext"].startswith(k["stammsatz"])
        assert k["text"] in k["volltext"]
        assert k["provenienz"]["nor"] == "NOR00000001"


def test_finde_kompetenz_case_insensitive_fach():
    assert K.finde_kompetenz("sek1.m") == K.finde_kompetenz("SEK1.M")


def test_finde_kompetenz_stufe_filter():
    gefiltert = K.finde_kompetenz("SEK1.M", stufe="K1")
    assert [k["id"] for k in gefiltert] == ["AT.LP23.SEK1.M.ALPHA.K1.01"]


def test_finde_kompetenz_kompetenzbereich_filter_by_slug_and_name():
    per_slug = K.finde_kompetenz("SEK1.D", kompetenzbereich="GAMMA")
    assert {k["id"] for k in per_slug} == {
        "AT.LP23.SEK1.D.GAMMA.K1.01",
        "AT.LP23.SEK1.D.GAMMA.K1.02",
        "AT.LP23.SEK1.D.GAMMA.K2.01",
    }
    per_name = K.finde_kompetenz("SEK1.D", kompetenzbereich="gamma-bereich")
    assert {k["id"] for k in per_name} == {k["id"] for k in per_slug}


def test_finde_kompetenz_kompetenzbereich_filter_strukturelle_area_ist_leer():
    """DELTA has an Anwendungsbereiche block but zero competences -- a
    filter naming it must return [], never invent a record (V-77)."""
    assert K.finde_kompetenz("SEK1.D", kompetenzbereich="DELTA") == []


def test_finde_kompetenz_code_lookup_exact():
    treffer = K.finde_kompetenz("SEK1.M", code="AT.LP23.SEK1.M.ALPHA.K2.01")
    assert [k["id"] for k in treffer] == ["AT.LP23.SEK1.M.ALPHA.K2.01"]


def test_finde_kompetenz_code_from_wrong_fach_is_empty():
    assert K.finde_kompetenz("SEK1.D", code="AT.LP23.SEK1.M.ALPHA.K1.01") == []


def test_finde_kompetenz_unknown_fach_raises():
    with pytest.raises(K.UnbekannterFachSchluessel):
        K.finde_kompetenz("SEK1.SU")  # not one of the six shard keys
    with pytest.raises(K.UnbekannterFachSchluessel):
        K.finde_kompetenz("keinpunkt")


def test_finde_kompetenz_no_match_returns_empty_list_not_error():
    assert K.finde_kompetenz("SEK1.M", stichworte=["xyzzy-nichts-hier"]) == []


def test_finde_kompetenz_sortierung_ist_stufe_bereich_ordinal():
    ids = [k["id"] for k in K.finde_kompetenz("PRIM.D")]
    assert ids == [
        "AT.LP23.PRIM.D.ETA.SCH1.01",  # SCH1, bereich ETA < ZETA
        "AT.LP23.PRIM.D.ZETA.SCH1.01",  # SCH1, bereich ZETA
        "AT.LP23.PRIM.D.ZETA.SCH2.01",  # SCH2
    ]


# --- stichworte: exact + compound union (V-71-shaped, own fixture) --------


def test_finde_kompetenz_stichworte_kompetenztreffer_via_compound_union():
    """"bruch" exact-hits alpha.json; "bruchtermen" (a compound key) routes
    to zusatz.json -- both are read, but only ALPHA.K1.01's own text
    actually contains "bruch", so it alone survives the post-filter."""
    treffer = K.finde_kompetenz("SEK1.M", stichworte=["Bruch"])
    assert [k["id"] for k in treffer] == ["AT.LP23.SEK1.M.ALPHA.K1.01"]


def test_finde_kompetenz_stichworte_liest_nur_indexkandidaten(monkeypatch):
    original = K._datei_laden
    geladen: list[str] = []

    def verfolgen(pfad):
        geladen.append(pfad.name)
        return original(pfad)

    monkeypatch.setattr(K, "_datei_laden", verfolgen)
    K.finde_kompetenz("SEK1.M", stichworte=["Bruch"])
    assert set(geladen) == {"index.json", "alpha.json", "zusatz.json"}


def test_finde_kompetenz_stichworte_treffer_nur_wenn_text_wirklich_passt():
    """The routed-but-non-matching zusatz.json competence (BETA) must not
    leak into the result just because its file was a routing candidate."""
    treffer = K.finde_kompetenz("SEK1.M", stichworte=["Bruch"])
    assert "AT.LP23.SEK1.M.BETA.K3.01" not in {k["id"] for k in treffer}


def test_finde_kompetenz_stichworte_item_only_begriff_ist_leer():
    """"Zusatzaufgaben" occurs only inside an Anwendungsbereiche item's
    text, never a competence's own text -- a true V-73 case on the mini
    fixture."""
    assert K.finde_kompetenz("SEK1.M", stichworte=["Zusatzaufgaben"]) == []


def test_finde_kompetenz_stichworte_durchsucht_auch_stammsatz():
    """The stem paragraph is part of the searchable text, not just
    `text` -- exercised via SEK1.E's V-58-shaped qualified stammsatz."""
    treffer = K.finde_kompetenz("SEK1.E", stichworte=["langsam"])
    assert [k["id"] for k in treffer] == ["AT.LP23.SEK1.E.EPSILON.K1.01"]


# ---------------------------------------------------------------------------
# stichwort_abdeckung -- all four suchstatus values
# ---------------------------------------------------------------------------


def test_stichwort_abdeckung_keine_indexkandidaten():
    abdeckung = K.stichwort_abdeckung("SEK1.M", "voellig-unbekannt")
    assert abdeckung["suchstatus"] == "keine_indexkandidaten"
    assert abdeckung["dateien"] == []
    assert abdeckung["kompetenz_ids"] == []
    assert abdeckung["lehrstoff_items"] == []
    assert "keine Aussage" in abdeckung["hinweis"]


def test_stichwort_abdeckung_kompetenztreffer():
    abdeckung = K.stichwort_abdeckung("SEK1.M", "bruch")
    assert abdeckung["suchstatus"] == "kompetenztreffer"
    assert abdeckung["kompetenz_ids"] == ["AT.LP23.SEK1.M.ALPHA.K1.01"]


def test_stichwort_abdeckung_nur_lehrstofftreffer():
    """"Zusatzaufgaben" is real Lehrstoff text (an Anwendungsbereiche item)
    but matches no competence description -- an empty finde_kompetenz must
    not be read as absence (V-73)."""
    abdeckung = K.stichwort_abdeckung("SEK1.M", "Zusatzaufgaben")
    assert abdeckung["suchstatus"] == "nur_lehrstofftreffer"
    assert abdeckung["kompetenz_ids"] == []
    assert abdeckung["lehrstoff_items"] == [
        {
            "id": "AT.LP23.SEK1.M.AB.ALPHA.K1.02",
            "text": "allenfalls Vertiefen mit Zusatzaufgaben.",
            "stufe": "K1",
            "verbindlich": False,
            "kompetenz_id": "AT.LP23.SEK1.M.ALPHA.K1.01",
        }
    ]
    assert K.finde_kompetenz("SEK1.M", stichworte=["Zusatzaufgaben"]) == []


def test_stichwort_abdeckung_kandidaten_ohne_texttreffer():
    """"bruchtermen" routes to zusatz.json, but the only occurrence there
    is inside a digitale_technologien item, which is excluded from both
    Kompetenz- and Lehrstoff-Praezisierungs matching by design (V-54)."""
    abdeckung = K.stichwort_abdeckung("SEK1.M", "bruchtermen")
    assert abdeckung["dateien"] == ["zusatz.json"]
    assert abdeckung["suchstatus"] == "kandidaten_ohne_texttreffer"
    assert abdeckung["kompetenz_ids"] == []
    assert abdeckung["lehrstoff_items"] == []
    assert "keine Aussage" in abdeckung["hinweis"]


# ---------------------------------------------------------------------------
# finde_progression
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fach,_bindung", SHARDS)
def test_finde_progression_never_crosses_kompetenzbereich(fach, _bindung):
    verstoesse = []
    for k in K.finde_kompetenz(fach):
        for richtung in ("zurueck", "vor"):
            for ziel in K.finde_progression(k["id"], richtung):
                if ziel["bereich_slug"] != k["bereich_slug"]:
                    verstoesse.append((k["id"], richtung, ziel["id"]))
    assert verstoesse == []


def test_finde_progression_kompetenz_bindung_beide_richtungen():
    vor = K.finde_progression("AT.LP23.SEK1.M.ALPHA.K1.01", "vor")
    assert [k["id"] for k in vor] == ["AT.LP23.SEK1.M.ALPHA.K2.01"]
    zurueck = K.finde_progression("AT.LP23.SEK1.M.ALPHA.K2.01", "zurueck")
    assert [k["id"] for k in zurueck] == ["AT.LP23.SEK1.M.ALPHA.K1.01"]


def test_finde_progression_bereich_bindung_mehrere_vorgaenger():
    """GAMMA.K2.01 has two K1 predecessors -- a multi-source case."""
    zurueck = K.finde_progression("AT.LP23.SEK1.D.GAMMA.K2.01", "zurueck")
    assert {k["id"] for k in zurueck} == {
        "AT.LP23.SEK1.D.GAMMA.K1.01",
        "AT.LP23.SEK1.D.GAMMA.K1.02",
    }


def test_finde_progression_stufe_bindung_ueber_zwei_areas_isoliert():
    """ZETA has real progression; ETA (same stufe, different area) has
    none -- proves progression is per-area, not per-stufe."""
    vor = K.finde_progression("AT.LP23.PRIM.D.ZETA.SCH1.01", "vor")
    assert [k["id"] for k in vor] == ["AT.LP23.PRIM.D.ZETA.SCH2.01"]
    assert K.finde_progression("AT.LP23.PRIM.D.ETA.SCH1.01", "vor") == []
    assert K.finde_progression("AT.LP23.PRIM.D.ETA.SCH1.01", "zurueck") == []


def test_finde_progression_invalid_richtung_raises():
    with pytest.raises(ValueError):
        K.finde_progression("AT.LP23.SEK1.M.ALPHA.K1.01", "seitwaerts")


def test_finde_progression_unknown_id_raises():
    with pytest.raises(K.KompetenzNichtGefunden):
        K.finde_progression("AT.LP23.SEK1.M.NICHT.K1.99", "vor")


# ---------------------------------------------------------------------------
# finde_anwendungsbereiche -- all five bindings, both call modes
# ---------------------------------------------------------------------------


def test_finde_anwendungsbereiche_kompetenz_bindung_verschachtelte_items():
    items = K.finde_anwendungsbereiche("AT.LP23.SEK1.M.ALPHA.K1.01")
    assert {i["id"] for i in items} == {
        "AT.LP23.SEK1.M.AB.ALPHA.K1.01",
        "AT.LP23.SEK1.M.AB.ALPHA.K1.02",
    }
    assert [i["id"] for i in K.finde_anwendungsbereiche("AT.LP23.SEK1.M.ALPHA.K1.01", nur_verbindlich=True)] == [
        "AT.LP23.SEK1.M.AB.ALPHA.K1.01"
    ]
    assert [i["id"] for i in K.finde_anwendungsbereiche("AT.LP23.SEK1.M.ALPHA.K1.01", nur_verbindlich=False)] == [
        "AT.LP23.SEK1.M.AB.ALPHA.K1.02"
    ]
    # K2.01's only item is verbindlich -- the False split is legitimately
    # empty there, never an error (V-42/V-60 generalised).
    assert K.finde_anwendungsbereiche("AT.LP23.SEK1.M.ALPHA.K2.01", nur_verbindlich=False) == []


def test_finde_anwendungsbereiche_bereich_bindung_teilt_sich_block():
    a = K.finde_anwendungsbereiche("AT.LP23.SEK1.D.GAMMA.K1.01")
    b = K.finde_anwendungsbereiche("AT.LP23.SEK1.D.GAMMA.K1.02")
    assert a == b
    assert [i["id"] for i in a] == ["AT.LP23.SEK1.D.AB.GAMMA.K1.01"]
    assert a[0]["kompetenz_id"] is None


def test_finde_anwendungsbereiche_bereich_bindung_fehlender_block_ist_still_leer():
    """GAMMA.K2 has no block at all. The legacy competence-ID call reports
    that as a defined-empty result, not an error."""
    assert K.finde_anwendungsbereiche("AT.LP23.SEK1.D.GAMMA.K2.01") == []


def test_finde_anwendungsbereiche_koordinaten_fehlender_block_wirft_dagegen():
    """The coordinate call for the same missing block raises instead -- the
    documented asymmetry: coordinates are an explicit claim the block
    exists, a competence-ID lookup only reports what it happens to carry."""
    with pytest.raises(ValueError, match="kein Anwendungsbereiche-Block"):
        K.finde_anwendungsbereiche(fach="SEK1.D", stufe="K2", bereich="GAMMA")


def test_finde_anwendungsbereiche_bereich_koordinaten_erreichen_strukturelle_area():
    """DELTA has zero competences -- only the coordinate call can honestly
    reach its official items (V-77)."""
    ergebnis = K.finde_anwendungsbereiche(fach="SEK1.D", stufe="K1", bereich="DELTA")
    assert [i["id"] for i in ergebnis] == ["AT.LP23.SEK1.D.AB.DELTA.K1.01"]
    assert ergebnis[0]["kompetenz_id"] is None
    # The official name is an equally valid coordinate.
    assert K.finde_anwendungsbereiche(fach="SEK1.D", stufe="K1", bereich="Delta-Struktur") == ergebnis


def test_finde_anwendungsbereiche_stufe_bindung_teilt_sich_ueber_areas():
    """ZETA and ETA are different Kompetenzbereiche but the same stufe --
    a stufe-bound block must be identical regardless of which area's
    competence asked for it."""
    a = K.finde_anwendungsbereiche("AT.LP23.PRIM.D.ZETA.SCH1.01")
    b = K.finde_anwendungsbereiche("AT.LP23.PRIM.D.ETA.SCH1.01")
    assert a == b
    assert [i["id"] for i in a] == ["AT.LP23.PRIM.D.AB.SCH1.01"]


def test_finde_anwendungsbereiche_stufe_koordinaten_lehnen_bereich_ab():
    with pytest.raises(ValueError, match="bereichsfrei"):
        K.finde_anwendungsbereiche(fach="PRIM.D", stufe="SCH1", bereich="ZETA")
    ergebnis = K.finde_anwendungsbereiche(fach="PRIM.D", stufe="SCH1")
    assert [i["id"] for i in ergebnis] == ["AT.LP23.PRIM.D.AB.SCH1.01"]


@pytest.mark.parametrize("fach", ["SEK1.E", "PRIM.M"])
def test_finde_anwendungsbereiche_prosa_und_keine_sind_defined_empty(fach):
    k = K.finde_kompetenz(fach)[0]
    assert K.finde_anwendungsbereiche(k["id"]) == []
    assert K.finde_anwendungsbereiche(k["id"], nur_verbindlich=True) == []
    assert K.finde_anwendungsbereiche(k["id"], nur_verbindlich=False) == []
    assert K.finde_anwendungsbereiche(fach=fach) == []


def test_finde_anwendungsbereiche_modusvalidierung():
    ziel = K.finde_kompetenz("SEK1.M")[0]
    with pytest.raises(ValueError, match="kompetenz_id und Koordinaten"):
        K.finde_anwendungsbereiche(ziel["id"], fach="SEK1.M")
    with pytest.raises(ValueError, match="kompetenz_id oder mindestens fach"):
        K.finde_anwendungsbereiche()
    with pytest.raises(ValueError, match="bindung 'kompetenz'"):
        K.finde_anwendungsbereiche(fach="SEK1.M")
    with pytest.raises(ValueError, match="erfordert fach, stufe und bereich"):
        K.finde_anwendungsbereiche(fach="SEK1.D", stufe="K1")
    with pytest.raises(ValueError, match="unbekannter bereich"):
        K.finde_anwendungsbereiche(fach="SEK1.D", stufe="K1", bereich="NICHT-VORHANDEN")
    with pytest.raises(K.KompetenzNichtGefunden):
        K.finde_anwendungsbereiche("AT.LP23.SEK1.M.NICHT.K1.99")


# ---------------------------------------------------------------------------
# finde_lehrstoff
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fach,_bindung", SHARDS)
def test_finde_lehrstoff_callable_gegen_alle_fixtur_shards(fach, _bindung):
    for k in K.finde_kompetenz(fach):
        ergebnis = K.finde_lehrstoff(k["id"])
        assert set(ergebnis) == {"quelle", "items"}
        assert ergebnis["quelle"] in ("aus_anwendungsbereichen", "eigen_ausgewiesen")
        assert isinstance(ergebnis["items"], list)


def test_finde_lehrstoff_aus_anwendungsbereichen_matcht_finde_anwendungsbereiche():
    k_id = "AT.LP23.SEK1.M.ALPHA.K1.01"
    ergebnis = K.finde_lehrstoff(k_id)
    assert ergebnis == {
        "quelle": "aus_anwendungsbereichen",
        "items": [i["text"] for i in K.finde_anwendungsbereiche(k_id)],
    }


def test_finde_lehrstoff_eigen_ausgewiesen_ist_die_eigene_volltext_zitierung():
    """PRIM.M (V-45): Lehrstoff IS the competence's own quotation, not a
    separate, possibly-missing field."""
    k = K.finde_kompetenz("PRIM.M")[0]
    ergebnis = K.finde_lehrstoff(k["id"])
    assert ergebnis == {"quelle": "eigen_ausgewiesen", "items": [k["volltext"]]}


def test_finde_lehrstoff_leere_und_kompetenzspezifische_faelle_sind_ehrlich():
    # prosa: real quelle, honestly empty items -- not an error, not omitted.
    assert K.finde_lehrstoff(fach="SEK1.E") == {"quelle": "aus_anwendungsbereichen", "items": []}
    # kompetenz binding needs a competence ID -- aggregating would misattribute.
    with pytest.raises(ValueError, match="bindung 'kompetenz'"):
        K.finde_lehrstoff(fach="SEK1.M")
    # eigen_ausgewiesen needs a competence ID -- there is no shard-wide text.
    with pytest.raises(ValueError, match="eigen_ausgewiesen"):
        K.finde_lehrstoff(fach="PRIM.M")


def test_finde_lehrstoff_koordinaten_erreichen_strukturellen_block():
    ergebnis = K.finde_lehrstoff(fach="SEK1.D", stufe="K1", bereich="DELTA")
    assert ergebnis == {
        "quelle": "aus_anwendungsbereichen",
        "items": ["Strukturitem ohne Kompetenzbezug."],
    }


# ---------------------------------------------------------------------------
# finde_bildungsstandard_bezug
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fach,_bindung", [(f, b) for f, b in SHARDS if f != "PRIM.SU"])
def test_finde_bildungsstandard_bezug_verordnet(fach, _bindung):
    k = K.finde_kompetenz(fach)[0]
    ergebnis = K.finde_bildungsstandard_bezug(k["id"])
    assert ergebnis["abgedeckt"] is True
    assert ergebnis["deskriptoren"] == []
    assert ergebnis["hinweis"]


def test_finde_bildungsstandard_bezug_keine_verordnung():
    k = K.finde_kompetenz("PRIM.SU")[0]
    assert K.finde_bildungsstandard_bezug(k["id"]) == {
        "abgedeckt": False,
        "grund": "keine BiSt verordnet",
    }


# ---------------------------------------------------------------------------
# finde_uebergreifende_themen -- exactly one of three modes
# ---------------------------------------------------------------------------


def test_finde_uebergreifende_themen_erfordert_genau_ein_argument():
    with pytest.raises(ValueError):
        K.finde_uebergreifende_themen()
    with pytest.raises(ValueError):
        K.finde_uebergreifende_themen(fach="SEK1.M", thema="Medienbildung")


def test_finde_uebergreifende_themen_per_kompetenz_kann_leer_sein():
    """Omission on the shipped/fixture record means no theme is tagged
    there -- distinct from an unresolved marker, and never an error."""
    assert K.finde_uebergreifende_themen(kompetenz_id="AT.LP23.SEK1.M.ALPHA.K1.01") == ["Medienbildung"]
    assert K.finde_uebergreifende_themen(kompetenz_id="AT.LP23.SEK1.D.GAMMA.K1.01") == []


def test_finde_uebergreifende_themen_per_fach():
    assert K.finde_uebergreifende_themen(fach="SEK1.M") == ["Medienbildung"]
    assert K.finde_uebergreifende_themen(fach="PRIM.SU") == ["Medienbildung"]


def test_finde_uebergreifende_themen_per_thema_scannt_alle_sechs_shards_ohne_volles_laden():
    """A cheap scan: only meta is read, and it must find the theme in
    every shard that carries it -- here two of six, by design."""
    treffer = K.finde_uebergreifende_themen(thema="Medienbildung")
    assert [t["fach"] for t in treffer] == ["PRIM.SU", "SEK1.M"]
    for t in treffer:
        assert "Medienbildung" in K.finde_uebergreifende_themen(fach=t["fach"])
    assert K.finde_uebergreifende_themen(thema="existiert-nirgendwo") == []


# ---------------------------------------------------------------------------
# finde_differenzierung
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fach,_bindung", SHARDS)
def test_finde_differenzierung_callable_gegen_alle_fixtur_shards(fach, _bindung):
    for k in K.finde_kompetenz(fach):
        ergebnis = K.finde_differenzierung(k["id"])
        assert set(ergebnis) == {
            "achse",
            "niveaus",
            "enrichment_items",
            "vorklasse_stuetzen",
            "docs_material",
        }
        assert isinstance(ergebnis["niveaus"], list)
        assert isinstance(ergebnis["enrichment_items"], list)
        assert isinstance(ergebnis["vorklasse_stuetzen"], list)
        assert isinstance(ergebnis["docs_material"], list)


def test_finde_differenzierung_niveaus_gate_vor_gilt_ab_stufe():
    k1 = K.finde_differenzierung("AT.LP23.SEK1.M.ALPHA.K1.01")
    assert k1["achse"]["niveaus"] == ["Standard", "Standard AHS"]
    assert k1["niveaus"] == []  # K1 is before gilt_ab_stufe: K2

    k2 = K.finde_differenzierung("AT.LP23.SEK1.M.ALPHA.K2.01")
    assert k2["niveaus"] == ["Standard", "Standard AHS"]


def test_finde_differenzierung_lehrplan_generisch_hat_kein_stufen_gate():
    """PRIM.D carries no gilt_ab_stufe -- niveaus are effective from the
    first stufe on, unlike the Sek I axis."""
    ergebnis = K.finde_differenzierung("AT.LP23.PRIM.D.ZETA.SCH1.01")
    assert ergebnis["achse"]["typ"] == "lehrplan_generisch"
    assert ergebnis["niveaus"] == ["grundlegend", "erweitert", "vertiefend"]


def test_finde_differenzierung_enrichment_nur_wenn_achse_es_traegt():
    """SEK1.M's axis carries enrichment_quelle: allenfalls -- its K1.02
    (verbindlich=False) item surfaces as enrichment. SEK1.D's axis has no
    such key at all, so enrichment_items stays [] even though it is the
    same standard_standardplus axis typ."""
    m = K.finde_differenzierung("AT.LP23.SEK1.M.ALPHA.K1.01")
    assert [i["id"] for i in m["enrichment_items"]] == ["AT.LP23.SEK1.M.AB.ALPHA.K1.02"]

    d = K.finde_differenzierung("AT.LP23.SEK1.D.GAMMA.K1.01")
    assert d["achse"]["typ"] == "standard_standardplus"
    assert d["enrichment_items"] == []


def test_finde_differenzierung_gers_subachse_ist_verbatim_metadaten():
    achse = K.finde_differenzierung("AT.LP23.SEK1.E.EPSILON.K1.01")["achse"]
    assert achse["gers"] == {
        "typ": "gers",
        "referenzrahmen": "Gemeinsamer Europäischer Referenzrahmen (Fixtur)",
        "niveaus": ["A1", "A2"],
        "je_stufe_ausgewiesen": False,
    }


def test_finde_differenzierung_vorklasse_stuetzen_ist_exakt_die_rueckwaertsprogression():
    for fach, _b in SHARDS:
        for k in K.finde_kompetenz(fach):
            ergebnis = K.finde_differenzierung(k["id"])
            assert [s["id"] for s in ergebnis["vorklasse_stuetzen"]] == [
                z["id"] for z in K.finde_progression(k["id"], "zurueck")
            ]


def test_finde_differenzierung_vorklasse_stuetzen_mehrere_vorgaenger():
    stuetzen = K.finde_differenzierung("AT.LP23.SEK1.D.GAMMA.K2.01")["vorklasse_stuetzen"]
    assert {s["id"] for s in stuetzen} == {
        "AT.LP23.SEK1.D.GAMMA.K1.01",
        "AT.LP23.SEK1.D.GAMMA.K1.02",
    }
    for s in stuetzen:
        assert s["volltext"] == f"{s['stammsatz']} {s['text']}"


def test_finde_differenzierung_unknown_id_raises():
    with pytest.raises(K.KompetenzNichtGefunden):
        K.finde_differenzierung("AT.LP23.SEK1.M.NICHT.K1.99")


# ---------------------------------------------------------------------------
# finde_typische_fehlvorstellungen -- E9 unimplemented, always []
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fach,_bindung", SHARDS)
def test_finde_typische_fehlvorstellungen_immer_leer(fach, _bindung):
    for k in K.finde_kompetenz(fach):
        assert K.finde_typische_fehlvorstellungen(k["id"]) == []


def test_finde_typische_fehlvorstellungen_unknown_id_gibt_leer_statt_fehler():
    assert K.finde_typische_fehlvorstellungen("AT.LP23.SEK1.M.NICHT.K1.99") == []
