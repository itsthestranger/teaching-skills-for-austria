"""Tests for detect_amendment.py (E10-07).

Run:  .venv/bin/python -m pytest data-pipeline/tests/test_detect_amendment.py -q

The acceptance criterion is "detects a synthetic amendment in tests". Every field class named in
the backlog row (NOR, ELI, Kundmachungsorgan, in-force date, out-of-force date, per-file SHA-256)
gets its own synthetic mutation and its own assertion that the mutation is caught -- and every
mutation asserts the *category* the report assigns it, not just that something was flagged, since
distinguishing an amendment/repeal from a silent re-publication is the point of the task. The
no-change case is asserted to exit clean so the check cannot be vacuously passing.

Manifests here are built in-memory or under ``tmp_path`` -- nothing in this module ever mutates
``data-pipeline/resources/manifest.json`` on disk. The committed manifest is used read-only, as
the real baseline, in the read-only checks at the bottom.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_DATA_PIPELINE = _HERE.parent
sys.path.insert(0, str(_DATA_PIPELINE))

import detect_amendment as A  # noqa: E402

REAL_BASELINE_PATH = _DATA_PIPELINE / "resources" / "manifest.json"


# --------------------------------------------------------------------------
# Fixture builder -- a minimal, realistic two-document manifest.
# --------------------------------------------------------------------------


def _document(
    *,
    nor: str = "NOR40255561",
    eli: str = "https://ris.bka.gv.at/eli/bgbl/ii/2009/1/ANL1/NOR40255561",
    gesetzesnummer: str = "20006166",
    kundmachungsorgan: str = "BGBl. II Nr. 1/2009 zuletzt geändert durch BGBl. II Nr. 262/2023 ",
    inkrafttretensdatum: str = "2023-09-09",
    ausserkrafttretensdatum: str | None = None,
    pdf_sha256: str = "a" * 64,
    xml_sha256: str = "b" * 64,
) -> dict:
    return {
        "nor": nor,
        "eli": eli,
        "gesetzesnummer": gesetzesnummer,
        "kundmachungsorgan": kundmachungsorgan,
        "inkrafttretensdatum": inkrafttretensdatum,
        "ausserkrafttretensdatum": ausserkrafttretensdatum,
        "artikel_paragraph_anlage": "Anl. 1",
        "disambiguated": False,
        "dokument_url": "https://www.ris.bka.gv.at/eli/bgbl/ii/2009/1/ANL1/NOR40255561",
        "fallback_used": False,
        "files": {
            "pdf": {"sha256": pdf_sha256, "size": 324098},
            "xml": {"sha256": xml_sha256, "size": 81009},
        },
        "images": {},
        "kurztitel": "Testverordnung",
        "retrieval_date": "2026-07-27",
    }


def _manifest() -> dict:
    return {
        "bildungsstandards": _document(),
        "mittelschule": _document(
            nor="NOR40271471",
            eli="https://ris.bka.gv.at/eli/bgbl/ii/2012/185/ANL1/NOR40271471",
            gesetzesnummer="20007850",
            kundmachungsorgan="BGBl. II Nr. 185/2012 zuletzt geändert durch BGBl. II Nr. 178/2025 ",
            inkrafttretensdatum="2025-09-01",
            pdf_sha256="c" * 64,
            xml_sha256="d" * 64,
        ),
    }


# --------------------------------------------------------------------------
# No-change case -- must exit clean, or the check would be vacuously passing.
# --------------------------------------------------------------------------


def test_identical_manifests_have_no_divergence() -> None:
    baseline = _manifest()
    candidate = copy.deepcopy(baseline)
    assert A.diff_manifests(baseline, candidate) == []


def test_identical_manifests_cli_exits_zero(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    candidate_path = tmp_path / "candidate.json"
    manifest = _manifest()
    baseline_path.write_text(json.dumps(manifest), encoding="utf-8")
    candidate_path.write_text(json.dumps(copy.deepcopy(manifest)), encoding="utf-8")

    code = A._cli(["--baseline", str(baseline_path), "--candidate", str(candidate_path)])
    assert code == 0


# --------------------------------------------------------------------------
# Synthetic amendments -- one per field class named in the backlog row.
# --------------------------------------------------------------------------


def test_detects_new_nor() -> None:
    baseline = _manifest()
    candidate = copy.deepcopy(baseline)
    candidate["bildungsstandards"]["nor"] = "NOR99999999"

    divergences = A.diff_manifests(baseline, candidate)
    assert len(divergences) == 1
    d = divergences[0]
    assert d.document == "bildungsstandards"
    assert d.field == "nor"
    assert d.category == A.CATEGORY_AMENDMENT
    assert d.baseline == "NOR40255561"
    assert d.candidate == "NOR99999999"


def test_detects_new_eli() -> None:
    baseline = _manifest()
    candidate = copy.deepcopy(baseline)
    candidate["bildungsstandards"]["eli"] = "https://ris.bka.gv.at/eli/bgbl/ii/2009/1/ANL1/NOR99999999"

    divergences = A.diff_manifests(baseline, candidate)
    assert len(divergences) == 1
    assert divergences[0].field == "eli"
    assert divergences[0].category == A.CATEGORY_AMENDMENT


def test_detects_new_kundmachungsorgan() -> None:
    """The "zuletzt geändert durch BGBl. II Nr. X/Y" suffix is exactly what changes when RIS
    incorporates a new amending regulation into the consolidated text -- the most realistic
    amendment signal of the identity fields."""
    baseline = _manifest()
    candidate = copy.deepcopy(baseline)
    candidate["mittelschule"]["kundmachungsorgan"] = (
        "BGBl. II Nr. 185/2012 zuletzt geändert durch BGBl. II Nr. 999/2026 "
    )

    divergences = A.diff_manifests(baseline, candidate)
    assert len(divergences) == 1
    d = divergences[0]
    assert d.document == "mittelschule"
    assert d.field == "kundmachungsorgan"
    assert d.category == A.CATEGORY_AMENDMENT


def test_detects_new_inkrafttretensdatum() -> None:
    baseline = _manifest()
    candidate = copy.deepcopy(baseline)
    candidate["mittelschule"]["inkrafttretensdatum"] = "2026-09-01"

    divergences = A.diff_manifests(baseline, candidate)
    assert len(divergences) == 1
    assert divergences[0].field == "inkrafttretensdatum"
    assert divergences[0].category == A.CATEGORY_AMENDMENT


def test_detects_newly_set_ausserkrafttretensdatum_as_repeal_not_amendment() -> None:
    baseline = _manifest()
    candidate = copy.deepcopy(baseline)
    candidate["bildungsstandards"]["ausserkrafttretensdatum"] = "2027-08-31"

    divergences = A.diff_manifests(baseline, candidate)
    assert len(divergences) == 1
    d = divergences[0]
    assert d.field == "ausserkrafttretensdatum"
    assert d.category == A.CATEGORY_REPEAL
    assert d.category != A.CATEGORY_AMENDMENT
    assert d.baseline is None
    assert d.candidate == "2027-08-31"


def test_detects_moved_ausserkrafttretensdatum() -> None:
    baseline = _manifest()
    baseline["bildungsstandards"]["ausserkrafttretensdatum"] = "2027-08-31"
    candidate = copy.deepcopy(baseline)
    candidate["bildungsstandards"]["ausserkrafttretensdatum"] = "2028-01-01"

    divergences = A.diff_manifests(baseline, candidate)
    assert len(divergences) == 1
    assert divergences[0].category == A.CATEGORY_REPEAL


def test_detects_changed_pdf_sha256_as_silent_republication() -> None:
    baseline = _manifest()
    candidate = copy.deepcopy(baseline)
    candidate["bildungsstandards"]["files"]["pdf"]["sha256"] = "e" * 64

    divergences = A.diff_manifests(baseline, candidate)
    assert len(divergences) == 1
    d = divergences[0]
    assert d.document == "bildungsstandards"
    assert d.field == "files.pdf.sha256"
    assert d.category == A.CATEGORY_SILENT_REPUBLICATION
    assert d.category not in (A.CATEGORY_AMENDMENT, A.CATEGORY_REPEAL)


def test_detects_changed_xml_sha256_as_silent_republication() -> None:
    baseline = _manifest()
    candidate = copy.deepcopy(baseline)
    candidate["mittelschule"]["files"]["xml"]["sha256"] = "f" * 64

    divergences = A.diff_manifests(baseline, candidate)
    assert len(divergences) == 1
    assert divergences[0].field == "files.xml.sha256"
    assert divergences[0].category == A.CATEGORY_SILENT_REPUBLICATION


def test_sha256_change_accompanying_identity_change_is_categorized_as_amendment() -> None:
    """The distinction the task calls out by name: a changed hash alongside a changed NOR/date is
    not a second, independent "silent re-publication" event -- it is the expected consequence of
    the amendment already detected on that document."""
    baseline = _manifest()
    candidate = copy.deepcopy(baseline)
    candidate["mittelschule"]["inkrafttretensdatum"] = "2026-09-01"
    candidate["mittelschule"]["files"]["xml"]["sha256"] = "f" * 64

    divergences = A.diff_manifests(baseline, candidate)
    assert len(divergences) == 2
    by_field = {d.field: d for d in divergences}
    assert by_field["inkrafttretensdatum"].category == A.CATEGORY_AMENDMENT
    assert by_field["files.xml.sha256"].category == A.CATEGORY_AMENDMENT
    assert by_field["files.xml.sha256"].category != A.CATEGORY_SILENT_REPUBLICATION


def test_detects_document_removed() -> None:
    baseline = _manifest()
    candidate = copy.deepcopy(baseline)
    del candidate["mittelschule"]

    divergences = A.diff_manifests(baseline, candidate)
    assert len(divergences) == 1
    d = divergences[0]
    assert d.document == "mittelschule"
    assert d.category == A.CATEGORY_DOCUMENT_REMOVED


def test_detects_document_added() -> None:
    baseline = _manifest()
    candidate = copy.deepcopy(baseline)
    candidate["volksschule"] = _document(nor="NOR40271469", gesetzesnummer="10009275")

    divergences = A.diff_manifests(baseline, candidate)
    assert len(divergences) == 1
    d = divergences[0]
    assert d.document == "volksschule"
    assert d.category == A.CATEGORY_DOCUMENT_ADDED


def test_multiple_documents_changing_are_all_reported_independently() -> None:
    baseline = _manifest()
    candidate = copy.deepcopy(baseline)
    candidate["bildungsstandards"]["nor"] = "NOR99999999"
    candidate["mittelschule"]["ausserkrafttretensdatum"] = "2027-01-01"

    divergences = A.diff_manifests(baseline, candidate)
    documents_flagged = {d.document for d in divergences}
    assert documents_flagged == {"bildungsstandards", "mittelschule"}
    by_doc = {d.document: d for d in divergences}
    assert by_doc["bildungsstandards"].category == A.CATEGORY_AMENDMENT
    assert by_doc["mittelschule"].category == A.CATEGORY_REPEAL


# --------------------------------------------------------------------------
# Report content -- "names exactly which document and which field changed".
# --------------------------------------------------------------------------


def test_text_report_names_the_document_and_field() -> None:
    baseline = _manifest()
    candidate = copy.deepcopy(baseline)
    candidate["bildungsstandards"]["nor"] = "NOR99999999"

    divergences = A.diff_manifests(baseline, candidate)
    text = A.format_text(divergences, Path("baseline.json"), Path("candidate.json"))
    assert "bildungsstandards" in text
    assert "nor" in text
    assert "NOR99999999" in text
    assert A.CATEGORY_LABEL[A.CATEGORY_AMENDMENT] in text


def test_json_report_is_valid_and_carries_category_counts() -> None:
    baseline = _manifest()
    candidate = copy.deepcopy(baseline)
    candidate["bildungsstandards"]["ausserkrafttretensdatum"] = "2027-08-31"
    candidate["mittelschule"]["files"]["pdf"]["sha256"] = "9" * 64

    divergences = A.diff_manifests(baseline, candidate)
    payload = json.loads(A.format_json(divergences, Path("baseline.json"), Path("candidate.json")))
    assert payload["counts"][A.CATEGORY_REPEAL] == 1
    assert payload["counts"][A.CATEGORY_SILENT_REPUBLICATION] == 1
    fields = {d["field"] for d in payload["divergences"]}
    assert fields == {"ausserkrafttretensdatum", "files.pdf.sha256"}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _write(tmp_path: Path, name: str, manifest: dict) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def test_cli_exits_1_and_prints_the_finding_on_a_synthetic_amendment(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    baseline = _manifest()
    candidate = copy.deepcopy(baseline)
    candidate["bildungsstandards"]["nor"] = "NOR99999999"
    baseline_path = _write(tmp_path, "baseline.json", baseline)
    candidate_path = _write(tmp_path, "candidate.json", candidate)

    code = A._cli(["--baseline", str(baseline_path), "--candidate", str(candidate_path)])
    out = capsys.readouterr().out
    assert code == 1
    assert "bildungsstandards" in out
    assert "nor" in out


def test_cli_json_output_matches_exit_code(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    baseline = _manifest()
    candidate = copy.deepcopy(baseline)
    candidate["mittelschule"]["eli"] = "https://ris.bka.gv.at/eli/bgbl/ii/2012/185/ANL1/NOR99999999"
    baseline_path = _write(tmp_path, "baseline.json", baseline)
    candidate_path = _write(tmp_path, "candidate.json", candidate)

    code = A._cli(["--baseline", str(baseline_path), "--candidate", str(candidate_path), "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert code == 1
    assert sum(payload["counts"].values()) == len(payload["divergences"]) == 1


def test_cli_returns_2_for_missing_baseline(tmp_path: Path) -> None:
    candidate_path = _write(tmp_path, "candidate.json", _manifest())
    code = A._cli(["--baseline", str(tmp_path / "no-such-file.json"), "--candidate", str(candidate_path)])
    assert code == 2


def test_cli_returns_2_for_missing_candidate(tmp_path: Path) -> None:
    baseline_path = _write(tmp_path, "baseline.json", _manifest())
    code = A._cli(["--baseline", str(baseline_path), "--candidate", str(tmp_path / "no-such-file.json")])
    assert code == 2


def test_cli_returns_2_for_non_object_json(tmp_path: Path) -> None:
    baseline_path = _write(tmp_path, "baseline.json", _manifest())
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text("[1, 2, 3]", encoding="utf-8")
    code = A._cli(["--baseline", str(baseline_path), "--candidate", str(candidate_path)])
    assert code == 2


# --------------------------------------------------------------------------
# The real committed baseline -- read-only. Proves the module can run offline
# against the tracked reference manifest without data-pipeline/resources/
# being otherwise populated.
# --------------------------------------------------------------------------


def test_real_baseline_manifest_is_tracked_and_loadable() -> None:
    assert REAL_BASELINE_PATH.is_file(), (
        "data-pipeline/resources/manifest.json must be committed as the reference baseline "
        "-- detect_amendment.py has nothing to diff against otherwise"
    )
    manifest = A.load_manifest(REAL_BASELINE_PATH)
    assert set(manifest) == {"bildungsstandards", "mittelschule", "volksschule"}


def test_real_baseline_diffed_against_itself_is_clean() -> None:
    manifest = A.load_manifest(REAL_BASELINE_PATH)
    candidate = copy.deepcopy(manifest)
    assert A.diff_manifests(manifest, candidate) == []


def test_real_baseline_cli_exits_zero_against_a_copy_of_itself(tmp_path: Path) -> None:
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(REAL_BASELINE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    code = A._cli(["--baseline", str(REAL_BASELINE_PATH), "--candidate", str(candidate_path)])
    assert code == 0


def test_real_baseline_detects_a_synthetic_amendment_on_the_real_document(tmp_path: Path) -> None:
    """The acceptance criterion, run against the actual committed manifest rather than the
    synthetic fixture above: a mutated copy of the real baseline must be detected."""
    manifest = A.load_manifest(REAL_BASELINE_PATH)
    candidate = copy.deepcopy(manifest)
    candidate["volksschule"]["kundmachungsorgan"] = (
        "BGBl. Nr. 134/1963 zuletzt geändert durch BGBl. II Nr. 999/2027 "
    )
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(json.dumps(candidate, ensure_ascii=False), encoding="utf-8")

    code = A._cli(["--baseline", str(REAL_BASELINE_PATH), "--candidate", str(candidate_path)])
    assert code == 1

    divergences = A.diff_manifests(manifest, candidate)
    assert len(divergences) == 1
    assert divergences[0].document == "volksschule"
    assert divergences[0].category == A.CATEGORY_AMENDMENT
