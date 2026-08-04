"""Area-level Lehrplan/Bildungsstandards crosswalk contract (E8-03)."""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPO_ROOT / "plugin" / "data"
KOMPETENZEN_ROOT = DATA_ROOT / "kompetenzen"
BIST_ROOT = DATA_ROOT / "bildungsstandards"
CROSSWALK_PATH = BIST_ROOT / "crosswalk.json"
SCHEMA_PATH = REPO_ROOT / "data-pipeline" / "schema" / "bildungsstandards-crosswalk.schema.json"

sys.path.insert(0, str(REPO_ROOT / "plugin" / "scripts"))
import kompetenz as K  # noqa: E402


def laden(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_crosswalk_validiert_und_markiert_keine_eins_zu_eins_praezision():
    doc = laden(CROSSWALK_PATH)
    jsonschema.Draft202012Validator(laden(SCHEMA_PATH)).validate(doc)
    assert doc["meta"]["amtlich"] is False
    assert "keine 1:1-Zuordnung" in doc["meta"]["praezisionsaussage"]
    assert all(z["amtlich"] is False and z["rationale"].strip() for z in doc["zuordnungen"])


def test_exakte_zuordnungszahlen_und_sachunterricht_defined_empty():
    doc = laden(CROSSWALK_PATH)
    assert len(doc["zuordnungen"]) == 50
    assert Counter(z["bildungsstandard_shard"] for z in doc["zuordnungen"]) == {
        "D4": 5,
        "M4": 20,
        "D8": 4,
        "E8": 5,
        "M8": 16,
    }
    assert doc["nicht_abgedeckt"] == [
        {
            "lehrplan_fach": "PRIM.SU",
            "abgedeckt": False,
            "grund": "keine BiSt verordnet",
            "amtlich": False,
            "rationale": doc["nicht_abgedeckt"][0]["rationale"],
        }
    ]
    assert K.finde_bildungsstandard_bezug(K.finde_kompetenz("PRIM.SU")[0]["id"]) == {
        "abgedeckt": False,
        "grund": "keine BiSt verordnet",
    }


def test_jeder_endpoint_existiert_und_alle_offiziellen_bereiche_sind_abgedeckt():
    doc = laden(CROSSWALK_PATH)
    lp_bereiche: dict[str, set[str]] = {}
    for fach in ("PRIM.D", "PRIM.M", "SEK1.D", "SEK1.E", "SEK1.M"):
        band, code = fach.split(".")
        index = laden(KOMPETENZEN_ROOT / band.casefold() / code.casefold() / "index.json")
        lp_bereiche[fach] = {
            t["slug"] for t in index["teile"] if t.get("typ") == "kompetenzbereich"
        }

    bist_bereiche = {
        shard: {b["code"] for b in laden(BIST_ROOT / f"{shard.casefold()}.json")["kompetenzbereiche"]}
        for shard in ("D4", "M4", "D8", "E8", "M8")
    }

    for z in doc["zuordnungen"]:
        assert z["lehrplan_bereich"] in lp_bereiche[z["lehrplan_fach"]]
        assert z["bildungsstandard_bereich"] in bist_bereiche[z["bildungsstandard_shard"]]

    for fach, bereiche in lp_bereiche.items():
        assert {z["lehrplan_bereich"] for z in doc["zuordnungen"] if z["lehrplan_fach"] == fach} == bereiche
    for shard, bereiche in bist_bereiche.items():
        assert {
            z["bildungsstandard_bereich"]
            for z in doc["zuordnungen"]
            if z["bildungsstandard_shard"] == shard
        } == bereiche


def test_m4_prozessachsen_und_m8_matrix_bleiben_unterschiedlich():
    zuordnungen = laden(CROSSWALK_PATH)["zuordnungen"]
    m4 = [z for z in zuordnungen if z["bildungsstandard_shard"] == "M4"]
    prozesse = {"MODELLIEREN", "OPERIEREN", "KOMMUNIZIEREN", "PROBLEMLOESEN"}
    je_lp: dict[str, list[dict]] = defaultdict(list)
    for z in m4:
        je_lp[z["lehrplan_bereich"]].append(z)
    assert set(je_lp) == {"ZAHLENDATEN", "OPERATIONEN", "GROESSEN", "EBENERAUM"}
    for eintraege in je_lp.values():
        assert {z["bildungsstandard_bereich"] for z in eintraege if z["beziehung"] == "querschnitt_prozess"} == prozesse
        assert sum(z["beziehung"] == "bereichsentsprechung" for z in eintraege) == 1

    m8 = [z for z in zuordnungen if z["bildungsstandard_shard"] == "M8"]
    assert all(z["beziehung"] == "matrix_inhaltsachse" for z in m8)
    for lp_bereich in ("ZAHLEN", "VARIABLEN", "FIGUREN", "DATEN"):
        assert sum(z["lehrplan_bereich"] == lp_bereich for z in m8) == 4


def test_zugriff_liefert_nur_gemappte_bereiche_ohne_descriptor_duplikate():
    crosswalk = laden(CROSSWALK_PATH)
    bist_docs = {
        shard: laden(BIST_ROOT / f"{shard.casefold()}.json")
        for shard in ("D4", "M4", "D8", "E8", "M8")
    }
    alle_bist_ids = {
        d["id"]: d for doc in bist_docs.values() for d in doc["deskriptoren"]
    }

    gemappt = 0
    gelieferte_bist_ids: set[str] = set()
    for fach in ("PRIM.D", "PRIM.M", "SEK1.D", "SEK1.E", "SEK1.M"):
        for k in K.finde_kompetenz(fach):
            ergebnis = K.finde_bildungsstandard_bezug(k["id"])
            assert ergebnis["abgedeckt"] is True
            assert "keine 1:1-Zuordnung" in ergebnis["methodik"]["praezisionsaussage"]
            ids = [d["id"] for d in ergebnis["deskriptoren"]]
            gelieferte_bist_ids.update(ids)
            assert len(ids) == len(set(ids))

            ziel = {
                (z["bildungsstandard_shard"], z["bildungsstandard_bereich"])
                for z in crosswalk["zuordnungen"]
                if z["lehrplan_fach"] == fach and z["lehrplan_bereich"] == k["bereich_slug"]
            }
            if k["bereich_slug"] == "GZINTEGRATIV":
                assert ziel == set()
                assert ergebnis["deskriptoren"] == []
                assert ergebnis["zuordnungen"] == []
                assert "Zusatzbereich" in ergebnis["hinweis"]
                continue

            gemappt += 1
            assert ziel
            assert ergebnis["zuordnungen"]
            assert all(z["rationale"] and z["amtlich"] is False for z in ergebnis["zuordnungen"])
            assert all(z["lehrplan_provenienz"]["nor"].startswith("NOR") for z in ergebnis["zuordnungen"])
            assert all(z["bildungsstandard_provenienz"]["nor"] == "NOR40255561" for z in ergebnis["zuordnungen"])
            assert ids
            for ident in ids:
                d = alle_bist_ids[ident]
                shard = ident.split(".")[2] + ident.split(".")[3].removeprefix("SCH")
                assert (shard, d["bereich_code"]) in ziel
            assert all(d["volltext"].startswith(d["stammsatz"]) for d in ergebnis["deskriptoren"])
            assert all(d["provenienz"]["nor"] == "NOR40255561" for d in ergebnis["deskriptoren"])

    assert gemappt == 197
    # SEK1.D/Sprachreflexion is an official structural Lehrplan area with
    # zero competence records (V-77). Its mapping exists and endpoint checks
    # above cover it, but a competence-id API cannot originate from it.
    nicht_per_kompetenz_erreichbar = {
        ident
        for ident, d in alle_bist_ids.items()
        if ident.startswith("AT.BIST.D.SCH8.SPRACHBEWUSSTSEIN.")
    }
    assert len(nicht_per_kompetenz_erreichbar) == 12
    assert gelieferte_bist_ids == set(alle_bist_ids) - nicht_per_kompetenz_erreichbar
