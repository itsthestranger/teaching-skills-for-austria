"""Tests for build_dataset.py (E3-04 / E3-03 / E3-07).

Run:  .venv/bin/python -m pytest data-pipeline/tests -q

Builds the real Sek I Mathematik shard parts from the live NOR40271471.xml
(skipped if that resource is not fetched) and checks the G1-gate conditions:
per-part schema validity, exact record counts recombined across all parts,
global ID uniqueness under the frozen scheme, byte-identical verbatim text
(including the text_roh omission contract), and that digitale_technologien
items are reachable from nowhere but zusatz.json's top-level array.
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
import id_schema as S  # noqa: E402
import parse_lehrplan as P  # noqa: E402

# The parser mirrors tolerated deviations to logging.WARNING; noise here.
logging.getLogger("parse_lehrplan").setLevel(logging.CRITICAL)
logging.getLogger("build_dataset").setLevel(logging.CRITICAL)

MS_XML = _DATA_PIPELINE / "resources" / "mittelschule" / "NOR40271471.xml"
MANIFEST = _DATA_PIPELINE / "resources" / "manifest.json"
SCHEMA_PATH = _DATA_PIPELINE / "schema" / "kompetenzen.schema.json"

pytestmark = pytest.mark.skipif(
    not MS_XML.exists(), reason="RIS resources not fetched; build_dataset tests need the real XML"
)


@pytest.fixture(scope="module")
def parse_result() -> P.ParseResult:
    return P.parse_lehrplan(MS_XML, P.SEK1_MATHEMATIK)


@pytest.fixture(scope="module")
def manifest() -> dict:
    return B.load_manifest(MANIFEST)


@pytest.fixture(scope="module")
def dateien_meta(parse_result: P.ParseResult, manifest: dict) -> dict[str, dict]:
    return B.build_parts(parse_result, P.SEK1_MATHEMATIK, manifest, modus="meta")


@pytest.fixture(scope="module")
def dateien_je_datensatz(parse_result: P.ParseResult, manifest: dict) -> dict[str, dict]:
    return B.build_parts(parse_result, P.SEK1_MATHEMATIK, manifest, modus="je_datensatz")


@pytest.fixture(scope="module")
def combined(dateien_meta: dict[str, dict]) -> dict:
    return B.combine_parts(dateien_meta)


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def validator(schema: dict) -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(schema)


def _all_kompetenzen(shard: dict):
    for bereich in shard["kompetenzbereiche"]:
        yield from bereich["kompetenzen"]
    yield from shard.get("zusatzkompetenzen", [])


def _all_anwendungsitems(shard: dict):
    for komp in _all_kompetenzen(shard):
        yield from komp.get("anwendungsbereiche", [])
    yield from shard.get("digitale_technologien_vorschlaege", [])


def _all_ids(shard: dict):
    for bereich in shard["kompetenzbereiche"]:
        for komp in bereich["kompetenzen"]:
            yield komp["id"]
            for item in komp.get("anwendungsbereiche", []):
                yield item["id"]
    for komp in shard.get("zusatzkompetenzen", []):
        yield komp["id"]
    for item in shard.get("digitale_technologien_vorschlaege", []):
        yield item["id"]


BEREICH_DATEIEN = ("zahlen.json", "variablen.json", "figuren.json", "daten.json")
ALLE_DATEIEN = BEREICH_DATEIEN + ("zusatz.json",)


# --------------------------------------------------------------------------
# Layout: exactly the expected part files
# --------------------------------------------------------------------------


def test_build_parts_produces_exactly_the_expected_files(dateien_meta: dict[str, dict]) -> None:
    assert set(dateien_meta) == set(ALLE_DATEIEN)


# --------------------------------------------------------------------------
# Schema validity: every part independently, including zusatz.json
# --------------------------------------------------------------------------


@pytest.mark.parametrize("dateiname", ALLE_DATEIEN)
def test_each_part_validates_against_schema_independently(
    validator: jsonschema.Draft202012Validator, dateien_meta: dict[str, dict], dateiname: str
) -> None:
    validator.validate(dateien_meta[dateiname])


@pytest.mark.parametrize("dateiname", ALLE_DATEIEN)
def test_each_je_datensatz_part_also_validates(
    validator: jsonschema.Draft202012Validator, dateien_je_datensatz: dict[str, dict], dateiname: str
) -> None:
    validator.validate(dateien_je_datensatz[dateiname])


def test_zusatz_json_has_empty_kompetenzbereiche(dateien_meta: dict[str, dict]) -> None:
    assert dateien_meta["zusatz.json"]["kompetenzbereiche"] == []


def test_each_bereich_part_has_exactly_one_kompetenzbereich(dateien_meta: dict[str, dict]) -> None:
    for dateiname in BEREICH_DATEIEN:
        assert len(dateien_meta[dateiname]["kompetenzbereiche"]) == 1


# --------------------------------------------------------------------------
# Recombination: the union of all parts reproduces the complete dataset
# --------------------------------------------------------------------------


def test_recombination_reproduces_exact_counts(combined: dict) -> None:
    in_bereichen = sum(len(b["kompetenzen"]) for b in combined["kompetenzbereiche"])
    zusatz = len(combined["zusatzkompetenzen"])
    nested_items = sum(
        len(k.get("anwendungsbereiche", []))
        for b in combined["kompetenzbereiche"]
        for k in b["kompetenzen"]
    )
    digital = len(combined["digitale_technologien_vorschlaege"])

    assert len(combined["kompetenzbereiche"]) == 4
    assert in_bereichen == 40
    assert zusatz == 2
    assert in_bereichen + zusatz == 42
    assert nested_items == 198
    assert digital == 39
    assert nested_items + digital == 237

    allenfalls = sum(1 for item in _all_anwendungsitems(combined) if item["verbindlich"] is False)
    assert allenfalls == 32
    verlinkt = sum(1 for item in _all_anwendungsitems(combined) if item["wiederholung_von"])
    assert verlinkt == 16


def test_recombination_has_no_duplicate_or_missing_records(
    parse_result: P.ParseResult, dateien_meta: dict[str, dict]
) -> None:
    """No record present in two parts, none missing from all."""
    erwartete_ids = {k.id for k in parse_result.kompetenzen} | {a.id for a in parse_result.anwendungsitems}

    gefunden: dict[str, list[str]] = {}
    for dateiname, doc in dateien_meta.items():
        for ident in _all_ids(doc):
            gefunden.setdefault(ident, []).append(dateiname)

    gefundene_ids = set(gefunden)
    assert gefundene_ids == erwartete_ids, (
        f"missing={erwartete_ids - gefundene_ids!r} extra={gefundene_ids - erwartete_ids!r}"
    )
    doppelt = {ident: dateien for ident, dateien in gefunden.items() if len(dateien) > 1}
    assert not doppelt, f"records present in more than one part: {doppelt!r}"


def test_recombination_matches_combine_parts_helper(combined: dict, dateien_meta: dict[str, dict]) -> None:
    ids_combined = set(_all_ids(combined))
    ids_over_parts = {ident for doc in dateien_meta.values() for ident in _all_ids(doc)}
    assert ids_combined == ids_over_parts


# --------------------------------------------------------------------------
# ID scheme: every ID parses under the frozen scheme and is globally unique
# --------------------------------------------------------------------------


def test_every_id_parses_under_frozen_scheme(combined: dict) -> None:
    for ident in _all_ids(combined):
        S.parse_id(ident)  # raises IdSchemaError on malformed input


def test_every_id_is_globally_unique_across_all_parts(dateien_meta: dict[str, dict]) -> None:
    ids = [ident for doc in dateien_meta.values() for ident in _all_ids(doc)]
    assert len(ids) == len(set(ids)), "duplicate IDs across the built shard parts"


def test_id_validation_reports_ok(combined: dict) -> None:
    result = S.validate_ids(list(_all_ids(combined)))
    assert result.ok, f"malformed={result.malformed!r} duplicates={result.duplicates!r}"


# --------------------------------------------------------------------------
# text_roh omission contract: absent means identical to text
# --------------------------------------------------------------------------


def test_text_roh_omitted_iff_identical_to_text(parse_result: P.ParseResult, combined: dict) -> None:
    by_id = {k.id: k for k in parse_result.kompetenzen}
    by_id.update({a.id: a for a in parse_result.anwendungsitems})

    mit_feld = 0
    ohne_feld = 0
    for node in list(_all_kompetenzen(combined)) + list(_all_anwendungsitems(combined)):
        quelle = by_id[node["id"]]
        if "text_roh" in node:
            mit_feld += 1
            assert node["text_roh"] != node["text"], (
                f"{node['id']}: text_roh present but identical to text -- should have been omitted"
            )
            assert node["text_roh"].encode("utf-8") == quelle.text_roh.encode("utf-8")
        else:
            ohne_feld += 1
            assert quelle.text_roh == quelle.text, (
                f"{node['id']}: text_roh omitted but parser's text_roh differs from text"
            )
    assert mit_feld == 31, f"expected 31 records with a genuinely different text_roh, got {mit_feld}"
    assert ohne_feld == 248, f"expected 248 records with text_roh omitted, got {ohne_feld}"
    assert mit_feld + ohne_feld == 279


# --------------------------------------------------------------------------
# Verbatim text: byte-identical to parser output, across the split files
# --------------------------------------------------------------------------


def test_kompetenz_text_is_byte_identical_to_parser_output(
    parse_result: P.ParseResult, combined: dict
) -> None:
    by_id = {k.id: k for k in parse_result.kompetenzen}
    geprueft = 0
    for komp in _all_kompetenzen(combined):
        quelle = by_id[komp["id"]]
        assert komp["text"].encode("utf-8") == quelle.text.encode("utf-8")
        geprueft += 1
    assert geprueft == 42


def test_anwendungsitem_text_is_byte_identical_to_parser_output(
    parse_result: P.ParseResult, combined: dict
) -> None:
    by_id = {a.id: a for a in parse_result.anwendungsitems}
    geprueft = 0
    for item in _all_anwendungsitems(combined):
        quelle = by_id[item["id"]]
        assert item["text"].encode("utf-8") == quelle.text.encode("utf-8")
        geprueft += 1
    assert geprueft == 237


def test_bereich_names_are_byte_identical_to_parser_output(
    parse_result: P.ParseResult, dateien_meta: dict[str, dict]
) -> None:
    by_slug = {b.slug: b.name for b in parse_result.bereiche}
    for dateiname in BEREICH_DATEIEN:
        bereich = dateien_meta[dateiname]["kompetenzbereiche"][0]
        assert bereich["name"].encode("utf-8") == by_slug[bereich["slug"]].encode("utf-8")


def test_no_ascii_folding_regression(combined: dict) -> None:
    """Regression guard: an earlier agent ASCII-folded umlauts/ß and had to
    revert (see schema/beispiel_kompetenzen.json's own regression test)."""
    roh = json.dumps(combined, ensure_ascii=False)
    for erwartet, verboten in [
        ("Zahlen und Maße", "Zahlen und Masse"),
        ("Figuren und Körper", "Figuren und Koerper"),
        ("natürliche", "natuerliche"),
        ("Integrative Führung", "Integrative Fuehrung"),
    ]:
        assert erwartet in roh, f"expected verbatim {erwartet!r} in the built shard"
        assert verboten not in roh, f"ASCII-folded {verboten!r} found in the built shard"


# --------------------------------------------------------------------------
# Per-record field slimming (band/fach/bereich_* dropped where implied)
# --------------------------------------------------------------------------


def test_bereich_nested_kompetenzen_drop_redundant_fields(dateien_meta: dict[str, dict]) -> None:
    for dateiname in BEREICH_DATEIEN:
        for komp in dateien_meta[dateiname]["kompetenzbereiche"][0]["kompetenzen"]:
            for feld in ("band", "fach", "bereich_name", "bereich_nummer"):
                assert feld not in komp, f"{komp['id']}: {feld} should be implied, not present"
            for item in komp.get("anwendungsbereiche", []):
                for feld in ("band", "fach", "bereich_name", "bereich_nummer"):
                    assert feld not in item, f"{item['id']}: {feld} should be implied, not present"


def test_zusatzkompetenzen_keep_bereich_attribution_but_not_band_fach(dateien_meta: dict[str, dict]) -> None:
    for komp in dateien_meta["zusatz.json"]["zusatzkompetenzen"]:
        assert komp["bereich_nummer"] is None
        assert komp["bereich_name"] == "Integrative Führung von Geometrisches Zeichnen"
        assert "band" not in komp
        assert "fach" not in komp
        assert "anwendungsbereiche" not in komp, "GZINTEGRATIV has no Anwendungsbereiche block in the source"


def test_digitale_technologien_keep_bereich_attribution_but_not_band_fach(dateien_meta: dict[str, dict]) -> None:
    items = dateien_meta["zusatz.json"]["digitale_technologien_vorschlaege"]
    assert len(items) == 39
    for item in items:
        assert item["bereich_nummer"] is not None
        assert item["bereich_name"]
        assert "band" not in item
        assert "fach" not in item


# --------------------------------------------------------------------------
# digitale_technologien items precisify no competence (E2-19)
# --------------------------------------------------------------------------


def test_digitale_technologien_items_have_no_kompetenz_id(dateien_meta: dict[str, dict]) -> None:
    for item in dateien_meta["zusatz.json"]["digitale_technologien_vorschlaege"]:
        assert item["art"] == "digitale_technologien"
        assert item["kompetenz_id"] is None


def test_digitale_technologien_items_are_unreachable_from_any_kompetenz(dateien_meta: dict[str, dict]) -> None:
    digital_ids = {item["id"] for item in dateien_meta["zusatz.json"]["digitale_technologien_vorschlaege"]}
    nested_ids = set()
    for dateiname in BEREICH_DATEIEN:
        for komp in dateien_meta[dateiname]["kompetenzbereiche"][0]["kompetenzen"]:
            nested_ids.update(item["id"] for item in komp.get("anwendungsbereiche", []))
    assert digital_ids.isdisjoint(nested_ids), "digitale_technologien items leaked into a competence's anwendungsbereiche[]"


def test_no_kompetenz_anwendungsbereiche_entry_has_art_digitale_technologien(dateien_meta: dict[str, dict]) -> None:
    for dateiname in BEREICH_DATEIEN:
        for komp in dateien_meta[dateiname]["kompetenzbereiche"][0]["kompetenzen"]:
            for item in komp.get("anwendungsbereiche", []):
                assert item["art"] != "digitale_technologien"


# --------------------------------------------------------------------------
# Provenance (E3-03): full meta.provenienz on every part, self-contained
# --------------------------------------------------------------------------


def test_every_part_carries_complete_meta_provenienz(dateien_meta: dict[str, dict]) -> None:
    for dateiname, doc in dateien_meta.items():
        prov = doc["meta"]["provenienz"]
        for feld in ("quelle", "kurztitel", "nor", "kundmachung", "anlage", "teil", "stand"):
            assert prov[feld], f"{dateiname}: meta.provenienz.{feld} is missing or empty"
        assert prov["nor"] == "NOR40271471"
        assert prov["teil"] == "ACHTER TEIL"


def test_meta_default_variant_has_no_per_record_provenienz(dateien_meta: dict[str, dict]) -> None:
    for doc in dateien_meta.values():
        for komp in _all_kompetenzen(doc):
            assert "provenienz" not in komp
        for item in _all_anwendungsitems(doc):
            assert "provenienz" not in item


def test_je_datensatz_variant_has_provenienz_on_every_record(dateien_je_datensatz: dict[str, dict]) -> None:
    for doc in dateien_je_datensatz.values():
        prov = doc["meta"]["provenienz"]
        for komp in _all_kompetenzen(doc):
            assert komp["provenienz"] == prov
        for item in _all_anwendungsitems(doc):
            assert item["provenienz"] == prov


def test_je_datensatz_variant_is_larger_than_meta(
    dateien_meta: dict[str, dict], dateien_je_datensatz: dict[str, dict]
) -> None:
    bytes_meta = sum(len(B._dump(doc).encode("utf-8")) for doc in dateien_meta.values())
    bytes_je = sum(len(B._dump(doc).encode("utf-8")) for doc in dateien_je_datensatz.values())
    assert bytes_je > bytes_meta


# --------------------------------------------------------------------------
# Abbildungen registry
# --------------------------------------------------------------------------


def test_abbildungen_registry_covers_every_referenced_image(
    parse_result: P.ParseResult, combined: dict
) -> None:
    registry = B.collect_abbildungen_registry_eintraege(parse_result)
    referenzierte_dateien = set()
    for node in list(_all_kompetenzen(combined)) + list(_all_anwendungsitems(combined)):
        for a in node.get("abbildungen", []):
            referenzierte_dateien.add(a["datei"])
    assert referenzierte_dateien, "expected at least one abbildung reference in Sek I Mathematik"
    assert referenzierte_dateien <= set(registry), "an inline abbildung is missing from the registry"
    for datei, eintrag in registry.items():
        for feld in ("nor", "quelle_url", "breite_px", "hoehe_px", "sha256"):
            assert eintrag[feld], f"registry[{datei!r}].{feld} missing or empty"


def test_abbildungen_records_keep_full_fields_because_schema_requires_them(combined: dict) -> None:
    """The renderers only read token/pfad/datei, but schema/kompetenzen.schema.json's
    $defs/abbildung (frozen, not owned by this task) requires all 8 fields --
    so records are NOT slimmed here; see build_dataset.py's module docstring."""
    gefunden = False
    for node in list(_all_kompetenzen(combined)) + list(_all_anwendungsitems(combined)):
        for a in node.get("abbildungen", []):
            gefunden = True
            for feld in ("token", "datei", "nor", "pfad", "quelle_url", "breite_px", "hoehe_px", "sha256"):
                assert feld in a, f"{node['id']}: abbildungen entry missing {feld!r}"
    assert gefunden, "expected at least one abbildungen entry in Sek I Mathematik"


# --------------------------------------------------------------------------
# index.json: consistent with what is on disk / in the built parts
# --------------------------------------------------------------------------


def test_index_matches_built_parts(dateien_meta: dict[str, dict]) -> None:
    index = B.build_index(P.SEK1_MATHEMATIK, dateien_meta)
    assert index["meta"] == dateien_meta["zusatz.json"]["meta"]
    assert {t["datei"] for t in index["teile"]} == set(ALLE_DATEIEN)

    for teil in index["teile"]:
        doc = dateien_meta[teil["datei"]]
        payload = B._dump(doc)
        assert teil["bytes"] == len(payload.encode("utf-8"))
        assert teil["tokens_approx"] == B.approx_tokens(payload)
        if teil["typ"] == "kompetenzbereich":
            bereich = doc["kompetenzbereiche"][0]
            assert teil["nummer"] == bereich["nummer"]
            assert teil["slug"] == bereich["slug"]
            assert teil["name"] == bereich["name"]
            assert teil["kompetenzen"] == len(bereich["kompetenzen"])
            assert teil["anwendungsitems"] == sum(
                len(k.get("anwendungsbereiche", [])) for k in bereich["kompetenzen"]
            )
        else:
            assert teil["zusatzkompetenzen"] == len(doc["zusatzkompetenzen"])
            assert teil["digitale_technologien_vorschlaege"] == len(doc["digitale_technologien_vorschlaege"])


def test_index_on_disk_matches_files_on_disk(tmp_path: Path, dateien_meta: dict[str, dict]) -> None:
    index = B.build_index(P.SEK1_MATHEMATIK, dateien_meta)
    B.write_parts(tmp_path, dateien_meta, index)

    on_disk_index = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    for teil in on_disk_index["teile"]:
        datei = tmp_path / teil["datei"]
        assert datei.is_file()
        inhalt = datei.read_text(encoding="utf-8")
        # write_parts appends a trailing newline; account for it.
        assert teil["bytes"] == len(inhalt.rstrip("\n").encode("utf-8"))


# --------------------------------------------------------------------------
# Size report (E3-07): oversize is a review trigger, never a build failure
# --------------------------------------------------------------------------


def test_build_report_never_raises_on_oversize(
    parse_result: P.ParseResult, dateien_meta: dict[str, dict], dateien_je_datensatz: dict[str, dict]
) -> None:
    report = B.build_report(P.SEK1_MATHEMATIK, MS_XML, parse_result, dateien_meta, dateien_je_datensatz, "meta")
    assert "PASS" in report or "REVIEW" in report
    for dateiname in ALLE_DATEIEN:
        assert dateiname in report


def test_build_report_states_actual_per_part_sizes(
    parse_result: P.ParseResult, dateien_meta: dict[str, dict], dateien_je_datensatz: dict[str, dict]
) -> None:
    report = B.build_report(P.SEK1_MATHEMATIK, MS_XML, parse_result, dateien_meta, dateien_je_datensatz, "meta")
    for dateiname, doc in dateien_meta.items():
        b = len(B._dump(doc).encode("utf-8"))
        assert str(b) in report, f"expected the real byte count for {dateiname} ({b}) in the report"


def test_approx_tokens_is_positive_and_monotonic() -> None:
    kurz = B.approx_tokens("a")
    lang = B.approx_tokens("a" * 1000)
    assert kurz >= 1
    assert lang > kurz


# --------------------------------------------------------------------------
# combine_parts / write_parts plumbing
# --------------------------------------------------------------------------


def test_combine_parts_kompetenzbereiche_ordered_by_nummer(combined: dict) -> None:
    nummern = [b["nummer"] for b in combined["kompetenzbereiche"]]
    assert nummern == sorted(nummern)


def test_write_parts_writes_every_file(tmp_path: Path, dateien_meta: dict[str, dict]) -> None:
    index = B.build_index(P.SEK1_MATHEMATIK, dateien_meta)
    B.write_parts(tmp_path, dateien_meta, index)
    on_disk = {p.name for p in tmp_path.glob("*.json")}
    assert on_disk == set(ALLE_DATEIEN) | {"index.json"}


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
