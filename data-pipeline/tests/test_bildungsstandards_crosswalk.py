"""Area-level Lehrplan/Bildungsstandards crosswalk contract (E8-03)."""

from __future__ import annotations

import copy
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


PAARUNGEN = {
    "PRIM.D": "D4",
    "PRIM.M": "M4",
    "SEK1.D": "D8",
    "SEK1.E": "E8",
    "SEK1.M": "M8",
}


def test_schema_erzwingt_die_fach_shard_paarungen_und_lehnt_jeden_swap_ab():
    """Regressionswaechter (E8-06): ein fachfremder Swap muss am Schema scheitern.

    Geprueft wird das **ganze Dokument**, nicht `$defs/zuordnung` allein -- nur der
    Dokumentpfad ist der Pfad, auf dem echte Daten validiert werden. Mutiert wird die
    ausgelieferte `crosswalk.json`, damit Zaehlungen und Abdeckung erhalten bleiben: genau
    so sieht die Vertauschung aus, die zuvor schema-gueltig und test-gruen blieb.

    Erschoepfend ueber alle 20 falschen Kombinationen. Ein Fall wie `SEK1.E -> E4` taugt
    dafuer nicht: `E4` steht ohnehin nicht im Enum und wuerde auch ohne die Paarungsregel
    abgewiesen -- ein solcher Test besteht bereits vor der Korrektur und bewacht nichts.
    """
    schema = laden(SCHEMA_PATH)
    validator = jsonschema.Draft202012Validator(schema)
    echt = laden(CROSSWALK_PATH)

    validator.validate(echt)  # Positivkontrolle: die ausgelieferten 50 Zuordnungen sind gueltig

    geprueft = 0
    for fach, richtig in PAARUNGEN.items():
        for falsch in PAARUNGEN.values():
            if falsch == richtig:
                continue
            mutiert = copy.deepcopy(echt)
            getroffen = False
            for z in mutiert["zuordnungen"]:
                if z["lehrplan_fach"] == fach:
                    z["bildungsstandard_shard"] = falsch
                    getroffen = True
                    break
            assert getroffen, f"keine Zuordnung fuer {fach} gefunden"
            geprueft += 1
            assert list(validator.iter_errors(mutiert)), (
                f"Schema akzeptiert {fach} -> {falsch}, erwartet war {fach} -> {richtig}"
            )

    assert geprueft == 20


def test_schema_lehnt_den_vollstaendigen_d4_d8_tausch_mit_erhaltenen_zahlen_ab():
    """Der konkrete Fall aus der Pruefung: `PRIM.D -> D8` **und** `SEK1.D -> D4` zugleich.

    Zaehlungen, Abdeckung und Schema-Form bleiben dabei unveraendert -- der Grund, warum
    zaehlende Tests diesen Fehler nicht finden konnten.
    """
    schema = laden(SCHEMA_PATH)
    validator = jsonschema.Draft202012Validator(schema)
    mutiert = laden(CROSSWALK_PATH)

    getauscht = 0
    for z in mutiert["zuordnungen"]:
        if z["lehrplan_fach"] == "PRIM.D" and z["bildungsstandard_shard"] == "D4":
            z["bildungsstandard_shard"] = "D8"
            getauscht += 1
        elif z["lehrplan_fach"] == "SEK1.D" and z["bildungsstandard_shard"] == "D8":
            z["bildungsstandard_shard"] = "D4"
            getauscht += 1

    assert getauscht == 9
    assert len(mutiert["zuordnungen"]) == 50
    assert len(list(validator.iter_errors(mutiert))) == getauscht


def test_schema_faengt_ein_fehlendes_shard_feld_statt_still_durchzulassen():
    """`then` fuehrt kein eigenes `required`, haelt also nur, solange
    `bildungsstandard_shard` auf Zuordnungsebene `required` bleibt. Faellt das weg,
    liefe die Paarungsregel ins Leere (`if` ohne Treffer => Teilschema gilt als erfuellt).
    Dieser Test bindet die Voraussetzung fest.
    """
    schema = laden(SCHEMA_PATH)
    assert "bildungsstandard_shard" in schema["$defs"]["zuordnung"]["required"]

    validator = jsonschema.Draft202012Validator(schema)
    mutiert = laden(CROSSWALK_PATH)
    del mutiert["zuordnungen"][0]["bildungsstandard_shard"]
    assert list(validator.iter_errors(mutiert))


def test_schema_beschraenkt_nicht_abgedeckt_auf_prim_su():
    """`nicht_abgedeckt.lehrplan_fach` war ein freier String; PRIM.SU ist der einzige
    legitime Eintrag, weil nur fuer Sachunterricht keine Bildungsstandards verordnet sind.
    """
    schema = laden(SCHEMA_PATH)
    validator = jsonschema.Draft202012Validator(schema)

    validator.validate(laden(CROSSWALK_PATH))

    for fremd in ("PRIM.D", "SEK1.M", "SEK1.E"):
        mutiert = laden(CROSSWALK_PATH)
        assert mutiert["nicht_abgedeckt"], "nicht_abgedeckt ist leer -- Test waere wirkungslos"
        mutiert["nicht_abgedeckt"][0]["lehrplan_fach"] = fremd
        assert list(validator.iter_errors(mutiert)), f"Schema akzeptiert nicht_abgedeckt {fremd}"
