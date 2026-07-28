"""Tests for validate_dataset.py (E3-06).

Run:  .venv/bin/python -m pytest data-pipeline/tests -q

The acceptance criterion is explicitly "both paths exercised": a hard-rule
fixture must fail with a non-zero exit code and the collision/missing-field
reported, and a soft-rule fixture must exit 0 while every surprise is still
reported. All fixtures are built in ``tmp_path`` -- nothing here ever reads
or writes ``plugin/data/`` except the read-only "real dataset" checks at the
bottom, which assert the shipped dataset has no hard findings (the actual
CI-relevant contract) without assuming it is perfectly free of soft ones.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_DATA_PIPELINE = _HERE.parent
sys.path.insert(0, str(_DATA_PIPELINE))
sys.path.insert(0, str(_DATA_PIPELINE / "schema"))

import validate_dataset as V  # noqa: E402

REAL_KOMPETENZEN_ROOT = _DATA_PIPELINE.parent / "plugin" / "data" / "kompetenzen"
REAL_REGISTRY_PATH = _DATA_PIPELINE.parent / "plugin" / "data" / "abbildungen" / "registry.json"
REAL_SCHEMA_PATH = _DATA_PIPELINE / "schema" / "kompetenzen.schema.json"
REAL_PLUGIN_ROOT = _DATA_PIPELINE.parent / "plugin"


# --------------------------------------------------------------------------
# Fixture builders -- minimal, schema-valid documents in the split shape.
# --------------------------------------------------------------------------


def _meta(*, band: str = "SEK1", fach_code: str = "M", fach_name: str = "Mathematik") -> dict:
    return {
        "dataset_version": "2026-01-01",
        "band": band,
        "fach": {"code": fach_code, "name": fach_name},
        "differenzierungs_achse": {"typ": "standard_standardplus"},
        "anwendungsbereiche_status": "item_flags",
        "provenienz": {
            "quelle": "RIS Bundesrecht konsolidiert",
            "kurztitel": "Testlehrplan",
            "nor": "NOR00000000",
            "kundmachung": "BGBl. II Nr. 1/2020",
            "anlage": "Anl. 1",
            "teil": "ACHTER TEIL",
            "stand": "2026-01-01",
        },
    }


def _kompetenz(ident: str, *, stufe: str = "K1", text: str = "Ein Beispieltext.", **extra) -> dict:
    d = {"id": ident, "stufe": stufe, "text": text}
    d.update(extra)
    return d


def _anwendungsitem(ident: str, *, stufe: str = "K1", text: str = "Ein Praezisierung.", kompetenz_id=None, **extra) -> dict:
    d = {"id": ident, "stufe": stufe, "text": text, "kompetenz_id": kompetenz_id}
    d.update(extra)
    return d


def _bereich_doc(nummer: int, slug: str, name: str, kompetenzen: list[dict], **meta_kw) -> dict:
    return {
        "meta": _meta(**meta_kw),
        "kompetenzbereiche": [{"nummer": nummer, "slug": slug, "name": name, "kompetenzen": kompetenzen}],
    }


def _zusatz_doc(zusatzkompetenzen=None, digitale_technologien=None, **meta_kw) -> dict:
    return {
        "meta": _meta(**meta_kw),
        "kompetenzbereiche": [],
        "zusatzkompetenzen": zusatzkompetenzen or [],
        "digitale_technologien_vorschlaege": digitale_technologien or [],
    }


def write_shard(tmp_path: Path, parts: dict[str, dict], *, band: str = "sek1", fach: str = "m", index: dict | None = None) -> Path:
    """Write *parts* (filename -> document) under
    ``tmp_path/kompetenzen/<band>/<fach>/`` and return the ``kompetenzen``
    root (what ``--root``/``kompetenzen_root`` expects)."""
    shard_dir = tmp_path / "kompetenzen" / band / fach
    shard_dir.mkdir(parents=True)
    for name, doc in parts.items():
        (shard_dir / name).write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    if index is not None:
        (shard_dir / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return tmp_path / "kompetenzen"


def _run(tmp_path: Path, kompetenzen_root: Path, *, registry: dict | None = None) -> V.Report:
    # Default to an empty-but-present registry.json so tests that don't
    # care about images aren't polluted by an incidental "registry-missing"
    # soft finding; tests that specifically want that finding write no
    # registry.json themselves via the CLI path instead.
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(registry or {}, ensure_ascii=False), encoding="utf-8")
    return V.run_validation(
        kompetenzen_root=kompetenzen_root,
        registry_path=registry_path,
        schema_path=V.DEFAULT_SCHEMA_PATH,
        plugin_root=tmp_path,
    )


# --------------------------------------------------------------------------
# HARD path -- duplicate ID across parts
# --------------------------------------------------------------------------


def test_duplicate_id_across_parts_is_hard_and_non_zero_exit(tmp_path: Path) -> None:
    dup_id = "AT.LP23.SEK1.M.ZAHLEN.K1.01"
    parts = {
        "zahlen.json": _bereich_doc(1, "ZAHLEN", "Zahlen und Maße", [_kompetenz(dup_id)]),
        # The same ID minted again in a *different* part file -- this is the
        # case that matters: id_schema.validate_ids() must see the union
        # across all parts of the shard, not just one file at a time.
        "variablen.json": _bereich_doc(2, "VARIABLEN", "Variablen und Funktionen", [_kompetenz(dup_id)]),
    }
    root = write_shard(tmp_path, parts)
    report = _run(tmp_path, root)

    assert report.exit_code(strict=False) == 1
    collisions = [f for f in report.hard if f.rule == V.RULE_ID_COLLISION]
    assert len(collisions) == 1
    assert collisions[0].record_id == dup_id
    assert "zahlen.json" in collisions[0].message and "variablen.json" in collisions[0].message


def test_duplicate_id_within_a_single_part_is_also_hard(tmp_path: Path) -> None:
    dup_id = "AT.LP23.SEK1.M.ZAHLEN.K1.01"
    parts = {"zahlen.json": _bereich_doc(1, "ZAHLEN", "Zahlen und Maße", [_kompetenz(dup_id), _kompetenz(dup_id)])}
    root = write_shard(tmp_path, parts)
    report = _run(tmp_path, root)

    assert report.exit_code(strict=False) == 1
    assert any(f.rule == V.RULE_ID_COLLISION and f.record_id == dup_id for f in report.hard)


# --------------------------------------------------------------------------
# HARD path -- missing id / stufe / text, one case each
# --------------------------------------------------------------------------


@pytest.mark.parametrize("missing_field", ["id", "stufe", "text"])
def test_missing_required_field_is_hard_and_non_zero_exit(tmp_path: Path, missing_field: str) -> None:
    rec = _kompetenz("AT.LP23.SEK1.M.ZAHLEN.K1.01")
    del rec[missing_field]
    parts = {"zahlen.json": _bereich_doc(1, "ZAHLEN", "Zahlen und Maße", [rec])}
    root = write_shard(tmp_path, parts)
    report = _run(tmp_path, root)

    assert report.exit_code(strict=False) == 1
    hits = [f for f in report.hard if f.rule == V.RULE_MISSING_REQUIRED_FIELD]
    assert len(hits) == 1
    assert missing_field in hits[0].message


def test_missing_required_field_on_anwendungsitem_is_also_hard(tmp_path: Path) -> None:
    komp = _kompetenz("AT.LP23.SEK1.M.ZAHLEN.K1.01")
    item = _anwendungsitem("AT.LP23.SEK1.M.AB.ZAHLEN.K1.01", kompetenz_id=komp["id"])
    del item["text"]
    komp["anwendungsbereiche"] = [item]
    parts = {"zahlen.json": _bereich_doc(1, "ZAHLEN", "Zahlen und Maße", [komp])}
    root = write_shard(tmp_path, parts)
    report = _run(tmp_path, root)

    assert report.exit_code(strict=False) == 1
    hits = [f for f in report.hard if f.rule == V.RULE_MISSING_REQUIRED_FIELD]
    assert len(hits) == 1
    assert hits[0].record_id == item["id"]


def test_clean_fixture_has_no_hard_findings(tmp_path: Path) -> None:
    """Sanity check: a well-formed fixture (mirroring the missing-field
    cases minus the defect) produces zero hard findings, so the hard tests
    above are attributable to the injected defect, not fixture noise."""
    parts = {"zahlen.json": _bereich_doc(1, "ZAHLEN", "Zahlen und Maße", [_kompetenz("AT.LP23.SEK1.M.ZAHLEN.K1.01")])}
    root = write_shard(tmp_path, parts)
    report = _run(tmp_path, root)
    assert report.hard == []
    assert report.exit_code(strict=False) == 0


# --------------------------------------------------------------------------
# SOFT path -- unknown enum, dangling reference, orphaned token, oversize
# part, all reported, exit still 0. This is the more important direction:
# it proves tolerance is real, not accidental.
# --------------------------------------------------------------------------


def test_soft_findings_are_reported_but_exit_zero(tmp_path: Path) -> None:
    dangling_target = "AT.LP23.SEK1.M.ZAHLEN.K1.99"  # never minted anywhere
    orphan_token = "⟦ABB:nicht_registriert.png⟧"

    normal = _kompetenz("AT.LP23.SEK1.M.ZAHLEN.K1.01", vorlaeufer=[dangling_target])
    with_orphan_token = _kompetenz(
        "AT.LP23.SEK1.M.ZAHLEN.K1.02",
        text=f"Text mit Formel {orphan_token} und mehr.",
        abbildungen=[],  # no matching entry -- the token is orphaned
    )
    # Oversize: comfortably over both the 50 KB byte target and the 15k
    # approx.-token target (bytes // 4).
    oversize = _kompetenz("AT.LP23.SEK1.M.ZAHLEN.K1.03", text="x" * 70_000)
    # Unrecognised 'art' -- a genuinely tolerant position (schema leaves it
    # a free string); must be informational, never a failure.
    item_unknown_art = _anwendungsitem(
        "AT.LP23.SEK1.M.AB.ZAHLEN.K1.04", kompetenz_id="AT.LP23.SEK1.M.ZAHLEN.K1.04", art="neuartiger_typ"
    )
    komp_with_item = _kompetenz("AT.LP23.SEK1.M.ZAHLEN.K1.04", anwendungsbereiche=[item_unknown_art])

    parts = {
        "zahlen.json": _bereich_doc(
            1, "ZAHLEN", "Zahlen und Maße",
            [normal, with_orphan_token, oversize, komp_with_item],
        ),
    }
    root = write_shard(tmp_path, parts)
    report = _run(tmp_path, root)

    # The headline contract: soft/info findings never fail a plain run.
    assert report.hard == []
    assert report.exit_code(strict=False) == 0

    soft_rules = {f.rule for f in report.soft}
    assert V.RULE_DANGLING_REFERENCE in soft_rules
    assert V.RULE_ORPHAN_TOKEN in soft_rules
    assert V.RULE_SIZE_TARGET_EXCEEDED in soft_rules

    dangling = [f for f in report.soft if f.rule == V.RULE_DANGLING_REFERENCE]
    assert any(dangling_target in f.message for f in dangling)

    orphan = [f for f in report.soft if f.rule == V.RULE_ORPHAN_TOKEN]
    assert any(orphan_token in f.message for f in orphan)

    oversize_hits = [f for f in report.soft if f.rule == V.RULE_SIZE_TARGET_EXCEEDED]
    assert len(oversize_hits) == 1
    assert oversize_hits[0].part == "zahlen.json"

    info_rules = {f.rule for f in report.info}
    assert V.RULE_UNKNOWN_ENUM_VALUE in info_rules
    assert any(f.rule == V.RULE_UNKNOWN_ENUM_VALUE and "neuartiger_typ" in f.message for f in report.info)


def test_strict_promotes_soft_findings_to_a_failing_exit_code(tmp_path: Path) -> None:
    komp = _kompetenz("AT.LP23.SEK1.M.ZAHLEN.K1.01", vorlaeufer=["AT.LP23.SEK1.M.ZAHLEN.K9.99"])
    parts = {"zahlen.json": _bereich_doc(1, "ZAHLEN", "Zahlen und Maße", [komp])}
    root = write_shard(tmp_path, parts)
    report = _run(tmp_path, root)

    assert report.hard == []
    assert report.soft  # the dangling vorlaeufer
    assert report.exit_code(strict=False) == 0
    assert report.exit_code(strict=True) == 1


def test_strict_never_promotes_informational_findings(tmp_path: Path) -> None:
    """An unrecognised value in a genuinely tolerant position must never
    fail the run, not even under --strict -- promoting it would defeat the
    E2-16 tolerant-enum policy it exists to document."""
    doc = _bereich_doc(
        1, "ZAHLEN", "Zahlen und Maße", [_kompetenz("AT.LP23.SEK1.M.ZAHLEN.K1.01")],
        fach_code="ZZ",  # unrecognised subject code, tolerant position
    )
    parts = {"zahlen.json": doc}
    payload = json.dumps(doc, ensure_ascii=False, indent=2)
    index = {
        "meta": doc["meta"],
        "teile": [
            {
                "datei": "zahlen.json", "typ": "kompetenzbereich", "nummer": 1, "slug": "ZAHLEN",
                "name": "Zahlen und Maße", "kompetenzen": 1, "anwendungsitems": 0,
                "bytes": len(payload.encode("utf-8")), "tokens_approx": V.BD.approx_tokens(payload),
            }
        ],
    }
    root = write_shard(tmp_path, parts, index=index)
    report = _run(tmp_path, root)

    # No index-missing noise (a real index.json is provided, byte-for-byte
    # consistent) and no other structural surprise -- the *only* finding
    # this fixture should produce is the informational unknown-enum one.
    assert report.hard == []
    assert report.soft == []
    assert report.info
    assert report.exit_code(strict=False) == 0
    assert report.exit_code(strict=True) == 0


# --------------------------------------------------------------------------
# Image-token integrity: the other direction (abbildungen entry with no
# matching token in text) and the registry / on-disk-file checks.
# --------------------------------------------------------------------------


def test_abbildungen_entry_with_no_matching_token_is_soft(tmp_path: Path) -> None:
    komp = _kompetenz(
        "AT.LP23.SEK1.M.ZAHLEN.K1.01",
        text="Text ohne Formel.",
        abbildungen=[{"token": "⟦ABB:verwaist.png⟧", "datei": "verwaist.png", "pfad": "data/abbildungen/X/verwaist.png"}],
    )
    parts = {"zahlen.json": _bereich_doc(1, "ZAHLEN", "Zahlen und Maße", [komp])}
    root = write_shard(tmp_path, parts)
    report = _run(tmp_path, root)

    assert report.hard == []
    assert any(f.rule == V.RULE_ORPHAN_ABBILDUNG_ENTRY for f in report.soft)
    assert any(f.rule == V.RULE_ABBILDUNG_NOT_IN_REGISTRY for f in report.soft)
    assert any(f.rule == V.RULE_ABBILDUNG_FILE_MISSING for f in report.soft)


def test_abbildung_registered_but_missing_provenance_field_is_soft(tmp_path: Path) -> None:
    (tmp_path / "data" / "abbildungen" / "X").mkdir(parents=True)
    bild_pfad = tmp_path / "data" / "abbildungen" / "X" / "vorhanden.png"
    bild_pfad.write_bytes(b"\x89PNG\r\n")
    token = "⟦ABB:vorhanden.png⟧"
    komp = _kompetenz(
        "AT.LP23.SEK1.M.ZAHLEN.K1.01",
        text=f"Formel {token} hier.",
        abbildungen=[{"token": token, "datei": "vorhanden.png", "pfad": "data/abbildungen/X/vorhanden.png"}],
    )
    parts = {"zahlen.json": _bereich_doc(1, "ZAHLEN", "Zahlen und Maße", [komp])}
    root = write_shard(tmp_path, parts)
    incomplete_registry = {"vorhanden.png": {"nor": "NOR1", "quelle_url": "", "breite_px": 1, "hoehe_px": 1, "sha256": ""}}
    report = _run(tmp_path, root, registry=incomplete_registry)

    assert report.hard == []
    assert not any(f.rule == V.RULE_ABBILDUNG_FILE_MISSING for f in report.soft), "the file does exist on disk"
    assert not any(f.rule == V.RULE_ORPHAN_TOKEN for f in report.soft)
    assert not any(f.rule == V.RULE_ORPHAN_ABBILDUNG_ENTRY for f in report.soft)
    hits = [f for f in report.soft if f.rule == V.RULE_REGISTRY_ENTRY_INCOMPLETE]
    assert len(hits) == 1
    assert "quelle_url" in hits[0].message and "sha256" in hits[0].message


# --------------------------------------------------------------------------
# index.json consistency
# --------------------------------------------------------------------------


def test_index_json_part_list_mismatch_is_soft(tmp_path: Path) -> None:
    parts = {"zahlen.json": _bereich_doc(1, "ZAHLEN", "Zahlen und Maße", [_kompetenz("AT.LP23.SEK1.M.ZAHLEN.K1.01")])}
    index = {"meta": _meta(), "teile": [{"datei": "variablen.json", "typ": "kompetenzbereich"}]}
    root = write_shard(tmp_path, parts, index=index)
    report = _run(tmp_path, root)

    assert report.hard == []
    assert any(f.rule == V.RULE_INDEX_MISMATCH for f in report.soft)


def test_index_json_missing_is_soft(tmp_path: Path) -> None:
    parts = {"zahlen.json": _bereich_doc(1, "ZAHLEN", "Zahlen und Maße", [_kompetenz("AT.LP23.SEK1.M.ZAHLEN.K1.01")])}
    root = write_shard(tmp_path, parts)  # no index kwarg -> no index.json written
    report = _run(tmp_path, root)

    assert report.hard == []
    assert any(f.rule == V.RULE_INDEX_MISSING for f in report.soft)


# --------------------------------------------------------------------------
# Schema violation -- judgement call: soft, not hard (see module docstring
# and the final report). Confirmed here with a structurally invalid record
# (wrong type for a schema-typed field).
# --------------------------------------------------------------------------


def test_schema_violation_is_soft_not_hard(tmp_path: Path) -> None:
    komp = _kompetenz("AT.LP23.SEK1.M.ZAHLEN.K1.01", ordinal="not-an-integer")  # schema: ordinal is type integer
    parts = {"zahlen.json": _bereich_doc(1, "ZAHLEN", "Zahlen und Maße", [komp])}
    root = write_shard(tmp_path, parts)
    report = _run(tmp_path, root)

    assert report.hard == []
    assert any(f.rule == V.RULE_SCHEMA_VIOLATION for f in report.soft)
    assert report.exit_code(strict=False) == 0


# --------------------------------------------------------------------------
# Malformed ID: soft, distinct from the hard collision case.
# --------------------------------------------------------------------------


def test_malformed_id_is_soft_not_hard(tmp_path: Path) -> None:
    komp = _kompetenz("NOT-A-VALID-ID")
    parts = {"zahlen.json": _bereich_doc(1, "ZAHLEN", "Zahlen und Maße", [komp])}
    root = write_shard(tmp_path, parts)
    report = _run(tmp_path, root)

    assert report.hard == []
    hits = [f for f in report.soft if f.rule == V.RULE_MALFORMED_ID]
    assert len(hits) == 1
    assert hits[0].record_id == "NOT-A-VALID-ID"


# --------------------------------------------------------------------------
# Shard discovery: not hardcoded to sek1/m
# --------------------------------------------------------------------------


def test_discover_shards_finds_nothing_under_an_empty_root(tmp_path: Path) -> None:
    root = tmp_path / "kompetenzen"
    root.mkdir()
    (root / "prim").mkdir()  # band dir with no fach subdir at all -- like the real .gitkeep placeholders
    assert V.discover_shards(root) == []


def test_discover_shards_finds_any_band_fach_combination(tmp_path: Path) -> None:
    parts = {"lesen.json": _bereich_doc(1, "LESEN", "Lesen", [_kompetenz("AT.LP23.PRIM.D.LESEN.SCH1.01")])}
    root = write_shard(tmp_path, parts, band="prim", fach="d")
    shards = V.discover_shards(root)
    assert shards == [("PRIM", "D", root / "prim" / "d")]


def test_discover_shards_returns_empty_for_missing_root(tmp_path: Path) -> None:
    assert V.discover_shards(tmp_path / "does-not-exist") == []


# --------------------------------------------------------------------------
# Part-level JSON that fails to parse -- hard (see module docstring: this
# is treated as every record in it failing the required-field check).
# --------------------------------------------------------------------------


def test_unparseable_part_file_is_hard(tmp_path: Path) -> None:
    shard_dir = tmp_path / "kompetenzen" / "sek1" / "m"
    shard_dir.mkdir(parents=True)
    (shard_dir / "zahlen.json").write_text("{not valid json", encoding="utf-8")
    root = tmp_path / "kompetenzen"
    report = _run(tmp_path, root)

    assert report.exit_code(strict=False) == 1
    assert any(f.rule == V.RULE_PART_UNREADABLE for f in report.hard)


# --------------------------------------------------------------------------
# CLI: exit codes end to end
# --------------------------------------------------------------------------


def test_cli_exits_non_zero_on_hard_fixture(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    dup_id = "AT.LP23.SEK1.M.ZAHLEN.K1.01"
    parts = {"zahlen.json": _bereich_doc(1, "ZAHLEN", "Zahlen und Maße", [_kompetenz(dup_id), _kompetenz(dup_id)])}
    root = write_shard(tmp_path, parts)
    code = V._cli(["--root", str(root), "--schema", str(V.DEFAULT_SCHEMA_PATH), "--registry", str(tmp_path / "no-registry.json")])
    out = capsys.readouterr().out
    assert code == 1
    assert V.RULE_ID_COLLISION in out


def test_cli_exits_zero_on_soft_only_fixture(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    komp = _kompetenz("AT.LP23.SEK1.M.ZAHLEN.K1.01", vorlaeufer=["AT.LP23.SEK1.M.ZAHLEN.K9.99"])
    parts = {"zahlen.json": _bereich_doc(1, "ZAHLEN", "Zahlen und Maße", [komp])}
    root = write_shard(tmp_path, parts)
    code = V._cli(["--root", str(root), "--schema", str(V.DEFAULT_SCHEMA_PATH), "--registry", str(tmp_path / "no-registry.json")])
    assert code == 0

    code_strict = V._cli(
        ["--root", str(root), "--schema", str(V.DEFAULT_SCHEMA_PATH), "--registry", str(tmp_path / "no-registry.json"), "--strict"]
    )
    assert code_strict == 1


def test_cli_json_output_is_valid_and_matches_exit_code(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    parts = {"zahlen.json": _bereich_doc(1, "ZAHLEN", "Zahlen und Maße", [_kompetenz("AT.LP23.SEK1.M.ZAHLEN.K1.01")])}
    root = write_shard(tmp_path, parts)
    code = V._cli(["--root", str(root), "--schema", str(V.DEFAULT_SCHEMA_PATH), "--registry", str(tmp_path / "no-registry.json"), "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["exit_code"] == code == 0
    assert payload["shards_checked"] == ["SEK1.M"]


def test_cli_returns_2_for_missing_root(tmp_path: Path) -> None:
    code = V._cli(["--root", str(tmp_path / "does-not-exist"), "--schema", str(V.DEFAULT_SCHEMA_PATH)])
    assert code == 2


def test_cli_returns_2_for_missing_schema(tmp_path: Path) -> None:
    root = tmp_path / "kompetenzen"
    root.mkdir()
    code = V._cli(["--root", str(root), "--schema", str(tmp_path / "no-such-schema.json")])
    assert code == 2


# --------------------------------------------------------------------------
# The real shipped dataset -- what CI actually runs. Must have zero hard
# findings. Soft findings (if any) are asserted on specifically, not via a
# blanket "must be empty", so this test documents rather than hides them.
# --------------------------------------------------------------------------


pytestmark_real = pytest.mark.skipif(
    not REAL_KOMPETENZEN_ROOT.exists(), reason="shipped plugin/data/kompetenzen not present"
)


@pytestmark_real
def test_real_shipped_dataset_has_no_hard_findings() -> None:
    report = V.run_validation(
        kompetenzen_root=REAL_KOMPETENZEN_ROOT,
        registry_path=REAL_REGISTRY_PATH,
        schema_path=REAL_SCHEMA_PATH,
        plugin_root=REAL_PLUGIN_ROOT,
    )
    assert report.hard == [], f"unexpected hard findings in the shipped dataset: {report.hard!r}"
    assert "SEK1.M" in report.shards_checked

    # As of this build the shipped SEK1.M shard is also free of soft/info
    # findings (schema-clean, no dangling references, no orphaned image
    # tokens, every part within the §6.7 size target, no unrecognised enum
    # values). That is a real, verified fact about the current dataset, not
    # an assumption -- document it explicitly rather than silently
    # asserting an empty list. If a future shard genuinely introduces a
    # soft finding, replace this with an assertion on that specific finding
    # (per the E3-06 brief) instead of reverting to a blanket "must be
    # empty" check.
    assert report.soft == [], f"new soft finding(s) in the shipped dataset -- document them: {report.soft!r}"
    assert report.info == [], f"new info finding(s) in the shipped dataset -- document them: {report.info!r}"


@pytestmark_real
def test_real_shipped_dataset_cli_exits_zero() -> None:
    code = V._cli(
        [
            "--root", str(REAL_KOMPETENZEN_ROOT),
            "--registry", str(REAL_REGISTRY_PATH),
            "--schema", str(REAL_SCHEMA_PATH),
            "--plugin-root", str(REAL_PLUGIN_ROOT),
        ]
    )
    assert code == 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
