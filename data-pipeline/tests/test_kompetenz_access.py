"""Tests for the access layer, ``plugin/scripts/kompetenz.py`` (E4-01, plan
§5, strategy B1).

Unlike every other test module in this directory, this one does **not**
parse or build anything -- it drives the shipped, byte-frozen dataset under
``plugin/data/kompetenzen/`` directly (the same files ``test_shipped_bytes.py``
guards), because the access layer is defined to read exactly that directory
layout at runtime. No gitignored ``data-pipeline/resources/`` involved, so
this runs in a fresh clone and in CI.

Covers: all nine ``finde_*`` functions callable against all six shards: the
five ``anwendungsbereiche_bindung`` values including the two defined-empty
axes (``prosa``/SEK1.E, ``keine``/PRIM.M); the PRIM.SU ``keine_verordnung``
Bildungsstandard case; and that no ``finde_progression`` result ever crosses
a Kompetenzbereich boundary, checked over every competence in all six
shards, not a sample.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "plugin" / "scripts"))

import kompetenz as K  # noqa: E402

#: All six shipped shards, plus their expected ``anwendungsbereiche_bindung``
#: (restated here, not imported, so a registry change makes this file's own
#: expectation visibly wrong -- same convention as test_bindung_contracts.py).
SHARDS = [
    ("SEK1.M", "kompetenz"),
    ("SEK1.D", "bereich"),
    ("SEK1.E", "prosa"),
    ("PRIM.D", "stufe"),
    ("PRIM.M", "keine"),
    ("PRIM.SU", "stufe"),
]

#: Measured competence counts per shard (V-72 / handover §6) -- re-asserted
#: here against the real shipped files, not copied unverified.
ERWARTETE_ANZAHL = {
    "SEK1.M": 42,
    "SEK1.D": 40,
    "SEK1.E": 37,
    "PRIM.D": 40,
    "PRIM.M": 40,
    "PRIM.SU": 48,
}


def test_alle_faecher_konstante_deckt_gleiche_sechs_shards_ab():
    assert set(K.ALLE_FAECHER) == {s for s, _b in SHARDS}


# ---------------------------------------------------------------------------
# finde_kompetenz -- every shard, plus filters
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fach,_bindung", SHARDS)
def test_finde_kompetenz_gegen_alle_sechs_shards(fach, _bindung):
    ergebnisse = K.finde_kompetenz(fach)
    assert len(ergebnisse) == ERWARTETE_ANZAHL[fach], fach
    for k in ergebnisse:
        assert k["fach"] == fach
        # Constraint 3: every returned record must make the full quotation
        # (stammsatz + text) available, not just text.
        assert k["stammsatz"]
        assert k["volltext"].startswith(k["stammsatz"])
        assert k["text"] in k["volltext"]
        assert k["provenienz"]["quelle"] == "RIS Bundesrecht konsolidiert"
        assert k["provenienz"]["nor"]


@pytest.mark.parametrize("fach,_bindung", SHARDS)
def test_finde_kompetenz_stufe_filter_narrows(fach, _bindung):
    alle = K.finde_kompetenz(fach)
    erste_stufe = sorted({k["stufe"] for k in alle})[0]
    gefiltert = K.finde_kompetenz(fach, stufe=erste_stufe)
    assert gefiltert
    assert len(gefiltert) < len(alle)
    assert all(k["stufe"] == erste_stufe for k in gefiltert)


@pytest.mark.parametrize("fach,_bindung", SHARDS)
def test_finde_kompetenz_kompetenzbereich_filter_narrows(fach, _bindung):
    alle = K.finde_kompetenz(fach)
    bereich = alle[0]["bereich_slug"]
    gefiltert = K.finde_kompetenz(fach, kompetenzbereich=bereich)
    assert gefiltert
    assert all(k["bereich_slug"] == bereich for k in gefiltert)
    # Name-based lookup (case-insensitive) must find the same records.
    bereich_name = alle[0]["bereich_name"]
    per_name = K.finde_kompetenz(fach, kompetenzbereich=bereich_name.upper())
    assert {k["id"] for k in per_name} == {k["id"] for k in gefiltert}


@pytest.mark.parametrize("fach,_bindung", SHARDS)
def test_finde_kompetenz_code_lookup_exact(fach, _bindung):
    ziel = K.finde_kompetenz(fach)[0]
    treffer = K.finde_kompetenz(fach, code=ziel["id"])
    assert [k["id"] for k in treffer] == [ziel["id"]]


def test_finde_kompetenz_code_from_wrong_fach_is_empty():
    ziel = K.finde_kompetenz("SEK1.M")[0]
    assert K.finde_kompetenz("PRIM.D", code=ziel["id"]) == []


def test_finde_kompetenz_unknown_fach_raises():
    with pytest.raises(K.UnbekannterFachSchluessel):
        K.finde_kompetenz("SEK1.SU")  # not one of the six shards
    with pytest.raises(K.UnbekannterFachSchluessel):
        K.finde_kompetenz("nonsense")


def test_finde_kompetenz_no_match_returns_empty_list_not_error():
    assert K.finde_kompetenz("SEK1.M", stufe="K1", kompetenzbereich="DATEN", stichworte=["xyzzy-nichts"]) == []


# ---------------------------------------------------------------------------
# finde_kompetenz stichworte -- V-71 exact-token / compound-fallback
# ---------------------------------------------------------------------------


def test_stichwort_index_ist_exakt_bruch_matcht_nicht_bruchtermen_als_schluessel():
    """V-71's measured fact, re-verified directly against the shipped index:
    "bruch" is its own exact key, "bruchtermen" a separate one -- the index
    itself does not fold compounds into their root."""
    shard_dir = K._shard_verzeichnis("SEK1.M")
    index = K._index_laden(shard_dir)
    si = index["stichwort_index"]
    assert "bruch" in si
    assert "bruchtermen" in si
    assert si["bruch"] != si["bruchtermen"]
    assert "variablen.json" in si["bruchtermen"]
    assert "variablen.json" not in si["bruch"]


def test_finde_kompetenz_stichworte_bruch_routes_through_compound_fallback():
    """Even though "bruch" already has an exact index hit, the compound
    "bruchtermen" file (variablen.json) must still be considered -- this is
    the whole point of _stichwort_dateien always unioning exact + substring,
    not falling back only on a miss."""
    abdeckung = K.stichwort_abdeckung("SEK1.M", "Bruch")
    assert abdeckung["exakt"] is True
    assert "variablen.json" in abdeckung["dateien"]
    assert "zahlen.json" in abdeckung["dateien"]
    assert "daten.json" in abdeckung["dateien"]


def test_finde_kompetenz_phase_1_bruch_routes_nur_index_und_kandidaten_parts(monkeypatch):
    """Phase-1's K2 Bruch lookup returns the official descriptions and
    source without a full-shard load.

    V-71 deliberately supersedes the old one-part expectation: the exact
    hit plus compound keys require three candidate parts (daten, variablen,
    zahlen). The post-filter leaves the two actual K2 descriptions from
    zahlen.json. Pin both the complete candidate set and the absence of a
    whole-fach / zusatz load.
    """
    original = K._datei_laden
    geladen: list[str] = []

    def verfolgen(pfad):
        geladen.append(pfad.name)
        return original(pfad)

    monkeypatch.setattr(K, "_datei_laden", verfolgen)
    treffer = K.finde_kompetenz("SEK1.M", stufe="K2", stichworte=["Bruch"])

    assert [k["id"] for k in treffer] == [
        "AT.LP23.SEK1.M.ZAHLEN.K2.02",
        "AT.LP23.SEK1.M.ZAHLEN.K2.03",
    ]
    assert {k["datei"] for k in treffer} == {"zahlen.json"}
    assert {k["provenienz"]["nor"] for k in treffer} == {"NOR40271471"}
    assert geladen.count("index.json") == 1
    assert set(geladen) == {"index.json", "daten.json", "variablen.json", "zahlen.json"}


def test_finde_kompetenz_stichworte_returns_only_records_that_genuinely_mention_it():
    treffer = K.finde_kompetenz("SEK1.M", stichworte=["Bruch"])
    assert treffer
    for k in treffer:
        haystack = f"{k.get('stammsatz','')} {k.get('text','')} {k.get('text_roh','')}".casefold()
        assert "bruch" in haystack


def test_finde_kompetenz_stichworte_true_miss_is_defined_empty():
    assert K.finde_kompetenz("SEK1.M", stichworte=["dieserbegriffexistiertganzsichernicht"]) == []


def test_stichwort_abdeckung_ohne_indexkandidat_behauptet_keine_lehrplan_abwesenheit(monkeypatch):
    original = K._datei_laden
    geladen: list[str] = []

    def verfolgen(pfad):
        geladen.append(pfad.name)
        return original(pfad)

    monkeypatch.setattr(K, "_datei_laden", verfolgen)
    abdeckung = K.stichwort_abdeckung("SEK1.M", "dieserbegriffexistiertganzsichernicht")

    assert abdeckung["suchstatus"] == "keine_indexkandidaten"
    assert abdeckung["kompetenz_ids"] == []
    assert abdeckung["lehrstoff_items"] == []
    assert "keine Aussage" in abdeckung["hinweis"]
    assert geladen == ["index.json"]


@pytest.mark.parametrize(
    ("begriff", "erwartetes_item"),
    [
        (
            "Bruchtermen",
            {
                "id": "AT.LP23.SEK1.M.AB.VARIABLEN.K4.03",
                "text": "allenfalls Umformen von Bruchtermen und Angeben von Bedingungen, die Variablen dabei erfüllen müssen.",
                "stufe": "K4",
                "verbindlich": False,
                "kompetenz_id": "AT.LP23.SEK1.M.VARIABLEN.K4.01",
            },
        ),
        (
            "Zinseszinsen",
            {
                "id": "AT.LP23.SEK1.M.AB.VARIABLEN.K3.21",
                "text": "Aufstellen von Formeln im Zusammenhang mit Zinsen bzw. Zinseszinsen;",
                "stufe": "K3",
                "verbindlich": True,
                "kompetenz_id": "AT.LP23.SEK1.M.VARIABLEN.K3.04",
            },
        ),
    ],
)
def test_stichwort_abdeckung_macht_lehrstoff_only_treffer_sichtbar(begriff, erwartetes_item, monkeypatch):
    """V-73: an empty Kompetenz[] is never evidence that a term is absent
    from the Lehrplan. Both measured terms occur only in official items."""
    original = K._datei_laden
    geladen: list[str] = []

    def verfolgen(pfad):
        geladen.append(pfad.name)
        return original(pfad)

    monkeypatch.setattr(K, "_datei_laden", verfolgen)
    abdeckung = K.stichwort_abdeckung("SEK1.M", begriff)
    assert abdeckung["dateien"] == ["variablen.json"]
    assert abdeckung["exakt"] is True
    assert abdeckung["kompetenz_ids"] == []
    assert abdeckung["anwendungsbereich_ids"] == [erwartetes_item["id"]]
    assert abdeckung["suchstatus"] == "nur_lehrstofftreffer"
    assert abdeckung["lehrstoff_items"] == [erwartetes_item]
    assert geladen == ["index.json", "variablen.json"]
    assert K.finde_kompetenz("SEK1.M", stichworte=[begriff]) == []


# ---------------------------------------------------------------------------
# finde_progression
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fach,_bindung", SHARDS)
def test_finde_progression_callable_both_directions(fach, _bindung):
    for k in K.finde_kompetenz(fach):
        vor = K.finde_progression(k["id"], "vor")
        zurueck = K.finde_progression(k["id"], "zurueck")
        assert isinstance(vor, list)
        assert isinstance(zurueck, list)


@pytest.mark.parametrize("fach,_bindung", SHARDS)
def test_finde_progression_never_crosses_kompetenzbereich(fach, _bindung):
    """The non-negotiable constraint: checked against every competence of
    every shard (not a sample) using the real access-layer function, not
    only the parser's own pre-computed vorlaeufer/folge arrays."""
    verstoesse = []
    for k in K.finde_kompetenz(fach):
        for richtung in ("zurueck", "vor"):
            for ziel in K.finde_progression(k["id"], richtung):
                if ziel["bereich_slug"] != k["bereich_slug"]:
                    verstoesse.append((k["id"], richtung, ziel["id"]))
    assert verstoesse == [], f"{fach}: cross-area progression: {verstoesse[:5]}"


def _assert_progression_antworten(
    ergebnisse, *, bereich_slug: str, stufe: str, nor: str
):
    """Common contract checks for concrete, non-vacuous progression cases."""
    assert ergebnisse
    for kompetenz in ergebnisse:
        assert kompetenz["bereich_slug"] == bereich_slug
        assert kompetenz["stufe"] == stufe
        assert kompetenz["volltext"] == f"{kompetenz['stammsatz']} {kompetenz['text']}"
        assert kompetenz["provenienz"]["nor"] == nor
        assert kompetenz["provenienz"]["quelle"] == "RIS Bundesrecht konsolidiert"


def test_finde_progression_sek1_m_wiederholen_backlink_both_directions():
    """SEK1.M's K2 Zahlen backlink is source-text-triggered.

    The regulation names no competence ID.  The parser resolves the textual
    ``Wiederholen und Festigen`` item positionally, then mirrors that result
    into the competence's progression fields.  Assert the two shipped fields
    agree before exercising the public lookup in both directions.
    """
    k2_id = "AT.LP23.SEK1.M.ZAHLEN.K2.02"
    k2 = K.kompetenz_nach_id(k2_id)
    backlink = next(
        item
        for item in K.finde_anwendungsbereiche(k2_id)
        if item["id"] == "AT.LP23.SEK1.M.AB.ZAHLEN.K2.05"
    )

    # These are source fields, rather than an inference from the IDs used in
    # this test: the item's official text triggers the resolved backlinks.
    assert backlink["kompetenz_id"] == k2_id
    assert backlink["text"].startswith("Wiederholen und Festigen:")
    assert backlink["wiederholung_von"] == k2["vorlaeufer"]

    vorgaenger = K.finde_progression(k2_id, "zurueck")
    assert [k["id"] for k in vorgaenger] == backlink["wiederholung_von"]
    _assert_progression_antworten(
        vorgaenger, bereich_slug=k2["bereich_slug"], stufe="K1", nor="NOR40271471"
    )

    # The reciprocal K1 -> K2 lookup need only contain this K2 competence:
    # one K1 competence can correctly feed multiple K2 competences in an area.
    for vorgaenger_kompetenz in vorgaenger:
        nachfolger = K.finde_progression(vorgaenger_kompetenz["id"], "vor")
        assert k2_id in {k["id"] for k in nachfolger}
        _assert_progression_antworten(
            nachfolger, bereich_slug=k2["bereich_slug"], stufe="K2", nor="NOR40271471"
        )


def test_finde_progression_sek1_d_positional_k1_k2_pair_both_directions():
    """SEK1.D progression is positional, not a guessed ID adjacency.

    Its area-bound official application items contain neither a textual
    Wiederholen marker nor resolved ``wiederholung_von`` links, while the
    shipped competence fields explicitly carry the K1/K2 progression.
    """
    k1_id = "AT.LP23.SEK1.D.LESEN.K1.01"
    k2_id = "AT.LP23.SEK1.D.LESEN.K2.01"
    k1 = K.kompetenz_nach_id(k1_id)
    k2 = K.kompetenz_nach_id(k2_id)

    # Prove the mechanism from shipped fields before testing public results.
    index = K._index_laden(K._shard_verzeichnis("SEK1.D"))
    assert index["meta"]["anwendungsbereiche_bindung"] == "bereich"
    assert k1_id in k2["vorlaeufer"]
    assert k2_id in k1["folge"]
    assert all(
        not item["wiederholung_von"]
        and not item["text"].startswith("Wiederholen und Festigen:")
        for item in K.finde_anwendungsbereiche(k2_id)
    )

    vorgaenger = K.finde_progression(k2_id, "zurueck")
    assert k1_id in {k["id"] for k in vorgaenger}
    _assert_progression_antworten(
        vorgaenger, bereich_slug=k2["bereich_slug"], stufe="K1", nor="NOR40271471"
    )

    nachfolger = K.finde_progression(k1_id, "vor")
    assert k2_id in {k["id"] for k in nachfolger}
    _assert_progression_antworten(
        nachfolger, bereich_slug=k1["bereich_slug"], stufe="K2", nor="NOR40271471"
    )


def test_finde_progression_invalid_richtung_raises():
    ziel = K.finde_kompetenz("SEK1.M")[0]
    with pytest.raises(ValueError):
        K.finde_progression(ziel["id"], "seitwaerts")


def test_finde_progression_unknown_id_raises():
    with pytest.raises(K.KompetenzNichtGefunden):
        K.finde_progression("AT.LP23.SEK1.M.NICHT.K1.99", "vor")


# ---------------------------------------------------------------------------
# finde_anwendungsbereiche -- dispatch on anwendungsbereiche_bindung
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fach,bindung", SHARDS)
def test_finde_anwendungsbereiche_callable_gegen_alle_sechs_shards(fach, bindung):
    for k in K.finde_kompetenz(fach):
        items = K.finde_anwendungsbereiche(k["id"])
        assert isinstance(items, list)


@pytest.mark.parametrize("fach,bindung", [(f, b) for f, b in SHARDS if b in ("prosa", "keine")])
def test_finde_anwendungsbereiche_prosa_und_keine_sind_defined_empty(fach, bindung):
    """SEK1.E (prosa) and PRIM.M (keine): every competence's application
    items must be [] -- data, not a build failure, and not an exception."""
    for k in K.finde_kompetenz(fach):
        assert K.finde_anwendungsbereiche(k["id"]) == []
        assert K.finde_anwendungsbereiche(k["id"], nur_verbindlich=True) == []
        assert K.finde_anwendungsbereiche(k["id"], nur_verbindlich=False) == []


@pytest.mark.parametrize("fach,bindung", [(f, b) for f, b in SHARDS if b not in ("prosa", "keine")])
def test_finde_anwendungsbereiche_non_empty_axes_have_at_least_one_item_somewhere(fach, bindung):
    gesamt = sum(len(K.finde_anwendungsbereiche(k["id"])) for k in K.finde_kompetenz(fach))
    assert gesamt > 0, fach


def test_finde_anwendungsbereiche_nur_verbindlich_split_ist_sek1_m_only():
    """Measured: 32 of 237 SEK1.M items carry allenfalls (verbindlich=False);
    every other shard is all-verbindlich, so nur_verbindlich=False must
    legitimately return [] there -- never an error, never silently implying
    a split that doesn't exist (V-42/V-60)."""
    verbindlich = 0
    nicht_verbindlich = 0
    for k in K.finde_kompetenz("SEK1.M"):
        verbindlich += len(K.finde_anwendungsbereiche(k["id"], nur_verbindlich=True))
        nicht_verbindlich += len(K.finde_anwendungsbereiche(k["id"], nur_verbindlich=False))
    assert nicht_verbindlich == 32, nicht_verbindlich
    # 237 is the section total (V-54): 198 praezisierung + 39
    # digitale_technologien. The latter are never attached to one specific
    # competence at all (V-54: "follow no competence sentence"), so
    # finde_anwendungsbereiche(kompetenz_id) -- which is always scoped to
    # one competence -- correctly never surfaces them; the reachable total
    # here is 198, not 237.
    assert verbindlich + nicht_verbindlich == 198

    for fach, bindung in SHARDS:
        if fach == "SEK1.M":
            continue
        for k in K.finde_kompetenz(fach):
            mit_flag_true = K.finde_anwendungsbereiche(k["id"], nur_verbindlich=True)
            ohne_flag = K.finde_anwendungsbereiche(k["id"])
            mit_flag_false = K.finde_anwendungsbereiche(k["id"], nur_verbindlich=False)
            assert [i["id"] for i in mit_flag_true] == [i["id"] for i in ohne_flag], fach
            assert mit_flag_false == [], fach


def test_finde_anwendungsbereiche_bereich_bindung_shares_block_across_area_and_stufe():
    """SEK1.D (bereich): every competence of the same (area, class year)
    must resolve to the identical block -- items attach to the pair, not to
    one competence exclusively (constraint 6)."""
    kompetenzen = [k for k in K.finde_kompetenz("SEK1.D") if k["bereich_slug"] == "LESEN" and k["stufe"] == "K1"]
    assert len(kompetenzen) >= 1
    ergebnisse = [tuple(i["id"] for i in K.finde_anwendungsbereiche(k["id"])) for k in kompetenzen]
    assert len(set(ergebnisse)) == 1, "all LESEN/K1 competences must see the same block"


def test_finde_anwendungsbereiche_stufe_bindung_shares_block_across_whole_year():
    """PRIM.SU (stufe): items attach to the school year only -- competences
    from *different* areas of the same year must still see the same block."""
    kompetenzen = [k for k in K.finde_kompetenz("PRIM.SU") if k["stufe"] == "SCH1"]
    bereiche = {k["bereich_slug"] for k in kompetenzen}
    assert len(bereiche) > 1, "need >1 area in SCH1 to prove this is stufe-wide, not area-scoped"
    ergebnisse = {tuple(i["id"] for i in K.finde_anwendungsbereiche(k["id"])) for k in kompetenzen}
    assert len(ergebnisse) == 1


def test_finde_anwendungsbereiche_unknown_id_raises():
    with pytest.raises(K.KompetenzNichtGefunden):
        K.finde_anwendungsbereiche("AT.LP23.SEK1.M.NICHT.K1.99")


# ---------------------------------------------------------------------------
# finde_lehrstoff
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fach,_bindung", SHARDS)
def test_finde_lehrstoff_callable_gegen_alle_sechs_shards(fach, _bindung):
    for k in K.finde_kompetenz(fach):
        ergebnis = K.finde_lehrstoff(k["id"])
        assert set(ergebnis) == {"quelle", "items"}
        assert ergebnis["quelle"] in ("aus_anwendungsbereichen", "eigen_ausgewiesen")
        assert isinstance(ergebnis["items"], list)


def test_finde_lehrstoff_prim_m_ist_eigen_ausgewiesen_und_nicht_leer():
    """V-45 (closed): PRIM.M's Lehrstoff IS its competence records -- not a
    gap, not a placeholder. items must be non-empty and must be the full
    quotation (stammsatz + text), never text alone."""
    for k in K.finde_kompetenz("PRIM.M"):
        ergebnis = K.finde_lehrstoff(k["id"])
        assert ergebnis["quelle"] == "eigen_ausgewiesen"
        assert ergebnis["items"] == [k["volltext"]]
        assert k["stammsatz"] in ergebnis["items"][0]


def test_finde_lehrstoff_aus_anwendungsbereichen_matches_finde_anwendungsbereiche_text():
    k = K.finde_kompetenz("SEK1.M")[0]
    ergebnis = K.finde_lehrstoff(k["id"])
    assert ergebnis["quelle"] == "aus_anwendungsbereichen"
    erwartete_texte = [i["text"] for i in K.finde_anwendungsbereiche(k["id"])]
    assert ergebnis["items"] == erwartete_texte


# ---------------------------------------------------------------------------
# finde_bildungsstandard_bezug
# ---------------------------------------------------------------------------


def test_finde_bildungsstandard_bezug_prim_su_ist_defined_empty_ueber_alle_kompetenzen():
    """PRIM.SU is keine_verordnung -- read from meta.bildungsstandard_bezug,
    never a hardcoded "Sachunterricht" special case."""
    for k in K.finde_kompetenz("PRIM.SU"):
        ergebnis = K.finde_bildungsstandard_bezug(k["id"])
        assert ergebnis == {"abgedeckt": False, "grund": "keine BiSt verordnet"}


@pytest.mark.parametrize("fach,_bindung", [(f, b) for f, b in SHARDS if f != "PRIM.SU"])
def test_finde_bildungsstandard_bezug_andere_fuenf_sind_verordnet(fach, _bindung):
    k = K.finde_kompetenz(fach)[0]
    ergebnis = K.finde_bildungsstandard_bezug(k["id"])
    assert ergebnis["abgedeckt"] is True
    assert ergebnis["deskriptoren"] == []


# ---------------------------------------------------------------------------
# finde_uebergreifende_themen
# ---------------------------------------------------------------------------


def test_finde_uebergreifende_themen_erfordert_genau_ein_argument():
    with pytest.raises(ValueError):
        K.finde_uebergreifende_themen()
    with pytest.raises(ValueError):
        K.finde_uebergreifende_themen(fach="SEK1.M", thema="Medienbildung")


@pytest.mark.parametrize("fach,_bindung", SHARDS)
def test_finde_uebergreifende_themen_per_fach_gegen_alle_sechs_shards(fach, _bindung):
    themen = K.finde_uebergreifende_themen(fach=fach)
    assert isinstance(themen, list)
    assert themen  # every shard's subject carries at least one cross-cutting theme


@pytest.mark.parametrize("fach,_bindung", SHARDS)
def test_finde_uebergreifende_themen_per_kompetenz_gegen_alle_sechs_shards(fach, _bindung):
    for k in K.finde_kompetenz(fach):
        themen = K.finde_uebergreifende_themen(kompetenz_id=k["id"])
        assert isinstance(themen, list)
        assert set(themen) <= set(K.finde_uebergreifende_themen(fach=fach))


def test_finde_uebergreifende_themen_per_thema_scannt_alle_sechs_shards():
    treffer = K.finde_uebergreifende_themen(thema="Medienbildung")
    faecher = {t["fach"] for t in treffer}
    assert faecher <= set(K.ALLE_FAECHER)
    assert faecher  # Medienbildung is a common theme, expected to hit >=1 shard
    for t in treffer:
        assert "Medienbildung" in K.finde_uebergreifende_themen(fach=t["fach"])


# ---------------------------------------------------------------------------
# finde_differenzierung
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fach,_bindung", SHARDS)
def test_finde_differenzierung_callable_gegen_alle_sechs_shards(fach, _bindung):
    for k in K.finde_kompetenz(fach):
        ergebnis = K.finde_differenzierung(k["id"])
        assert set(ergebnis) == {
            "achse",
            "niveaus",
            "enrichment_items",
            "vorklasse_stuetzen",
            "docs_material",
        }
        assert isinstance(ergebnis["niveaus"], list) and ergebnis["niveaus"]


def test_finde_differenzierung_achse_ist_subject_correct_ohne_hardcoded_liste():
    erwartet = {
        "SEK1.M": "standard_standardplus",
        "SEK1.D": "standard_standardplus",
        "SEK1.E": "standard_standardplus",
        "PRIM.D": "lehrplan_generisch",
        "PRIM.M": "lehrplan_generisch",
        "PRIM.SU": "lehrplan_generisch",
    }
    for fach, typ in erwartet.items():
        k = K.finde_kompetenz(fach)[0]
        ergebnis = K.finde_differenzierung(k["id"])
        assert ergebnis["achse"]["typ"] == typ, fach


def test_finde_differenzierung_enrichment_nur_sek1_m():
    """V-60: allenfalls-derived enrichment is SEK1.M-only, dispatched on the
    axis's own enrichment_quelle field."""
    hat_enrichment = any(
        K.finde_differenzierung(k["id"])["enrichment_items"] for k in K.finde_kompetenz("SEK1.M")
    )
    assert hat_enrichment
    for fach, _b in SHARDS:
        if fach == "SEK1.M":
            continue
        for k in K.finde_kompetenz(fach):
            assert K.finde_differenzierung(k["id"])["enrichment_items"] == []


def test_finde_differenzierung_gers_axis_present_only_for_sek1_e_and_not_per_stufe():
    k = K.finde_kompetenz("SEK1.E")[0]
    achse = K.finde_differenzierung(k["id"])["achse"]
    assert "gers" in achse
    assert achse["gers"]["je_stufe_ausgewiesen"] is False


# ---------------------------------------------------------------------------
# finde_lernaufgaben -- docs/ only
# ---------------------------------------------------------------------------


def test_finde_lernaufgaben_missing_docs_root_returns_empty_list():
    assert K.finde_lernaufgaben(fach="SEK1.M", docs_root="/pfad/der/nicht/existiert") == []


def test_finde_lernaufgaben_empty_docs_dir_returns_empty_list(tmp_path):
    assert K.finde_lernaufgaben(fach="SEK1.M", docs_root=tmp_path) == []


def test_finde_lernaufgaben_ships_shard_agnostic_default_returns_list():
    """Callable against all six without a docs_root override -- exercises
    the real repo-root docs/ (present, but its only committed file is the
    scaffolding README, which must never itself surface as a Lernaufgabe)."""
    for fach in K.ALLE_FAECHER:
        ergebnis = K.finde_lernaufgaben(fach=fach)
        assert isinstance(ergebnis, list)
        assert all(e["pfad"] != "README.md" for e in ergebnis)


def test_finde_lernaufgaben_folder_convention_and_filters(tmp_path):
    (tmp_path / "mathematik" / "K2").mkdir(parents=True)
    (tmp_path / "mathematik" / "K2" / "bruchrechnen.md").write_text(
        "# Bruchrechnen Übung\ntext", encoding="utf-8"
    )
    (tmp_path / "deutsch").mkdir()
    (tmp_path / "deutsch" / "allgemein.md").write_text("kein Titel-Header", encoding="utf-8")
    (tmp_path / "unbekanntesfach").mkdir()
    (tmp_path / "unbekanntesfach" / "sonstiges.md").write_text("x", encoding="utf-8")
    (tmp_path / ".cache").mkdir()
    (tmp_path / ".cache" / "konvertiert.md").write_text("sollte nie erscheinen", encoding="utf-8")
    (tmp_path / "README.md").write_text("Anleitung", encoding="utf-8")

    alle = K.finde_lernaufgaben(docs_root=tmp_path)
    pfade = {e["pfad"] for e in alle}
    assert pfade == {
        str(Path("mathematik") / "K2" / "bruchrechnen.md"),
        str(Path("deutsch") / "allgemein.md"),
        str(Path("unbekanntesfach") / "sonstiges.md"),
    }
    for e in alle:
        assert e["herkunft"] == "docs"
        assert e["amtlich"] is False

    nur_mathe = K.finde_lernaufgaben(fach="SEK1.M", docs_root=tmp_path)
    assert {e["pfad"] for e in nur_mathe} == {str(Path("mathematik") / "K2" / "bruchrechnen.md")}
    treffer = next(e for e in nur_mathe if e["stufe"] == "K2")
    assert treffer["titel"] == "Bruchrechnen Übung"


# ---------------------------------------------------------------------------
# finde_typische_fehlvorstellungen -- E9 not implemented, always []
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fach,_bindung", SHARDS)
def test_finde_typische_fehlvorstellungen_immer_leer(fach, _bindung):
    for k in K.finde_kompetenz(fach):
        assert K.finde_typische_fehlvorstellungen(k["id"]) == []


def test_finde_typische_fehlvorstellungen_unknown_id_still_returns_empty_not_raise():
    assert K.finde_typische_fehlvorstellungen("AT.LP23.SEK1.M.NICHT.K1.99") == []


# ---------------------------------------------------------------------------
# ID parsing helper -- the module's own frozen-grammar mirror
# ---------------------------------------------------------------------------


def test_parse_id_unterscheidet_die_drei_grammatiken():
    komp = K._parse_id("AT.LP23.SEK1.M.ZAHLEN.K1.01")
    assert komp["art"] is None and komp["bereich"] == "ZAHLEN"

    item = K._parse_id("AT.LP23.SEK1.M.AB.ZAHLEN.K1.01")
    assert item["art"] == "AB" and item["bereich"] == "ZAHLEN"

    frei = K._parse_id("AT.LP23.PRIM.SU.AB.SCH1.01")
    assert frei["art"] == "AB" and frei["bereich"] is None


def test_parse_id_rejects_malformed():
    with pytest.raises(K.KompetenzFehler):
        K._parse_id("nicht-einmal-annaehernd-eine-id")
    with pytest.raises(K.KompetenzFehler):
        K._parse_id("AT.LP23.SEK1.M.ZAHLEN.K1")  # too short
