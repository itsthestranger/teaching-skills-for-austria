#!/usr/bin/env python3
"""Parser for the Austrian Bildungsstandards RIS XML (BiSt Anl. 1, NOR40255561).

Scope: the five shards named in FINDINGS.md V-13/plan Executive Summary --
**D4, M4, D8, E8, M8** (Deutsch/Mathematik at the end of primary, 4.
Schulstufe; Deutsch/(Erste) Lebende Fremdsprache/Mathematik at the end of
Sekundarstufe I, 8. Schulstufe). There is no Sachunterricht chapter in this
regulation (measured, not assumed -- see the E8-01 report); that gap is
handled downstream as a defined-empty result (E8-04), not here.

Design notes -- deliberately a separate, simpler module from
``parse_lehrplan.py``, not an extension of it
------------------------------------------------------------------------
* **A different document, a different shape.** BiSt is 393 flat children in
  one ``<abschnitt>`` (measured -- matches the plan's figure exactly, see
  the E8-01 report), covering two fixed-grade *outcome checkpoints*, not a
  four-year curriculum grid. There is no Anwendungsbereiche/Lehrstoff axis,
  no progression, no differentiation, no inline images, no ``<super>``
  footnote system -- all measured absent (see ``_zaehle_elementtypen`` in
  the test suite). Reusing ``parse_lehrplan``'s state machine would carry a
  great deal of Lehrplan-specific machinery this document has no use for.
* **stdlib only**, same as ``parse_lehrplan.py``.
* **Verbatim text is sacred.** :func:`element_text` documents its two
  interventions (list-bullet ``<symbol>`` drop, ``<gdash/>`` hyphen
  restoration) exactly the way ``parse_lehrplan.element_text`` documents
  its own -- see the module for why ``<gdash/>`` needed a *new* rule BiSt's
  sibling document never triggered.
* **Own IDs, RIS text only.** No IQS numbering, graphics or presentations
  are read or reproduced -- see ``data-pipeline/schema/bist_id_schema.py``
  for the new ``AT.BIST`` namespace this module mints into.
* **Tolerant by default**, same policy as ``parse_lehrplan.py``: unexpected
  structure is logged as a :class:`ParseIssue` and carried; the only hard
  failures are a missing required field or an ID collision.

Usage
-----
    python3 parse_bildungsstandards.py --summary
    python3 parse_bildungsstandards.py --verify
    python3 parse_bildungsstandards.py --write   # plugin/data/bildungsstandards/*.json
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "schema"))
import bist_id_schema as BID  # noqa: E402

NS = "{http://www.bka.gv.at}"
LOG = logging.getLogger("parse_bildungsstandards")

DEFAULT_SOURCE = (
    Path(__file__).resolve().parent / "resources" / "bildungsstandards" / "NOR40255561.xml"
)
DEFAULT_OUT_DIR = Path(__file__).resolve().parents[1] / "plugin" / "data" / "bildungsstandards"
MANIFEST_PATH = Path(__file__).resolve().parent / "resources" / "manifest.json"


class ParseError(Exception):
    """A required field is missing, or an ID collision occurred."""


@dataclass
class ParseIssue:
    """A tolerated structural surprise -- logged, parsing continues."""

    art: str
    kontext: str
    detail: str = ""


# --------------------------------------------------------------------------
# XML primitives
# --------------------------------------------------------------------------


def localname(el: ET.Element) -> str:
    return el.tag.replace(NS, "", 1) if isinstance(el.tag, str) else ""


def find_abschnitt(root: ET.Element) -> ET.Element:
    nutzdaten = root.find(NS + "nutzdaten")
    if nutzdaten is None:
        raise ParseError("no <nutzdaten> element -- not a RIS document")
    for c in nutzdaten:
        if localname(c) == "abschnitt":
            return c
    raise ParseError("<nutzdaten> contains no <abschnitt>")


def element_text(el: ET.Element) -> str:
    """Extract text from *el* verbatim, with two documented interventions.

    1. ``<symbol>`` list-bullet glyphs (a standalone ``–``/``-``) are
       presentation, not text, and are dropped -- exactly
       ``parse_lehrplan.element_text``'s rule 1. Measured against the live
       document: every one of BiSt's 268 ``<symbol>`` elements is this bullet
       form (one per ``<listelem>``, no exceptions) -- unlike the Lehrplan
       documents, BiSt never uses ``<symbol>`` to carry a real word, so no
       V-69-style word-loss case exists here today. The rule is kept
       word-preserving anyway (mirroring the Lehrplan fix), not because a
       live case needs it, but because "drop unconditionally" is exactly the
       mistake V-69 already cost the project once.
    2. ``<gdash/>`` -- a self-closing element found only in this document, not
       in either Lehrplan XML (measured: 8 occurrences, both inside
       Mathematik-8 Handlungsbereich/Inhaltsbereich list items, e.g.
       ``(Un<gdash/>)Gleichungen``, ``(Rechen<gdash/>)Modell``). It renders a
       typeset hyphen inside a bracketed compound-word shorthand. Naive
       ``itertext()`` drops it silently (no text/tail of its own), turning
       "(Un-)Gleichungen" into "(Un)Gleichungen" -- a real verbatim-fidelity
       loss of exactly the kind the project's CLAUDE.md flags as having
       already happened three times. Replaced with a literal ASCII hyphen
       ``-`` at the position it occupies.

    Nothing else is touched: no reflowing, no whitespace collapsing. This
    document has no ``<super>`` and no ``<binary>`` (measured: zero of
    either across all 393 elements), so unlike ``ExtractedText`` there is no
    separate "roh" variant to track -- ``text`` already is the complete,
    lossless-modulo-bullet-glyph rendering.
    """
    parts: list[str] = []

    def emit(chunk: str | None) -> None:
        if chunk:
            parts.append(chunk)

    def walk(node: ET.Element, *, is_root: bool) -> None:
        name = localname(node)
        if not is_root:
            if name == "symbol":
                symbol_text = node.text or ""
                if symbol_text.strip() in {"–", "-"}:
                    emit(node.tail)
                    return
                emit(symbol_text)
                for child in node:
                    walk(child, is_root=False)
                if (node.text and node.tail and node.text[-1].isalnum()
                        and node.tail[0].isalnum()):
                    emit(" ")
                emit(node.tail)
                return
            if name == "gdash":
                emit("-")
                emit(node.tail)
                return
        emit(node.text)
        for child in node:
            walk(child, is_root=False)
        if not is_root:
            emit(node.tail)

    walk(el, is_root=True)
    return "".join(parts).strip()


# --------------------------------------------------------------------------
# Structural regexes
# --------------------------------------------------------------------------

#: "N. Teil" -- a checkpoint boundary (4./8. Schulstufe). Matched on TEXT,
#: not on the ``typ`` attribute: measured against the live document, the
#: heading LEVEL attribute is not a reliable signal here (unlike the
#: Lehrplan documents' g1/g1min split for TEIL vs. Abschnitt) -- "2. Teil" is
#: ``typ="g1"`` exactly like "1. Teil", but so is "2. Abschnitt" further
#: down, which is ``typ="g1min"`` the first time ("1. Abschnitt") and
#: ``typ="g1"`` every subsequent time. This is a real, measured source
#: inconsistency (logged as a deviation), not a parsing bug -- text pattern
#: is the only reliable discriminator.
TEIL_RE = re.compile(r"^\d+\.\s*Teil$")

#: "N. Abschnitt" -- a subject-group boundary. See TEIL_RE's note: matched
#: on text, never on ``typ``.
ABSCHNITT_RE = re.compile(r"^\d+\.\s*Abschnitt$")

#: The three subject headings BiSt actually contains (measured against the
#: live document -- no Sachunterricht chapter exists at all). "(Erste)
#: Lebende Fremdsprache (Englisch)" is BiSt's own designation (FINDINGS
#: V-29) -- note the "(Englisch)" suffix the Lehrplan heading omits.
FACH_HEADINGS: dict[str, str] = {
    "Deutsch": "D",
    "Mathematik": "M",
    "(Erste) Lebende Fremdsprache (Englisch)": "E",
}

#: A Kompetenzbereich/Handlungsbereich heading. Both forms are
#: ``ueberschrift/@typ="erll"`` in the live document.
BEREICH_RE = re.compile(r"^(Kompetenzbereich|Handlungsbereich)\b")

#: The plain "Kompetenzbereich: <Name>" form (D4/M4/D8/E8). Always carries a
#: colon in the live document -- measured, all 23 occurrences.
KOMPETENZBEREICH_RE = re.compile(r"^Kompetenzbereich:\s*(.+)$")

#: The two-axis "Handlungsbereich[:] „HB[“] – Inhaltsbereich „IB“" form
#: (M8 only). Tolerant of two measured source quirks that are NOT
#: normalised away from the stored ``ueberschrift_roh`` (only used here to
#: extract the two clean axis labels for code-minting/display):
#: one heading keeps the colon after "Handlungsbereich" that all 15 others
#: drop, and one is missing its closing „" guillemet after the HB name.
#: Both are genuine RIS typesetting inconsistencies, preserved verbatim
#: elsewhere and never "corrected" here.
HANDLUNGSBEREICH_RE = re.compile(
    r"^Handlungsbereich:?\s*„(?P<hb>.+?)“?\s*–\s*Inhaltsbereich\s*„(?P<ib>.+)“$"
)

#: The literal section-label prefix introducing a competence stem/list,
#: e.g. "Kompetenzen: Die Schülerinnen und Schüler können". This is BiSt's
#: own scaffolding word (absent from the Lehrplan documents) and is
#: deliberately stripped before stem-splitting -- it is a run-in label
#: ("Competencies:"), not part of the competence sentence itself.
KOMPETENZEN_PREFIX_RE = re.compile(r"^Kompetenzen:\s*", re.IGNORECASE)

#: The competence-stem sentence opener, with or without the trailing verb
#: "können" (both occur -- measured) and with or without the plural suffix
#: "-innen". Group 1 is the stem; group 2 is whatever text follows it in
#: the same paragraph (non-empty only for the two standalone single-sentence
#: competences that carry no following ``<liste>`` -- see the E8-01 report).
STEM_RE = re.compile(
    r"^(Die\s+Sch(?:ü|ue)lerinnen\s+und\s+Sch(?:ü|ue)ler(?:innen)?"
    r"(?:\s+k(?:ö|oe)nnen)?)\s*[:,]?\s*(.*)$",
    re.IGNORECASE | re.DOTALL,
)


def _slugify(text: str) -> str:
    """Deterministic fallback area code for an area name missing from
    ``bist_id_schema.BEREICH_CODES`` -- should never fire against the live
    document (asserted by the test suite); kept only as the same tolerant
    safety net ``parse_lehrplan.py`` has for the Lehrplan tables."""
    s = re.sub(r"[^A-Za-z0-9]+", "", text).upper()
    if not s:
        return "UNBEKANNT"
    if not s[0].isalpha():
        s = "X" + s
    return s[:24]


# --------------------------------------------------------------------------
# Result shapes
# --------------------------------------------------------------------------


@dataclass
class Kompetenzbereich:
    code: str
    name: str
    ueberschrift_roh: str
    handlungsbereich: str | None = None
    inhaltsbereich: str | None = None
    gruppe: str | None = None
    """The M4-only subject-internal grouping label ("Allgemeine
    mathematische Kompetenzen" / "Inhaltliche mathematische Kompetenzen") --
    ``ueberschrift/@typ="para"`` headings that group several Kompetenzbereiche
    without being one themselves. ``None`` for every other shard."""
    beschreibung: str | None = None
    """A verbatim area-level description sentence immediately following the
    Kompetenzbereich heading, before any titled sub-group -- measured:
    D8-only (all 4 of its areas), e.g. "Durch Zuhören gesprochene Texte
    (auch medial vermittelt) verstehen, an private und öffentliche
    Kommunikationssituationen angepasste Gespräche führen und mündliche
    Präsentationen durchführen." Distinguished from a sub-group Titel by
    carrying no ``<gs>`` (bold) wrapper and not starting with "Kompetenzen:".
    Dropping this sentence (as an early version of this parser did, logging
    it as an "unerwarteter_absatz" issue) would silently lose real
    regulation text -- exactly the failure mode CLAUDE.md warns has already
    happened three times in this project."""
    kompetenzen_begonnen: bool = False
    """Internal parser bookkeeping (not serialised): whether a titled
    sub-group, a stem or a ``<liste>`` has been seen yet for this area.
    Distinguishes a legitimate ``beschreibung`` sentence (only ever the
    very first content after the heading) from a genuinely unexpected
    paragraph appearing later, which still logs as an issue."""


@dataclass
class Deskriptor:
    id: str
    fach: str
    programmstufe: str
    bereich_code: str
    stammsatz: str
    text: str
    ordinal: int
    titel: str | None = None


@dataclass
class ShardResult:
    shard: str
    fach: str
    fach_name: str
    programmstufe: str
    programmstufe_name: str
    teil: str
    abschnitt: str
    kompetenzbereiche: list[Kompetenzbereich] = field(default_factory=list)
    deskriptoren: list[Deskriptor] = field(default_factory=list)
    kompetenzmodell_hinweis: str | None = None
    """Subject-level explanatory prose preceding the first Kompetenzbereich,
    e.g. Mathematik-8's "Das Kompetenzmodell für Mathematik auf der 8.
    Schulstufe legt „Inhaltsbereiche" fest, ..." paragraph -- present only
    where the source actually has one (measured: M8 only)."""
    issues: list[ParseIssue] = field(default_factory=list)


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------


class BildungsstandardsParser:
    def __init__(self, root: ET.Element):
        self.abschnitt = find_abschnitt(root)
        self.children: list[ET.Element] = list(self.abschnitt)
        self.kopf = self._lese_kopf_metadaten()
        self.global_issues: list[ParseIssue] = []

    # -- header/footer metadata (RIS document fields, not content) --------

    def _lese_kopf_metadaten(self) -> dict[str, str]:
        """Read every ``ueberschrift/@typ="titel"`` + following ``absatz``
        label/value pair, wherever it occurs (header fields 4-20, footer
        fields 385-392 -- measured, none occur inside the 21-384 content
        span). One dict covering both; footer keys simply overwrite nothing
        since the labels differ (Kurztitel vs. Gesetzesnummer etc.)."""
        out: dict[str, str] = {}
        n = len(self.children)
        i = 0
        while i < n:
            c = self.children[i]
            if localname(c) == "ueberschrift" and c.get("typ") == "titel":
                label = element_text(c)
                j = i + 1
                while j < n and localname(self.children[j]) == "abstand":
                    j += 1
                value = ""
                if j < n and localname(self.children[j]) == "absatz":
                    value = element_text(self.children[j])
                    j += 1
                out[label] = value
                i = j
                continue
            i += 1
        return out

    def provenienz(self) -> dict:
        k = self.kopf
        prov = {
            "quelle": "RIS Bundesrecht konsolidiert",
            "kurztitel": k.get("Kurztitel", ""),
            "nor": k.get("Dokumentnummer", ""),
            "gesetzesnummer": k.get("Gesetzesnummer", ""),
            "kundmachungsorgan": k.get("Kundmachungsorgan", "").strip(),
            "anlage": k.get("§/Artikel/Anlage", ""),
            "typ": k.get("Typ", ""),
            "abkuerzung": k.get("Abkürzung", ""),
            "inkrafttretensdatum": k.get("Inkrafttretensdatum", ""),
            "zuletzt_aktualisiert": k.get("Zuletzt aktualisiert am", ""),
        }
        manifest_extra = _lade_manifest_eintrag_optional()
        if manifest_extra:
            for key in ("dokument_url", "eli"):
                if manifest_extra.get(key):
                    prov[key] = manifest_extra[key]
            # The manifest calls it `retrieval_date`; every shipped shard calls it `stand`,
            # exactly as build_dataset.py maps it for the curriculum shards. One name across
            # both datasets keeps lesson_common.kompetenz_citation()'s "Stand:" half working
            # for a Bildungsstandards source too, instead of silently dropping it.
            if manifest_extra.get("retrieval_date"):
                prov["stand"] = manifest_extra["retrieval_date"]
        return prov

    # -- helpers ------------------------------------------------------

    def _naechstes_nicht_abstand(self, start: int) -> int | None:
        n = len(self.children)
        j = start
        while j < n and localname(self.children[j]) == "abstand":
            j += 1
        return j if j < n else None

    @staticmethod
    def _teile_stamm(rest: str) -> tuple[str, str]:
        m = STEM_RE.match(rest)
        if not m:
            return rest.strip(), ""
        stem = re.sub(r"\s+", " ", m.group(1)).strip()
        inhalt = m.group(2).strip()
        return stem, inhalt

    def _neuer_bereich(
        self, txt: str, fach_code: str, programmstufe: str, shard: ShardResult, gruppe: str | None
    ) -> Kompetenzbereich:
        m = HANDLUNGSBEREICH_RE.match(txt)
        if m:
            hb = m.group("hb").strip()
            ib = m.group("ib").strip()
            try:
                code = BID.m_sch8_bereich_code(hb, ib)
            except KeyError:
                code = _slugify(txt)
                shard.issues.append(ParseIssue("bereich_ohne_code", txt))
            name = f"{hb} – {ib}"
            bereich = Kompetenzbereich(
                code=code, name=name, ueberschrift_roh=txt,
                handlungsbereich=hb, inhaltsbereich=ib, gruppe=gruppe,
            )
        else:
            m2 = KOMPETENZBEREICH_RE.match(txt)
            clean = m2.group(1).strip() if m2 else txt
            tabelle = BID.BEREICH_CODES.get(f"{fach_code}.{programmstufe}", {})
            code = tabelle.get(clean)
            if code is None:
                code = _slugify(clean)
                shard.issues.append(ParseIssue("bereich_ohne_code", txt))
            bereich = Kompetenzbereich(code=code, name=clean, ueberschrift_roh=txt, gruppe=gruppe)

        vorhandene = [b for b in shard.kompetenzbereiche if b.code == bereich.code]
        if vorhandene:
            shard.issues.append(ParseIssue("bereichscode_wiederholt", txt, bereich.code))
            return vorhandene[0]
        shard.kompetenzbereiche.append(bereich)
        return bereich

    def _liste_lesen(
        self, liste_el: ET.Element, pending_titel: str | None, pending_stem: str | None,
        shard: ShardResult,
    ) -> tuple[str | None, str, list[str]]:
        schlussteile = [ch for ch in liste_el if localname(ch) == "schlussteil"]
        titel = pending_titel
        stem = pending_stem

        if len(schlussteile) == 1:
            combined = element_text(schlussteile[0])
            m = re.search(r"Kompetenzen:\s*", combined, re.IGNORECASE)
            if not m:
                shard.issues.append(ParseIssue("schlussteil_ohne_kompetenzen_label", combined))
                titel = combined
            else:
                titel_teil = combined[: m.start()].strip()
                stem_teil = combined[m.end():]
                if titel_teil:
                    titel = titel_teil
                stem, extra = self._teile_stamm(stem_teil)
                if extra:
                    shard.issues.append(ParseIssue("schlussteil_stamm_mit_ueberschuss", combined, extra))
        elif len(schlussteile) == 2:
            titel = element_text(schlussteile[0]).strip() or titel
            raw = element_text(schlussteile[1])
            if not KOMPETENZEN_PREFIX_RE.match(raw):
                shard.issues.append(ParseIssue("schlussteil_ohne_kompetenzen_label", raw))
                stem = raw
            else:
                rest = KOMPETENZEN_PREFIX_RE.sub("", raw)
                stem, extra = self._teile_stamm(rest)
                if extra:
                    shard.issues.append(ParseIssue("schlussteil_stamm_mit_ueberschuss", raw, extra))
        elif len(schlussteile) > 2:
            shard.issues.append(ParseIssue("unerwartete_schlussteil_anzahl", str(len(schlussteile))))

        if stem is None:
            shard.issues.append(ParseIssue("liste_ohne_stamm", element_text(liste_el)[:60]))
            stem = ""

        items: list[str] = []
        for aufzaehlung in liste_el:
            if localname(aufzaehlung) != "aufzaehlung":
                continue
            for listelem in aufzaehlung:
                if localname(listelem) != "listelem":
                    continue
                items.append(element_text(listelem))
        return titel, stem, items

    # -- main pass ------------------------------------------------------

    def parse(self) -> dict[tuple[str, str], ShardResult]:
        shards: dict[tuple[str, str], ShardResult] = {}
        lfd_zaehler: dict[tuple[str, str, str], int] = {}

        teil_text: str | None = None
        programmstufe: str | None = None
        programmstufe_name: str | None = None
        abschnitt_text: str | None = None
        fach_code: str | None = None
        fach_name: str | None = None
        pending_gruppe: str | None = None
        current_shard: ShardResult | None = None
        bereich: Kompetenzbereich | None = None
        pending_titel: str | None = None
        pending_stem: str | None = None

        n = len(self.children)
        started = False
        i = 0
        while i < n:
            c = self.children[i]
            tag = localname(c)
            typ = c.get("typ", "")

            if tag == "ueberschrift" and typ == "titel":
                if started:
                    break  # footer metadata block -- content region is over
                i += 1
                continue

            txt = element_text(c)

            if tag == "ueberschrift" and TEIL_RE.match(txt):
                started = True
                teil_text = txt
                programmstufe = BID.TEIL_ZU_PROGRAMMSTUFE.get(txt)
                if programmstufe is None:
                    self.global_issues.append(ParseIssue("unbekanntes_teil", txt))
                fach_code = fach_name = None
                current_shard = None
                bereich = None
                pending_gruppe = None
                nxt = self._naechstes_nicht_abstand(i + 1)
                if (nxt is not None and localname(self.children[nxt]) == "ueberschrift"
                        and self.children[nxt].get("typ") == "g2"):
                    programmstufe_name = element_text(self.children[nxt])
                i += 1
                continue

            if tag == "ueberschrift" and ABSCHNITT_RE.match(txt):
                abschnitt_text = txt
                fach_code = fach_name = None
                current_shard = None
                bereich = None
                pending_gruppe = None
                i += 1
                continue

            if tag == "ueberschrift" and txt in FACH_HEADINGS and programmstufe is not None:
                fach_code = FACH_HEADINGS[txt]
                fach_name = txt
                bereich = None
                pending_titel = pending_stem = None
                pending_gruppe = None
                if BID.ist_gueltige_kombination(fach_code, programmstufe):
                    key = (fach_code, programmstufe)
                    if key not in shards:
                        shards[key] = ShardResult(
                            shard=BID.shard_name(fach_code, programmstufe),
                            fach=fach_code, fach_name=fach_name,
                            programmstufe=programmstufe,
                            programmstufe_name=programmstufe_name or "",
                            teil=teil_text or "", abschnitt=abschnitt_text or "",
                        )
                    current_shard = shards[key]
                else:
                    current_shard = None
                    self.global_issues.append(
                        ParseIssue("fach_ausserhalb_scope", txt, f"{fach_code}/{programmstufe}")
                    )
                i += 1
                continue

            if current_shard is None:
                i += 1
                continue

            if tag == "ueberschrift" and typ == "erll" and BEREICH_RE.match(txt):
                bereich = self._neuer_bereich(txt, fach_code, programmstufe, current_shard, pending_gruppe)
                pending_titel = pending_stem = None
                i += 1
                continue

            if (bereich is not None and bereich.beschreibung is None and not bereich.kompetenzen_begonnen
                    and tag == "absatz" and typ == "abs"
                    and not any(localname(ch) == "gs" for ch in c)
                    and not txt.startswith("Kompetenzen:")):
                # Area-level description sentence immediately following the
                # Kompetenzbereich heading, before any titled sub-group
                # (measured: D8 only). See Kompetenzbereich.beschreibung.
                bereich.beschreibung = txt
                i += 1
                continue

            if tag == "ueberschrift" and typ == "para" and txt not in FACH_HEADINGS:
                # M4-only subject-internal grouping label, e.g. "Allgemeine
                # mathematische Kompetenzen" -- applies to every Kompetenzbereich
                # until the next one, TEIL, Abschnitt or Fach change.
                pending_gruppe = txt
                i += 1
                continue

            if bereich is None and tag == "absatz" and typ == "abs":
                # Subject-level explanatory prose before the first
                # Kompetenzbereich (measured: Mathematik-8 only).
                if current_shard.kompetenzmodell_hinweis:
                    current_shard.kompetenzmodell_hinweis += " " + txt
                else:
                    current_shard.kompetenzmodell_hinweis = txt
                i += 1
                continue

            if bereich is None:
                i += 1
                continue

            if tag == "absatz" and typ == "abs":
                has_gs = any(localname(ch) == "gs" for ch in c)
                if txt.startswith("Kompetenzen:"):
                    rest = KOMPETENZEN_PREFIX_RE.sub("", txt)
                    stem, inhalt = self._teile_stamm(rest)
                    next_idx = self._naechstes_nicht_abstand(i + 1)
                    next_is_liste = next_idx is not None and localname(self.children[next_idx]) == "liste"
                    bereich.kompetenzen_begonnen = True
                    if next_is_liste:
                        pending_stem = stem
                        if inhalt:
                            current_shard.issues.append(ParseIssue("stamm_mit_ueberschuss", txt, inhalt))
                    else:
                        lfd = self._naechste_lfd(lfd_zaehler, fach_code, programmstufe, bereich.code)
                        ident = BID.format_id(fach_code, programmstufe, bereich.code, lfd)
                        current_shard.deskriptoren.append(Deskriptor(
                            id=ident, fach=fach_code, programmstufe=programmstufe,
                            bereich_code=bereich.code, titel=pending_titel,
                            stammsatz=stem, text=inhalt, ordinal=lfd,
                        ))
                        pending_titel = pending_stem = None
                elif has_gs:
                    pending_titel = txt
                    bereich.kompetenzen_begonnen = True
                else:
                    current_shard.issues.append(ParseIssue("unerwarteter_absatz", txt))
                i += 1
                continue

            if tag == "liste":
                bereich.kompetenzen_begonnen = True
                titel, stem, item_texte = self._liste_lesen(c, pending_titel, pending_stem, current_shard)
                for item_text in item_texte:
                    lfd = self._naechste_lfd(lfd_zaehler, fach_code, programmstufe, bereich.code)
                    ident = BID.format_id(fach_code, programmstufe, bereich.code, lfd)
                    current_shard.deskriptoren.append(Deskriptor(
                        id=ident, fach=fach_code, programmstufe=programmstufe,
                        bereich_code=bereich.code, titel=titel,
                        stammsatz=stem, text=item_text, ordinal=lfd,
                    ))
                pending_titel = pending_stem = None
                i += 1
                continue

            i += 1

        self._pruefe_pflichtfelder(shards)
        self._pruefe_id_kollisionen(shards)
        return shards

    @staticmethod
    def _naechste_lfd(counter: dict[tuple[str, str, str], int], fach: str, programmstufe: str, bereich_code: str) -> int:
        key = (fach, programmstufe, bereich_code)
        counter[key] = counter.get(key, 0) + 1
        return counter[key]

    @staticmethod
    def _pruefe_pflichtfelder(shards: dict[tuple[str, str], ShardResult]) -> None:
        for shard in shards.values():
            for d in shard.deskriptoren:
                if not d.id or not d.text:
                    raise ParseError(f"{shard.shard}: descriptor missing id/text: {d!r}")

    @staticmethod
    def _pruefe_id_kollisionen(shards: dict[tuple[str, str], ShardResult]) -> None:
        alle_ids = [d.id for shard in shards.values() for d in shard.deskriptoren]
        ergebnis = BID.validate_ids(alle_ids)
        if not ergebnis.ok:
            raise ParseError(
                f"ID validation failed: {len(ergebnis.malformed)} malformed, "
                f"{len(ergebnis.duplicates)} duplicate: "
                f"{ergebnis.malformed[:5]} {ergebnis.duplicates[:5]}"
            )


def _lade_manifest_eintrag_optional() -> dict:
    """Best-effort: read ``resources/manifest.json``'s ``bildungsstandards``
    entry for citation extras (``dokument_url``, ``eli``, ``retrieval_date``)
    not present in the XML itself. ``resources/`` is gitignored, so this
    returns ``{}`` on a fresh clone -- callers must not require it."""
    try:
        with MANIFEST_PATH.open(encoding="utf-8") as fh:
            manifest = json.load(fh)
        return manifest.get("bildungsstandards", {})
    except (OSError, json.JSONDecodeError):
        return {}


# --------------------------------------------------------------------------
# Serialisation
# --------------------------------------------------------------------------


def shard_to_dict(shard: ShardResult, provenienz: dict, dataset_version: str) -> dict:
    meta: dict = {
        "dataset_version": dataset_version,
        "shard": shard.shard,
        "fach": {"code": shard.fach, "name": shard.fach_name},
        "programmstufe": shard.programmstufe,
        "programmstufe_name": shard.programmstufe_name,
        "teil": shard.teil,
        "abschnitt": shard.abschnitt,
        "provenienz": provenienz,
    }
    if shard.kompetenzmodell_hinweis:
        meta["kompetenzmodell_hinweis"] = shard.kompetenzmodell_hinweis

    kompetenzbereiche = []
    for b in shard.kompetenzbereiche:
        entry = {"code": b.code, "name": b.name, "ueberschrift_roh": b.ueberschrift_roh}
        if b.handlungsbereich is not None:
            entry["handlungsbereich"] = b.handlungsbereich
            entry["inhaltsbereich"] = b.inhaltsbereich
        if b.gruppe is not None:
            entry["gruppe"] = b.gruppe
        if b.beschreibung is not None:
            entry["beschreibung"] = b.beschreibung
        kompetenzbereiche.append(entry)

    deskriptoren = []
    for d in shard.deskriptoren:
        entry = {
            "id": d.id,
            "fach": d.fach,
            "programmstufe": d.programmstufe,
            "bereich_code": d.bereich_code,
            "stammsatz": d.stammsatz,
            "text": d.text,
            "ordinal": d.ordinal,
        }
        if d.titel:
            entry["titel"] = d.titel
        deskriptoren.append(entry)

    return {"meta": meta, "kompetenzbereiche": kompetenzbereiche, "deskriptoren": deskriptoren}


# --------------------------------------------------------------------------
# Expected counts -- measured 2026-08-04 against the live NOR40255561.xml
# --------------------------------------------------------------------------

ERWARTET: dict[str, dict[str, int]] = {
    "D4": {"kompetenzbereiche": 5, "deskriptoren": 75},
    "M4": {"kompetenzbereiche": 8, "deskriptoren": 58},
    "D8": {"kompetenzbereiche": 4, "deskriptoren": 52},
    "E8": {"kompetenzbereiche": 5, "deskriptoren": 35},
    "M8": {"kompetenzbereiche": 16, "deskriptoren": 48},
}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def load_root(source: Path) -> ET.Element:
    tree = ET.parse(source)
    return tree.getroot()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--write", action="store_true", help="write plugin/data/bildungsstandards/*.json")
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--verify", action="store_true", help="non-zero exit on a count regression")
    ap.add_argument("--dataset-version", default=None)
    args = ap.parse_args(argv)

    if not args.source.exists():
        print(f"error: source not found: {args.source}", file=sys.stderr)
        return 2

    root = load_root(args.source)
    parser = BildungsstandardsParser(root)
    shards = parser.parse()
    provenienz = parser.provenienz()
    dataset_version = args.dataset_version or provenienz.get("stand") or provenienz.get("zuletzt_aktualisiert", "")

    ok = True
    for key in sorted(shards, key=lambda k: BID.shard_name(*k)):
        shard = shards[key]
        n_bereiche = len(shard.kompetenzbereiche)
        n_desk = len(shard.deskriptoren)
        n_issues = len(shard.issues)
        if args.summary or args.verify:
            print(f"{shard.shard}: {n_bereiche} Kompetenzbereiche, {n_desk} Deskriptoren, {n_issues} issues")
        if args.verify:
            erwartet = ERWARTET.get(shard.shard)
            if erwartet is None:
                print(f"  ! no expected-count entry for {shard.shard}")
                ok = False
            else:
                if n_bereiche != erwartet["kompetenzbereiche"]:
                    print(f"  ! kompetenzbereiche drift: expected {erwartet['kompetenzbereiche']}, got {n_bereiche}")
                    ok = False
                if n_desk != erwartet["deskriptoren"]:
                    print(f"  ! deskriptoren drift: expected {erwartet['deskriptoren']}, got {n_desk}")
                    ok = False
        if args.write:
            args.out_dir.mkdir(parents=True, exist_ok=True)
            out_path = args.out_dir / f"{shard.shard.lower()}.json"
            data = shard_to_dict(shard, provenienz, dataset_version)
            with out_path.open("w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=False)
                fh.write("\n")
            if args.summary:
                print(f"  wrote {out_path} ({out_path.stat().st_size} bytes)")

    missing = set(ERWARTET) - {BID.shard_name(*k) for k in shards}
    if missing:
        print(f"  ! missing shards: {sorted(missing)}")
        ok = False

    if args.verify:
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
