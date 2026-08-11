"""Guard: misconception data is either absent or properly sourced -- never invented.

Backlog E9-02's intent was "assert no misconception entry is model-generated".
E9-01 (human curation from subject-didactics literature) is deferred past v1.0,
so today the dataset ships **zero** misconception entries and
``finde_typische_fehlvorstellungen`` returns ``[]`` by construction.

That makes this guard cheap now and valuable later.  It does not merely assert
"the field is empty" -- that would go vacuous and stay green the day somebody
pastes in unsourced entries.  Instead it asserts the *invariant that matters*:

    every shipped misconception entry carries a ``quelle`` and ``amtlich: false``

which is trivially true over an empty set today, and becomes the real sign-off
check the moment E9-01 lands.  A model-generated entry -- which by definition has
no literature source -- fails it.

The second half keeps the rubric honest.  ``P16-AT`` grades curated misconceptions
and would fail *every* lesson while the dataset ships none, so it carries
``Conditional: fehlvorstellungen-kuratiert``.  That conditional must track reality
in both directions, or the rubrics silently grade the wrong thing (V-84/V-85:
nothing executes the rubrics, a human reads them).
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
KOMPETENZEN_ROOT = REPO_ROOT / "plugin" / "data" / "kompetenzen"
SHARED_RUBRIC = REPO_ROOT / "evals" / "at-unterrichtsplanung" / "rubrics" / "shared.csv"

FELD = "typische_fehlvorstellungen"
BEDINGUNG = "fehlvorstellungen-kuratiert"

sys.path.insert(0, str(REPO_ROOT / "plugin" / "scripts"))


def _shard_dateien() -> list[Path]:
    return sorted(p for p in KOMPETENZEN_ROOT.glob("*/*/*.json") if p.name != "index.json")


def _alle_eintraege() -> list[tuple[str, str, dict]]:
    """(shard, kompetenz_id, entry) for every shipped misconception entry."""
    treffer: list[tuple[str, str, dict]] = []
    for pfad in _shard_dateien():
        daten = json.loads(pfad.read_text(encoding="utf8"))
        shard = f"{pfad.parent.parent.name}/{pfad.parent.name}/{pfad.name}"
        for bereich in daten.get("kompetenzbereiche", []):
            for komp in bereich.get("kompetenzen", []):
                for eintrag in komp.get(FELD, []) or []:
                    treffer.append((shard, komp.get("id", "<ohne id>"), eintrag))
    return treffer


def test_shards_exist_so_this_guard_is_not_scanning_nothing():
    """Fail loudly if the glob breaks -- an empty sweep would pass everything."""
    dateien = _shard_dateien()
    assert len(dateien) >= 30, f"expected the six shards' parts, found {len(dateien)}"


@pytest.mark.parametrize("pflichtfeld", ["quelle", "lehrkraft_hinweis"])
def test_every_shipped_misconception_carries_its_provenance(pflichtfeld):
    """Vacuously true today; the real E9-02 sign-off once E9-01 lands."""
    fehlend = [
        f"{shard} {kid}" for shard, kid, e in _alle_eintraege() if not e.get(pflichtfeld)
    ]
    assert not fehlend, (
        f"misconception entries without '{pflichtfeld}' -- a model-generated entry "
        f"would look exactly like this: {fehlend[:5]}"
    )


def test_no_shipped_misconception_claims_to_be_official():
    verletzt = [
        f"{shard} {kid}" for shard, kid, e in _alle_eintraege() if e.get("amtlich") is not False
    ]
    assert not verletzt, (
        "misconception entries must be explicitly 'amtlich': false -- curated "
        f"didactics literature is never Verordnungstext: {verletzt[:5]}"
    )


def test_access_layer_returns_nothing_while_none_are_curated():
    """Pins the deliberate defined-empty contract, not an accident of the data."""
    import kompetenz

    if _alle_eintraege():
        pytest.skip("curated entries now ship; the always-empty contract no longer holds")
    assert kompetenz.finde_typische_fehlvorstellungen("AT.LP23.SEK1.M.ZAHLEN.K1.01") == []
    # A *well-formed* ID that resolves to nothing must behave identically: the
    # lookup failure is logged, not raised, because the answer is the same either way.
    assert kompetenz.finde_typische_fehlvorstellungen("AT.LP23.SEK1.M.ZAHLEN.K4.99") == []
    # A *malformed* ID is a different case and does still raise -- pinned here so the
    # distinction is not lost: only the not-found path is swallowed.
    with pytest.raises(kompetenz.KompetenzFehler):
        kompetenz.finde_typische_fehlvorstellungen("AT.LP23.GIBT.ES.NICHT.K1.99")


def _p16_at() -> dict:
    with SHARED_RUBRIC.open(encoding="utf8") as fh:
        for zeile in csv.DictReader(fh):
            if zeile["ID"] == "P16-AT":
                return zeile
    raise AssertionError("P16-AT is missing from shared.csv")


def test_p16_at_conditional_tracks_whether_curated_data_actually_ships():
    """Both directions: the rubric must not grade against data that is not there,
    and must not stay skipped once the data arrives."""
    bedingungen = [t.strip() for t in _p16_at()["Conditional"].split(";") if t.strip()]
    if _alle_eintraege():
        assert BEDINGUNG not in bedingungen, (
            "curated misconceptions now ship, so P16-AT must no longer be skipped -- "
            f"remove '{BEDINGUNG}' from its Conditional"
        )
    else:
        assert BEDINGUNG in bedingungen, (
            "the dataset ships no curated misconceptions, so P16-AT would fail every "
            f"lesson; it must carry '{BEDINGUNG}' in Conditional, found {bedingungen!r}"
        )


def test_p16_at_still_demands_a_source_when_it_does_apply():
    """The conditional must not be a way to quietly drop the sourcing requirement."""
    text = _p16_at()["What pass requires"]
    assert "Quelle" in text
    assert "amtlich" in text
