"""Tests for parse_bildungsstandards.py and schema/bildungsstandards.schema.json (E8-01/E8-02).

Run:  .venv/bin/python -m pytest data-pipeline/tests -q

Uses the committed fixture ``fixtures/bildungsstandards_anl1.xml`` -- a
byte-for-byte copy of the full live BiSt Anl. 1 document (NOR40255561.xml,
81 009 bytes; small enough to check in whole, unlike the multi-hundred-KB
Lehrplan documents that need trimming). ``resources/`` is gitignored, so
this fixture is what makes the suite exercise the real parser on a fresh
clone / CI, per CLAUDE.md's hard constraint.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "schema"))

import bist_id_schema as BID  # noqa: E402
import parse_bildungsstandards as P  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIXTURE_XML = FIXTURES / "bildungsstandards_anl1.xml"
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "bildungsstandards.schema.json"

RESOURCES_XML = (
    Path(__file__).resolve().parents[1] / "resources" / "bildungsstandards" / "NOR40255561.xml"
)


@pytest.fixture(scope="module")
def shards() -> dict[tuple[str, str], P.ShardResult]:
    root = P.load_root(FIXTURE_XML)
    parser = P.BildungsstandardsParser(root)
    return parser.parse()


@pytest.fixture(scope="module")
def provenienz() -> dict:
    root = P.load_root(FIXTURE_XML)
    parser = P.BildungsstandardsParser(root)
    return parser.provenienz()


@pytest.fixture(scope="module")
def schema() -> dict:
    with SCHEMA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def _shard(shards_map, name: str) -> P.ShardResult:
    for shard in shards_map.values():
        if shard.shard == name:
            return shard
    raise AssertionError(f"shard {name!r} not found among {[s.shard for s in shards_map.values()]}")


# --------------------------------------------------------------------------
# Structural counts -- measured 2026-08-04 against the live document
# --------------------------------------------------------------------------


class TestElementCount:
    def test_393_top_level_children(self):
        """FINDINGS.md/plan says 393 elements for BiSt Anl. 1 -- verify it
        directly against the fixture rather than trusting the plan figure."""
        root = P.load_root(FIXTURE_XML)
        abschnitt = P.find_abschnitt(root)
        assert len(list(abschnitt)) == 393

    @pytest.mark.skipif(not RESOURCES_XML.exists(), reason="resources/ not present (gitignored)")
    def test_fixture_is_byte_identical_to_live_resource(self):
        assert FIXTURE_XML.read_bytes() == RESOURCES_XML.read_bytes()


class TestShardCounts:
    """Every count here was measured against the live XML on 2026-08-04 by
    an independent census script before the parser was written, then
    cross-checked against the parser's own output -- both agree exactly.
    See the E8-01 report for the full derivation."""

    def test_five_shards_present(self, shards):
        names = {s.shard for s in shards.values()}
        assert names == {"D4", "M4", "D8", "E8", "M8"}

    @pytest.mark.parametrize(
        "name,n_bereiche,n_desk",
        [
            ("D4", 5, 75),
            ("M4", 8, 58),
            ("D8", 4, 52),
            ("E8", 5, 35),
            ("M8", 16, 48),
        ],
    )
    def test_expected_counts(self, shards, name, n_bereiche, n_desk):
        shard = _shard(shards, name)
        assert len(shard.kompetenzbereiche) == n_bereiche
        assert len(shard.deskriptoren) == n_desk
        assert P.ERWARTET[name] == {"kompetenzbereiche": n_bereiche, "deskriptoren": n_desk}

    def test_total_descriptor_count(self, shards):
        # 75 + 58 + 52 + 35 + 48 = 268, matching the live document's 268
        # <listelem> elements plus the 2 standalone single-sentence
        # competences that carry no <liste> at all (measured: 266 + 2).
        total = sum(len(s.deskriptoren) for s in shards.values())
        assert total == 268

    def test_no_shard_has_parse_issues(self, shards):
        """Every tolerated structural surprise found while building this
        parser (the D8 area-description sentences, the two fused
        <schlussteil> groups, the two standalone competences) has a
        dedicated code path -- none should still be logged as an issue
        against the live document."""
        for shard in shards.values():
            assert shard.issues == [], f"{shard.shard}: unexpected issues {shard.issues}"

    def test_no_sachunterricht_shard(self, shards):
        """BiSt has no Sachunterricht chapter (measured) -- confirms the
        E8-04 defined-empty-result premise rather than assuming it."""
        assert all(s.fach != "SU" for s in shards.values())
        assert "SU" not in BID.FAECHER


# --------------------------------------------------------------------------
# Verbatim fidelity -- the load-bearing spot checks
# --------------------------------------------------------------------------


class TestVerbatimFidelity:
    def test_gdash_renders_as_hyphen_not_dropped(self, shards):
        """<gdash/> has no text/tail of its own; a naive itertext() traversal
        drops it silently, turning '(Un<gdash/>)Gleichungen' into
        '(Un)Gleichungen' -- exactly the kind of silent verbatim loss
        CLAUDE.md flags. Measured: 8 occurrences in the live document, all
        inside M8 RECHNENVARIABLE/ARGUMENTIERENZAHLEN items."""
        m8 = _shard(shards, "M8")
        texte = [d.text for d in m8.deskriptoren]
        assert any("(Un-)Gleichungen" in t for t in texte)
        assert any("(Rechen-)Modell" in t for t in texte)
        assert any("(Rechen-)Operationen" in t for t in texte)
        assert any("(un-)zutreffend" in t for t in texte)
        # And the naive-drop failure mode must NOT be present anywhere.
        for t in texte:
            assert "(Un)Gleichungen" not in t
            assert "(Rechen)Modell" not in t

    def test_m8_heading_typo_preserved_verbatim(self, shards):
        """One live M8 heading is missing its closing „" guillemet after the
        Handlungsbereich name -- a genuine RIS typesetting inconsistency,
        not a parser bug. ueberschrift_roh must reproduce it exactly; the
        cleaned handlungsbereich/inhaltsbereich labels must NOT carry the
        glitch (the code-minting path is glitch-tolerant by design)."""
        m8 = _shard(shards, "M8")
        roh_texte = [b.ueberschrift_roh for b in m8.kompetenzbereiche]
        glitched = [t for t in roh_texte if "Modellbilden – Inhaltsbereich" in t and "Modellbilden“" not in t]
        assert len(glitched) == 1
        assert glitched[0] == (
            "Handlungsbereich „Darstellen, Modellbilden – Inhaltsbereich "
            "„Variable, funktionale Abhängigkeiten“"
        )
        bereich = next(b for b in m8.kompetenzbereiche if b.ueberschrift_roh == glitched[0])
        assert bereich.handlungsbereich == "Darstellen, Modellbilden"
        assert bereich.code == "DARSTELLENVARIABLE"

    def test_one_heading_keeps_the_colon_the_others_drop(self, shards):
        """Exactly one of 16 M8 headings has 'Handlungsbereich:' with a
        colon; the other 15 do not. Both must mint the same kind of code via
        the same regex path (glitch-tolerant), and ueberschrift_roh keeps
        each form as printed."""
        m8 = _shard(shards, "M8")
        mit_doppelpunkt = [b for b in m8.kompetenzbereiche if b.ueberschrift_roh.startswith("Handlungsbereich:")]
        ohne_doppelpunkt = [b for b in m8.kompetenzbereiche if b.ueberschrift_roh.startswith("Handlungsbereich „")]
        assert len(mit_doppelpunkt) == 1
        assert len(ohne_doppelpunkt) == 15

    def test_d8_area_description_captured_not_dropped(self, shards):
        """D8's four Kompetenzbereich headings are each followed by a
        general area-description sentence before the first titled
        sub-group. An early version of this parser silently dropped it as
        an 'unerwarteter_absatz' issue -- it must now land on
        Kompetenzbereich.beschreibung, verbatim."""
        d8 = _shard(shards, "D8")
        hoeren = next(b for b in d8.kompetenzbereiche if b.code == "ZUHOERENSPRECHEN")
        assert hoeren.beschreibung == (
            "Durch Zuhören gesprochene Texte (auch medial vermittelt) verstehen, an "
            "private und öffentliche Kommunikationssituationen angepasste Gespräche "
            "führen und mündliche Präsentationen durchführen."
        )
        assert all(b.beschreibung for b in d8.kompetenzbereiche)

    def test_fused_schlussteil_single_splits_titel_and_stem(self, shards):
        """D4 Rechtschreiben, 'Regelungen für normgerechtes Schreiben...': in
        the live XML the Titel and the 'Kompetenzen:' stem are fused into a
        single <schlussteil> text node inside <liste> (no separate
        preceding <absatz> at all). Must still split cleanly."""
        d4 = _shard(shards, "D4")
        treffer = [d for d in d4.deskriptoren if d.titel == "Regelungen für normgerechtes Schreiben kennen und anwenden"]
        assert len(treffer) == 2
        assert all(d.stammsatz == "Die Schülerinnen und Schüler" for d in treffer)
        assert treffer[0].text == "kennen die wichtigsten Regeln der Rechtschreibung und können sie anwenden,"

    def test_fused_schlussteil_double_splits_titel_and_stem(self, shards):
        """D8 Lesen, 'Eine textbezogene Interpretation entwickeln': two
        separate <schlussteil> elements inside one <liste> (no preceding
        <absatz> at all)."""
        d8 = _shard(shards, "D8")
        treffer = [d for d in d8.deskriptoren if d.titel == "Eine textbezogene Interpretation entwickeln"]
        assert len(treffer) == 3
        assert all(d.stammsatz == "Die Schülerinnen und Schüler können" for d in treffer)

    def test_standalone_single_sentence_competences(self, shards):
        """M4 Modellieren/Problemlösen each carry one competence expressed as
        a single sentence with no following <liste> at all -- the stem and
        the descriptor content are both inside one <absatz>."""
        m4 = _shard(shards, "M4")
        modellieren_04 = next(d for d in m4.deskriptoren if d.id == "AT.BIST.M.SCH4.MODELLIEREN.04")
        assert modellieren_04.stammsatz == "Die Schülerinnen und Schüler können"
        assert modellieren_04.text == "zu Termen und Gleichungen Sachaufgaben erstellen."
        assert modellieren_04.titel == "Ein mathematisches Modell in eine Sachsituation übertragen"

        problemloesen_01 = next(d for d in m4.deskriptoren if d.id == "AT.BIST.M.SCH4.PROBLEMLOESEN.01")
        assert problemloesen_01.text == "ein innermathematisches Problem erkennen und dazu relevante Fragen stellen."

    def test_stem_without_koennen_kept_verbatim(self, shards):
        """Some stems omit 'können' (the verb moves into the first item
        text instead, e.g. '...können Situationen richtig einschätzen...').
        Both forms are real and must be kept exactly as printed, not
        normalised to a single canonical stem."""
        d4 = _shard(shards, "D4")
        mit_koennen = {d.stammsatz for d in d4.deskriptoren if d.bereich_code == "HOERENSPRECHEN"}
        assert "Die Schülerinnen und Schüler können" in mit_koennen
        assert "Die Schülerinnen und Schüler" in mit_koennen

    def test_m8_kompetenzmodell_hinweis_captured(self, shards):
        m8 = _shard(shards, "M8")
        assert m8.kompetenzmodell_hinweis is not None
        assert m8.kompetenzmodell_hinweis.startswith(
            "Das Kompetenzmodell für Mathematik auf der 8. Schulstufe legt „Inhaltsbereiche“ fest"
        )

    def test_other_shards_have_no_kompetenzmodell_hinweis(self, shards):
        for name in ("D4", "M4", "D8", "E8"):
            assert _shard(shards, name).kompetenzmodell_hinweis is None

    def test_titel_absent_for_e8_and_m8(self, shards):
        """E8 and M8 go straight from the Kompetenzbereich heading to the
        'Kompetenzen:' stem -- no bold sub-title exists in the source."""
        for name in ("E8", "M8"):
            shard = _shard(shards, name)
            assert all(d.titel is None for d in shard.deskriptoren)

    def test_m4_gruppe_labels(self, shards):
        m4 = _shard(shards, "M4")
        gruppen = {b.code: b.gruppe for b in m4.kompetenzbereiche}
        assert gruppen["MODELLIEREN"] == "Allgemeine mathematische Kompetenzen"
        assert gruppen["ZAHLEN"] == "Inhaltliche mathematische Kompetenzen"


# --------------------------------------------------------------------------
# IDs
# --------------------------------------------------------------------------


class TestIds:
    def test_all_ids_well_formed_and_unique(self, shards):
        all_ids = [d.id for shard in shards.values() for d in shard.deskriptoren]
        result = BID.validate_ids(all_ids)
        assert result.ok, (result.malformed, result.duplicates)
        assert result.total == 268

    def test_id_matches_at_bist_namespace_not_at_lp23(self, shards):
        for shard in shards.values():
            for d in shard.deskriptoren:
                assert d.id.startswith("AT.BIST.")
                assert not d.id.startswith("AT.LP23.")

    def test_lfd_scoped_per_bereich_starts_at_one(self, shards):
        d4 = _shard(shards, "D4")
        erste = [d for d in d4.deskriptoren if d.bereich_code == "HOERENSPRECHEN" and d.ordinal == 1]
        assert len(erste) == 1
        assert erste[0].id == "AT.BIST.D.SCH4.HOERENSPRECHEN.01"

    def test_ids_round_trip_through_parse_id(self, shards):
        for shard in shards.values():
            for d in shard.deskriptoren:
                parsed = BID.parse_id(d.id)
                assert parsed.fach == d.fach
                assert parsed.programmstufe == d.programmstufe
                assert parsed.bereich == d.bereich_code
                assert parsed.lfd == d.ordinal

    def test_bist_and_lp23_grammars_never_both_match(self):
        """Sanity check on the two independent ID namespaces: an AT.BIST id
        must never satisfy the frozen AT.LP23 grammar, and vice versa --
        they are trivially disambiguated by the second segment, but this
        pins that invariant explicitly rather than leaving it implicit."""
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "schema"))
        import id_schema as LP23  # noqa: E402

        beispiel_bist = "AT.BIST.D.SCH4.HOERENSPRECHEN.01"
        with pytest.raises(LP23.IdSchemaError):
            LP23.parse_id(beispiel_bist)

        beispiel_lp23 = "AT.LP23.SEK1.M.ZAHLEN.K1.01"
        with pytest.raises(BID.BistIdSchemaError):
            BID.parse_id(beispiel_lp23)


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------


class TestProvenienz:
    def test_provenienz_from_document_header(self, provenienz):
        assert provenienz["nor"] == "NOR40255561"
        assert provenienz["kurztitel"] == "Bildungsstandardsverordnung"
        assert provenienz["gesetzesnummer"] == "20006166"
        assert provenienz["anlage"] == "Anl. 1"
        assert provenienz["inkrafttretensdatum"] == "09.09.2023"
        # V-51: no hyphen in the live Kurztitel value.
        assert "-" not in provenienz["kurztitel"]


# --------------------------------------------------------------------------
# Schema validity (E8-02 acceptance: plugin/data/bildungsstandards/*.json
# schema-valid)
# --------------------------------------------------------------------------


class TestSchemaValidity:
    def test_schema_itself_is_valid_draft_2020_12(self, schema):
        jsonschema.Draft202012Validator.check_schema(schema)

    @pytest.mark.parametrize("name", ["D4", "M4", "D8", "E8", "M8"])
    def test_each_shard_dict_validates(self, shards, provenienz, schema, name):
        shard = _shard(shards, name)
        data = P.shard_to_dict(shard, provenienz, dataset_version="2026-08-04")
        jsonschema.validate(instance=data, schema=schema)

    def test_shipped_files_validate(self, schema):
        """The actual files under plugin/data/bildungsstandards/ -- the
        literal E8-02 acceptance criterion. Skipped if not yet written in
        this environment (build is a separate --write step)."""
        out_dir = Path(__file__).resolve().parents[2] / "plugin" / "data" / "bildungsstandards"
        # crosswalk.json is a separately schematized E8-03 artifact in the
        # same shipped directory; only the five named descriptor shards are
        # inputs to bildungsstandards.schema.json.
        files = [out_dir / f"{name}.json" for name in ("d4", "m4", "d8", "e8", "m8")]
        files = [f for f in files if f.exists()]
        if not files:
            pytest.skip("plugin/data/bildungsstandards/*.json not written in this environment")
        assert {f.stem for f in files} == {"d4", "m4", "d8", "e8", "m8"}
        for f in files:
            with f.open(encoding="utf-8") as fh:
                data = json.load(fh)
            jsonschema.validate(instance=data, schema=schema)

    def test_missing_id_is_rejected(self, schema):
        bad = {
            "meta": {
                "dataset_version": "x", "shard": "D4", "fach": {"code": "D", "name": "Deutsch"},
                "programmstufe": "SCH4",
                "provenienz": {"quelle": "x", "kurztitel": "x", "nor": "NOR1", "kundmachungsorgan": "x", "anlage": "Anl. 1"},
            },
            "kompetenzbereiche": [],
            "deskriptoren": [{"fach": "D", "programmstufe": "SCH4", "bereich_code": "X", "stammsatz": "s", "text": "t", "ordinal": 1}],
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad, schema=schema)

    def test_unknown_shard_enum_is_rejected(self, schema):
        bad = {
            "meta": {
                "dataset_version": "x", "shard": "D6", "fach": {"code": "D", "name": "Deutsch"},
                "programmstufe": "SCH4",
                "provenienz": {"quelle": "x", "kurztitel": "x", "nor": "NOR1", "kundmachungsorgan": "x", "anlage": "Anl. 1"},
            },
            "kompetenzbereiche": [],
            "deskriptoren": [],
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad, schema=schema)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


class TestCli:
    def test_verify_exits_zero_against_fixture(self, capsys):
        rc = P.main(["--source", str(FIXTURE_XML), "--verify"])
        assert rc == 0

    def test_write_produces_five_schema_valid_files(self, tmp_path, schema):
        out_dir = tmp_path / "bist_out"
        rc = P.main(["--source", str(FIXTURE_XML), "--write", "--out-dir", str(out_dir)])
        assert rc == 0
        files = sorted(out_dir.glob("*.json"))
        assert {f.stem for f in files} == {"d4", "m4", "d8", "e8", "m8"}
        for f in files:
            with f.open(encoding="utf-8") as fh:
                data = json.load(fh)
            jsonschema.validate(instance=data, schema=schema)

    def test_missing_source_exits_nonzero(self):
        rc = P.main(["--source", "/nonexistent/path.xml", "--verify"])
        assert rc == 2
