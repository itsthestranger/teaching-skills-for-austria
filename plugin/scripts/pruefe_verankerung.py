#!/usr/bin/env python3
"""Verankerungs-Checker for a generated ``lesson.json`` (E6-04).

E6-03 already *specifies* the anchoring flow in
``plugin/skills/at-unterrichtsplanung/SKILL.md`` (Schritt 2/4) and
*demonstrates* it once in the shipped fixture. Nothing, however, mechanically
checks that any given emitted ``lesson.json`` actually honours that flow --
a plan with a paraphrased quote, a missing/altered provenance, an invented
"binding" item, or a merged binding/optional section would render
perfectly. This module is that check.

**Ground truth is exclusively :mod:`kompetenz` (this package's sibling
access layer).** Nothing here re-implements a lookup, reads
``plugin/data/`` directly, or hardcodes competence text -- every judgement
is "does this claim match what ``kompetenz.py`` actually returns for the
cited ID", never a self-referential shape check.

Five violation classes, none of which requires anything to be non-empty:

- ``kein-kompetenzbezug`` -- no ``kompetenzbezug`` block anywhere in the
  document at all.
- ``id-unaufloesbar`` -- a ``kompetenzbezug`` block's ``kompetenz_id`` does
  not resolve via :func:`kompetenz.kompetenz_nach_id` (missing, malformed,
  or an Anwendungsitem ID mistaken for a competence ID).
- ``zitat-nicht-wortgetreu`` -- the block's ``text`` is not exactly
  :func:`kompetenz.voller_wortlaut` of the cited record (a paraphrase, a
  truncation, a dropped clause).
- ``provenienz-veraendert`` -- the block's ``quelle`` dict is not exactly
  the cited record's ``provenienz`` (a dropped/added/altered field, e.g. an
  edited ``stand``).
- ``verbindlich-optional-vermischt`` / ``erfundenes-verbindliches-item`` /
  ``erfundenes-optionales-item`` / ``optionales-item-als-verbindlich...`` /
  ``verbindliches-item-als-optional...`` -- see :func:`_pruefe_anwendungsblock`.

**Critical constraint this module must never violate:** ``keine`` and
``prosa`` shards (``PRIM.M``, ``SEK1.E``) legitimately have *zero*
binding/optional application items -- :func:`kompetenz.finde_anwendungsbereiche`
returns ``[]`` for both flags there by design (V-77/V-79), and
``PRIM.M``'s Lehrstoff is its own competence quotation (V-45). This checker
therefore never demands that a binding or optional block exist -- it only
ever validates blocks that are actually present in the document against the
access layer, so a legitimately-empty shard cannot be made to fail by
inventing content to fill a document section that has nothing to put there.

Blocks are found by a generic, renderer-independent walk over every dict in
the document that carries a string ``"type"`` key (mirrors
``tests/test_planning_flow.py``'s ``_blocks`` helper) -- this module does
not import anything under ``plugin/skills/*/scripts/`` and does not expand
``from_shared`` references; the one real ``kompetenzbezug`` block a
``lesson.json`` carries lives directly in the document tree (typically
under ``shared``, which ``json.loads`` always visits before ``documents``
in file order), so the walk still finds and anchors it.

A ``list`` block is only ever treated as a binding/optional claim when it
carries a string ``label`` matching ``verbindlich`` or
``optional``/``allenfalls`` (case-insensitive) -- an unlabelled ``list``
(ordinary lesson activities) is never touched.

Pure stdlib. Offline. Deterministic (no network, no randomness).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import kompetenz as K  # noqa: E402  pylint: disable=wrong-import-position

# ---------------------------------------------------------------------------
# Rule identifiers -- stable strings, so callers/tests assert on them.
# ---------------------------------------------------------------------------

REGEL_KEIN_ANKER = "kein-kompetenzbezug"
REGEL_ID_UNAUFLOESBAR = "id-unaufloesbar"
REGEL_ZITAT_NICHT_WORTGETREU = "zitat-nicht-wortgetreu"
REGEL_PROVENIENZ_VERAENDERT = "provenienz-veraendert"
REGEL_BLOECKE_VERMISCHT = "verbindlich-optional-vermischt"
REGEL_ERFUNDENES_VERBINDLICHES_ITEM = "erfundenes-verbindliches-item"
REGEL_ERFUNDENES_OPTIONALES_ITEM = "erfundenes-optionales-item"
REGEL_OPTIONAL_ALS_VERBINDLICH = "optionales-item-als-verbindlich-ausgegeben"
REGEL_VERBINDLICH_ALS_OPTIONAL = "verbindliches-item-als-optional-ausgegeben"

#: A list block is a binding/optional claim only when its label matches one
#: of these -- an unlabelled list (ordinary lesson activities) never is.
_VERBINDLICH_LABEL = re.compile(r"verbindlich", re.IGNORECASE)
_OPTIONAL_LABEL = re.compile(r"optional|allenfalls", re.IGNORECASE)


@dataclass(frozen=True)
class Verletzung:
    """One anchoring violation."""

    regel: str
    meldung: str
    pfad: str | None = None
    """In-document JSON-path locator, e.g. ``$.shared.kompetenz``."""

    def to_dict(self) -> dict[str, Any]:
        return {"regel": self.regel, "meldung": self.meldung, "pfad": self.pfad}


# ---------------------------------------------------------------------------
# Generic, renderer-independent block walk
# ---------------------------------------------------------------------------


def _iter_bloecke(wert: Any, pfad: str = "$") -> Iterator[tuple[str, dict[str, Any]]]:
    """Pre-order walk yielding ``(pfad, block)`` for every dict anywhere in
    *wert* that carries a string ``"type"`` key -- shared content and every
    document's own sections alike, in file order (``dict`` preserves
    ``json.loads`` insertion order, so ``shared`` is always visited before
    ``documents`` for a document shaped like the shipped fixtures)."""
    if isinstance(wert, dict):
        if isinstance(wert.get("type"), str):
            yield pfad, wert
        for schluessel, kind in wert.items():
            yield from _iter_bloecke(kind, f"{pfad}.{schluessel}")
    elif isinstance(wert, list):
        for i, kind in enumerate(wert):
            yield from _iter_bloecke(kind, f"{pfad}[{i}]")


# ---------------------------------------------------------------------------
# Per-block checks
# ---------------------------------------------------------------------------


def _pruefe_kompetenzbezug(
    pfad: str, block: dict[str, Any]
) -> tuple[list[Verletzung], str | None, dict[str, Any] | None]:
    """Validate one ``kompetenzbezug`` block against the access layer.

    Returns ``(verletzungen, kompetenz_id, datensatz)`` -- ``kompetenz_id``
    and ``datensatz`` are ``None`` whenever the ID itself does not resolve,
    since there is then nothing to check application items against.
    """
    verletzungen: list[Verletzung] = []
    kid = block.get("kompetenz_id")
    if not isinstance(kid, str) or not kid.strip():
        return (
            [Verletzung(REGEL_ID_UNAUFLOESBAR, "kompetenzbezug-Block ohne kompetenz_id", pfad)],
            None,
            None,
        )
    try:
        datensatz = K.kompetenz_nach_id(kid)
    except K.KompetenzFehler as exc:
        return (
            [Verletzung(
                REGEL_ID_UNAUFLOESBAR,
                f"kompetenz_id {kid!r} loest ueber kompetenz_nach_id nicht auf: {exc}",
                pfad,
            )],
            None,
            None,
        )

    erwarteter_wortlaut = K.voller_wortlaut(datensatz)
    if block.get("text") != erwarteter_wortlaut:
        verletzungen.append(
            Verletzung(
                REGEL_ZITAT_NICHT_WORTGETREU,
                f"Zitat fuer {kid} ist nicht wortgetreu -- erwartet {erwarteter_wortlaut!r}, "
                f"erhalten {block.get('text')!r}",
                pfad,
            )
        )
    if block.get("quelle") != datensatz["provenienz"]:
        verletzungen.append(
            Verletzung(
                REGEL_PROVENIENZ_VERAENDERT,
                f"quelle fuer {kid} entspricht nicht der von kompetenz_nach_id gelieferten "
                f"provenienz -- erwartet {datensatz['provenienz']!r}, erhalten {block.get('quelle')!r}",
                pfad,
            )
        )
    return verletzungen, kid, datensatz


def _ist_anwendungsblock(block: dict[str, Any]) -> bool:
    """A block is an application-area claim when it carries a string ``label``
    matching ``verbindlich``/``optional``/``allenfalls`` **and** an ``items``
    list -- regardless of its ``type``.

    Deliberately *not* keyed on ``type == "list"``: keying on the block type
    would let a plan evade the whole check by carrying the same labelled
    items in any other block shape, and an enforcement mechanism that a
    different block type walks straight through is not enforcement. An
    unlabelled list (ordinary lesson activities) is still never touched.
    """
    label = block.get("label")
    if not isinstance(label, str) or not isinstance(block.get("items"), list):
        return False
    return bool(_VERBINDLICH_LABEL.search(label) or _OPTIONAL_LABEL.search(label))


def _pruefe_anwendungsblock(
    pfad: str,
    block: dict[str, Any],
    kandidaten: list[str],
    echte_items: dict[tuple[str, bool], set[str]],
) -> list[Verletzung]:
    """Validate one labelled block's items against
    ``finde_anwendungsbereiche(id, nur_verbindlich=...)``.

    A block whose label matches *both* patterns is flagged immediately --
    binding and optional content must live in separate blocks, never one.
    Otherwise, every listed item must be a genuine member of the matching
    real set; an item that belongs to the *other* set is reported as
    misclassified (smuggled across the binding/optional line), and an item
    in neither is reported as fabricated/paraphrased.

    *kandidaten* are the competence IDs this block may legitimately draw
    from -- the nearest preceding anchor when there is one, otherwise every
    resolved anchor in the document (see :func:`pruefe_daten`). An item
    counts as genuine when it belongs to *any* candidate's matching set, so
    the check never invents a violation merely because of block ordering.
    """
    label = block.get("label")
    if not isinstance(label, str):
        return []
    ist_verbindlich = bool(_VERBINDLICH_LABEL.search(label))
    ist_optional = bool(_OPTIONAL_LABEL.search(label))
    if not (ist_verbindlich or ist_optional):
        return []

    if ist_verbindlich and ist_optional:
        return [
            Verletzung(
                REGEL_BLOECKE_VERMISCHT,
                f"Block mit Label {label!r} kennzeichnet verbindliche und optionale "
                "Anwendungsbereiche gleichzeitig -- diese muessen in getrennten Bloecken stehen",
                pfad,
            )
        ]

    if not kandidaten:
        # No resolved anchor anywhere in the document -- already reported as
        # REGEL_KEIN_ANKER / REGEL_ID_UNAUFLOESBAR, nothing to compare against.
        return []

    items = [i for i in block.get("items", []) if isinstance(i, str)]

    def _laden(kid: str, verbindlich: bool) -> set[str]:
        schluessel = (kid, verbindlich)
        if schluessel not in echte_items:
            treffer = K.finde_anwendungsbereiche(kid, nur_verbindlich=verbindlich)
            echte_items[schluessel] = {i["text"] for i in treffer}
        return echte_items[schluessel]

    def _vereinigt(verbindlich: bool) -> set[str]:
        vereint: set[str] = set()
        for kid in kandidaten:
            vereint |= _laden(kid, verbindlich)
        return vereint

    if ist_verbindlich:
        echt, anderes = _vereinigt(True), _vereinigt(False)
        fehlerregel_vertauscht = REGEL_OPTIONAL_ALS_VERBINDLICH
        fehlerregel_erfunden = REGEL_ERFUNDENES_VERBINDLICHES_ITEM
        art = "verbindlich"
    else:
        echt, anderes = _vereinigt(False), _vereinigt(True)
        fehlerregel_vertauscht = REGEL_VERBINDLICH_ALS_OPTIONAL
        fehlerregel_erfunden = REGEL_ERFUNDENES_OPTIONALES_ITEM
        art = "optional"

    bezug = ", ".join(repr(k) for k in kandidaten)
    verletzungen: list[Verletzung] = []
    for item in items:
        if item in echt:
            continue
        if item in anderes:
            verletzungen.append(
                Verletzung(
                    fehlerregel_vertauscht,
                    f"Item {item!r} ist als {art} ausgegeben, ist laut "
                    f"finde_anwendungsbereiche({bezug}) aber tatsaechlich das Gegenteil",
                    pfad,
                )
            )
        else:
            verletzungen.append(
                Verletzung(
                    fehlerregel_erfunden,
                    f"Item {item!r} ist als {art} ausgegeben, ist aber fuer "
                    f"{bezug} nicht in finde_anwendungsbereiche(..., nur_verbindlich={ist_verbindlich}) "
                    "enthalten -- erfunden oder paraphrasiert",
                    pfad,
                )
            )
    return verletzungen


# ---------------------------------------------------------------------------
# Whole-document check
# ---------------------------------------------------------------------------


def pruefe_lesson(pfad: Path) -> list[Verletzung]:
    """Validate one ``lesson.json`` file. Returns every violation found (an
    empty list means the anchoring is enforced end to end)."""
    daten = json.loads(pfad.read_text(encoding="utf-8"))
    return pruefe_daten(daten)


def pruefe_daten(daten: Any) -> list[Verletzung]:
    """Same as :func:`pruefe_lesson`, over an already-parsed document -- the
    entry point ``at-differenzierung`` (E7) can reuse directly without a
    round trip through disk."""
    verletzungen: list[Verletzung] = []
    echte_items: dict[tuple[str, bool], set[str]] = {}
    bloecke = list(_iter_bloecke(daten))

    # Pass 1 -- validate every anchor and collect the resolved IDs with their
    # position. Two passes rather than one running "current anchor": a single
    # forward pass silently skips validation for any application block that
    # happens to precede the anchor in document order, so the *same* fabricated
    # item would pass or fail purely on block ordering. An enforcement check
    # must not depend on where in the file the author put the anchor.
    anker_gefunden = False
    aufgeloest: list[tuple[int, str]] = []
    for i, (block_pfad, block) in enumerate(bloecke):
        if block.get("type") != "kompetenzbezug":
            continue
        anker_gefunden = True
        neue, kid, _datensatz = _pruefe_kompetenzbezug(block_pfad, block)
        verletzungen.extend(neue)
        if kid is not None:
            aufgeloest.append((i, kid))

    alle_ids = [kid for _, kid in aufgeloest]

    # Pass 2 -- application blocks. The nearest *preceding* anchor governs when
    # there is one (the normal, unambiguous case); with none preceding, every
    # resolved anchor in the document is a candidate, so ordering can neither
    # hide a fabricated item nor invent a false positive.
    for i, (block_pfad, block) in enumerate(bloecke):
        if block.get("type") == "kompetenzbezug" or not _ist_anwendungsblock(block):
            continue
        vorher = [kid for j, kid in aufgeloest if j < i]
        kandidaten = [vorher[-1]] if vorher else alle_ids
        verletzungen.extend(
            _pruefe_anwendungsblock(block_pfad, block, kandidaten, echte_items)
        )

    if not anker_gefunden:
        verletzungen.insert(
            0, Verletzung(REGEL_KEIN_ANKER, "Kein kompetenzbezug-Block im Dokument gefunden")
        )
    return verletzungen


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def format_text(verletzungen: list[Verletzung], quelle: str) -> str:
    zeilen = [f"pruefe_verankerung: {quelle}"]
    if not verletzungen:
        zeilen.append("Keine Verletzungen -- Verankerung ist vollstaendig und quellengetreu.")
        return "\n".join(zeilen)
    zeilen.append(f"{len(verletzungen)} Verletzung(en):")
    for v in verletzungen:
        ort = f" ({v.pfad})" if v.pfad else ""
        zeilen.append(f"  - [{v.regel}]{ort}: {v.meldung}")
    return "\n".join(zeilen)


def _cli(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("lesson_json", help="Pfad zu einer lesson.json-Datei")
    ap.add_argument("--json", action="store_true", help="maschinenlesbarer JSON-Bericht")
    args = ap.parse_args(argv)

    pfad = Path(args.lesson_json)
    if not pfad.is_file():
        print(f"Fehler: Datei nicht gefunden: {pfad}", file=sys.stderr)
        return 2

    try:
        verletzungen = pruefe_lesson(pfad)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        print(f"Fehler: {pfad} konnte nicht gelesen/geparst werden: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps([v.to_dict() for v in verletzungen], ensure_ascii=False, indent=2))
    else:
        print(format_text(verletzungen, str(pfad)))

    return 1 if verletzungen else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
