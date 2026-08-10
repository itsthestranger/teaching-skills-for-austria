#!/usr/bin/env python3
"""E10-09 -- assert shipped text against the RIS XML itself, by independent extraction.

Every other check in this repository compares an artifact to the output of the pipeline that
produced it. A fidelity bug present in *both* the parser and the build is therefore invisible,
and that is not hypothetical: four independent silent-loss mechanisms have reached shipped data
(V-58's SEK1.E stems, V-69's `<symbol>`-wrapped words, `element_text`'s `<symbol>` drop, and
V-80's `<gdash/>` plus the dropped D8 area descriptions), each caught by a human noticing an
anomaly rather than by any test.

So this module deliberately shares **no code** with `parse_lehrplan.py` or
`parse_bildungsstandards.py`. It re-implements the documented text contract from
`notes/ris-xml-structure.md` against the raw document, and asks one question per record: does
this exact shipped string occur in the source at all?

Two design rules keep it honest:

1. **Locate, do not re-derive.** It never tries to rebuild the record boundaries the parser
   found -- it flattens the whole document to text and asks whether the shipped string is
   present. A verifier that re-derived the structure would re-import the assumptions it exists
   to check.
2. **Normalise as little as possible.** Only whitespace collapsing and Unicode NFC are applied
   to both sides. Dashes, quotes, brackets and punctuation are compared as-is: normalising them
   away is what would make this check pass on text it should reject. `--audit-normalisation`
   reports how much slack the normalisation actually grants.

Usage::

    python data-pipeline/verify_source_fidelity.py                    # fixtures (offline)
    python data-pipeline/verify_source_fidelity.py --source resources # full documents
    python data-pipeline/verify_source_fidelity.py --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_ROOT = REPO_ROOT / "data-pipeline" / "tests" / "fixtures"
RESOURCE_ROOT = REPO_ROOT / "data-pipeline" / "resources"
KOMPETENZEN_ROOT = REPO_ROOT / "plugin" / "data" / "kompetenzen"
BIST_ROOT = REPO_ROOT / "plugin" / "data" / "bildungsstandards"

# Which source document each shipped shard must be located in. The fixture column is the
# committed per-subject extract (offline, and what CI runs); the resource column is the full
# RIS document, present only when data-pipeline/resources/ has been fetched.
SHARD_SOURCES: dict[str, tuple[str, str]] = {
    "PRIM.D": ("prim_deutsch.xml", "volksschule.xml"),
    "PRIM.M": ("prim_mathematik.xml", "volksschule.xml"),
    "PRIM.SU": ("prim_sachunterricht.xml", "volksschule.xml"),
    "SEK1.D": ("sek1_deutsch.xml", "mittelschule.xml"),
    "SEK1.E": ("sek1_fremdsprache.xml", "mittelschule.xml"),
    "SEK1.M": ("sek1_mathematik.xml", "mittelschule.xml"),
}
BIST_SOURCE = ("bildungsstandards_anl1.xml", "bildungsstandards.xml")

# Block-level elements: their text may not run into the neighbouring block's text, or a shipped
# string could be "located" across a boundary that does not exist in the document.
BLOCK_TAGS = {"absatz", "listelem", "ueberschrift", "td", "tr", "table", "liste",
              "aufzaehlung", "abschnitt", "schlussteil", "para", "g1", "g2"}

# The list bullet glyph, per notes/ris-xml-structure.md: a <symbol> is dropped by its *content*
# (a bare dash) and never by its `stellen` attribute -- 2,977 live symbols use stellen="3" for
# real sentence words, so keying on the attribute is what deleted words in V-69.
BULLET_GLYPHS = {"-", "–", "—", "−"}

ALNUM_TAIL = re.compile(r"[0-9A-Za-zÄÖÜäöüß]$")
ALNUM_HEAD = re.compile(r"^[0-9A-Za-zÄÖÜäöüß]")


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def normalise(text: str) -> str:
    """The only normalisation applied, to both sides alike: NFC plus whitespace collapse.

    Soft hyphens and zero-width characters are removed because they are invisible in both the
    source and the shipped string and would otherwise produce a mismatch no human could read.
    Nothing else is touched -- in particular dashes, quotation marks and brackets keep their
    exact code points, because collapsing those is precisely how a fidelity check stops being
    one.
    """
    text = _nfc(text)
    text = text.replace("­", "").replace("​", "").replace("﻿", "")
    text = text.replace(" ", " ")
    return re.sub(r"\s+", " ", text).strip()


def _image_token(element: ET.Element) -> str:
    """Inline formula images are shipped as ``⟦ABB:<datei>⟧`` tokens, so the source's <img>
    must be rendered the same way or every affected record would look divergent."""
    src = element.get("src") or element.get("Src") or ""
    return f"⟦ABB:{Path(src.replace('\\', '/')).name}⟧" if src else "⟦ABB⟧"


@dataclass
class _Flattener:
    """Flattens a RIS document to plain text, implementing the documented rules directly.

    Written as an explicit stack walk rather than a recursive `element_text`-style helper on
    purpose: the point is not to produce the same string the parser produces, but to produce
    one derived from the raw document by rules a reader can check against the notes.
    """

    parts: list[str] = field(default_factory=list)

    def _append(self, text: str, *, restore_boundary: bool = False) -> None:
        if not text:
            return
        if restore_boundary and self.parts:
            previous = self.parts[-1]
            if previous and ALNUM_TAIL.search(previous) and ALNUM_HEAD.match(text):
                # `Die</symbol>Schülerinnen` -> `Die Schülerinnen` (V-69 / §13.4). Only ever
                # inserted between a retained symbol word and an adjacent alphanumeric tail.
                self.parts.append(" ")
        self.parts.append(text)

    def walk(self, element: ET.Element) -> None:
        # RIS documents are namespaced, so ElementTree reports `{uri}listelem`. Stripping the
        # namespace is not cosmetic: with the prefix left on, every rule below silently stops
        # matching and the flattener degenerates into "concatenate all text", which keeps
        # bullets and footnote markers in the output and reports false divergences.
        tag = element.tag.rsplit("}", 1)[-1].lower()

        if tag == "super":
            # Footnote marker for the cross-cutting themes; removed from the quotable text and
            # preserved elsewhere as text_roh. Its tail still belongs to the sentence.
            self._append(element.tail or "")
            return

        if tag == "gdash":
            # V-80: an element that *is* the hyphen. Dropping it silently ate the hyphen in
            # "(Un-)Gleichungen" and shipped it that way.
            self._append("-")
            self._append(element.tail or "")
            return

        if tag in {"img", "binary"}:
            if tag == "img":
                self._append(_image_token(element))
            self._append(element.tail or "")
            return

        if tag in {"br", "tab", "abstand"}:
            self._append(" ")
            self._append(element.tail or "")
            return

        if tag == "nbsp":
            self._append(" ")
            self._append(element.tail or "")
            return

        if tag == "symbol":
            content = "".join(element.itertext())
            if content.strip() in BULLET_GLYPHS:
                pass  # presentation, not text
            else:
                self._append(content, restore_boundary=True)
                self._append("", restore_boundary=False)
                # a retained symbol word may also need separating from its own tail
                tail = element.tail or ""
                if tail and ALNUM_TAIL.search(content.strip()) and ALNUM_HEAD.match(tail):
                    self._append(" ")
                self._append(tail)
                return
            self._append(element.tail or "")
            return

        if tag in BLOCK_TAGS:
            self._append("\n")

        self._append(element.text or "")
        for child in element:
            self.walk(child)
        if tag in BLOCK_TAGS:
            self._append("\n")
        self._append(element.tail or "")

    def result(self) -> str:
        return "".join(self.parts)


def flatten_document(path: Path) -> str:
    flattener = _Flattener()
    flattener.walk(ET.parse(path).getroot())
    return flattener.result()


def haystack(path: Path) -> str:
    """The searchable form of a source document: flattened, then normalised exactly as the
    shipped strings are."""
    return normalise(flatten_document(path))


# Elements that hold a self-contained run of text. `schlussteil` belongs here and is easy to
# miss: it carries the Bildungsstandards sub-headings, so omitting it makes five perfectly
# faithful descriptor titles look invented.
TEXT_BLOCK_TAGS = {"listelem", "absatz", "ueberschrift", "td", "schlussteil"}


def source_blocks(path: Path) -> list[str]:
    """The document as a list of normalised text blocks.

    Matching per block rather than against one flattened string is what lets a shipped record be
    compared for *equality* with its source block. Whole-document containment cannot catch a
    truncation -- drop the leading word of a stem and the remainder is still a substring of the
    document -- and truncation is precisely the defect class (V-58, V-69) this guard exists for.
    """
    blocks = []
    for element in ET.parse(path).getroot().iter():
        if element.tag.rsplit("}", 1)[-1].lower() in TEXT_BLOCK_TAGS:
            flattener = _Flattener()
            flattener.walk(element)
            text = normalise(flattener.result())
            if text:
                blocks.append(text)
    return blocks


# ---------------------------------------------------------------------------
# Shipped records
# ---------------------------------------------------------------------------


@dataclass
class Record:
    record_id: str
    shard: str
    field_name: str
    text: str
    #: The record's own stem, when the source places it immediately before this string in the
    #: same block ("Kompetenzen: Die Schülerinnen und Schüler können <text>"). It is the only
    #: *word* content allowed to precede a bounded match; anything else means the shipped string
    #: starts partway into a source sentence.
    stem: str = ""


def _iter_json(value: object):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_json(child)


def competence_records(shard: str) -> list[Record]:
    """Every shipped competence's `stammsatz` and `text`, both of which are quoted verbatim as
    law by the skills and therefore both in scope.

    Reads the shard files directly rather than through the access layer: the access layer is
    part of what a fidelity bug could be hiding behind.
    """
    band, code = shard.split(".")
    shard_dir = KOMPETENZEN_ROOT / band.lower() / code.lower()
    records: list[Record] = []
    seen: set[tuple[str, str, str]] = set()
    for path in sorted(shard_dir.glob("*.json")):
        if path.name == "index.json":
            continue
        for node in _iter_json(json.loads(path.read_text(encoding="utf-8"))):
            record_id = node.get("id")
            if not isinstance(record_id, str) or ".AB." in record_id:
                continue
            if not isinstance(node.get("text"), str):
                continue
            for field_name in ("stammsatz", "text"):
                value = node.get(field_name)
                if not isinstance(value, str) or not value.strip():
                    continue
                key = (record_id, field_name, value)
                if key in seen:
                    continue  # SEK1.M repeats IDs across stages; identical text is one check
                seen.add(key)
                records.append(Record(record_id, shard, field_name, value))
    return records


def zielniveau_records(shard: str) -> list[Record]:
    """The per-class-year GeR sentences shipped in `meta.differenzierungs_achse.gers.je_stufe`.

    These are quoted to teachers as law ("das Zielniveau dieser Klasse ist ..."), so they belong
    inside this guard for the same reason `stammsatz` does. They arrived after the original sweep
    and would otherwise be the one class of shipped regulation text nothing located in the source.

    Unlike the competence records they are *not* whole source blocks -- each is the opening
    sentence of a block that continues with its own commentary ("... angestrebt. Es ist zu
    beachten, dass ...") -- so they take the bounded path. `test_verify_source_fidelity.py`
    additionally pins that each is a sentence-complete prefix, which is what rules out the
    trailing truncation the bounded mode alone cannot see.
    """
    band, code = shard.split(".")
    shard_dir = KOMPETENZEN_ROOT / band.lower() / code.lower()
    records: list[Record] = []
    seen: set[tuple[str, str]] = set()
    for path in sorted(shard_dir.glob("*.json")):
        achse = (json.loads(path.read_text(encoding="utf-8"))
                 .get("meta", {}).get("differenzierungs_achse", {}))
        for stufe, entry in sorted((achse.get("gers") or {}).get("je_stufe", {}).items()):
            satz = entry.get("satz")
            if not isinstance(satz, str) or not satz.strip():
                continue
            key = (stufe, satz)
            if key in seen:
                continue  # every part file of a shard carries the same meta block
            seen.add(key)
            records.append(Record(f"{shard}.GERS.{stufe}", shard, "gers.je_stufe.satz", satz))
    return records


def descriptor_records() -> list[Record]:
    records: list[Record] = []
    for path in sorted(BIST_ROOT.glob("*.json")):
        if path.name == "crosswalk.json":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        shard = data["meta"]["shard"]
        for descriptor in data.get("deskriptoren", []):
            stem = descriptor.get("stammsatz") or ""
            for field_name in ("stammsatz", "text", "titel"):
                value = descriptor.get(field_name)
                if isinstance(value, str) and value.strip():
                    records.append(Record(descriptor["id"], shard, field_name, value,
                                          stem="" if field_name == "stammsatz" else stem))
        for bereich in data.get("kompetenzbereiche", []):
            # M8 is two-dimensional (4 Handlungs- x 4 Inhaltsbereiche, V-80), and its `name` is
            # the project's own composition of the two axes -- "Darstellen, Modellbilden -
            # Zahlen und Maße" occurs nowhere in the source as one string. Checking the
            # composition verbatim would be checking the wrong thing, so the two axis names are
            # checked instead; that both exist in the source is the real claim. The composition
            # itself is pinned separately, in the test module.
            composed = "handlungsbereich" in bereich and "inhaltsbereich" in bereich
            fields = ("handlungsbereich", "inhaltsbereich") if composed else ("name",)
            for field_name in (*fields, "beschreibung"):
                value = bereich.get(field_name)
                if isinstance(value, str) and value.strip():
                    # V-80's fourth silent-loss mechanism was exactly these descriptions being
                    # dropped, so they are in scope, not just the descriptors. Kompetenzbereiche
                    # are keyed by `code`; they carry no `id`.
                    records.append(Record(bereich["code"], shard, f"bereich.{field_name}", value))
    return records


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


@dataclass
class Divergence:
    record_id: str
    shard: str
    field_name: str
    shipped: str
    longest_prefix_found: str
    reason: str = "not-in-source"

    def to_dict(self) -> dict[str, str]:
        return {
            "record_id": self.record_id,
            "shard": self.shard,
            "field": self.field_name,
            "reason": self.reason,
            "shipped": self.shipped,
            "longest_prefix_located_in_source": self.longest_prefix_found,
        }


def _longest_located_prefix(needle: str, hay: str) -> str:
    """How far into the shipped string the source still agrees -- the first point of divergence
    is what a human needs in order to act on a failure."""
    low, high = 0, len(needle)
    while low < high:
        mid = (low + high + 1) // 2
        if needle[:mid] in hay:
            low = mid
        else:
            high = mid - 1
    return needle[:low]


# What may legitimately precede a shipped string inside its source block: nothing, a label
# ("Kompetenzen:", "Kompetenzbereich:"), or an opening quote ("Handlungsbereich: „...").
# Anything else -- in particular a preceding *word* -- means the shipped string starts partway
# into the source sentence, which is what a leading truncation looks like. This is the rule that
# rejects V-69's dropped "Die".
LEADING_RESIDUE_OK = re.compile(r'(^$|[:„“"«(\[]$)')


def _is_bounded(needle: str, block: str, stem: str = "") -> bool:
    """Does *needle* occur in *block* on word boundaries, and not partway into a sentence?

    A shipped record may legitimately be part of a block -- the Bildungsstandards stem sits
    inside "Kompetenzen: Die Schülerinnen und Schüler können", and an area name inside
    "Kompetenzbereich: Zuhören und Sprechen". What it may never be is a match that begins in the
    middle of a source word, or after a word that the shipped string dropped.

    **Known limit, deliberate:** a *trailing* truncation inside a shared block is not caught
    here, because a shipped title legitimately shares a block with the label that follows it
    (D4 `RECHTSCHREIBEN`). Curriculum records do not rely on this path at all -- they are held
    to whole-block equality, where truncation in either direction fails.
    """
    start = block.find(needle)
    while start != -1:
        end = start + len(needle)
        left_ok = start == 0 or not ALNUM_HEAD.match(block[start - 1])
        right_ok = end == len(block) or not ALNUM_TAIL.search(block[end])
        residue = block[:start].strip()
        residue_ok = bool(LEADING_RESIDUE_OK.search(residue))
        if not residue_ok and stem:
            # A descriptor's text may follow its own stem inside one block; the stem must then
            # be exactly what precedes it, and the text before *that* must itself be a label.
            head = normalise(stem)
            if residue.endswith(head):
                before = residue[: len(residue) - len(head)].strip()
                residue_ok = bool(LEADING_RESIDUE_OK.search(before))
        if left_ok and right_ok and residue_ok:
            return True
        start = block.find(needle, start + 1)
    return False


def verify(records: list[Record], blocks: list[str], *, require_exact: bool = False) -> list[Divergence]:
    """Locate every shipped string in the source blocks.

    A record passes in one of two modes, strongest first:

    ``exact``    the normalised record *is* a whole source block. Every one of the 533 shipped
                 curriculum strings matches this way, so any truncation, insertion or edit fails.
    ``bounded``  the record occurs inside a block on word boundaries. Needed for the
                 Bildungsstandards, whose stems and area names share a block with a label.
    """
    block_set = set(blocks)
    divergences = []
    for record in records:
        needle = normalise(record.text)
        if not needle:
            continue
        if needle in block_set:
            continue
        if not require_exact and any(_is_bounded(needle, block, record.stem) for block in blocks):
            continue
        hay = " \n".join(blocks)
        if require_exact and any(_is_bounded(needle, block, record.stem) for block in blocks):
            reason = "not-a-whole-source-block"
        else:
            reason = "mid-word-match-only" if needle in hay else "not-in-source"
        divergences.append(
            Divergence(record.record_id, record.shard, record.field_name, needle,
                       _longest_located_prefix(needle, hay), reason)
        )
    return divergences


def match_modes(records: list[Record], blocks: list[str]) -> dict[str, int]:
    """How each record matched. Reported so a regression that quietly demotes records from
    `exact` to `bounded` -- i.e. weakens the guard -- is visible rather than silent."""
    block_set = set(blocks)
    modes = {"exact": 0, "bounded": 0, "failed": 0}
    for record in records:
        needle = normalise(record.text)
        if not needle:
            continue
        if needle in block_set:
            modes["exact"] += 1
        elif any(_is_bounded(needle, block, record.stem) for block in blocks):
            modes["bounded"] += 1
        else:
            modes["failed"] += 1
    return modes


def resolve_source(name_pair: tuple[str, str], mode: str) -> Path | None:
    fixture_name, resource_name = name_pair
    if mode == "resources":
        candidate = RESOURCE_ROOT / resource_name
        return candidate if candidate.is_file() else None
    candidate = FIXTURE_ROOT / fixture_name
    return candidate if candidate.is_file() else None


def run(mode: str) -> tuple[list[Divergence], dict[str, int], list[str], dict[str, int]]:
    divergences: list[Divergence] = []
    checked: dict[str, int] = {}
    unavailable: list[str] = []
    modes: dict[str, int] = {"exact": 0, "bounded": 0, "failed": 0}

    def tally(records: list[Record], blocks: list[str]) -> None:
        for key, count in match_modes(records, blocks).items():
            modes[key] += count

    for shard, sources in SHARD_SOURCES.items():
        path = resolve_source(sources, mode)
        if path is None:
            unavailable.append(shard)
            continue
        records = competence_records(shard)
        blocks = source_blocks(path)
        # Every one of the 533 shipped curriculum strings *is* a whole source block (measured),
        # so they are held to equality: a truncation in either direction fails. Only the
        # Bildungsstandards, whose records share blocks with their labels, need the weaker mode.
        divergences.extend(verify(records, blocks, require_exact=True))
        tally(records, blocks)
        checked[shard] = len(records)

        # Opening sentences of their blocks, not whole blocks -- bounded, see zielniveau_records.
        niveau_records = zielniveau_records(shard)
        divergences.extend(verify(niveau_records, blocks))
        tally(niveau_records, blocks)
        checked[shard] += len(niveau_records)

    bist_path = resolve_source(BIST_SOURCE, mode)
    if bist_path is None:
        unavailable.append("BIST")
    else:
        blocks = source_blocks(bist_path)
        records = descriptor_records()
        divergences.extend(verify(records, blocks))
        tally(records, blocks)
        for record in records:
            checked[record.shard] = checked.get(record.shard, 0) + 1

    return divergences, checked, unavailable, modes


def format_text(divergences: list[Divergence], checked: dict[str, int], unavailable: list[str],
                mode: str, modes: dict[str, int]) -> str:
    total = sum(checked.values())
    lines = [f"verify_source_fidelity: {total} shipped string(s) checked against the RIS XML "
             f"({mode})"]
    for shard in sorted(checked):
        lines.append(f"  {shard:8} {checked[shard]:4} string(s)")
    lines.append(f"  match modes: {modes['exact']} exact block, {modes['bounded']} bounded "
                 f"fragment, {modes['failed']} failed")
    if unavailable:
        lines.append(f"  not available in this mode: {', '.join(sorted(unavailable))}")
    if not divergences:
        lines.append("")
        lines.append("No divergence: every shipped string was located verbatim in the source.")
        return "\n".join(lines)
    lines.append("")
    lines.append(f"DIVERGENCE -- {len(divergences)} shipped string(s) not found in the source:")
    for divergence in divergences:
        lines.append(f"  [{divergence.shard}] {divergence.record_id} ({divergence.field_name})")
        lines.append(f"    shipped : {divergence.shipped[:160]}")
        lines.append(f"    matched : {divergence.longest_prefix_found[:160]}")
        lines.append(f"    diverges after {len(divergence.longest_prefix_found)} character(s)")
    return "\n".join(lines)


def _audit_normalisation() -> str:
    """How much slack does `normalise` grant? A fidelity check whose normalisation is wide
    enough to absorb real edits proves nothing, so the slack is reported rather than assumed."""
    probes = [
        ("whitespace collapse", "a  b", "a b", True),
        ("NFC composition", "Schön", "Schön", True),
        ("soft hyphen removal", "Ge­setz", "Gesetz", True),
        ("en dash vs hyphen", "A–B", "A-B", False),
        ("typographic vs straight quote", "„Wort“", '"Wort"', False),
        ("dropped word", "a b c", "a c", False),
        ("dropped hyphen (V-80)", "(Un-)Gleichungen", "(Un)Gleichungen", False),
        ("changed number", "1/2", "1/3", False),
    ]
    lines = ["normalisation audit -- equal after normalise()?"]
    for label, left, right, expected in probes:
        actual = normalise(left) == normalise(right)
        flag = "ok " if actual == expected else "!! "
        lines.append(f"  {flag}{label}: {actual} (expected {expected})")
    if any(normalise(a) == normalise(b) for _, a, b, e in probes if not e):
        lines.append("  WARNING: normalisation absorbs a difference it must not")
    return "\n".join(lines)


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", choices=("fixtures", "resources"), default="fixtures",
                        help="committed per-subject extracts (default, offline) or the full "
                             "documents in data-pipeline/resources/")
    parser.add_argument("--json", action="store_true", help="machine-readable report")
    parser.add_argument("--audit-normalisation", action="store_true",
                        help="report what the normalisation does and does not absorb")
    args = parser.parse_args(argv)

    if args.audit_normalisation:
        print(_audit_normalisation())
        return 0

    divergences, checked, unavailable, modes = run(args.source)

    if args.json:
        print(json.dumps({
            "mode": args.source,
            "checked": checked,
            "total_checked": sum(checked.values()),
            "match_modes": modes,
            "unavailable": sorted(unavailable),
            "divergences": [d.to_dict() for d in divergences],
        }, ensure_ascii=False, indent=2))
    else:
        print(format_text(divergences, checked, unavailable, args.source, modes))

    if args.source == "resources" and unavailable:
        print(f"error: --source resources requested but missing: {', '.join(unavailable)}",
              file=sys.stderr)
        return 2
    return 1 if divergences else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
