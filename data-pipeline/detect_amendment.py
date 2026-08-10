#!/usr/bin/env python3
"""Amendment detection (E10-07): diff a candidate ``manifest.json`` against the committed
reference over NOR, ELI, Kundmachungsorgan, in-force/out-of-force dates and per-file SHA-256.

Why this exists (risk register: "RIS amendment mid-build -> shards drift from provenance"). The
shipped shards are built from three RIS documents at a point in time. If RIS amends, repeals, or
merely re-publishes one of those documents afterwards, the shards silently drift from the source
they claim provenance for while every other check in this repository stays green -- every other
checker compares the shipped dataset to the pipeline that produced it, never to a fresh look at
the source. This module is the one check that looks outward.

The committed reference is ``data-pipeline/resources/manifest.json`` -- tracked in git even
though the rest of ``data-pipeline/resources/`` is gitignored (``git ls-files
data-pipeline/resources/`` shows only this one file). That is what makes this module able to run
**offline**: the baseline it diffs against ships with the repository, so no fetch is required to
detect that something changed relative to it. Re-running ``fetch_ris_resources.py`` to produce a
fresh candidate manifest is a separate, deliberately manual step (plan section 10.3, "re-run is
manual and on-notice") -- this module only compares two manifests already on disk.

Not every divergence means the same thing, and the report says which:

``amendment``
    NOR, ELI, Kundmachungsorgan or the in-force date changed -- the document's legal identity
    moved. A SHA-256 change on the same document is reported under this category too (the file
    changing is the expected consequence of the identity changing, not a separate event).
``repeal``
    ``ausserkrafttretensdatum`` changed -- most commonly ``null`` to a date, meaning the document
    is now scheduled to go out of force.
``silent-republication``
    A file's SHA-256 changed while NOR/ELI/Kundmachungsorgan/dates on that same document did not.
    RIS re-served different bytes under an unchanged legal identity -- worth an operator's eyes,
    but not the same event as an amendment or repeal, and conflating the two would make the
    operator re-derive this distinction by hand every time.
``document-added`` / ``document-removed``
    A top-level document key exists in one manifest but not the other.

Exit codes
----------
``0``
    No divergence: the candidate matches the committed baseline exactly.
``1``
    At least one divergence detected.
``2``
    Usage/environment error: ``--baseline`` or ``--candidate`` does not exist, or does not parse
    as a JSON object.

Usage
-----
::

    .venv/bin/python data-pipeline/detect_amendment.py --candidate path/to/new/manifest.json
    .venv/bin/python data-pipeline/detect_amendment.py --candidate ... --baseline ... --json

stdlib only.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_BASELINE_PATH = HERE / "resources" / "manifest.json"

#: Fields whose change means the document's legal identity moved. "gesetzesnummer" is included
#: alongside the fields the task names explicitly (NOR/ELI/Kundmachungsorgan/dates) because it is
#: the same class of identity field and a change to it would be at least as significant.
IDENTITY_FIELDS: tuple[str, ...] = ("nor", "eli", "gesetzesnummer", "kundmachungsorgan", "inkrafttretensdatum")

#: The out-of-force date, tracked separately from IDENTITY_FIELDS because a change here is a
#: repeal signal, not an "identity moved" signal -- see the module docstring's category table.
OUT_OF_FORCE_FIELD = "ausserkrafttretensdatum"

#: The two files tracked per document (fetch_ris_resources.py::build_manifest_entry).
FILE_KEYS: tuple[str, ...] = ("pdf", "xml")

CATEGORY_AMENDMENT = "amendment"
CATEGORY_REPEAL = "repeal"
CATEGORY_SILENT_REPUBLICATION = "silent-republication"
CATEGORY_DOCUMENT_ADDED = "document-added"
CATEGORY_DOCUMENT_REMOVED = "document-removed"

CATEGORY_ORDER = (
    CATEGORY_AMENDMENT,
    CATEGORY_REPEAL,
    CATEGORY_SILENT_REPUBLICATION,
    CATEGORY_DOCUMENT_ADDED,
    CATEGORY_DOCUMENT_REMOVED,
)
CATEGORY_LABEL = {
    CATEGORY_AMENDMENT: "AMENDMENT (legal identity changed)",
    CATEGORY_REPEAL: "REPEAL (out-of-force date changed)",
    CATEGORY_SILENT_REPUBLICATION: "SILENT RE-PUBLICATION (file content changed, legal identity did not)",
    CATEGORY_DOCUMENT_ADDED: "DOCUMENT ADDED",
    CATEGORY_DOCUMENT_REMOVED: "DOCUMENT REMOVED",
}


@dataclass(frozen=True)
class Divergence:
    """One field-level change between the baseline and the candidate manifest."""

    document: str
    category: str
    field: str
    baseline: Any
    candidate: Any
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "document": self.document,
            "category": self.category,
            "field": self.field,
            "baseline": self.baseline,
            "candidate": self.candidate,
            "message": self.message,
        }


def _get_path(doc: dict, dotted: str) -> Any:
    """Dotted-path getter, e.g. ``files.pdf.sha256``. Missing intermediates read as None rather
    than raising -- a manifest entry missing ``files`` entirely is itself just "the field
    changed to None", not a crash."""
    cur: Any = doc
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def diff_document(name: str, baseline: dict, candidate: dict) -> list[Divergence]:
    """Diff one document's baseline vs. candidate entry. Returns every field-level change,
    classified per the module docstring's category table."""
    divergences: list[Divergence] = []
    identity_changed = False

    for field_name in IDENTITY_FIELDS:
        b_val = baseline.get(field_name)
        c_val = candidate.get(field_name)
        if b_val != c_val:
            identity_changed = True
            divergences.append(
                Divergence(
                    document=name, category=CATEGORY_AMENDMENT, field=field_name,
                    baseline=b_val, candidate=c_val,
                    message=f"{field_name} changed from {b_val!r} to {c_val!r} -- legal identity moved, treat as an amendment",
                )
            )

    b_akd = baseline.get(OUT_OF_FORCE_FIELD)
    c_akd = candidate.get(OUT_OF_FORCE_FIELD)
    if b_akd != c_akd:
        if b_akd is None and c_akd is not None:
            msg = f"{OUT_OF_FORCE_FIELD} newly set to {c_akd!r} -- this document is now scheduled to go out of force"
        elif b_akd is not None and c_akd is None:
            msg = f"{OUT_OF_FORCE_FIELD} cleared (was {b_akd!r}) -- the repeal date was withdrawn or moved"
        else:
            msg = f"{OUT_OF_FORCE_FIELD} changed from {b_akd!r} to {c_akd!r} -- the repeal date moved"
        divergences.append(
            Divergence(
                document=name, category=CATEGORY_REPEAL, field=OUT_OF_FORCE_FIELD,
                baseline=b_akd, candidate=c_akd, message=msg,
            )
        )

    for key in FILE_KEYS:
        field_name = f"files.{key}.sha256"
        b_sha = _get_path(baseline, field_name)
        c_sha = _get_path(candidate, field_name)
        if b_sha != c_sha:
            if identity_changed:
                category = CATEGORY_AMENDMENT
                message = (
                    f"{field_name} changed from {b_sha!r} to {c_sha!r} -- consistent with the "
                    f"legal-identity change also detected on this document"
                )
            else:
                category = CATEGORY_SILENT_REPUBLICATION
                message = (
                    f"{field_name} changed from {b_sha!r} to {c_sha!r} but NOR/ELI/Kundmachungsorgan/"
                    f"dates on this document are unchanged -- RIS re-served different bytes under the "
                    f"same legal identity"
                )
            divergences.append(
                Divergence(
                    document=name, category=category, field=field_name,
                    baseline=b_sha, candidate=c_sha, message=message,
                )
            )

    return divergences


def diff_manifests(baseline: dict, candidate: dict) -> list[Divergence]:
    """Diff two whole manifests (top-level document key -> entry dict)."""
    divergences: list[Divergence] = []
    baseline_keys = set(baseline)
    candidate_keys = set(candidate)

    for name in sorted(baseline_keys - candidate_keys):
        entry = baseline[name] if isinstance(baseline[name], dict) else {}
        divergences.append(
            Divergence(
                document=name, category=CATEGORY_DOCUMENT_REMOVED, field="<document>",
                baseline=entry.get("nor"), candidate=None,
                message=f"document {name!r} is present in the baseline manifest but missing from the candidate",
            )
        )
    for name in sorted(candidate_keys - baseline_keys):
        entry = candidate[name] if isinstance(candidate[name], dict) else {}
        divergences.append(
            Divergence(
                document=name, category=CATEGORY_DOCUMENT_ADDED, field="<document>",
                baseline=None, candidate=entry.get("nor"),
                message=f"document {name!r} is present in the candidate manifest but has no counterpart in the baseline",
            )
        )
    for name in sorted(baseline_keys & candidate_keys):
        b_doc, c_doc = baseline[name], candidate[name]
        if not isinstance(b_doc, dict) or not isinstance(c_doc, dict):
            continue
        divergences.extend(diff_document(name, b_doc, c_doc))

    return divergences


def load_manifest(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top-level JSON is a {type(data).__name__}, not an object")
    return data


# --------------------------------------------------------------------------
# Output formatting
# --------------------------------------------------------------------------


def _sort_key(d: Divergence) -> tuple:
    return (CATEGORY_ORDER.index(d.category), d.document, d.field)


def format_text(divergences: list[Divergence], baseline_path: Path, candidate_path: Path) -> str:
    lines = [f"detect_amendment: baseline={baseline_path}  candidate={candidate_path}"]
    if not divergences:
        lines.append("")
        lines.append("No divergence: the candidate manifest matches the committed baseline exactly.")
        return "\n".join(lines)

    lines.append("")
    lines.append(f"DIVERGENCE -- {len(divergences)} change(s) detected:")
    for category in CATEGORY_ORDER:
        bucket = [d for d in divergences if d.category == category]
        if not bucket:
            continue
        lines.append(f"  {CATEGORY_LABEL[category]} -- {len(bucket)}:")
        for d in sorted(bucket, key=_sort_key):
            lines.append(f"    [{d.document}] {d.field}: {d.message}")
    return "\n".join(lines)


def format_json(divergences: list[Divergence], baseline_path: Path, candidate_path: Path) -> str:
    payload = {
        "baseline": str(baseline_path),
        "candidate": str(candidate_path),
        "counts": {category: sum(1 for d in divergences if d.category == category) for category in CATEGORY_ORDER},
        "divergences": [d.to_dict() for d in sorted(divergences, key=_sort_key)],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _cli(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--baseline", default=str(DEFAULT_BASELINE_PATH),
        help="committed reference manifest.json (default: data-pipeline/resources/manifest.json)",
    )
    ap.add_argument("--candidate", required=True, help="candidate manifest.json to diff against the baseline")
    ap.add_argument("--json", action="store_true", help="machine-readable JSON report (for CI)")
    args = ap.parse_args(argv)

    baseline_path = Path(args.baseline)
    candidate_path = Path(args.candidate)

    if not baseline_path.exists():
        print(f"error: --baseline not found: {baseline_path}", file=sys.stderr)
        return 2
    if not candidate_path.exists():
        print(f"error: --candidate not found: {candidate_path}", file=sys.stderr)
        return 2

    try:
        baseline = load_manifest(baseline_path)
        candidate = load_manifest(candidate_path)
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        print(f"error: could not read manifest: {exc}", file=sys.stderr)
        return 2

    divergences = diff_manifests(baseline, candidate)

    if args.json:
        print(format_json(divergences, baseline_path, candidate_path))
    else:
        print(format_text(divergences, baseline_path, candidate_path))

    return 1 if divergences else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
