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


def test_unknown_prozesse_value_still_validates(
    validator: jsonschema.Draft202012Validator, beispiel: dict
) -> None:
    kompetenz = _first_kompetenz(beispiel)
    kompetenz["prozesse"] = ["ein_noch_nicht_kodifizierter_prozess"]
    validator.validate(beispiel)


# --------------------------------------------------------------------------
# 4. E-P3: coarse Anwendungsbereiche attachment (nullable kompetenz_id,
#    'bindung', meta.anwendungsbereiche_je_stufe, the area-free ID form)
# --------------------------------------------------------------------------


def test_example_exercises_anwendungsbereiche_je_stufe(beispiel: dict) -> None:
    block = beispiel["meta"]["anwendungsbereiche_je_stufe"]
    assert set(block) == {"SCH1"}
    sch1 = block["SCH1"]
    assert sch1["bindung"] == "stufe"
    assert len(sch1["items"]) == 2
    for item in sch1["items"]:
        assert item["kompetenz_id"] is None
        assert item["bindung"] == "stufe"
        assert "bereich_name" not in item
        assert "bereich_nummer" not in item


def test_example_stufe_items_use_the_area_free_id_form(beispiel: dict) -> None:
    """The E-P3 area-free form: AT.LP23.<Band>.<Fach>.<Art>.<Stufe>.<lfd>,
    7 segments, no Bereich -- inventing one would assert a scoping the
    regulation does not make (PRIM.D / PRIM.SU stufe-bound items)."""
    for item in beispiel["meta"]["anwendungsbereiche_je_stufe"]["SCH1"]["items"]:
        assert len(item["id"].split(".")) == 7
        assert item["id"].startswith("AT.LP23.PRIM.SU.AB.SCH1.")


def test_example_kompetenz_bound_items_carry_bindung_kompetenz(beispiel: dict) -> None:
    for item in _first_kompetenz(beispiel)["anwendungsbereiche"]:
        assert item["bindung"] == "kompetenz"
        assert item["kompetenz_id"] is not None


def test_meta_anwendungsbereiche_je_stufe_is_optional(
    validator: jsonschema.Draft202012Validator, beispiel: dict
) -> None:
    """Not every shard has bindung: stufe items (only PRIM.D/PRIM.SU do) --
    the property must be safely omittable."""
    del beispiel["meta"]["anwendungsbereiche_je_stufe"]
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
    bindung: 'bereich'. Constructed inline (no live SEK1.D fixture exists
    yet -- that shard is a later task) purely to exercise the schema shape."""
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
    validator: jsonschema.Draft202012Validator, beispiel: dict
) -> None:
    item = copy.deepcopy(
        beispiel["meta"]["anwendungsbereiche_je_stufe"]["SCH1"]["items"][0]
    )
    item["id"] = "AT.LP23.PRIM.D.AB.SCH3.07"
    item["band"] = "PRIM"
    item["fach"] = "D"
    item["stufe"] = "SCH3"
    beispiel["meta"]["anwendungsbereiche_je_stufe"]["SCH1"]["items"].append(item)
    validator.validate(beispiel)


def test_item_id_pattern_rejects_a_malformed_area_free_id(
    validator: jsonschema.Draft202012Validator, beispiel: dict
) -> None:
    item = _first_anwendungsitem(beispiel)
    item["id"] = "AT.LP23.PRIM.SU.AB.SCH1"  # missing lfd, even for the area-free shape
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(beispiel)


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
