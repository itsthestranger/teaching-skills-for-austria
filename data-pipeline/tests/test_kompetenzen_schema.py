"""Tests for schema/kompetenzen.schema.json (E3-01).

Run:  .venv/bin/python -m pytest data-pipeline/tests -q

Covers three things:
1. The schema itself is a structurally valid draft 2020-12 schema.
2. The hand-written example (schema/beispiel_kompetenzen.json, real Sek I
   Mathematik content taken from parse_lehrplan.py output) validates against it.
3. Targeted negative cases fail for the right reason, and the E2-16 tolerant-
   enum policy holds: an unknown value in a tolerant position (Anwendungsitem
   'art') must NOT be rejected.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema
import pytest

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "kompetenzen.schema.json"
BEISPIEL_PATH = Path(__file__).resolve().parents[1] / "schema" / "beispiel_kompetenzen.json"
BEISPIEL_PRIM_STUFE_PATH = (
    Path(__file__).resolve().parents[1] / "schema" / "beispiel_kompetenzen_prim_stufe.json"
)
BEISPIEL_SEK1_BEREICH_PATH = (
    Path(__file__).resolve().parents[1] / "schema" / "beispiel_kompetenzen_sek1_bereich.json"
)

#: Every example file shipped under data-pipeline/schema/, discovered by glob
#: rather than hardcoded, so a future added example is picked up automatically
#: by the "every example validates" / "no example mixes two shards" tests.
ALLE_BEISPIEL_PFADE = sorted(
    Path(__file__).resolve().parents[1].joinpath("schema").glob("beispiel_kompetenzen*.json")
)


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def validator(schema: dict) -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(schema)


@pytest.fixture()
def beispiel() -> dict:
    # Fresh copy per test so mutations in one test never leak into another.
    return json.loads(BEISPIEL_PATH.read_text(encoding="utf-8"))


@pytest.fixture()
def beispiel_prim_stufe() -> dict:
    """PRIM.SU shape: bindung: stufe, area-free items, nummer: null areas."""
    return json.loads(BEISPIEL_PRIM_STUFE_PATH.read_text(encoding="utf-8"))


@pytest.fixture()
def beispiel_sek1_bereich() -> dict:
    """SEK1.D shape: bindung: bereich, block carries bereich_name/bereich_slug."""
    return json.loads(BEISPIEL_SEK1_BEREICH_PATH.read_text(encoding="utf-8"))


def _minimal_dokument(*, band: str, fach_code: str, fach_name: str, bindung: str) -> dict:
    """The smallest meta+kompetenzbereiche shape that satisfies the schema's
    required fields, used to exercise the 'prosa' (SEK1.E) and 'keine'
    (PRIM.M) bindung values, for which no example file exists -- those
    subjects carry zero Anwendungsbereiche items by design, so there is no
    novel block shape worth a standalone example file (only the axis value
    itself differs)."""
    stufe = "K1" if band == "SEK1" else "SCH1"
    status = "keine" if bindung == "keine" else "optional_sektion"
    return {
        "meta": {
            "dataset_version": "2026-07-30",
            "band": band,
            "fach": {"code": fach_code, "name": fach_name},
            "differenzierungs_achse": {"typ": "lehrplan_generisch"},
            "anwendungsbereiche_status": status,
            "anwendungsbereiche_bindung": bindung,
            "bildungsstandard_bezug": "verordnet",
            "provenienz": {
                "quelle": "RIS Bundesrecht konsolidiert",
                "kurztitel": f"Lehrplan Beispiel {fach_name}",
                "nor": "NOR40271471",
                "kundmachung": "BGBl. II Nr. 185/2012 idF BGBl. II Nr. 178/2025",
                "anlage": "Anl. 1",
                "teil": "ACHTER TEIL" if band == "SEK1" else "NEUNTER TEIL",
                "stand": "2026-07-30",
            },
        },
        "kompetenzbereiche": [
            {
                "nummer": None,
                "slug": "BEISPIEL",
                "name": "Beispielbereich",
                "kompetenzen": [
                    {
                        "id": f"AT.LP23.{band}.{fach_code}.BEISPIEL.{stufe}.01",
                        "band": band,
                        "fach": fach_code,
                        "bereich_nummer": None,
                        "bereich_name": "Beispielbereich",
                        "stufe": stufe,
                        "ordinal": 0,
                        "stammsatz": "Die Schülerinnen und Schüler können",
                        "text": "ein Beispielsatz für diese Kompetenz formulieren;",
                    }
                ],
            }
        ],
    }


def _first_kompetenz(doc: dict) -> dict:
    return doc["kompetenzbereiche"][0]["kompetenzen"][0]


def _first_anwendungsitem(doc: dict) -> dict:
    return doc["kompetenzbereiche"][0]["kompetenzen"][0]["anwendungsbereiche"][0]


# --------------------------------------------------------------------------
# 1. The schema is a valid draft 2020-12 schema
# --------------------------------------------------------------------------


def test_schema_is_valid_draft_2020_12(schema: dict) -> None:
    jsonschema.Draft202012Validator.check_schema(schema)


def test_schema_declares_draft_2020_12(schema: dict) -> None:
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


# --------------------------------------------------------------------------
# 2. The hand-written example validates
# --------------------------------------------------------------------------


def test_example_validates(validator: jsonschema.Draft202012Validator, beispiel: dict) -> None:
    validator.validate(beispiel)


def test_example_exercises_zusatzkompetenzen(beispiel: dict) -> None:
    assert len(beispiel["zusatzkompetenzen"]) == 2
    for eintrag in beispiel["zusatzkompetenzen"]:
        assert eintrag["bereich_nummer"] is None
        assert eintrag["bereich_name"] == "Integrative Führung von Geometrisches Zeichnen"


def test_example_exercises_digitale_technologien(beispiel: dict) -> None:
    assert len(beispiel["digitale_technologien_vorschlaege"]) == 1
    item = beispiel["digitale_technologien_vorschlaege"][0]
    assert item["art"] == "digitale_technologien"
    assert item["kompetenz_id"] is None


def test_example_exercises_allenfalls(beispiel: dict) -> None:
    items = _first_kompetenz(beispiel)["anwendungsbereiche"]
    assert any(item["verbindlich"] is False for item in items)


def test_example_exercises_abbildung_token(beispiel: dict) -> None:
    item = _first_anwendungsitem(beispiel)
    assert "⟦ABB:" in item["text"]
    assert item["abbildungen"], "record with an ABB token must carry abbildungen metadata"
    eintrag = item["abbildungen"][0]
    assert eintrag["token"] in item["text"]


# --------------------------------------------------------------------------
# 3a. Negative cases: the three hard-required fields and an ID collision-
#     adjacent structural check (malformed stufe / status)
# --------------------------------------------------------------------------


def test_missing_id_fails(validator: jsonschema.Draft202012Validator, beispiel: dict) -> None:
    del _first_kompetenz(beispiel)["id"]
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(beispiel)


def test_missing_stufe_fails(validator: jsonschema.Draft202012Validator, beispiel: dict) -> None:
    del _first_kompetenz(beispiel)["stufe"]
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(beispiel)


def test_missing_text_fails(validator: jsonschema.Draft202012Validator, beispiel: dict) -> None:
    del _first_kompetenz(beispiel)["text"]
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(beispiel)


def test_bad_stufe_gs1_fails(validator: jsonschema.Draft202012Validator, beispiel: dict) -> None:
    """FINDINGS.md V-22: GS1/GS2/VOR are removed entirely, not tolerated."""
    _first_kompetenz(beispiel)["stufe"] = "GS1"
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(beispiel)


def test_bad_anwendungsbereiche_status_fails(
    validator: jsonschema.Draft202012Validator, beispiel: dict
) -> None:
    beispiel["meta"]["anwendungsbereiche_status"] = "irgendwas_unbekanntes"
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(beispiel)


# --------------------------------------------------------------------------
# 3b. anwendungsbereiche_status: 'keine' is the amended third value (V-24)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["optional_sektion", "item_flags", "keine"])
def test_anwendungsbereiche_status_accepts_all_three_values(
    validator: jsonschema.Draft202012Validator, beispiel: dict, status: str
) -> None:
    beispiel["meta"]["anwendungsbereiche_status"] = status
    validator.validate(beispiel)


# --------------------------------------------------------------------------
# 3c. E2-16 tolerant-enum policy: an unknown value in a tolerant position
#     (Anwendungsitem.art) must still validate, never be silently dropped.
# --------------------------------------------------------------------------


def test_unknown_art_value_still_validates(
    validator: jsonschema.Draft202012Validator, beispiel: dict
) -> None:
    item = _first_anwendungsitem(beispiel)
    item["art"] = "eine_zukuenftige_kategorie_die_heute_niemand_kennt"
    validator.validate(beispiel)  # must not raise -- tolerant, not a closed enum


def test_anwendungsitem_theme_fields_validate_when_present(
    validator: jsonschema.Draft202012Validator, beispiel: dict
) -> None:
    item = _first_anwendungsitem(beispiel)
    item["uebergreifende_themen"] = ["Informatische Bildung"]
    item["themen_marker_roh"] = ["4, 99"]
    item["fussnoten_unaufgeloest"] = ["99"]
    validator.validate(beispiel)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("uebergreifende_themen", "Informatische Bildung"),
        ("themen_marker_roh", "4, 99"),
        ("fussnoten_unaufgeloest", "99"),
    ],
)
def test_anwendungsitem_theme_fields_must_be_arrays_when_present(
    validator: jsonschema.Draft202012Validator, beispiel: dict, field: str, value: str
) -> None:
    _first_anwendungsitem(beispiel)[field] = value
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(beispiel)


def test_unknown_prozesse_value_still_validates(
    validator: jsonschema.Draft202012Validator, beispiel: dict
) -> None:
    kompetenz = _first_kompetenz(beispiel)
    kompetenz["prozesse"] = ["ein_noch_nicht_kodifizierter_prozess"]
    validator.validate(beispiel)


# --------------------------------------------------------------------------
# 4. E-P3 / E12-02: coarse Anwendungsbereiche attachment (nullable
#    kompetenz_id, 'bindung', meta.anwendungsbereiche_bloecke, the area-free
#    ID form)
# --------------------------------------------------------------------------


def test_example_exercises_anwendungsbereiche_bloecke_stufe(
    beispiel_prim_stufe: dict,
) -> None:
    block = beispiel_prim_stufe["meta"]["anwendungsbereiche_bloecke"]
    assert set(block) == {"SCH1"}
    sch1 = block["SCH1"]
    assert sch1["bindung"] == "stufe"
    assert len(sch1["items"]) == 2
    for item in sch1["items"]:
        assert item["kompetenz_id"] is None
        assert item["bindung"] == "stufe"
        assert "bereich_name" not in item
        assert "bereich_nummer" not in item


def test_example_stufe_items_use_the_area_free_id_form(beispiel_prim_stufe: dict) -> None:
    """The E-P3 area-free form: AT.LP23.<Band>.<Fach>.<Art>.<Stufe>.<lfd>,
    7 segments, no Bereich -- inventing one would assert a scoping the
    regulation does not make (PRIM.D / PRIM.SU stufe-bound items)."""
    for item in beispiel_prim_stufe["meta"]["anwendungsbereiche_bloecke"]["SCH1"]["items"]:
        assert len(item["id"].split(".")) == 7
        assert item["id"].startswith("AT.LP23.PRIM.SU.AB.SCH1.")


def test_example_kompetenz_bound_items_carry_bindung_kompetenz(beispiel: dict) -> None:
    for item in _first_kompetenz(beispiel)["anwendungsbereiche"]:
        assert item["bindung"] == "kompetenz"
        assert item["kompetenz_id"] is not None


def test_meta_anwendungsbereiche_bloecke_is_optional(
    validator: jsonschema.Draft202012Validator, beispiel: dict
) -> None:
    """Not every shard has coarsely-attached items (only PRIM.D/PRIM.SU/
    SEK1.D do) -- the property must be safely omittable, as it already is
    on the SEK1.M (bindung: kompetenz) example."""
    assert "anwendungsbereiche_bloecke" not in beispiel["meta"]
    validator.validate(beispiel)


def test_bindung_enum_rejects_an_unrecognised_value(
    validator: jsonschema.Draft202012Validator, beispiel: dict
) -> None:
    """Unlike 'art' (tolerant free string), 'bindung' is a closed enum: it
    mirrors parse_lehrplan.py's SubjectSpec.anwendungsbereiche_bindung axis,
    which has exactly five known values, three of which ever appear on an
    item (kompetenz | bereich | stufe -- 'prosa' and 'keine' subjects never
    emit an item at all, so no item ever needs to spell those out)."""
    item = _first_anwendungsitem(beispiel)
    item["bindung"] = "irgendwas_unbekanntes"
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(beispiel)


@pytest.mark.parametrize("bindung", ["kompetenz", "bereich", "stufe"])
def test_bindung_enum_accepts_all_three_item_level_values(
    validator: jsonschema.Draft202012Validator, beispiel: dict, bindung: str
) -> None:
    item = _first_anwendungsitem(beispiel)
    item["bindung"] = bindung
    validator.validate(beispiel)


def test_bereich_bound_item_with_null_kompetenz_id_validates(
    validator: jsonschema.Draft202012Validator, beispiel: dict
) -> None:
    """SEK1.D shape: an item attached to (bereich, stufe), not to one
    competence -- kompetenz_id null, bereich_name/bereich_nummer set,
    bindung: 'bereich'. Constructed inline purely to exercise the item-level
    schema shape (the block-level shape is exercised by
    beispiel_kompetenzen_sek1_bereich.json instead)."""
    item = copy.deepcopy(_first_anwendungsitem(beispiel))
    item["id"] = "AT.LP23.SEK1.D.AB.HOERENSPRECHEN.K1.01"
    item["band"] = "SEK1"
    item["fach"] = "D"
    item["bereich_nummer"] = 1
    item["bereich_name"] = "Zuhören und Sprechen"
    item["bindung"] = "bereich"
    item["kompetenz_id"] = None
    beispiel["kompetenzbereiche"][0]["kompetenzen"][0]["anwendungsbereiche"].append(item)
    validator.validate(beispiel)


def test_item_id_pattern_accepts_the_area_free_form(
    validator: jsonschema.Draft202012Validator, beispiel_prim_stufe: dict
) -> None:
    item = copy.deepcopy(
        beispiel_prim_stufe["meta"]["anwendungsbereiche_bloecke"]["SCH1"]["items"][0]
    )
    item["id"] = "AT.LP23.PRIM.D.AB.SCH3.07"
    item["band"] = "PRIM"
    item["fach"] = "D"
    item["stufe"] = "SCH3"
    beispiel_prim_stufe["meta"]["anwendungsbereiche_bloecke"]["SCH1"]["items"].append(item)
    validator.validate(beispiel_prim_stufe)


def test_item_id_pattern_rejects_a_malformed_area_free_id(
    validator: jsonschema.Draft202012Validator, beispiel_prim_stufe: dict
) -> None:
    block = beispiel_prim_stufe["meta"]["anwendungsbereiche_bloecke"]["SCH1"]
    block["items"][0]["id"] = "AT.LP23.PRIM.SU.AB.SCH1"  # missing lfd
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(beispiel_prim_stufe)


# --------------------------------------------------------------------------
# 5. E12-02: kompetenzbereich.nummer nullable (V-62 regression)
# --------------------------------------------------------------------------


def test_kompetenzbereich_nummer_null_validates(
    validator: jsonschema.Draft202012Validator, beispiel: dict
) -> None:
    """V-62: measured against the live documents, only SEK1.M numbers its
    Kompetenzbereiche -- every other subject's area heading is unnumbered,
    so 'nummer: null' must validate, not be rejected as 'not of type
    integer'."""
    beispiel["kompetenzbereiche"][0]["nummer"] = None
    validator.validate(beispiel)


def test_kompetenzbereich_missing_nummer_still_fails(
    validator: jsonschema.Draft202012Validator, beispiel: dict
) -> None:
    """'nummer' stays required -- it must be present and explicitly null,
    not omitted."""
    del beispiel["kompetenzbereiche"][0]["nummer"]
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(beispiel)


def test_example_prim_stufe_areas_are_all_unnumbered(beispiel_prim_stufe: dict) -> None:
    for bereich in beispiel_prim_stufe["kompetenzbereiche"]:
        assert bereich["nummer"] is None


def test_example_sek1_bereich_areas_are_all_unnumbered(beispiel_sek1_bereich: dict) -> None:
    for bereich in beispiel_sek1_bereich["kompetenzbereiche"]:
        assert bereich["nummer"] is None


# --------------------------------------------------------------------------
# 6. E12-02: anwendungsbereiche_block_eintrag if/then -- bereich requires its
#    own area, stufe must not carry one
# --------------------------------------------------------------------------


def test_bereich_block_missing_bereich_name_and_slug_fails(
    validator: jsonschema.Draft202012Validator, beispiel_sek1_bereich: dict
) -> None:
    block = beispiel_sek1_bereich["meta"]["anwendungsbereiche_bloecke"]["K1"]
    del block["bereich_name"]
    del block["bereich_slug"]
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(beispiel_sek1_bereich)


def test_bereich_block_missing_only_bereich_name_fails(
    validator: jsonschema.Draft202012Validator, beispiel_sek1_bereich: dict
) -> None:
    del beispiel_sek1_bereich["meta"]["anwendungsbereiche_bloecke"]["K1"]["bereich_name"]
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(beispiel_sek1_bereich)


def test_stufe_block_carrying_bereich_name_fails(
    validator: jsonschema.Draft202012Validator, beispiel_prim_stufe: dict
) -> None:
    """A stufe-bound block must not carry an area -- attaching a year-bound
    block to an area is exactly the misattribution this design prevents."""
    beispiel_prim_stufe["meta"]["anwendungsbereiche_bloecke"]["SCH1"]["bereich_name"] = (
        "Sozialwissenschaftlicher Kompetenzbereich"
    )
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(beispiel_prim_stufe)


def test_stufe_block_carrying_bereich_slug_fails(
    validator: jsonschema.Draft202012Validator, beispiel_prim_stufe: dict
) -> None:
    beispiel_prim_stufe["meta"]["anwendungsbereiche_bloecke"]["SCH1"]["bereich_slug"] = (
        "SOZIALWISS"
    )
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(beispiel_prim_stufe)


def test_stufe_block_with_explicit_null_bereich_fields_validates(
    validator: jsonschema.Draft202012Validator, beispiel_prim_stufe: dict
) -> None:
    """'must be absent or null' -- both are legal, not just omission."""
    beispiel_prim_stufe["meta"]["anwendungsbereiche_bloecke"]["SCH1"]["bereich_name"] = None
    beispiel_prim_stufe["meta"]["anwendungsbereiche_bloecke"]["SCH1"]["bereich_slug"] = None
    validator.validate(beispiel_prim_stufe)


def test_bereich_block_validates_with_its_area_fields(
    validator: jsonschema.Draft202012Validator, beispiel_sek1_bereich: dict
) -> None:
    validator.validate(beispiel_sek1_bereich)


# --------------------------------------------------------------------------
# 7. E12-02/E12-16: meta.anwendungsbereiche_bindung -- five-value enum,
#    required since E12-16 (build_dataset.py has emitted it since E12-11)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("bindung", ["kompetenz", "bereich", "stufe", "prosa", "keine"])
def test_meta_anwendungsbereiche_bindung_accepts_all_five_values(
    validator: jsonschema.Draft202012Validator, beispiel: dict, bindung: str
) -> None:
    beispiel["meta"]["anwendungsbereiche_bindung"] = bindung
    validator.validate(beispiel)


def test_meta_anwendungsbereiche_bindung_rejects_an_unknown_value(
    validator: jsonschema.Draft202012Validator, beispiel: dict
) -> None:
    beispiel["meta"]["anwendungsbereiche_bindung"] = "irgendwas_unbekanntes"
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(beispiel)


def test_meta_anwendungsbereiche_bindung_is_required(
    validator: jsonschema.Draft202012Validator, beispiel: dict
) -> None:
    """E12-16: promoted to required now that build_dataset.py emits it
    (E12-11) and all six shipped shards carry it -- omitting it must fail."""
    del beispiel["meta"]["anwendungsbereiche_bindung"]
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(beispiel)


def test_meta_bildungsstandard_bezug_accepts_both_values(
    validator: jsonschema.Draft202012Validator, beispiel: dict
) -> None:
    for wert in ("verordnet", "keine_verordnung"):
        beispiel["meta"]["bildungsstandard_bezug"] = wert
        validator.validate(beispiel)


def test_meta_bildungsstandard_bezug_rejects_an_unknown_value(
    validator: jsonschema.Draft202012Validator, beispiel: dict
) -> None:
    beispiel["meta"]["bildungsstandard_bezug"] = "irgendwas_unbekanntes"
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(beispiel)


def test_meta_bildungsstandard_bezug_is_required(
    validator: jsonschema.Draft202012Validator, beispiel: dict
) -> None:
    """E12-16: promoted to required now that build_dataset.py emits it
    (E12-11) and all six shipped shards carry it -- omitting it must fail."""
    del beispiel["meta"]["bildungsstandard_bezug"]
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(beispiel)


# --------------------------------------------------------------------------
# 8. E12-02/E12-16: kompetenz.stammsatz -- required since E12-16, holds the
#    verbatim competence stem
# --------------------------------------------------------------------------


def test_kompetenz_stammsatz_validates_when_present(
    validator: jsonschema.Draft202012Validator, beispiel: dict
) -> None:
    _first_kompetenz(beispiel)["stammsatz"] = (
        "Die Schülerinnen und Schüler können, wenn sehr langsam, klar und "
        "deutlich in Standardsprache gesprochen wird,"
    )
    validator.validate(beispiel)


def test_kompetenz_stammsatz_is_required(
    validator: jsonschema.Draft202012Validator, beispiel: dict
) -> None:
    """E12-16: promoted to required now that the parser captures it
    (E12-06) and build_dataset.py emits it (E12-11), so all 247 competence
    records across the six shipped shards carry it -- omitting it must
    fail."""
    del _first_kompetenz(beispiel)["stammsatz"]
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(beispiel)


def test_kompetenz_stammsatz_must_be_a_string(
    validator: jsonschema.Draft202012Validator, beispiel: dict
) -> None:
    _first_kompetenz(beispiel)["stammsatz"] = 123
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(beispiel)


# --------------------------------------------------------------------------
# 9. E12-02: one document per bindung value (all five), plus every shipped
#    example file
# --------------------------------------------------------------------------


def test_bindung_kompetenz_document_validates(
    validator: jsonschema.Draft202012Validator, beispiel: dict
) -> None:
    assert beispiel["meta"].get("lehrstoff_quelle") == "aus_anwendungsbereichen"
    validator.validate(beispiel)


def test_bindung_bereich_document_validates(
    validator: jsonschema.Draft202012Validator, beispiel_sek1_bereich: dict
) -> None:
    assert beispiel_sek1_bereich["meta"]["anwendungsbereiche_bindung"] == "bereich"
    validator.validate(beispiel_sek1_bereich)


def test_bindung_stufe_document_validates(
    validator: jsonschema.Draft202012Validator, beispiel_prim_stufe: dict
) -> None:
    assert beispiel_prim_stufe["meta"]["anwendungsbereiche_bindung"] == "stufe"
    validator.validate(beispiel_prim_stufe)


def test_bindung_prosa_document_validates(
    validator: jsonschema.Draft202012Validator,
) -> None:
    """SEK1.E: a heading followed by prose, zero application items."""
    doc = _minimal_dokument(
        band="SEK1", fach_code="E", fach_name="(Erste) Lebende Fremdsprache", bindung="prosa"
    )
    validator.validate(doc)


def test_bindung_keine_document_validates(
    validator: jsonschema.Draft202012Validator,
) -> None:
    """PRIM.M: no Anwendungsbereiche section at all."""
    doc = _minimal_dokument(band="PRIM", fach_code="M", fach_name="Mathematik", bindung="keine")
    validator.validate(doc)


@pytest.mark.parametrize("pfad", ALLE_BEISPIEL_PFADE, ids=lambda p: p.name)
def test_every_example_file_validates(
    validator: jsonschema.Draft202012Validator, pfad: Path
) -> None:
    doc = json.loads(pfad.read_text(encoding="utf-8"))
    validator.validate(doc)


def _bands_and_fachs(doc: dict) -> set[tuple[str, str]]:
    """Every (band, fach) pair mentioned anywhere in the document -- at meta
    level and on every nested record that carries its own band/fach copy."""
    gefunden: set[tuple[str, str]] = set()
    meta_band = doc["meta"]["band"]
    meta_fach = doc["meta"]["fach"]["code"]
    gefunden.add((meta_band, meta_fach))

    def _besuche(knoten):
        if isinstance(knoten, dict):
            if "band" in knoten and "fach" in knoten:
                band, fach = knoten["band"], knoten["fach"]
                if isinstance(band, str) and isinstance(fach, str):
                    gefunden.add((band, fach))
            for wert in knoten.values():
                _besuche(wert)
        elif isinstance(knoten, list):
            for eintrag in knoten:
                _besuche(eintrag)

    _besuche(doc)
    return gefunden


@pytest.mark.parametrize("pfad", ALLE_BEISPIEL_PFADE, ids=lambda p: p.name)
def test_no_example_file_mixes_two_shards(pfad: Path) -> None:
    doc = json.loads(pfad.read_text(encoding="utf-8"))
    paare = _bands_and_fachs(doc)
    assert len(paare) == 1, (
        f"{pfad.name} mixes more than one (band, fach) shard: {paare}"
    )


def test_at_least_two_dedicated_example_files_exist() -> None:
    """Guards against silently deleting the prim_stufe / sek1_bereich
    example files this task added -- 'every example validates' would
    otherwise pass vacuously on just the original SEK1.M file."""
    namen = {p.name for p in ALLE_BEISPIEL_PFADE}
    assert "beispiel_kompetenzen_prim_stufe.json" in namen
    assert "beispiel_kompetenzen_sek1_bereich.json" in namen


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))


# ---------------------------------------------------------------------------
# Verbatim guarantee
#
# The example is the reference for what a built shard looks like, so its quoted
# regulation text must be byte-identical to what the parser reads out of the
# RIS XML.  An earlier revision had umlauts ASCII-folded ("natuerliche" for
# "natürliche", "Zahlen und Masse" for "Zahlen und Maße") -- the ASCII rule
# covers code identifiers and JSON keys, never quoted regulation text.  That is
# the product's core legal promise, so it is enforced here rather than trusted.
# ---------------------------------------------------------------------------

def _live_records():
    """Parse the real Mittelschule XML and index every record by ID."""
    import sys

    pipeline = Path(__file__).resolve().parents[1]
    if str(pipeline) not in sys.path:
        sys.path.insert(0, str(pipeline))
    import parse_lehrplan as P

    quelle = pipeline / "resources" / "mittelschule" / "NOR40271471.xml"
    if not quelle.exists():
        pytest.skip("RIS resources not fetched; verbatim check needs the real XML")
    ergebnis = P.parse_lehrplan(str(quelle), P.SUBJECT_SPECS["SEK1.M"])
    records = {k.id: k for k in ergebnis.kompetenzen}
    records.update({a.id: a for a in ergebnis.anwendungsitems})
    bereiche = {b.slug: b.name for b in ergebnis.bereiche}
    return records, bereiche


def _example_records(beispiel):
    """Every record in the example that carries an ID, flattened."""
    for bereich in beispiel["kompetenzbereiche"]:
        for komp in bereich.get("kompetenzen", []):
            yield komp
            yield from komp.get("anwendungsbereiche", [])
    yield from beispiel.get("zusatzkompetenzen", [])
    yield from beispiel.get("digitale_technologien_vorschlaege", [])


def test_example_text_is_verbatim_ris_text(beispiel):
    records, _ = _live_records()
    geprueft = 0
    for node in _example_records(beispiel):
        quelle = records.get(node.get("id"))
        if quelle is None:
            continue
        assert node["text"] == quelle.text, (
            f"{node['id']}: example text is not verbatim RIS text"
        )
        if "text_roh" in node:
            assert node["text_roh"] == quelle.text_roh, (
                f"{node['id']}: example text_roh is not verbatim"
            )
        geprueft += 1
    assert geprueft >= 5, f"verbatim check only covered {geprueft} records"


def test_example_area_names_are_verbatim_ris_names(beispiel):
    _, bereiche = _live_records()
    for bereich in beispiel["kompetenzbereiche"]:
        erwartet = bereiche.get(bereich.get("slug"))
        if erwartet is None:
            continue
        assert bereich["name"] == erwartet, (
            f"{bereich['slug']}: area name is not the verbatim RIS name"
        )


def test_example_keeps_the_umlauts_that_were_once_folded(beispiel):
    """Regression guard naming the exact strings that were wrong before."""
    roh = BEISPIEL_PATH.read_text(encoding="utf-8")
    for erwartet, verboten in [
        ("Zahlen und Maße", "Zahlen und Masse"),
        ("Figuren und Körper", "Figuren und Koerper"),
        ("natürliche", "natuerliche"),
        ("Fällen", "Faellen"),
        ("römischer", "roemischer"),
        ("Überprüfen", "Ueberpruefen"),
        ("Lösungen", "Loesungen"),
        ("Schrägrisse", "Schraegrisse"),
        ("Integrative Führung", "Integrative Fuehrung"),
    ]:
        assert erwartet in roh, f"expected verbatim {erwartet!r} in the example"
        assert verboten not in roh, f"ASCII-folded {verboten!r} is back in the example"
