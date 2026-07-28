"""Tests for the frozen AT.LP23 ID scheme (data-pipeline/schema/id_schema.py).

Run:  .venv/bin/python -m pytest data-pipeline/tests -q
  or: .venv/bin/python -m pytest data-pipeline/tests/test_id_schema.py -q

The last test in this file is the integration check that proves the frozen
scheme describes reality: it runs the live parser over the real Mittelschule
XML and asserts every emitted ID parses under the scheme and is globally
unique.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_DATA_PIPELINE = _HERE.parent
sys.path.insert(0, str(_DATA_PIPELINE))
sys.path.insert(0, str(_DATA_PIPELINE / "schema"))

import id_schema as S  # noqa: E402
import parse_lehrplan as P  # noqa: E402

# The parser mirrors tolerated deviations to logging.WARNING; noise here.
logging.getLogger("parse_lehrplan").setLevel(logging.CRITICAL)

MS_XML = _DATA_PIPELINE / "resources" / "mittelschule" / "NOR40271471.xml"


# ---------------------------------------------------------------------------
# 1. The code table itself: unique codes, valid code shape, valid band/fach
# ---------------------------------------------------------------------------


def test_area_code_table_covers_exactly_the_six_shards():
    assert set(S.AREA_CODES) == {
        "SEK1.M", "SEK1.D", "SEK1.E", "PRIM.M", "PRIM.D", "PRIM.SU",
    }


@pytest.mark.parametrize("schluessel", sorted(S.AREA_CODES))
def test_area_codes_unique_within_shard(schluessel):
    codes = list(S.AREA_CODES[schluessel].values())
    assert len(codes) == len(set(codes)), f"duplicate area code within {schluessel}"


@pytest.mark.parametrize(
    "schluessel,name,code",
    [
        (schluessel, name, code)
        for schluessel, tabelle in S.AREA_CODES.items()
        for name, code in tabelle.items()
    ],
)
def test_area_code_matches_code_regex(schluessel, name, code):
    assert S.BEREICH_CODE_RE.match(code), f"{schluessel}/{name!r}: code {code!r} malformed"


@pytest.mark.parametrize("schluessel", sorted(S.AREA_CODES))
def test_area_code_table_key_is_a_valid_band_fach_combination(schluessel):
    band, fach = schluessel.split(".")
    assert band in S.BAENDER
    assert S.ist_gueltige_kombination(band, fach), f"{schluessel} not in BAND_FAECHER scope"


def test_sek1_mathematik_codes_reused_verbatim_from_the_parser():
    """The four already-shipped area codes must never be re-minted."""
    assert S.AREA_CODES["SEK1.M"]["Zahlen und Maße"] == "ZAHLEN"
    assert S.AREA_CODES["SEK1.M"]["Variablen und Funktionen"] == "VARIABLEN"
    assert S.AREA_CODES["SEK1.M"]["Figuren und Körper"] == "FIGUREN"
    assert S.AREA_CODES["SEK1.M"]["Daten und Zufall"] == "DATEN"
    # And match parse_lehrplan.py's own table exactly (not just by value).
    assert S.AREA_CODES["SEK1.M"]["Zahlen und Maße"] == P.SEK1_MATHEMATIK.bereich_slugs["Zahlen und Maße"]
    assert S.AREA_CODES["SEK1.M"]["Variablen und Funktionen"] == P.SEK1_MATHEMATIK.bereich_slugs["Variablen und Funktionen"]
    assert S.AREA_CODES["SEK1.M"]["Figuren und Körper"] == P.SEK1_MATHEMATIK.bereich_slugs["Figuren und Körper"]
    assert S.AREA_CODES["SEK1.M"]["Daten und Zufall"] == P.SEK1_MATHEMATIK.bereich_slugs["Daten und Zufall"]


def test_gzintegrativ_code_reused_verbatim_from_the_parser():
    assert (
        S.AREA_CODES["SEK1.M"][P.GZ_INTEGRATIV_BEREICH_NAME]
        == P.GZ_INTEGRATIV_BEREICH_SLUG
        == "GZINTEGRATIV"
    )


@pytest.mark.parametrize("count,expected", [
    ("PRIM.M", 4),
    ("PRIM.D", 4),
    ("PRIM.SU", 6),
    ("SEK1.M", 5),   # 4 numbered areas + the synthetic GZINTEGRATIV
    ("SEK1.D", 4),   # 3 competence-bearing + 1 structural (Sprachreflexion)
    ("SEK1.E", 4),
])
def test_area_counts_match_findings(count, expected):
    assert len(S.AREA_CODES[count]) == expected


@pytest.mark.parametrize("daz_bereich", [
    "Hören",
    "Sprechen",
    "Linguistische Kompetenzen",
])
def test_sek1_deutsch_excludes_the_daz_lehrplanzusatz_areas(daz_bereich):
    """The DEUTSCH g1 span holds two curricula: the main one, and the
    ``LEHRPLANZUSATZ DEUTSCH ALS ZWEITSPRACHE FÜR ORDENTLICHE SCHÜLERINNEN UND
    SCHÜLER`` at child 515 -- an ``erll`` heading, so g1 segmentation does not
    separate it.  Its areas are out of v1 scope, and two of them (``Lesen``,
    ``Schreiben``) share a name with a main-curriculum area, so folding them in
    would mint a duplicate code under ``SEK1.D`` and trip the ID-collision hard
    fail.  See ``notes/deviations.md`` and ``notes/id-schema.md`` section 4.3."""
    assert daz_bereich not in S.AREA_CODES["SEK1.D"]


def test_sek1_deutsch_lesen_and_schreiben_are_single_entries():
    """The collision this guards against is silent: both names are legitimate
    main-curriculum areas, so a duplicate would look like a correct entry."""
    for name in ("Lesen", "Schreiben"):
        assert list(S.AREA_CODES["SEK1.D"]).count(name) == 1


# ---------------------------------------------------------------------------
# 2. Stufen
# ---------------------------------------------------------------------------


def test_stufen_werte_primary():
    assert S.stufen_werte("PRIM") == ("SCH1", "SCH2", "SCH3", "SCH4")


def test_stufen_werte_sek1():
    assert S.stufen_werte("SEK1") == ("K1", "K2", "K3", "K4")


def test_gs_and_vor_are_not_valid_stufen():
    """V-22 closed: GS1/GS2/VOR are removed from the scheme entirely."""
    for verboten in ("GS1", "GS2", "VOR"):
        with pytest.raises(S.IdSchemaError):
            S.parse_id(f"AT.LP23.PRIM.M.ZAHLENDATEN.{verboten}.01")


# ---------------------------------------------------------------------------
# 3. Round-tripping both grammars through format_*/parse_id
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "band,fach,bereich,stufe,lfd",
    [
        ("SEK1", "M", "ZAHLEN", "K1", 1),
        ("SEK1", "M", "GZINTEGRATIV", "K3", 1),
        ("SEK1", "D", "SPRACHREFLEXION", "K4", 12),
        ("SEK1", "E", "HOEREN", "K2", 99),
        ("PRIM", "M", "ZAHLENDATEN", "SCH1", 0),
        ("PRIM", "D", "RECHTSCHREIBEN", "SCH4", 7),
        ("PRIM", "SU", "GEOGRAFIE", "SCH3", 23),
    ],
)
def test_format_id_round_trips_through_parse_id(band, fach, bereich, stufe, lfd):
    ident = S.format_id(band, fach, bereich, stufe, lfd)
    assert ident == f"AT.LP23.{band}.{fach}.{bereich}.{stufe}.{lfd:02d}"
    parsed = S.parse_id(ident)
    assert isinstance(parsed, S.KompetenzId)
    assert parsed.band == band
    assert parsed.fach == fach
    assert parsed.bereich == bereich
    assert parsed.stufe == stufe
    assert parsed.lfd == lfd
    assert parsed.raw == ident


@pytest.mark.parametrize(
    "band,fach,art,bereich,stufe,lfd",
    [
        ("SEK1", "M", "AB", "ZAHLEN", "K2", 5),
        ("SEK1", "M", "DT", "DATEN", "K1", 1),
        ("SEK1", "D", "AB", "SPRACHREFLEXION", "K1", 1),
        ("PRIM", "SU", "AB", "TECHNIK", "SCH2", 15),
    ],
)
def test_format_item_id_round_trips_through_parse_id(band, fach, art, bereich, stufe, lfd):
    ident = S.format_item_id(band, fach, art, bereich, stufe, lfd)
    assert ident == f"AT.LP23.{band}.{fach}.{art}.{bereich}.{stufe}.{lfd:02d}"
    parsed = S.parse_id(ident)
    assert isinstance(parsed, S.AnwendungsitemId)
    assert parsed.band == band
    assert parsed.fach == fach
    assert parsed.art == art
    assert parsed.bereich == bereich
    assert parsed.stufe == stufe
    assert parsed.lfd == lfd


def test_kompetenz_id_has_seven_segments():
    ident = S.format_id("SEK1", "M", "ZAHLEN", "K1", 1)
    assert len(ident.split(".")) == 7


def test_anwendungsitem_id_has_eight_segments():
    ident = S.format_item_id("SEK1", "M", "AB", "ZAHLEN", "K1", 1)
    assert len(ident.split(".")) == 8


# ---------------------------------------------------------------------------
# 4. Rejection of malformed input
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bogus",
    [
        "",
        "not-an-id-at-all",
        "AT.LP23.SEK1.M.ZAHLEN.K1",          # missing lfd
        "AT.LP23.SEK1.M.ZAHLEN.K1.1",         # lfd not zero-padded to 2
        "AT.LP23.SEK1.M.ZAHLEN.K1.001",       # lfd too long
        "AT.LP23.SEK1.M.zahlen.K1.01",        # lowercase bereich
        "AT.LP23.SEK1.X.ZAHLEN.K1.01",        # unknown fach code
        "AT.LP23.SEK2.M.ZAHLEN.K1.01",        # unknown band
        "AT.LP23.SEK1.M.ZAHLEN.K5.01",        # stufe out of range
        "AT.LP23.SEK1.M.ZAHLEN.SCH1.01",      # stufe prefix wrong for band
        "AT.LP23.PRIM.M.ZAHLENDATEN.K1.01",   # stufe prefix wrong for band (other way)
        "AT.LP23.SEK1.M.XY.ZAHLEN.K1.01",     # unknown art segment (not AB/DT) -> 8 segments but invalid
        "AT.LP23.SEK1.M.AB.ZAHLEN.K1",        # item form missing lfd
        "at.lp23.sek1.m.zahlen.k1.01",        # wrong case entirely
        " AT.LP23.SEK1.M.ZAHLEN.K1.01",       # leading whitespace
        "AT.LP23.SEK1.M.ZAHLEN.K1.01 ",       # trailing whitespace
        "AT.LP24.SEK1.M.ZAHLEN.K1.01",        # wrong scheme year
    ],
)
def test_parse_id_rejects_malformed_input(bogus):
    with pytest.raises(S.IdSchemaError):
        S.parse_id(bogus)


def test_format_id_rejects_unknown_fach():
    with pytest.raises(S.IdSchemaError):
        S.format_id("SEK1", "X", "ZAHLEN", "K1", 1)


def test_format_id_rejects_stufe_not_valid_for_band():
    with pytest.raises(S.IdSchemaError):
        S.format_id("SEK1", "M", "ZAHLEN", "SCH1", 1)


def test_format_item_id_rejects_unknown_art():
    with pytest.raises(S.IdSchemaError):
        S.format_item_id("SEK1", "M", "XY", "ZAHLEN", "K1", 1)


def test_format_id_rejects_out_of_range_lfd():
    with pytest.raises(S.IdSchemaError):
        S.format_id("SEK1", "M", "ZAHLEN", "K1", 100)
    with pytest.raises(S.IdSchemaError):
        S.format_id("SEK1", "M", "ZAHLEN", "K1", -1)


# ---------------------------------------------------------------------------
# 5. validate_ids: duplicates and malformed IDs
# ---------------------------------------------------------------------------


def test_validate_ids_reports_ok_for_clean_unique_set():
    ids = [
        S.format_id("SEK1", "M", "ZAHLEN", "K1", 1),
        S.format_id("SEK1", "M", "ZAHLEN", "K1", 2),
        S.format_item_id("SEK1", "M", "AB", "ZAHLEN", "K1", 1),
    ]
    result = S.validate_ids(ids)
    assert result.ok
    assert result.malformed == ()
    assert result.duplicates == ()
    assert result.total == 3


def test_validate_ids_catches_an_injected_duplicate():
    dup = S.format_id("SEK1", "M", "ZAHLEN", "K1", 1)
    other = S.format_id("SEK1", "M", "ZAHLEN", "K1", 2)
    ids = [dup, other, dup]
    result = S.validate_ids(ids)
    assert not result.ok
    assert result.duplicates == (dup,)
    assert result.malformed == ()


def test_validate_ids_catches_malformed_entries():
    good = S.format_id("SEK1", "M", "ZAHLEN", "K1", 1)
    result = S.validate_ids([good, "garbage", "AT.LP23.SEK1.M.ZAHLEN.K1"])
    assert not result.ok
    assert set(result.malformed) == {"garbage", "AT.LP23.SEK1.M.ZAHLEN.K1"}
    assert result.duplicates == ()


def test_validate_ids_empty_input_is_ok():
    result = S.validate_ids([])
    assert result.ok
    assert result.total == 0


# ---------------------------------------------------------------------------
# 6. The integration check: the live parser output must fit the frozen scheme
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def live_result() -> P.ParseResult:
    if not MS_XML.exists():
        pytest.skip(f"live source not present: {MS_XML}")
    return P.parse_lehrplan(MS_XML, P.SEK1_MATHEMATIK)


def test_live_parser_produces_expected_counts(live_result):
    """Sanity check before trusting the ID assertions below."""
    assert len(live_result.kompetenzen) == 42
    assert len(live_result.anwendungsitems) == 237


def test_every_live_competence_id_parses_under_the_frozen_scheme(live_result):
    for k in live_result.kompetenzen:
        parsed = S.parse_id(k.id)
        assert isinstance(parsed, S.KompetenzId)
        assert parsed.band == "SEK1"
        assert parsed.fach == "M"
        assert parsed.stufe == k.stufe
        assert parsed.bereich in S.alle_bereich_codes("SEK1", "M")


def test_every_live_application_item_id_parses_under_the_frozen_scheme(live_result):
    for item in live_result.anwendungsitems:
        parsed = S.parse_id(item.id)
        assert isinstance(parsed, S.AnwendungsitemId)
        assert parsed.band == "SEK1"
        assert parsed.fach == "M"
        assert parsed.stufe == item.stufe
        assert parsed.art == ("DT" if item.art == "digitale_technologien" else "AB")
        assert parsed.bereich in S.alle_bereich_codes("SEK1", "M")


def test_live_ids_are_globally_unique(live_result):
    """The real integration check: all 42 + 237 = 279 emitted IDs parse and
    are unique together, competences and application items in one pool --
    proving the freeze describes what the parser actually emits."""
    alle_ids = [k.id for k in live_result.kompetenzen] + [a.id for a in live_result.anwendungsitems]
    assert len(alle_ids) == 42 + 237
    result = S.validate_ids(alle_ids)
    assert result.malformed == (), f"malformed live IDs: {result.malformed}"
    assert result.duplicates == (), f"duplicate live IDs: {result.duplicates}"
    assert result.ok
    assert result.total == len(alle_ids)
