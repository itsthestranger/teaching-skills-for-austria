"""Static data invariant: a domain scope stated in `Notes` must be encoded in `Conditional`.

`evals/README.md` (lines 41, 147) defines `Conditional` as the column that makes a
criterion skippable; `Notes` is only "Begründung oder Design-Notizen" (rationale /
design notes). Nothing executes these rubrics (V-85: no code anywhere reads
`evals/`, there is no runner, `.github/` does not exist) -- `Conditional` is
honoured by a human or model reader, not by an executor. So a domain restriction
stated only in prose in `Notes` is invisible to whoever is applying `Conditional`,
and a criterion silently gets graded outside its intended scope (V-84 / review
finding R-01: 13 of 14 Sachunterricht science/society rows carried their domain
scope only in `Notes`, leaving `Conditional` empty).

This test does not build or exercise an eval runner -- there is no skipping
behaviour to test. It asserts a static data invariant over the CSV rows
themselves, across all six rubric CSVs: whenever a row's `Notes` text asserts a
known domain/subject-area scope, that row's `Conditional` must carry a matching
slug. The check is keyed on the *wording of `Notes`*, not on a fixed list of row
IDs, so it also catches the defect if a future or renamed row restates one of
these scopes in `Notes` without encoding it in `Conditional`.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

RUBRIC_CSVS = (
    REPO_ROOT / "evals" / "at-unterrichtsplanung" / "rubrics" / "shared.csv",
    REPO_ROOT / "evals" / "at-unterrichtsplanung" / "rubrics" / "mathematik.csv",
    REPO_ROOT / "evals" / "at-unterrichtsplanung" / "rubrics" / "deutsch.csv",
    REPO_ROOT / "evals" / "at-unterrichtsplanung" / "rubrics" / "sachunterricht.csv",
    REPO_ROOT / "evals" / "at-differenzierung" / "rubrics" / "rueckfrage.csv",
    REPO_ROOT / "evals" / "at-differenzierung" / "rubrics" / "differenzierung.csv",
)

HEADER = ["ID", "Bucket", "Criterion", "What pass requires", "Notes", "Conditional"]

#: Each entry is (human label, a regex over `Notes` that identifies a stated
#: domain/subject-area scope, the substring that must then appear somewhere in
#: `Conditional`). Regexes match on word stems (`\w*` / `.` for the inflected
#: adjective ending and for the en-dash in stage ranges like "3-4"), so minor
#: wording variation does not defeat the check -- the scope statement itself
#: is what triggers the requirement, not an exact string match on one row.
SCOPE_RULES: tuple[tuple[str, str, str], ...] = (
    (
        "PRIM.SU Naturwissenschaft/Technik",
        r"Naturwissenschaftlic\w*\s+oder\s+Technisch\w*\s+Kompetenzbereich",
        "PRIM.SU-Naturwissenschaft",
    ),
    (
        "PRIM.SU Gesellschaft (Sozialwiss./Geografie/Geschichte/Wirtschaft)",
        r"Sozialwissenschaftlic\w*,\s*Geografisch\w*,\s*Historisch\w*\s+oder\s+Wirtschaftlic\w*\s+Kompetenzbereich",
        "PRIM.SU-Gesellschaft",
    ),
    (
        "PRIM.SU quantitative Daten, Schulstufe 3-4",
        r"nur bei quantitativen Daten in Schulstufe 3.4",
        "PRIM.SU-SCH3-4-quantitative-daten",
    ),
    (
        "PRIM.D Schriftspracherwerb, 1.-2. Schulstufe",
        r"Schriftspracherwerb in der 1\..2\. Schulstufe",
        "PRIM.D-SCH1-2-Schriftspracherwerb",
    ),
    (
        "SEK1.D argumentierendes Schreiben, K4",
        r"argumentierendes Schreiben in SEK1\.D,\s*4\.\s*Klasse",
        "SEK1.D-K4-argumentierendes-schreiben",
    ),
)


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames == HEADER, f"{path.name}: unexpected header {reader.fieldnames}"
        return [row for row in reader if any(value.strip() for value in row.values())]


def test_rubric_csvs_are_the_expected_six() -> None:
    for path in RUBRIC_CSVS:
        assert path.is_file(), f"missing rubric file: {path}"


@pytest.mark.parametrize("path", RUBRIC_CSVS, ids=lambda p: p.name)
def test_notes_domain_scope_is_encoded_in_conditional(path: Path) -> None:
    """No row may assert a domain/subject-area scope in `Notes` that its
    `Conditional` does not encode. If someone reintroduces the defect -- adds
    or restores a row whose `Notes` states one of the known scopes above
    while leaving `Conditional` empty or without the matching slug -- this
    fails, regardless of the row's ID.
    """
    rows = _read_rows(path)
    failures = []
    for row in rows:
        notes = row["Notes"]
        conditional = row["Conditional"]
        for scope_name, notes_pattern, required_slug in SCOPE_RULES:
            if re.search(notes_pattern, notes) and required_slug not in conditional:
                failures.append(
                    f"{row['ID']}: Notes asserts scope [{scope_name}] but "
                    f"Conditional ({conditional!r}) does not encode {required_slug!r}"
                )
    assert not failures, "\n".join(failures)


def test_r_s2_carries_both_its_domain_scope_and_its_quantitative_condition() -> None:
    """R-S2 is the row the review singled out as *not* already correct: its
    `Conditional` already carried the quantitative-data condition, but its
    `Notes` additionally assert the Naturwissenschaft/Technik domain scope,
    which stayed unencoded. Both conditions must be present in one cell.
    """
    rows = _read_rows(
        REPO_ROOT / "evals" / "at-unterrichtsplanung" / "rubrics" / "sachunterricht.csv"
    )
    row = next(r for r in rows if r["ID"] == "R-S2")
    assert "PRIM.SU-Naturwissenschaft" in row["Conditional"]
    assert "PRIM.SU-SCH3-4-quantitative-daten" in row["Conditional"]
