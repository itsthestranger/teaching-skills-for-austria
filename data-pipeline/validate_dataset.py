#!/usr/bin/env python3
"""Validate the *shipped* dataset on disk (E3-06).

This is the CI entry point (E10-02: "schema validation on every push -- hard
rules fail, soft rules report"). It is offline and deterministic: it reads
only files already on disk under ``plugin/data/`` and never touches the
network or the RIS source.

It is a **different job** from ``build_dataset.py``'s internal pre-flight
checks (e.g. ``assert_abbildungen_registry_complete``): the builder checks
its own in-memory ``ParseResult`` before writing; this module checks
*whatever is actually on disk*, independent of how it got there, and works
standalone against a shard this process never built.

Policy (plan section 0.1 / E2-16, "tolerant by default"): the **only** hard
failures are

* a record missing ``id``, ``stufe`` or ``text``, and
* an ID collision -- the same ID minted twice anywhere in one shard
  (across *all* of that shard's part files, not just within one).

Every other check -- schema violations, malformed IDs, dangling references,
orphaned image tokens, index.json drift, oversize parts, unrecognised enum
values in tolerant positions -- is a **soft finding**: reported, never
fatal. See the module docstring sections below for the judgement calls this
makes explicit (schema violations in particular).

Layout validated
-----------------
::

    plugin/data/kompetenzen/<band>/<fach>/<bereich-slug-lowercase>.json
    plugin/data/kompetenzen/<band>/<fach>/zusatz.json
    plugin/data/kompetenzen/<band>/<fach>/index.json
    plugin/data/abbildungen/registry.json

Shards are *discovered* by walking ``plugin/data/kompetenzen/`` -- a
``<band>/<fach>`` directory that contains at least one ``*.json`` file is a
shard. Nothing is hardcoded to ``sek1/m``; more shards can land later
without touching this file.

Exit codes
----------
``0``
    No hard findings. Soft (and informational) findings may still be
    present and are printed/reported -- this is the expected, common case.
``1``
    At least one hard finding, **or** (with ``--strict``) at least one soft
    finding. Informational findings never affect the exit code, even under
    ``--strict`` -- promoting them would defeat the point of the E2-16
    tolerant-enum policy they exist to document.
``2``
    Usage/environment error: a required path (``--root``, ``--schema``)
    does not exist. Not a dataset finding -- the process could not even
    start checking.

Usage
-----
::

    .venv/bin/python data-pipeline/validate_dataset.py
    .venv/bin/python data-pipeline/validate_dataset.py --json
    .venv/bin/python data-pipeline/validate_dataset.py --strict

stdlib + ``jsonschema`` only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import jsonschema

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "schema"))

import build_dataset as BD  # noqa: E402 -- reused: approx_tokens(), the §6.7 size targets
import id_schema as ID  # noqa: E402 -- reused: validate_ids(), FAECHER
import parse_lehrplan as PL  # noqa: E402 -- reused: ERWARTET_BY_SPEC, the frozen expected counts

PLUGIN_ROOT = HERE.parent / "plugin"
DEFAULT_KOMPETENZEN_ROOT = PLUGIN_ROOT / "data" / "kompetenzen"
DEFAULT_REGISTRY_PATH = PLUGIN_ROOT / "data" / "abbildungen" / "registry.json"
DEFAULT_SCHEMA_PATH = HERE / "schema" / "kompetenzen.schema.json"

#: Every ⟦ABB:...⟧ token in a text (FINDINGS.md V-53). U+27E6/U+27E7 cannot
#: occur in the source text, so this pattern cannot false-positive on prose.
ABB_TOKEN_RE = re.compile(r"⟦ABB:[^⟧]*⟧")

#: The five provenance fields registry.json must carry per referenced image
#: (build_dataset.py::ABBILDUNG_REGISTRY_FELDER, duplicated here rather than
#: imported so this module's registry contract stays explicit and does not
#: silently drift if build_dataset's internal tuple is ever renamed).
REGISTRY_REQUIRED_FIELDS = ("nor", "quelle_url", "breite_px", "hoehe_px", "sha256")

#: Tolerant-position enum reference sets (plan section 0.1 / E2-16). An
#: unrecognised value here is reported as an *informational* finding, never
#: a failure -- these are deliberately open positions per the schema's own
#: comments (see schema/kompetenzen.schema.json's descriptions for
#: anwendungsitem.art, meta.fach.code and meta.differenzierungs_achse.typ).
KNOWN_ART_VALUES = frozenset({"praezisierung", "digitale_technologien"})  # FINDINGS V-54
KNOWN_DIFFERENZIERUNGS_ACHSE_TYPEN = frozenset(
    {"standard_standardplus", "gers", "lehrplan_generisch"}
)  # plan section 4.7

# --------------------------------------------------------------------------
# Rule identifiers -- stable strings so callers/tests can assert on them.
# --------------------------------------------------------------------------

# Hard (fail the run)
RULE_MISSING_REQUIRED_FIELD = "missing-required-field"
RULE_ID_COLLISION = "id-collision"
RULE_PART_UNREADABLE = "part-unreadable"
RULE_REGISTRY_UNREADABLE = "registry-unreadable"

# Soft (reported, exit 0 unless --strict)
RULE_SCHEMA_VIOLATION = "schema-violation"
RULE_MALFORMED_ID = "malformed-id"
RULE_DANGLING_REFERENCE = "dangling-reference"
RULE_ORPHAN_TOKEN = "orphan-token-no-abbildung-entry"
RULE_ORPHAN_ABBILDUNG_ENTRY = "orphan-abbildung-entry-no-token"
RULE_ABBILDUNG_NOT_IN_REGISTRY = "abbildung-not-in-registry"
RULE_REGISTRY_ENTRY_INCOMPLETE = "registry-entry-incomplete"
RULE_ABBILDUNG_FILE_MISSING = "abbildung-file-missing"
RULE_INDEX_MISSING = "index-missing"
RULE_INDEX_UNREADABLE = "index-unreadable"
RULE_INDEX_MISMATCH = "index-mismatch"
RULE_SIZE_TARGET_EXCEEDED = "size-target-exceeded"
RULE_REGISTRY_MISSING = "registry-missing"
RULE_NO_SHARDS_FOUND = "no-shards-found"
RULE_UNKNOWN_AREA_CODE = "unknown-area-code"
RULE_KOMPETENZ_ID_NOT_ALLOWED = "kompetenz-id-not-allowed-for-binding"
RULE_AREA_FREE_ID_OUTSIDE_STUFE = "area-free-id-outside-stufe-binding"
RULE_VERBINDLICH_ANOMALY = "verbindlich-false-outside-sek1-m"
RULE_COUNT_MISMATCH = "count-mismatch-vs-frozen-expected"

# Informational (never a failure, even under --strict)
RULE_UNKNOWN_ENUM_VALUE = "unknown-enum-value"

HARD_RULES = frozenset(
    {RULE_MISSING_REQUIRED_FIELD, RULE_ID_COLLISION, RULE_PART_UNREADABLE, RULE_REGISTRY_UNREADABLE}
)
INFO_RULES = frozenset({RULE_UNKNOWN_ENUM_VALUE})


@dataclass(frozen=True)
class Finding:
    """One validation finding."""

    severity: str
    """``hard`` | ``soft`` | ``info``."""

    rule: str
    message: str
    shard: str | None = None
    """``<BAND>.<FACH>``, e.g. ``SEK1.M`` -- absent for dataset-wide findings."""
    part: str | None = None
    """Part filename, e.g. ``zahlen.json`` -- absent when not part-specific."""
    path: str | None = None
    """In-document location, e.g. ``kompetenzbereiche[0].kompetenzen[3]``."""
    record_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "rule": self.rule,
            "message": self.message,
            "shard": self.shard,
            "part": self.part,
            "path": self.path,
            "record_id": self.record_id,
        }


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    shards_checked: list[str] = field(default_factory=list)

    @property
    def hard(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "hard"]

    @property
    def soft(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "soft"]

    @property
    def info(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "info"]

    def exit_code(self, strict: bool) -> int:
        if self.hard:
            return 1
        if strict and self.soft:
            return 1
        return 0


def _finding(severity: str, rule: str, message: str, **kw) -> Finding:
    return Finding(severity=severity, rule=rule, message=message, **kw)


# --------------------------------------------------------------------------
# Shard discovery
# --------------------------------------------------------------------------


def discover_shards(kompetenzen_root: Path) -> list[tuple[str, str, Path]]:
    """Walk *kompetenzen_root* for ``<band>/<fach>/`` directories that hold
    at least one ``*.json`` file. Nothing is hardcoded to ``sek1/m`` -- more
    shards can appear later without a code change here. Returns
    ``(band, fach, dir)`` triples, ``band``/``fach`` upper-cased to match the
    ID scheme's own vocabulary (``SEK1.M``, not ``sek1/m``)."""
    shards: list[tuple[str, str, Path]] = []
    if not kompetenzen_root.is_dir():
        return shards
    for band_dir in sorted(p for p in kompetenzen_root.iterdir() if p.is_dir()):
        for fach_dir in sorted(p for p in band_dir.iterdir() if p.is_dir()):
            if any(fach_dir.glob("*.json")):
                shards.append((band_dir.name.upper(), fach_dir.name.upper(), fach_dir))
    return shards


# --------------------------------------------------------------------------
# Record walking -- mirrors the nested shard shape (schema/kompetenzen.schema.json)
# --------------------------------------------------------------------------


def iter_records(doc: dict) -> Iterator[tuple[str, str, dict, bool]]:
    """Yield ``(kind, path, record, is_stufe_block)`` for every Kompetenz /
    Anwendungsitem in one part document, ``kind`` in
    ``{"kompetenz", "anwendungsitem"}``. ``path`` is an in-document locator
    string, e.g. ``kompetenzbereiche[0].kompetenzen[3].anwendungsbereiche[1]``,
    used to identify a record that may not (yet) have a usable ``id``.

    ``is_stufe_block`` is True only for an ``anwendungsitem`` sourced from a
    ``meta.anwendungsbereiche_bloecke`` entry whose ``bindung`` is
    ``"stufe"`` (PRIM.D, PRIM.SU, E12-14 / plan section 5 B1) -- the one
    case where the *complete* block is deliberately repeated verbatim in
    every area part file of the shard, so the same item id legitimately
    recurs across parts (see ``validate_shard``'s ID-collision handling).
    It is False for every other record, including ``bindung: "bereich"``
    block items (SEK1.D): those are NOT repeated across parts (each area
    part file carries only its own blocks -- see
    ``build_dataset.py::build_anwendungsbereiche_bloecke``), so a repeated
    id there is a genuine collision, not by-design.
    """
    for bi, bereich in enumerate(doc.get("kompetenzbereiche") or []):
        if not isinstance(bereich, dict):
            continue
        for ki, k in enumerate(bereich.get("kompetenzen") or []):
            if not isinstance(k, dict):
                continue
            base = f"kompetenzbereiche[{bi}].kompetenzen[{ki}]"
            yield "kompetenz", base, k, False
            for ai, a in enumerate(k.get("anwendungsbereiche") or []):
                if isinstance(a, dict):
                    yield "anwendungsitem", f"{base}.anwendungsbereiche[{ai}]", a, False
    for zi, k in enumerate(doc.get("zusatzkompetenzen") or []):
        if isinstance(k, dict):
            yield "kompetenz", f"zusatzkompetenzen[{zi}]", k, False
    for di, a in enumerate(doc.get("digitale_technologien_vorschlaege") or []):
        if isinstance(a, dict):
            yield "anwendungsitem", f"digitale_technologien_vorschlaege[{di}]", a, False

    # --- meta.anwendungsbereiche_bloecke (E12-14): the coarse-attachment
    # container for bindung: bereich (SEK1.D) and bindung: stufe (PRIM.D,
    # PRIM.SU) items. Previously not walked at all here, so a missing
    # id/stufe/text inside a block went undetected -- see the module
    # docstring's rule list.
    meta = doc.get("meta")
    bloecke = meta.get("anwendungsbereiche_bloecke") if isinstance(meta, dict) else None
    if isinstance(bloecke, dict):
        for key in sorted(bloecke, key=str):
            block = bloecke[key]
            if not isinstance(block, dict):
                continue
            is_stufe_block = block.get("bindung") == "stufe"
            items = block.get("items")
            if not isinstance(items, list):
                continue
            for ii, a in enumerate(items):
                if isinstance(a, dict):
                    yield (
                        "anwendungsitem",
                        f"meta.anwendungsbereiche_bloecke[{key}].items[{ii}]",
                        a,
                        is_stufe_block,
                    )


# --------------------------------------------------------------------------
# Per-shard validation
# --------------------------------------------------------------------------


def validate_shard(
    band: str,
    fach: str,
    shard_dir: Path,
    registry: dict[str, dict],
    validator: jsonschema.Draft202012Validator,
    plugin_root: Path,
) -> list[Finding]:
    findings: list[Finding] = []
    shard_label = f"{band}.{fach}"

    part_paths = sorted(p for p in shard_dir.glob("*.json") if p.name != "index.json")
    parts: dict[str, dict] = {}
    for p in part_paths:
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            # Hard: without a parseable document we cannot verify id/stufe/
            # text are present on any record it contains -- treated as
            # equivalent to every record in it missing its required fields,
            # not merely a "structural surprise" (see module docstring).
            findings.append(
                _finding(
                    "hard", RULE_PART_UNREADABLE, f"could not parse as JSON: {exc}",
                    shard=shard_label, part=p.name,
                )
            )
            continue
        if not isinstance(doc, dict):
            findings.append(
                _finding(
                    "hard", RULE_PART_UNREADABLE, f"top-level JSON is a {type(doc).__name__}, not an object",
                    shard=shard_label, part=p.name,
                )
            )
            continue
        parts[p.name] = doc

    index_doc: dict | None = None
    index_path = shard_dir / "index.json"
    if index_path.exists():
        try:
            loaded = json.loads(index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            findings.append(
                _finding("soft", RULE_INDEX_UNREADABLE, f"could not parse index.json: {exc}", shard=shard_label)
            )
        else:
            if isinstance(loaded, dict):
                index_doc = loaded
            else:
                findings.append(
                    _finding("soft", RULE_INDEX_UNREADABLE, "index.json top level is not an object", shard=shard_label)
                )
    else:
        findings.append(_finding("soft", RULE_INDEX_MISSING, "index.json not found", shard=shard_label))

    # --- Collect every record with its origin, for every check below.
    # (part, kind, path, record, is_stufe_block) -- see iter_records for what
    # is_stufe_block means (E12-14).
    all_records: list[tuple[str, str, str, dict, bool]] = []
    for part_name, doc in parts.items():
        for kind, path, rec, is_stufe_block in iter_records(doc):
            all_records.append((part_name, kind, path, rec, is_stufe_block))

    # --- Per-part anwendungsbereiche_bindung (E12-14): several soft rules
    # below need to know what a shard's application items are scoped to
    # (kompetenz / bereich / stufe / prosa / keine). The field is per-part
    # meta, not (yet) guaranteed identical across every part of a shard --
    # read it per part rather than assuming.
    bindung_je_part: dict[str, str | None] = {
        part_name: (doc.get("meta") or {}).get("anwendungsbereiche_bindung")
        for part_name, doc in parts.items()
    }

    # --- HARD: missing id / stufe / text. Walks meta.anwendungsbereiche_bloecke
    # too (via iter_records, E12-14) -- previously those items were not
    # walked at all, so a missing id/stufe/text inside a block went
    # undetected.
    for part_name, kind, path, rec, _ in all_records:
        missing = [field_name for field_name in ("id", "stufe", "text") if not rec.get(field_name)]
        if missing:
            findings.append(
                _finding(
                    "hard", RULE_MISSING_REQUIRED_FIELD,
                    f"{kind} is missing required field(s) {missing}",
                    shard=shard_label, part=part_name, path=path, record_id=rec.get("id") or None,
                )
            )

    # --- ID collisions (hard) and malformed IDs (soft).
    #
    # Malformed-ID detection still delegates to id_schema.validate_ids() (the
    # E3-06 brief). Collision detection is now repetition-aware (E12-14,
    # backlog rule 2): under anwendungsbereiche_bindung: "stufe" (PRIM.D,
    # PRIM.SU) the *complete* meta.anwendungsbereiche_bloecke block is
    # deliberately repeated verbatim in every area part file, so the same
    # item id legitimately occurs several times -- that is not a collision
    # as long as every occurrence's content is identical. Any occurrence
    # that is NOT from that by-design pool, or that differs in content from
    # its sibling occurrences, is still a hard collision -- the global
    # uniqueness rule is not weakened for anything else.
    ids_for_validation: list[str] = []
    id_locations: dict[str, list[str]] = {}
    occurrences: dict[str, list[tuple[str, str, dict, bool]]] = {}
    kompetenz_ids: set[str] = set()
    anwendungsitem_ids: set[str] = set()
    for part_name, kind, path, rec, is_stufe_block in all_records:
        ident = rec.get("id")
        if isinstance(ident, str) and ident:
            ids_for_validation.append(ident)
            id_locations.setdefault(ident, []).append(f"{part_name}:{path}")
            occurrences.setdefault(ident, []).append((part_name, path, rec, is_stufe_block))
            if kind == "kompetenz":
                kompetenz_ids.add(ident)
            else:
                anwendungsitem_ids.add(ident)
        elif ident:
            # Present, truthy, but not a string -- can't be scheme-validated;
            # flagged as malformed rather than silently skipped.
            findings.append(
                _finding(
                    "soft", RULE_MALFORMED_ID, f"id is not a string: {ident!r}",
                    shard=shard_label, part=part_name, path=path,
                )
            )

    id_result = ID.validate_ids(ids_for_validation)
    malformed_ids = set(id_result.malformed)
    for malformed in id_result.malformed:
        findings.append(
            _finding(
                "soft", RULE_MALFORMED_ID,
                f"ID {malformed!r} does not parse under the frozen AT.LP23 scheme",
                shard=shard_label, record_id=malformed,
                part=(id_locations.get(malformed, [None])[0] or "").split(":", 1)[0] or None,
            )
        )

    for ident, occs in occurrences.items():
        if ident in malformed_ids or len(occs) <= 1:
            # A malformed id is reported via RULE_MALFORMED_ID above only --
            # it cannot also be scored for collision, mirroring the original
            # id_schema.validate_ids() boundary.
            continue
        if all(is_stufe_block for _part, _path, _rec, is_stufe_block in occs):
            first_rec = occs[0][2]
            mismatched = [o for o in occs[1:] if o[2] != first_rec]
            if mismatched:
                findings.append(
                    _finding(
                        "hard", RULE_ID_COLLISION,
                        f"ID {ident!r} occurs in meta.anwendungsbereiche_bloecke "
                        f"(bindung: stufe) in more than one location with differing "
                        f"content -- by-design repetition across parts requires "
                        f"identical content: {id_locations.get(ident, [])}",
                        shard=shard_label, record_id=ident,
                    )
                )
            # else: identical content across every occurrence -- by design
            # (E12-14 rule 2), not a collision.
            continue
        findings.append(
            _finding(
                "hard", RULE_ID_COLLISION,
                f"ID {ident!r} occurs more than once in this shard: {id_locations.get(ident, [])}",
                shard=shard_label, record_id=ident,
            )
        )

    # --- Schema validation per part (SOFT -- see module docstring / final
    # report for the reasoning behind this call).
    for part_name, doc in parts.items():
        errors = sorted(validator.iter_errors(doc), key=lambda e: "/".join(str(x) for x in e.absolute_path))
        for err in errors:
            json_path = "/".join(str(x) for x in err.absolute_path) or "<root>"
            findings.append(
                _finding(
                    "soft", RULE_SCHEMA_VIOLATION, f"{json_path}: {err.message}",
                    shard=shard_label, part=part_name, path=json_path,
                )
            )

    # --- Referential integrity (SOFT): vorlaeufer / folge / wiederholung_von
    # / kompetenz_id must resolve to an id that exists somewhere in this shard.
    valid_ids = set(id_locations)
    for part_name, kind, path, rec, _ in all_records:
        record_id = rec.get("id")
        for ref_field in ("vorlaeufer", "folge", "wiederholung_von"):
            for ref in rec.get(ref_field) or []:
                if isinstance(ref, str) and ref and ref not in valid_ids:
                    findings.append(
                        _finding(
                            "soft", RULE_DANGLING_REFERENCE,
                            f"{ref_field} references {ref!r}, which does not exist in this shard",
                            shard=shard_label, part=part_name, path=path, record_id=record_id,
                        )
                    )
        if kind == "anwendungsitem":
            kompetenz_id = rec.get("kompetenz_id")
            if isinstance(kompetenz_id, str) and kompetenz_id and kompetenz_id not in valid_ids:
                findings.append(
                    _finding(
                        "soft", RULE_DANGLING_REFERENCE,
                        f"kompetenz_id references {kompetenz_id!r}, which does not exist in this shard",
                        shard=shard_label, part=part_name, path=path, record_id=record_id,
                    )
                )

    # --- Image-token integrity (SOFT, but the one that protects the
    # verbatim-quotation guarantee -- see module docstring).
    for part_name, kind, path, rec, _ in all_records:
        record_id = rec.get("id")
        text = rec.get("text") or ""
        tokens_in_text = set(ABB_TOKEN_RE.findall(text))
        abbildungen = rec.get("abbildungen") or []
        tokens_in_abbildungen: set[str] = set()
        for entry in abbildungen:
            if not isinstance(entry, dict):
                continue
            token = entry.get("token")
            if isinstance(token, str) and token:
                tokens_in_abbildungen.add(token)
            datei = entry.get("datei")
            pfad = entry.get("pfad")
            if datei:
                reg_entry = registry.get(datei)
                if reg_entry is None:
                    findings.append(
                        _finding(
                            "soft", RULE_ABBILDUNG_NOT_IN_REGISTRY,
                            f"abbildung {datei!r} has no entry in registry.json",
                            shard=shard_label, part=part_name, path=path, record_id=record_id,
                        )
                    )
                else:
                    fehlend = [f for f in REGISTRY_REQUIRED_FIELDS if not reg_entry.get(f)]
                    if fehlend:
                        findings.append(
                            _finding(
                                "soft", RULE_REGISTRY_ENTRY_INCOMPLETE,
                                f"registry entry for {datei!r} is missing {fehlend}",
                                shard=shard_label, part=part_name, path=path, record_id=record_id,
                            )
                        )
            if pfad:
                if not (plugin_root / pfad).is_file():
                    findings.append(
                        _finding(
                            "soft", RULE_ABBILDUNG_FILE_MISSING,
                            f"abbildung file does not exist on disk at {pfad!r}",
                            shard=shard_label, part=part_name, path=path, record_id=record_id,
                        )
                    )
        for token in sorted(tokens_in_text - tokens_in_abbildungen):
            findings.append(
                _finding(
                    "soft", RULE_ORPHAN_TOKEN,
                    f"text contains {token!r} with no matching abbildungen[] entry",
                    shard=shard_label, part=part_name, path=path, record_id=record_id,
                )
            )
        for token in sorted(tokens_in_abbildungen - tokens_in_text):
            findings.append(
                _finding(
                    "soft", RULE_ORPHAN_ABBILDUNG_ENTRY,
                    f"abbildungen[] entry {token!r} does not occur in text",
                    shard=shard_label, part=part_name, path=path, record_id=record_id,
                )
            )

    # --- index.json consistency (SOFT).
    if index_doc is not None:
        teile = index_doc.get("teile") if isinstance(index_doc.get("teile"), list) else []
        listed = {t.get("datei") for t in teile if isinstance(t, dict)}
        on_disk = set(parts)
        if listed != on_disk:
            findings.append(
                _finding(
                    "soft", RULE_INDEX_MISMATCH,
                    f"index.json lists {sorted(listed)}, but parts on disk are {sorted(on_disk)}",
                    shard=shard_label, part="index.json",
                )
            )
        for teil in teile:
            if not isinstance(teil, dict):
                continue
            dateiname = teil.get("datei")
            doc = parts.get(dateiname)
            if doc is None:
                continue  # already reported via the mismatch above
            payload = json.dumps(doc, ensure_ascii=False, indent=2)
            actual_bytes = len(payload.encode("utf-8"))
            actual_tokens = BD.approx_tokens(payload)
            if teil.get("bytes") != actual_bytes:
                findings.append(
                    _finding(
                        "soft", RULE_INDEX_MISMATCH,
                        f"index.json records {teil.get('bytes')!r} bytes, actual is {actual_bytes}",
                        shard=shard_label, part=dateiname,
                    )
                )
            if teil.get("tokens_approx") != actual_tokens:
                findings.append(
                    _finding(
                        "soft", RULE_INDEX_MISMATCH,
                        f"index.json records ~{teil.get('tokens_approx')!r} tokens, actual is ~{actual_tokens}",
                        shard=shard_label, part=dateiname,
                    )
                )
            if teil.get("typ") == "kompetenzbereich":
                bereiche = doc.get("kompetenzbereiche") or []
                bereich = bereiche[0] if bereiche else {}
                kompetenzen = bereich.get("kompetenzen") or []
                if teil.get("kompetenzen") != len(kompetenzen):
                    findings.append(
                        _finding(
                            "soft", RULE_INDEX_MISMATCH,
                            f"index.json records {teil.get('kompetenzen')!r} kompetenzen, actual is {len(kompetenzen)}",
                            shard=shard_label, part=dateiname,
                        )
                    )
                actual_items = sum(len(k.get("anwendungsbereiche") or []) for k in kompetenzen if isinstance(k, dict))
                if teil.get("anwendungsitems") != actual_items:
                    findings.append(
                        _finding(
                            "soft", RULE_INDEX_MISMATCH,
                            f"index.json records {teil.get('anwendungsitems')!r} anwendungsitems, actual is {actual_items}",
                            shard=shard_label, part=dateiname,
                        )
                    )
            elif teil.get("typ") == "zusatz":
                actual_zk = len(doc.get("zusatzkompetenzen") or [])
                if teil.get("zusatzkompetenzen") != actual_zk:
                    findings.append(
                        _finding(
                            "soft", RULE_INDEX_MISMATCH,
                            f"index.json records {teil.get('zusatzkompetenzen')!r} zusatzkompetenzen, actual is {actual_zk}",
                            shard=shard_label, part=dateiname,
                        )
                    )
                actual_dt = len(doc.get("digitale_technologien_vorschlaege") or [])
                if teil.get("digitale_technologien_vorschlaege") != actual_dt:
                    findings.append(
                        _finding(
                            "soft", RULE_INDEX_MISMATCH,
                            f"index.json records {teil.get('digitale_technologien_vorschlaege')!r} "
                            f"digitale_technologien_vorschlaege, actual is {actual_dt}",
                            shard=shard_label, part=dateiname,
                        )
                    )

    # --- Size targets (SOFT, §6.7). Report the number, do not editorialise.
    for part_name, doc in parts.items():
        payload = json.dumps(doc, ensure_ascii=False, indent=2)
        actual_bytes = len(payload.encode("utf-8"))
        actual_tokens = BD.approx_tokens(payload)
        if actual_bytes > BD.SHARD_BYTES_ZIEL or actual_tokens > BD.SHARD_TOKENS_ZIEL:
            findings.append(
                _finding(
                    "soft", RULE_SIZE_TARGET_EXCEEDED,
                    f"{actual_bytes} bytes / ~{actual_tokens} tokens "
                    f"(§6.7 soft target: <= {BD.SHARD_BYTES_ZIEL} bytes / <= {BD.SHARD_TOKENS_ZIEL} tokens)",
                    shard=shard_label, part=part_name,
                )
            )

    # --- Unknown enum values in tolerant positions (INFO -- E2-16 policy
    # working as designed, explicitly not a failure).
    for part_name, doc in parts.items():
        meta = doc.get("meta") or {}
        fach_code = (meta.get("fach") or {}).get("code")
        if fach_code and fach_code not in ID.FAECHER:
            findings.append(
                _finding(
                    "info", RULE_UNKNOWN_ENUM_VALUE,
                    f"meta.fach.code {fach_code!r} is not one of the currently known subject codes "
                    f"{sorted(ID.FAECHER)} -- tolerant position, not a failure",
                    shard=shard_label, part=part_name,
                )
            )
        achse_typ = (meta.get("differenzierungs_achse") or {}).get("typ")
        if achse_typ and achse_typ not in KNOWN_DIFFERENZIERUNGS_ACHSE_TYPEN:
            findings.append(
                _finding(
                    "info", RULE_UNKNOWN_ENUM_VALUE,
                    f"meta.differenzierungs_achse.typ {achse_typ!r} is not one of the currently known values "
                    f"{sorted(KNOWN_DIFFERENZIERUNGS_ACHSE_TYPEN)} -- tolerant position, not a failure",
                    shard=shard_label, part=part_name,
                )
            )
    for part_name, kind, path, rec, _ in all_records:
        if kind != "anwendungsitem":
            continue
        art = rec.get("art")
        if art and art not in KNOWN_ART_VALUES:
            findings.append(
                _finding(
                    "info", RULE_UNKNOWN_ENUM_VALUE,
                    f"anwendungsitem.art {art!r} is not one of the currently known values "
                    f"{sorted(KNOWN_ART_VALUES)} -- tolerant position, not a failure",
                    shard=shard_label, part=part_name, path=path, record_id=rec.get("id"),
                )
            )

    # --- Unknown area code (SOFT, E12-14 rule 3): an id's Bereich segment
    # that is not in id_schema.AREA_CODES for this shard. Only meaningful
    # for one of the six frozen shards -- a future band/fach combination has
    # no area-code table to compare against yet, so this check is skipped
    # entirely rather than flagging every area as unknown.
    if ID.ist_gueltige_kombination(band, fach):
        known_areas = ID.alle_bereich_codes(band, fach)
        for part_name, kind, path, rec, _ in all_records:
            ident = rec.get("id")
            if not (isinstance(ident, str) and ident):
                continue
            try:
                parsed = ID.parse_id(ident)
            except ID.IdSchemaError:
                continue  # already reported via RULE_MALFORMED_ID
            bereich = getattr(parsed, "bereich", None)
            if bereich and bereich not in known_areas:
                findings.append(
                    _finding(
                        "soft", RULE_UNKNOWN_AREA_CODE,
                        f"id {ident!r} uses area code {bereich!r}, which is not in "
                        f"id_schema.AREA_CODES[{shard_label!r}] ({sorted(known_areas)})",
                        shard=shard_label, part=part_name, path=path, record_id=ident,
                    )
                )

    # --- kompetenz_id set where the binding axis forbids it (SOFT, rule 3):
    # only anwendungsbereiche_bindung: "kompetenz" (SEK1.M) may join an item
    # to a competence via kompetenz_id -- every other axis attaches items to
    # a bereich, a stufe, or nothing. Skipped when a part's bindung is not
    # (yet) recorded at all (meta.anwendungsbereiche_bindung is still
    # optional, E12-11) -- absence means "unknown", not "forbidden", and the
    # shipped SEK1.M shard does not carry it yet (see module docstring).
    for part_name, kind, path, rec, _ in all_records:
        if kind != "anwendungsitem":
            continue
        bindung = bindung_je_part.get(part_name)
        if bindung is None or bindung == "kompetenz":
            continue
        kompetenz_id = rec.get("kompetenz_id")
        if kompetenz_id:
            findings.append(
                _finding(
                    "soft", RULE_KOMPETENZ_ID_NOT_ALLOWED,
                    f"anwendungsitem carries kompetenz_id {kompetenz_id!r}, but this part's "
                    f"anwendungsbereiche_bindung is {bindung!r}, not 'kompetenz'",
                    shard=shard_label, part=part_name, path=path, record_id=rec.get("id"),
                )
            )

    # --- Area-free 7-segment item ID used outside bindung: stufe (SOFT,
    # rule 3): the area-free application-item grammar
    # (id_schema.ANWENDUNGSITEM_AREA_FREI_ID_RE) exists only for the
    # PRIM.D/PRIM.SU-style bindung: "stufe" items. Skipped, as above, when
    # the part's bindung is not (yet) recorded.
    for part_name, kind, path, rec, _ in all_records:
        if kind != "anwendungsitem":
            continue
        ident = rec.get("id")
        if not (isinstance(ident, str) and ident):
            continue
        try:
            parsed = ID.parse_id(ident)
        except ID.IdSchemaError:
            continue  # already reported via RULE_MALFORMED_ID
        if not (isinstance(parsed, ID.AnwendungsitemId) and parsed.bereich is None):
            continue
        bindung = bindung_je_part.get(part_name)
        if bindung is not None and bindung != "stufe":
            findings.append(
                _finding(
                    "soft", RULE_AREA_FREE_ID_OUTSIDE_STUFE,
                    f"id {ident!r} uses the area-free 7-segment application-item form, "
                    f"but this part's anwendungsbereiche_bindung is {bindung!r}, not 'stufe'",
                    shard=shard_label, part=part_name, path=path, record_id=ident,
                )
            )

    # --- verbindlich anomalies (SOFT, rule 3): the 'allenfalls' marker that
    # produces verbindlich: false is measured SEK1.M-only (FINDINGS.md /
    # notes/deviations.md, 2026-07-29) -- a non-binding item in any other
    # shard is a structural surprise worth surfacing, not a failure.
    if shard_label != "SEK1.M":
        for part_name, kind, path, rec, _ in all_records:
            if kind == "anwendungsitem" and rec.get("verbindlich") is False:
                findings.append(
                    _finding(
                        "soft", RULE_VERBINDLICH_ANOMALY,
                        "anwendungsitem carries verbindlich: false outside SEK1.M -- the "
                        "'allenfalls' marker that produces this flag is measured SEK1.M-only",
                        shard=shard_label, part=part_name, path=path, record_id=rec.get("id"),
                    )
                )

    # --- Counts vs the frozen expected counts (SOFT, rule 3):
    # parse_lehrplan.ERWARTET_BY_SPEC, measured against the live RIS source
    # (notes/ris-xml-structure.md) and reproduced against committed
    # fixtures (tests/test_parse_lehrplan.py). Distinct-id counts, not raw
    # record counts, so a bindung: stufe shard's by-design cross-part
    # repetition (see the ID-collision handling above) is not
    # double-counted. Skipped for a shard this table does not (yet) cover.
    erwartet = PL.ERWARTET_BY_SPEC.get(shard_label)
    if erwartet is not None:
        area_slugs: set[str] = set()
        for doc in parts.values():
            for bereich in doc.get("kompetenzbereiche") or []:
                if isinstance(bereich, dict) and bereich.get("slug"):
                    area_slugs.add(bereich["slug"])
        for feld, erwartet_wert, gemessen_wert in (
            ("kompetenzen", erwartet["kompetenzen"], len(kompetenz_ids)),
            ("anwendungsitems", erwartet["anwendungsitems"], len(anwendungsitem_ids)),
            ("kompetenzbereiche", erwartet["kompetenzbereiche"], len(area_slugs)),
        ):
            if erwartet_wert != gemessen_wert:
                findings.append(
                    _finding(
                        "soft", RULE_COUNT_MISMATCH,
                        f"{feld}: frozen expected count is {erwartet_wert}, measured {gemessen_wert} "
                        f"(parse_lehrplan.ERWARTET_BY_SPEC[{shard_label!r}])",
                        shard=shard_label,
                    )
                )

    return findings


# --------------------------------------------------------------------------
# Top-level orchestration
# --------------------------------------------------------------------------


def run_validation(
    kompetenzen_root: Path = DEFAULT_KOMPETENZEN_ROOT,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    schema_path: Path = DEFAULT_SCHEMA_PATH,
    plugin_root: Path = PLUGIN_ROOT,
) -> Report:
    """Validate every shard discovered under *kompetenzen_root* against
    *schema_path*, cross-checking image references against *registry_path*
    and resolving ``abbildungen[].pfad`` relative to *plugin_root*. Pure
    function of the filesystem state passed in -- never mutates anything,
    never depends on having built the dataset in this process."""
    findings: list[Finding] = []

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)

    registry: dict[str, dict] = {}
    if registry_path.exists():
        try:
            loaded = json.loads(registry_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            findings.append(_finding("hard", RULE_REGISTRY_UNREADABLE, f"could not parse registry.json: {exc}"))
        else:
            if isinstance(loaded, dict):
                registry = loaded
            else:
                findings.append(_finding("hard", RULE_REGISTRY_UNREADABLE, "registry.json top level is not an object"))
    else:
        findings.append(
            _finding("soft", RULE_REGISTRY_MISSING, f"{registry_path} not found -- treating as an empty registry")
        )

    shards = discover_shards(kompetenzen_root)
    if not shards:
        findings.append(
            _finding("soft", RULE_NO_SHARDS_FOUND, f"no shards discovered under {kompetenzen_root}")
        )

    for band, fach, shard_dir in shards:
        findings.extend(validate_shard(band, fach, shard_dir, registry, validator, plugin_root))

    return Report(findings=findings, shards_checked=[f"{b}.{f}" for b, f, _ in shards])


# --------------------------------------------------------------------------
# Output formatting
# --------------------------------------------------------------------------

_SEVERITY_ORDER = {"hard": 0, "soft": 1, "info": 2}
_SEVERITY_LABEL = {"hard": "HARD (fails the run)", "soft": "SOFT (reported, non-fatal)", "info": "INFO (tolerant policy, non-fatal)"}


def _sort_key(f: Finding) -> tuple:
    return (_SEVERITY_ORDER[f.severity], f.shard or "", f.part or "", f.rule, f.record_id or "")


def format_text(report: Report, strict: bool) -> str:
    lines: list[str] = []
    shards = ", ".join(report.shards_checked) if report.shards_checked else "(none)"
    lines.append(f"validate_dataset: {len(report.shards_checked)} shard(s) checked: {shards}")
    lines.append(
        f"  {len(report.hard)} hard, {len(report.soft)} soft, {len(report.info)} info finding(s)"
        f"{'  (--strict: soft findings also fail the run)' if strict else ''}"
    )

    if not report.findings:
        lines.append("")
        lines.append("Clean run: no findings at all.")
        return "\n".join(lines)

    for severity in ("hard", "soft", "info"):
        bucket = [f for f in report.findings if f.severity == severity]
        if not bucket:
            continue
        lines.append("")
        lines.append(f"{_SEVERITY_LABEL[severity]} -- {len(bucket)} finding(s):")
        current_shard = object()
        for f in sorted(bucket, key=_sort_key):
            shard_key = (f.shard, f.part)
            if shard_key != current_shard:
                current_shard = shard_key
                header = f.shard or "(dataset-wide)"
                if f.part:
                    header += f" / {f.part}"
                lines.append(f"  [{header}]")
            loc = f" ({f.path})" if f.path else ""
            rid = f" [{f.record_id}]" if f.record_id else ""
            lines.append(f"    - {f.rule}{rid}{loc}: {f.message}")

    if not report.hard and not report.soft:
        lines.append("")
        lines.append("Clean run: no hard or soft findings (informational findings only).")

    return "\n".join(lines)


def format_json(report: Report, strict: bool) -> str:
    payload = {
        "shards_checked": report.shards_checked,
        "counts": {"hard": len(report.hard), "soft": len(report.soft), "info": len(report.info)},
        "strict": strict,
        "exit_code": report.exit_code(strict),
        "findings": [f.to_dict() for f in sorted(report.findings, key=_sort_key)],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _cli(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=str(DEFAULT_KOMPETENZEN_ROOT), help="plugin/data/kompetenzen root to validate")
    ap.add_argument("--registry", default=str(DEFAULT_REGISTRY_PATH), help="plugin/data/abbildungen/registry.json path")
    ap.add_argument("--schema", default=str(DEFAULT_SCHEMA_PATH), help="schema/kompetenzen.schema.json path")
    ap.add_argument("--plugin-root", default=None, help="plugin/ root, used to resolve abbildungen pfad (default: derived from --root)")
    ap.add_argument("--json", action="store_true", help="machine-readable JSON report (for CI)")
    ap.add_argument(
        "--strict", action="store_true",
        help="promote soft findings to failures too (exit 1); informational findings are never promoted",
    )
    args = ap.parse_args(argv)

    root = Path(args.root)
    if not root.exists():
        print(f"error: --root not found: {root}", file=sys.stderr)
        return 2

    schema_path = Path(args.schema)
    if not schema_path.exists():
        print(f"error: --schema not found: {schema_path}", file=sys.stderr)
        return 2

    registry_path = Path(args.registry)
    plugin_root = Path(args.plugin_root) if args.plugin_root else root.resolve().parent.parent

    report = run_validation(root, registry_path, schema_path, plugin_root)

    if args.json:
        print(format_json(report, args.strict))
    else:
        print(format_text(report, args.strict))

    return report.exit_code(args.strict)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
