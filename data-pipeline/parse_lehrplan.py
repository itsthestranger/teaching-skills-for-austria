#!/usr/bin/env python3
"""Parser for Austrian RIS curriculum XML (Lehrplan, BGBl. II).

Scope of this module *today*: **Sekundarstufe I / MATHEMATIK** from the
Mittelschule annex (NOR40271471).  The other five subject x band shards are a
deliberate later task -- see ``notes/ris-xml-structure.md``.  The code is
organised so that breadth is added by writing a new :class:`SubjectSpec`, not
by forking the state machine.

Design notes
------------
* stdlib only (``xml.etree.ElementTree``).
* The source XML is *flat presentation markup*: one ``<abschnitt>`` whose
  ~2400 direct children carry hierarchy only through attributes.  The parser is
  therefore a sequential state machine over that child list.
* **Verbatim text is sacred.**  Text is captured by joining ``itertext()``
  fragments; the only interventions are documented in :func:`element_text`
  (list bullets, inline images, superscript footnote markers) and each of them
  is recorded losslessly alongside the clean text.
* **Tolerant by default.**  Unknown enum values, unexpected headings and
  structural surprises are logged as :class:`ParseIssue` and carried.  The only
  hard failures are a missing required field (``id``, ``stufe``, ``text``) and
  an ID collision -- see :exc:`ParseError`.

Usage
-----
    python3 parse_lehrplan.py --source resources/mittelschule/NOR40271471.xml
    python3 parse_lehrplan.py --source ... --verify   # assert expected counts
"""

from __future__ import annotations

import argparse
import dataclasses
import difflib
import json
import logging
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterator, Sequence

import abbildungen as ABB

# --------------------------------------------------------------------------
# XML primitives
# --------------------------------------------------------------------------

NS = "{http://www.bka.gv.at}"

#: Token substituted for an inline ``<binary>`` image (formulae are shipped
#: as PNG in the RIS XML and have no textual representation at all).
#:
#: U+27E6 / U+27E7 MATHEMATICAL WHITE SQUARE BRACKET -- chosen because this
#: pair cannot occur in the source text, so it is unambiguous to find and
#: match downstream. This *is* the faithful serialisation: the source
#: sentence genuinely contains an image at this point, and the token marks
#: exactly where. See the ``abbildungen`` field on Kompetenz/Anwendungsitem
#: for the accompanying image metadata (dimensions, sha256, shipped path).
ABBILDUNG_TOKEN_RE = re.compile(r"⟦ABB:(?P<dateiname>[^⟧]+)⟧")


def abbildung_token(dateiname: str) -> str:
    """Build the ⟦ABB:<dateiname>⟧ token for one inline image."""
    return f"⟦ABB:{dateiname}⟧"


LOG = logging.getLogger("parse_lehrplan")


def localname(el: ET.Element) -> str:
    """Return the namespace-stripped tag of *el*."""
    return el.tag.replace(NS, "", 1) if isinstance(el.tag, str) else ""


def find_abschnitt(root: ET.Element) -> ET.Element:
    """Return the single content ``<abschnitt>`` under ``<nutzdaten>``."""
    nutzdaten = root.find(NS + "nutzdaten")
    if nutzdaten is None:
        raise ParseError("no <nutzdaten> element -- not a RIS document")
    abschnitte = [c for c in nutzdaten if localname(c) == "abschnitt"]
    if not abschnitte:
        raise ParseError("<nutzdaten> contains no <abschnitt>")
    return abschnitte[0]


@dataclass
class ExtractedText:
    """Result of :func:`element_text` -- clean text plus everything removed."""

    text: str
    """Quotable sentence: bullets dropped, images replaced by an ⟦ABB:...⟧
    token, superscripts removed. Faithful: an image genuinely sits there."""

    roh: str
    """Same traversal but with superscript digits inlined; nothing is lost."""

    super_marker: tuple[str, ...] = ()
    """Raw contents of each ``<super>`` (a single one may read ``"6, 7"``)."""

    abbildungen: tuple[str, ...] = ()
    """``<binary>/<src>`` paths, in document order (one per ⟦ABB:...⟧ token
    in ``text``, same order)."""

    @property
    def hat_abbildung(self) -> bool:
        return bool(self.abbildungen)


def element_text(el: ET.Element) -> ExtractedText:
    """Extract text from *el* verbatim, with three documented interventions.

    1. ``<symbol>`` -- the list bullet glyph ("--").  Presentation, not text.
    2. ``<binary>`` -- an inline PNG (fraction/formula graphic).  ``itertext()``
       would otherwise splice the *file path* from ``<src>`` into the sentence.
       Replaced by the token :func:`abbildung_token` builds (e.g.
       ``⟦ABB:hauptdokument.img1is.png⟧``); the paths are kept in
       ``abbildungen`` and the shipped image plus its metadata are attached
       to the owning Kompetenz/Anwendungsitem record -- see
       :func:`_abbildung_eintraege`.
    3. ``<super>`` -- superscript footnote markers referencing the 13 cross
       cutting themes.  Removed from ``text`` (a raised "4" is not part of the
       sentence) and preserved verbatim in ``super_marker`` and ``roh``.

    Nothing else is touched: no reflowing, no whitespace collapsing, no
    gender-reforming.  Fragments are joined and the result is stripped at the
    ends only.
    """
    clean: list[str] = []
    roh: list[str] = []
    supers: list[str] = []
    bilder: list[str] = []

    def emit(chunk: str | None) -> None:
        if chunk:
            clean.append(chunk)
            roh.append(chunk)

    def walk(node: ET.Element, *, is_root: bool) -> None:
        name = localname(node)
        if not is_root:
            if name == "symbol":
                emit(node.tail)
                return
            if name == "binary":
                src = node.find(NS + "src")
                pfad = (src.text or "").strip() if src is not None else ""
                bilder.append(pfad)
                dateiname = pfad.rsplit("/", 1)[-1] if pfad else ""
                token = abbildung_token(dateiname)
                clean.append(token)
                roh.append(token)
                emit(node.tail)
                return
            if name == "super":
                raw = "".join(node.itertext())
                supers.append(raw)
                roh.append(raw)
                emit(node.tail)
                return
        emit(node.text)
        for child in node:
            walk(child, is_root=False)
        if not is_root:
            emit(node.tail)

    walk(el, is_root=True)
    return ExtractedText(
        text="".join(clean).strip(),
        roh="".join(roh).strip(),
        super_marker=tuple(supers),
        abbildungen=tuple(bilder),
    )


def plain_text(el: ET.Element) -> str:
    """Convenience wrapper returning only the clean text."""
    return element_text(el).text


# --------------------------------------------------------------------------
# Errors and the issue log
# --------------------------------------------------------------------------


class ParseError(Exception):
    """Hard failure: missing required field, ID collision, unusable document."""


@dataclass(frozen=True)
class ParseIssue:
    """A tolerated deviation.  Logged and carried, never fatal."""

    art: str
    """Machine-readable kind, e.g. ``unbekannte_ueberschrift``."""

    nachricht: str
    index: int | None = None
    kontext: str = ""

    def __str__(self) -> str:  # pragma: no cover - formatting only
        pos = f"[{self.index}]" if self.index is not None else "[-]"
        extra = f" | {self.kontext}" if self.kontext else ""
        return f"{pos} {self.art}: {self.nachricht}{extra}"


class IssueLog:
    """Collects :class:`ParseIssue` objects and mirrors them to ``logging``."""

    def __init__(self) -> None:
        self._issues: list[ParseIssue] = []

    def add(self, art: str, nachricht: str, index: int | None = None, kontext: str = "") -> None:
        issue = ParseIssue(art=art, nachricht=nachricht, index=index, kontext=kontext)
        self._issues.append(issue)
        LOG.warning("%s", issue)

    def __iter__(self) -> Iterator[ParseIssue]:
        return iter(self._issues)

    def __len__(self) -> int:
        return len(self._issues)

    def by_art(self, art: str) -> list[ParseIssue]:
        return [i for i in self._issues if i.art == art]

    def as_dicts(self) -> list[dict]:
        return [dataclasses.asdict(i) for i in self._issues]


# --------------------------------------------------------------------------
# Normalisation (for the competence <-> application-area join)
# --------------------------------------------------------------------------

#: The official parsing anchor.  Kept exactly as published (plan section 6.8);
#: only the *matching* form is normalised, never the stored text.
STEM_RE = re.compile(
    r"^\s*Die\s+Sch(?:ü|ue)lerinnen\s+und\s+Sch(?:ü|ue)ler\s+k(?:ö|oe)nnen\b\s*:?\s*",
    re.IGNORECASE,
)

_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−"), "-")
_QUOTES = dict.fromkeys(map(ord, "„“”‚‘’«»"), '"')
_SPACES = dict.fromkeys(map(ord, "      "), " ")


def strip_stem(s: str) -> str:
    """Remove the ``Die Schülerinnen und Schüler können`` stem if present."""
    return STEM_RE.sub("", s)


def normalise_for_match(s: str) -> str:
    """Aggressive normalisation used **only** for join comparison.

    Never applied to stored text.  Folds unicode dashes/quotes/spaces, drops
    the stem, collapses whitespace, drops trailing punctuation, casefolds.
    """
    s = unicodedata.normalize("NFC", s)
    s = s.translate(_DASHES).translate(_QUOTES).translate(_SPACES)
    s = re.sub(r"\s+", " ", s).strip()
    s = strip_stem(s)
    s = s.rstrip(" .;:,")
    return s.casefold()


# --------------------------------------------------------------------------
# Subject specification -- the extension point for further subjects
# --------------------------------------------------------------------------

#: ``Kompetenzbereich 1: Zahlen und Maße`` -- the numbered Sek I form.
AREA_NUMMERIERT_RE = re.compile(r"^Kompetenzbereich\s+(\d+)\s*:\s*(?P<name>.+?)\s*$")

#: Class year / school year marker, e.g. ``1. Klasse:`` or ``2. Schulstufe:``.
STUFE_RE = re.compile(r"^(?P<nr>\d+)\.\s*(?P<einheit>Klasse|Schulstufe)\s*:?\s*$")

#: A ``Wiederholen und Festigen:`` application item (Sek I only, years 2-4).
WIEDERHOLUNG_RE = re.compile(r"^\s*Wiederholen\s+und\s+Festigen\s*:")

#: The non-binding marker, with the official legend quoted in the notes file.
ALLENFALLS_RE = re.compile(r"\ballenfalls\b", re.IGNORECASE)

#: ``Vorschläge für den Einsatz digitaler Technologien4 in der 1. Klasse``.
DIGITALE_TECHNOLOGIEN_RE = re.compile(r"^Vorschl(?:ä|ae)ge f(?:ü|ue)r den Einsatz digitaler Technologien")

#: The inline ``Anwendungsbereiche`` sub-heading used by every subject except
#: SEK1.M (which has a separate top-level ``Anwendungsbereiche (…):`` section
#: instead -- matched by ``SubjectSpec.anwendung_sektion_re``). This one is
#: the bare word, no parenthetical, marking the start of an AB-BLOCK inside
#: the combined competence/application section -- see
#: notes/deviations.md, 2026-07-29.
AB_BLOCK_RE = re.compile(r"^Anwendungsbereiche\s*:?\s*$")

#: ``LEHRPLANZUSATZ DEUTSCH ALS ZWEITSPRACHE …`` -- an embedded second
#: curriculum that follows some subjects' main one on the same ``erll``
#: element type as an ordinary in-subject heading (so it does not open a new
#: ``g1`` subject span). Belt-and-braces subject terminator alongside the
#: legend-table terminator (both derived from notes/deviations.md,
#: 2026-07-29) -- prevents duplicate-area ID collisions (e.g. SEK1.D's
#: ``Lesen``/``Schreiben`` recurring inside the DaZ Lehrplanzusatz).
LEHRPLANZUSATZ_RE = re.compile(r"^LEHRPLANZUSATZ\b")

#: ``Dieser Lehrplan greift folgende übergreifende Themen auf: …``
THEMEN_SATZ_RE = re.compile(r"^Dieser Lehrplan greift folgende (?:ü|ue)bergreifende Themen auf\s*:\s*(?P<liste>.+)$")

#: A cell of the per-subject footnote legend table: ``4Informatische Bildung``.
THEMA_ZELLE_RE = re.compile(r"^(?P<nr>\d{1,2})\s*(?P<name>\D.+)$")

#: ``ACHTER TEIL`` and friends -- a g1 heading that opens a part, not a subject.
TEIL_RE = re.compile(
    r"^(?:ERSTER|ZWEITER|DRITTER|VIERTER|F(?:Ü|UE)NFTER|SECHSTER|SIEBENTER"
    r"|ACHTER|NEUNTER|ZEHNTER|ELFTER|ZW(?:Ö|OE)LFTER)\s+TEIL$"
)

#: ``Kompetenzen für den Mathematik-Lehrplan bei integrativer Führung von
#: Geometrisches Zeichnen (1. bis 4. Klasse):`` -- a short appendix to Sek I
#: Mathematik, structurally outside the four numbered Kompetenzbereiche.
#:
#: Decision taken (see FINDINGS.md V-57 and notes/deviations.md): the two
#: competences under this heading (one for K3, one for K4) are promoted into
#: the main dataset rather than left in ``zusatzbloecke``. They fit none of
#: the four official Kompetenzbereiche, so they are given a synthetic,
#: clearly-labelled area (:data:`GZ_INTEGRATIV_BEREICH_NAME` /
#: :data:`GZ_INTEGRATIV_BEREICH_SLUG`, ``bereich_nummer=None``) rather than
#: being folded into one of the four -- and that synthetic area is *not*
#: added to :attr:`ParseResult.bereiche`, so the "4 Kompetenzbereiche" count
#: stays faithful to the regulation's actual structure.
GZ_INTEGRATIV_RE = re.compile(
    r"^Kompetenzen f(?:ü|ue)r den Mathematik-Lehrplan bei integrativer "
    r"F(?:ü|ue)hrung von Geometrisches Zeichnen\b"
)
GZ_INTEGRATIV_BEREICH_NAME = "Integrative Führung von Geometrisches Zeichnen"
GZ_INTEGRATIV_BEREICH_SLUG = "GZINTEGRATIV"


@dataclass(frozen=True)
class SubjectSpec:
    """Everything subject- and band-specific in one declarative object.

    Adding a subject means adding one of these (plus, where the source really
    differs, a new heading regex) -- not a second state machine.
    """

    band: str
    """``SEK1`` | ``PRIM``."""

    fach_code: str
    """``M``, ``D``, ``E``, ``SU``, ..."""

    fach_ueberschrift: str
    """The exact ``ueberschrift/@typ="g1"`` that opens the subject.

    Matched case-sensitively and in full.  Sek I subject headings are ALL CAPS;
    several primary ones are not (``Deutsch``, ``Musik``, ``Rhythmik``)."""

    stufen_praefix: str
    """``K`` for Sek I class years, ``SCH`` for primary school years."""

    kompetenz_sektion_re: re.Pattern[str]
    """Heading opening the competence-description section."""

    anwendung_sektion_re: re.Pattern[str] | None
    """Heading opening the application-area section, or ``None`` if the subject
    has no separate one (primary mathematics: ``anwendungsbereiche_status`` is
    then ``keine``)."""

    teil_ueberschrift: str | None = None
    """TEIL that must be open for the subject heading to count.

    The primary document repeats subject names across TEILs -- ``BEWEGUNG UND
    SPORT`` appears in the Vorschulstufe TEIL, in the Grundschule TEIL and
    among the Freigegenstände.  Without this guard the first occurrence wins,
    which is the wrong one.  ``None`` disables the check."""

    bereich_re: re.Pattern[str] = AREA_NUMMERIERT_RE
    """Competence-area heading.  Sek I is ``Kompetenzbereich <n>: <Name>``;
    primary Sachunterricht is adjective-first (``Sozialwissenschaftlicher
    Kompetenzbereich``) and will need its own pattern."""

    bereich_slugs: dict[str, str] = field(default_factory=dict)
    """Area name -> ID segment.  Missing entries fall back to
    :func:`slugify_bereich`, which is deterministic but less readable."""

    anwendungsbereiche_status: str = "item_flags"
    """``item_flags`` | ``optional_sektion`` | ``keine`` (plan section 4.4)."""

    lehrstoff_quelle: str = "aus_anwendungsbereichen"
    """``aus_anwendungsbereichen`` | ``eigen_ausgewiesen`` (plan section 4.5)."""

    anwendungsbereiche_bindung: str = "kompetenz"
    """How application-area items attach to the rest of the structure.

    ``kompetenz`` -- verbatim text-repetition join to one competence (SEK1.M
    only -- see :data:`AREA_NUMMERIERT_RE`/:func:`join_anwendungen`; V-27).
    ``bereich`` -- the ``Anwendungsbereiche`` block follows an area's
    competence list and attaches to ``(bereich, stufe)`` (SEK1.D).
    ``stufe`` -- the block follows the *last* area of a school year and
    attaches to ``(stufe)`` only, never to an area (PRIM.D, PRIM.SU).
    ``prosa`` -- the ``Anwendungsbereiche`` heading is followed by descriptive
    prose, not a ``liste``; no items exist to capture (SEK1.E).
    ``keine`` -- the subject has no Anwendungsbereiche at all (PRIM.M).

    Measured 2026-07-29 (see notes/deviations.md): there is no text-repetition
    join outside SEK1.M -- everywhere else attachment is by XML containment.
    For ``bereich``/``stufe`` a per-competence ``kompetenz_id`` must **not**
    be synthesised; the source does not make that link."""

    bereich_aus_absatz: bool = False
    """Whether an ``absatz/@typ="abs"`` may ever be classified as an area
    heading (the SEK1.M element-type trap -- see notes/ris-xml-structure.md
    §3). ``False`` by construction makes the 11 known prose false positives
    in the other five subjects (e.g. "In allen vier Kompetenzbereichen wird
    das Zielniveau A1/A2 angestrebt") impossible rather than merely
    suppressed by a state guard. ``True`` only for SEK1.M."""

    allenfalls_pruefen: bool = False
    """Whether application items are scanned for the ``allenfalls`` marker to
    set ``verbindlich``. ``allenfalls`` occurs zero times in the competence
    sections of the five subjects other than SEK1.M -- do not scan for it
    there (it would report a meaningless 0/N split) and leave ``verbindlich``
    ``True`` unconditionally. ``True`` only for SEK1.M."""


SEK1_MATHEMATIK = SubjectSpec(
    band="SEK1",
    fach_code="M",
    fach_ueberschrift="MATHEMATIK",
    teil_ueberschrift="ACHTER TEIL",
    stufen_praefix="K",
    kompetenz_sektion_re=re.compile(r"^Kompetenzbereiche\s*\("),
    anwendung_sektion_re=re.compile(r"^Anwendungsbereiche\s*\("),
    bereich_re=AREA_NUMMERIERT_RE,
    bereich_slugs={
        "Zahlen und Maße": "ZAHLEN",
        "Variablen und Funktionen": "VARIABLEN",
        "Figuren und Körper": "FIGUREN",
        "Daten und Zufall": "DATEN",
    },
    anwendungsbereiche_status="item_flags",
    lehrstoff_quelle="aus_anwendungsbereichen",
    anwendungsbereiche_bindung="kompetenz",
    bereich_aus_absatz=True,
    allenfalls_pruefen=True,
)

#: Registry keyed ``<BAND>.<FACH>``.  Five more entries belong here later.
SUBJECT_SPECS: dict[str, SubjectSpec] = {
    "SEK1.M": SEK1_MATHEMATIK,
}


def slugify_bereich(name: str) -> str:
    """Deterministic fallback ID segment for an unmapped competence area."""
    folded = (
        unicodedata.normalize("NFKD", name)
        .replace("ß", "ss")
        .encode("ascii", "ignore")
        .decode("ascii")
        .upper()
    )
    return re.sub(r"[^A-Z0-9]+", "", folded)[:12] or "BEREICH"


# --------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------


@dataclass
class Kompetenzbereich:
    nummer: int | None
    name: str
    slug: str
    quell_index: int


@dataclass
class Kompetenz:
    id: str
    band: str
    fach: str
    bereich_nummer: int | None
    bereich_name: str
    stufe: str
    ordinal: int
    text: str
    text_roh: str
    uebergreifende_themen: list[str] = field(default_factory=list)
    themen_marker_roh: list[str] = field(default_factory=list)
    fussnoten_unaufgeloest: list[str] = field(default_factory=list)
    abbildungen: list[dict] = field(default_factory=list)
    """One entry per ⟦ABB:...⟧ token in ``text``, in order -- see the ABB
    interface contract in notes/ris-xml-structure.md (token, datei, nor,
    pfad, quelle_url, breite_px, hoehe_px, sha256)."""

    quell_index: int = -1
    vorlaeufer: list[str] = field(default_factory=list)
    folge: list[str] = field(default_factory=list)


@dataclass
class Anwendungsitem:
    id: str
    band: str
    fach: str
    bereich_nummer: int | None
    bereich_name: str
    stufe: str
    ordinal: int
    text: str
    text_roh: str
    verbindlich: bool
    art: str
    """``praezisierung`` (attached to a competence) |
    ``digitale_technologien`` (the per-year suggestion list, attached to the
    class year only).  Both are ``listelem`` children of the Anwendungsbereiche
    section and both are counted in the section total."""

    kompetenz_id: str | None = None
    join_methode: str | None = None
    """``exact`` | ``fuzzy`` | ``positional`` | ``None`` (no competence)."""

    join_score: float | None = None
    ist_wiederholung: bool = False
    wiederholung_von: list[str] = field(default_factory=list)
    abbildungen: list[dict] = field(default_factory=list)
    """See :attr:`Kompetenz.abbildungen`."""

    quell_index: int = -1


@dataclass
class Anwendungsblock:
    """A group of application items and how they attach to the rest.

    Two shapes, keyed by ``SubjectSpec.anwendungsbereiche_bindung``:

    * ``kompetenz`` (SEK1.M) -- ``satz`` is the repeated competence sentence
      the block is matched against (V-27); ``kompetenz_id``/``join_methode``/
      ``join_score`` are filled in by :func:`join_anwendungen`.
    * ``bereich``/``stufe`` -- attachment is by containment, not by a
      repeated sentence: ``satz`` is empty and ``kompetenz_id``/
      ``join_methode``/``join_score`` stay at their ``None`` default, never
      computed. For ``stufe`` blocks, ``bereich_nummer``/``bereich_name`` are
      likewise left empty/``None`` -- the block attaches to the school year
      only, not to whichever area happened to precede it (see
      notes/ris-xml-structure.md §11)."""

    stufe: str
    bereich_nummer: int | None
    bereich_name: str
    ordinal: int
    satz: str
    quell_index: int
    items: list[Anwendungsitem] = field(default_factory=list)
    kompetenz_id: str | None = None
    join_methode: str | None = None
    join_score: float | None = None


@dataclass
class ParseResult:
    spec: SubjectSpec
    fach_name: str
    bereiche: list[Kompetenzbereich]
    kompetenzen: list[Kompetenz]
    anwendungsitems: list[Anwendungsitem]
    bloecke: list[Anwendungsblock]
    themen_map: dict[str, str]
    uebergreifende_themen_fach: list[str]
    issues: IssueLog
    join_stats: dict[str, float | int] = field(default_factory=dict)
    zusatzbloecke: list[dict] = field(default_factory=list)
    """Content found inside the subject but outside the two known sections --
    e.g. Sek I maths' 'integrative Führung von Geometrisches Zeichnen'.  Kept so
    nothing is silently dropped; not counted among the core competences."""


# --------------------------------------------------------------------------
# State machine
# --------------------------------------------------------------------------


class State(Enum):
    """Explicit states.  Every transition is made in :meth:`_step`."""

    VOR_FACH = "vor_fach"
    """Scanning the document for the subject's g1 heading."""

    FACH_PRAEAMBEL = "fach_praeambel"
    """Inside the subject, before the competence section (Bildungs- und
    Lehraufgabe, Kompetenzmodell, Didaktische Grundsätze, ...)."""

    KOMPETENZBEREICHE = "kompetenzbereiche"
    """Inside ``Kompetenzbereiche (1. bis 4. Klasse):``.  Areas arrive as
    ``ueberschrift/@typ="erll"``."""

    ANWENDUNGSBEREICHE = "anwendungsbereiche"
    """Inside ``Anwendungsbereiche (1. bis 4. Klasse):``.  The *same* area
    headings arrive as ``absatz/@typ="abs"`` -- see the element-type trap in
    the notes."""

    KOMPETENZ_GZ_INTEGRATIV = "kompetenz_gz_integrativ"
    """Inside the ``... bei integrativer Führung von Geometrisches
    Zeichnen ...`` appendix (promoted into the main dataset -- see
    :data:`GZ_INTEGRATIV_RE`). Shape mirrors KOMPETENZBEREICHE (class-year
    marker, bare stem, list) but for one fixed synthetic area."""

    FACH_ANHANG = "fach_anhang"
    """Inside the subject, after both sections closed."""

    NACH_FACH = "nach_fach"
    """The next subject's g1 heading was seen; parsing is done."""


class Token(Enum):
    """Classification of one flat child element."""

    FACH_UEBERSCHRIFT = "fach_ueberschrift"
    LEHRPLANZUSATZ = "lehrplanzusatz"
    SEKTION_KOMPETENZ = "sektion_kompetenz"
    SEKTION_ANWENDUNG = "sektion_anwendung"
    SEKTION_GZ_INTEGRATIV = "sektion_gz_integrativ"
    AB_BLOCK = "ab_block"
    """The inline ``Anwendungsbereiche`` sub-heading (bindung ``bereich`` |
    ``stufe`` | ``prosa``) -- see :data:`AB_BLOCK_RE`."""

    BEREICH = "bereich"
    STUFE = "stufe"
    STAMMSATZ = "stammsatz"
    """Bare ``Die Schülerinnen und Schüler können`` -- introduces a list."""

    KOMPETENZSATZ = "kompetenzsatz"
    """Stem *plus* the competence text inline (Anwendungsbereiche form)."""

    DIGITALE_TECHNOLOGIEN = "digitale_technologien"
    LISTE = "liste"
    ANDERE_UEBERSCHRIFT = "andere_ueberschrift"
    TABELLE = "tabelle"
    TEXT = "text"
    IGNORIEREN = "ignorieren"


@dataclass
class Ereignis:
    token: Token
    index: int
    element: ET.Element
    extracted: ExtractedText
    daten: dict = field(default_factory=dict)


class LehrplanParser:
    """Sequential state machine over the flat ``<abschnitt>`` child list."""

    def __init__(
        self,
        spec: SubjectSpec,
        issues: IssueLog | None = None,
        abbildungen_registry: dict[tuple[str, str], ABB.AbbildungRecord] | None = None,
    ) -> None:
        self.spec = spec
        self.issues = issues if issues is not None else IssueLog()
        #: (nor, dateiname) -> AbbildungRecord for every image shipped under
        #: plugin/data/abbildungen/. Injectable (tests use a synthetic one);
        #: defaults to scanning the real shipped directory.
        self._abbildungen = (
            abbildungen_registry if abbildungen_registry is not None else ABB.build_registry()
        )

    # -- public ----------------------------------------------------------

    def parse_file(self, path: str | Path) -> ParseResult:
        root = ET.parse(str(path)).getroot()
        return self.parse_root(root)

    def parse_root(self, root: ET.Element) -> ParseResult:
        kinder = list(find_abschnitt(root))
        return self.parse_children(kinder)

    def parse_children(self, kinder: Sequence[ET.Element]) -> ParseResult:
        self._reset()
        for index, el in enumerate(kinder):
            ereignis = self._classify(index, el)
            self._step(ereignis)
            if self.state is State.NACH_FACH:
                break
        if not self._fach_gesehen:
            raise ParseError(
                f"subject heading {self.spec.fach_ueberschrift!r} not found in document"
            )
        return self._finish()

    # -- setup -----------------------------------------------------------

    def _reset(self) -> None:
        self.state = State.VOR_FACH
        self._fach_gesehen = False
        self._teil: str | None = None
        self.stufe: str | None = None
        self.bereich: Kompetenzbereich | None = None
        self.bereiche: dict[str, Kompetenzbereich] = {}
        self.kompetenzen: list[Kompetenz] = []
        self.bloecke: list[Anwendungsblock] = []
        self.anwendungsitems: list[Anwendungsitem] = []
        self._offener_block: Anwendungsblock | None = None
        self._digital_offen = False
        self._offener_ab_block: Anwendungsblock | None = None
        """Containment-attachment AB-BLOCK currently open (bindung 'bereich'
        or 'stufe') -- see :meth:`_oeffne_ab_block`. Distinct from
        ``_offener_block``, which is SEK1.M's text-join-based mechanism; the
        two are never active for the same spec."""

        self._ab_block_prosa_offen = False
        """A bindung='prosa' AB-BLOCK is open (SEK1.E): the heading was seen
        and logged, but it captures no items by design -- see
        :meth:`_oeffne_ab_block`."""

        self._block_ordinal = 0
        self._komp_ordinal = 0
        self._ids: dict[str, int] = {}
        self._themen_map: dict[str, str] = {}
        self._themen_fach: list[str] = []
        self._zusatz: list[dict] = []
        self._zusatz_stufe: str | None = None
        self._zusatz_titel: str | None = None

    # -- classification --------------------------------------------------

    def _classify(self, index: int, el: ET.Element) -> Ereignis:
        name = localname(el)
        typ = el.get("typ")
        ex = element_text(el)
        text = ex.text

        if name == "ueberschrift":
            if typ in ("g1", "g1min"):
                return Ereignis(Token.FACH_UEBERSCHRIFT, index, el, ex)
            if typ == "erll":
                if LEHRPLANZUSATZ_RE.match(text):
                    return Ereignis(Token.LEHRPLANZUSATZ, index, el, ex)
                # The level marker is `absatz/@typ="erltext"` in the Sek I
                # document but `ueberschrift/@typ="erll"` in the primary one
                # (35 of 40 occurrences).  Accept both element types.
                m = STUFE_RE.match(text)
                if m:
                    return Ereignis(Token.STUFE, index, el, ex,
                                    {"nr": int(m.group("nr")), "einheit": m.group("einheit")})
                if self.spec.kompetenz_sektion_re.search(text):
                    return Ereignis(Token.SEKTION_KOMPETENZ, index, el, ex)
                if self.spec.anwendung_sektion_re and self.spec.anwendung_sektion_re.search(text):
                    return Ereignis(Token.SEKTION_ANWENDUNG, index, el, ex)
                if GZ_INTEGRATIV_RE.match(text):
                    return Ereignis(Token.SEKTION_GZ_INTEGRATIV, index, el, ex)
                m = self.spec.bereich_re.match(text)
                if m:
                    return Ereignis(Token.BEREICH, index, el, ex, self._bereich_daten(m, text))
                return Ereignis(Token.ANDERE_UEBERSCHRIFT, index, el, ex)
            return Ereignis(Token.IGNORIEREN, index, el, ex)

        if name == "absatz":
            if typ == "erltext":
                m = STUFE_RE.match(text)
                if m:
                    return Ereignis(Token.STUFE, index, el, ex, {"nr": int(m.group("nr")),
                                                                 "einheit": m.group("einheit")})
                return Ereignis(Token.TEXT, index, el, ex)
            if typ == "abs":
                # The inline "Anwendungsbereiche" sub-heading (bindung
                # bereich/stufe/prosa) -- only meaningful while inside the
                # combined competence section; gated by state exactly like
                # the element-type trap below, for the same reason.
                if self.state is State.KOMPETENZBEREICHE and AB_BLOCK_RE.match(text):
                    return Ereignis(Token.AB_BLOCK, index, el, ex)
                # THE TRAP: in the Anwendungsbereiche section the area heading
                # is an ordinary body paragraph, not an <ueberschrift>. Opt-in
                # per SubjectSpec (bereich_aus_absatz) -- True only for
                # SEK1.M, which is the only subject where this form occurs;
                # False elsewhere makes the 11 known prose false positives
                # (e.g. "In allen vier Kompetenzbereichen wird das
                # Zielniveau A1/A2 angestrebt") impossible by construction.
                m = self.spec.bereich_re.match(text)
                if self.spec.bereich_aus_absatz and m and self.state is State.ANWENDUNGSBEREICHE:
                    return Ereignis(Token.BEREICH, index, el, ex, self._bereich_daten(m, text))
                if DIGITALE_TECHNOLOGIEN_RE.match(text):
                    return Ereignis(Token.DIGITALE_TECHNOLOGIEN, index, el, ex)
                rest = strip_stem(text)
                if rest != text:
                    if rest.strip(" .:;"):
                        return Ereignis(Token.KOMPETENZSATZ, index, el, ex, {"rest": rest})
                    return Ereignis(Token.STAMMSATZ, index, el, ex)
                return Ereignis(Token.TEXT, index, el, ex)
            return Ereignis(Token.TEXT, index, el, ex)

        if name == "liste":
            return Ereignis(Token.LISTE, index, el, ex)
        if name == "table":
            return Ereignis(Token.TABELLE, index, el, ex)
        return Ereignis(Token.IGNORIEREN, index, el, ex)

    def _bereich_daten(self, m: re.Match[str], text: str) -> dict:
        try:
            nummer: int | None = int(m.group(1))
        except (IndexError, ValueError):
            nummer = None
        name = (m.groupdict().get("name") or text).strip()
        return {"nummer": nummer, "name": name}

    # -- transitions -----------------------------------------------------

    def _step(self, ev: Ereignis) -> None:
        state = self.state

        if state is State.VOR_FACH:
            if ev.token is not Token.FACH_UEBERSCHRIFT:
                return
            titel = ev.extracted.text.strip()
            if TEIL_RE.match(titel):
                self._teil = titel
                return
            if titel != self.spec.fach_ueberschrift:
                return
            if self.spec.teil_ueberschrift and self._teil != self.spec.teil_ueberschrift:
                self.issues.add(
                    "fachueberschrift_im_falschen_teil",
                    f"{titel!r} found under {self._teil!r}, expected "
                    f"{self.spec.teil_ueberschrift!r}; skipping this occurrence",
                    ev.index,
                )
                return
            self._fach_gesehen = True
            self.state = State.FACH_PRAEAMBEL
            return

        # Any further g1 heading ends the subject, whatever state we are in.
        if ev.token is Token.FACH_UEBERSCHRIFT:
            self._close_block()
            self._schliesse_ab_block()
            if self.state in (State.KOMPETENZBEREICHE, State.ANWENDUNGSBEREICHE):
                self.issues.add(
                    "sektion_nicht_geschlossen",
                    f"subject ended while still in {self.state.value}",
                    ev.index,
                    ev.extracted.text[:80],
                )
            self.state = State.NACH_FACH
            return

        # A LEHRPLANZUSATZ heading also ends the subject -- belt-and-braces
        # second terminator alongside the legend table below (see
        # LEHRPLANZUSATZ_RE). In the live document the legend table normally
        # fires first and this branch never triggers, but it must not depend
        # on that ordering.
        if ev.token is Token.LEHRPLANZUSATZ:
            self._close_block()
            self._schliesse_ab_block()
            if self.state in (State.KOMPETENZBEREICHE, State.ANWENDUNGSBEREICHE):
                self.issues.add(
                    "sektion_nicht_geschlossen",
                    f"subject ended (LEHRPLANZUSATZ) while still in {self.state.value}",
                    ev.index,
                    ev.extracted.text[:80],
                )
            self.state = State.NACH_FACH
            return

        # The per-subject footnote legend table is the general subject
        # terminator (notes/deviations.md, 2026-07-29): every one of the six
        # target subjects ends its main curriculum with exactly one 18-cell
        # legend table, immediately before the next subject or insert. Parse
        # it for the theme map, then leave the subject -- this bounds e.g.
        # SEK1.D at child 514 without a hardcoded index, structurally
        # preventing the LEHRPLANZUSATZ duplicate-area ID collision.
        if ev.token is Token.TABELLE and state in (
            State.KOMPETENZBEREICHE,
            State.ANWENDUNGSBEREICHE,
            State.KOMPETENZ_GZ_INTEGRATIV,
        ):
            self._themen_map.update(self._parse_themen_tabelle(ev.element))
            self._close_block()
            self._schliesse_ab_block()
            self.state = State.NACH_FACH
            return

        if ev.token is Token.SEKTION_KOMPETENZ:
            self._close_block()
            self.state = State.KOMPETENZBEREICHE
            self.stufe = None
            self.bereich = None
            return

        if ev.token is Token.SEKTION_ANWENDUNG:
            self._close_block()
            self.state = State.ANWENDUNGSBEREICHE
            self.stufe = None
            self.bereich = None
            self._block_ordinal = 0
            return

        if ev.token is Token.SEKTION_GZ_INTEGRATIV:
            self._close_block()
            self.state = State.KOMPETENZ_GZ_INTEGRATIV
            self.stufe = None
            # Fixed, synthetic area for the life of this appendix -- not
            # registered in self.bereiche (see GZ_INTEGRATIV_RE docstring),
            # so it never appears as a 5th entry in ParseResult.bereiche.
            self.bereich = Kompetenzbereich(
                nummer=None,
                name=GZ_INTEGRATIV_BEREICH_NAME,
                slug=GZ_INTEGRATIV_BEREICH_SLUG,
                quell_index=ev.index,
            )
            return

        if state is State.FACH_PRAEAMBEL:
            self._praeambel(ev)
            return
        if state is State.KOMPETENZBEREICHE:
            self._kompetenzbereiche(ev)
            return
        if state is State.ANWENDUNGSBEREICHE:
            self._anwendungsbereiche(ev)
            return
        if state is State.KOMPETENZ_GZ_INTEGRATIV:
            self._kompetenz_gz_integrativ(ev)
            return
        if state is State.FACH_ANHANG:
            self._fach_anhang(ev)
            return

    # -- per-state handlers ---------------------------------------------

    def _praeambel(self, ev: Ereignis) -> None:
        if ev.token is Token.TEXT:
            m = THEMEN_SATZ_RE.match(ev.extracted.roh)
            if m:
                self._themen_fach = self._parse_themen_satz(m.group("liste"))

    def _kompetenzbereiche(self, ev: Ereignis) -> None:
        if ev.token is Token.STUFE:
            self._schliesse_ab_block()
            self.stufe = self._stufe_code(ev)
            self.bereich = None
            return
        if ev.token is Token.BEREICH:
            self._schliesse_ab_block()
            self.bereich = self._bereich(ev)
            self._komp_ordinal = 0
            return
        if ev.token is Token.AB_BLOCK:
            self._oeffne_ab_block(ev)
            return
        if ev.token is Token.LISTE:
            if self._offener_ab_block is not None:
                self._emit_ab_items(ev)
            elif self._ab_block_prosa_offen:
                self.issues.add(
                    "anwendungsliste_bei_prosa_bindung",
                    "list found after a prosa-bindung Anwendungsbereiche "
                    "heading; not expected for this spec, skipping",
                    ev.index,
                )
            else:
                self._emit_kompetenzen(ev)
            return
        if ev.token is Token.ANDERE_UEBERSCHRIFT:
            self._schliesse_ab_block()
            self._verlasse_sektion(ev)
            return

    def _anwendungsbereiche(self, ev: Ereignis) -> None:
        if ev.token is Token.STUFE:
            self._close_block()
            self.stufe = self._stufe_code(ev)
            self.bereich = None
            self._block_ordinal = 0
            return
        if ev.token is Token.BEREICH:
            self._close_block()
            self.bereich = self._bereich(ev)
            self._block_ordinal = 0
            return
        if ev.token is Token.KOMPETENZSATZ:
            self._close_block()
            if self.bereich is None:
                self.issues.add(
                    "satz_ohne_bereich",
                    "competence sentence before any Kompetenzbereich heading",
                    ev.index,
                    ev.extracted.text[:80],
                )
            self._offener_block = Anwendungsblock(
                stufe=self.stufe or "",
                bereich_nummer=self.bereich.nummer if self.bereich else None,
                bereich_name=self.bereich.name if self.bereich else "",
                ordinal=self._block_ordinal,
                satz=ev.extracted.text,
                quell_index=ev.index,
            )
            self._block_ordinal += 1
            return
        if ev.token is Token.DIGITALE_TECHNOLOGIEN:
            self._close_block()
            self._digital_offen = True
            return
        if ev.token is Token.LISTE:
            self._emit_anwendungsitems(ev)
            return
        if ev.token is Token.ANDERE_UEBERSCHRIFT:
            self._close_block()
            self._verlasse_sektion(ev)
            return
        if ev.token is Token.STAMMSATZ:
            self.issues.add(
                "bloßer_stammsatz_in_anwendungsbereichen",
                "bare stem paragraph inside Anwendungsbereiche (expected inline form)",
                ev.index,
            )

    def _kompetenz_gz_integrativ(self, ev: Ereignis) -> None:
        """The integrative-Geometrisches-Zeichnen appendix (promoted).

        Shape: ``STUFE`` (3. Klasse / 4. Klasse), a bare stem paragraph
        (ignored, same as in KOMPETENZBEREICHE), then one ``LISTE`` of
        competences for that class year. ``self.bereich`` was fixed to the
        synthetic GZ area when this state was entered and never changes
        here; only ``self.stufe`` and the per-stufe ordinal reset. The
        trailing footnote-legend ``TABELLE`` is handled generically in
        :meth:`_step` (the legend-table subject terminator), not here.
        """
        if ev.token is Token.STUFE:
            self.stufe = self._stufe_code(ev)
            self._komp_ordinal = 0
            return
        if ev.token is Token.LISTE:
            self._emit_kompetenzen(ev)
            return
        if ev.token is Token.ANDERE_UEBERSCHRIFT:
            self._verlasse_sektion(ev)
            return

    def _fach_anhang(self, ev: Ereignis) -> None:
        """Capture, without interpreting, anything after the two sections."""
        if ev.token is Token.ANDERE_UEBERSCHRIFT:
            self._zusatz_titel = ev.extracted.text
            self._zusatz_stufe = None
            return
        if ev.token is Token.STUFE:
            self._zusatz_stufe = self._stufe_code(ev)
            return
        if ev.token is Token.LISTE:
            for el in ev.element.findall(".//" + NS + "listelem"):
                ex = element_text(el)
                self._zusatz.append(
                    {
                        "titel": self._zusatz_titel or "",
                        "stufe": self._zusatz_stufe,
                        "text": ex.text,
                        "quell_index": ev.index,
                    }
                )
            return
        if ev.token is Token.TABELLE:
            self._themen_map.update(self._parse_themen_tabelle(ev.element))

    # -- helpers ---------------------------------------------------------

    def _verlasse_sektion(self, ev: Ereignis) -> None:
        self.issues.add(
            "unbekannte_ueberschrift",
            "heading is neither a Kompetenzbereich nor a known section; "
            f"leaving {self.state.value}",
            ev.index,
            ev.extracted.text[:100],
        )
        self.state = State.FACH_ANHANG
        self._zusatz_titel = ev.extracted.text
        self._zusatz_stufe = None

    def _stufe_code(self, ev: Ereignis) -> str:
        nr = ev.daten["nr"]
        einheit = ev.daten["einheit"]
        erwartet = "Klasse" if self.spec.stufen_praefix == "K" else "Schulstufe"
        if einheit != erwartet:
            self.issues.add(
                "unerwartete_stufeneinheit",
                f"expected {erwartet!r}, found {einheit!r}; carrying on",
                ev.index,
            )
        return f"{self.spec.stufen_praefix}{nr}"

    def _bereich(self, ev: Ereignis) -> Kompetenzbereich:
        name = ev.daten["name"]
        nummer = ev.daten["nummer"]
        vorhanden = self.bereiche.get(name)
        if vorhanden is not None:
            if vorhanden.nummer != nummer:
                self.issues.add(
                    "bereichsnummer_wechselt",
                    f"area {name!r} was number {vorhanden.nummer}, now {nummer}",
                    ev.index,
                )
            return vorhanden
        slug = self.spec.bereich_slugs.get(name) or slugify_bereich(name)
        if name not in self.spec.bereich_slugs:
            self.issues.add(
                "bereich_ohne_slug",
                f"no ID slug configured for area {name!r}; derived {slug!r}",
                ev.index,
            )
        bereich = Kompetenzbereich(nummer=nummer, name=name, slug=slug, quell_index=ev.index)
        self.bereiche[name] = bereich
        return bereich

    def _make_id(self, bereich_slug: str, stufe: str, lfd: int, index: int, praefix: str = "") -> str:
        ident = (
            f"AT.LP23.{self.spec.band}.{self.spec.fach_code}."
            f"{praefix}{bereich_slug}.{stufe}.{lfd:02d}"
        )
        if ident in self._ids:
            raise ParseError(
                f"ID collision {ident!r}: child index {index} collides with {self._ids[ident]}"
            )
        self._ids[ident] = index
        return ident

    def _require(self, wert: object, feld: str, index: int) -> None:
        if wert in (None, ""):
            raise ParseError(f"required field {feld!r} missing at child index {index}")

    def _abbildung_eintraege(self, pfade: Sequence[str], index: int) -> list[dict]:
        """Resolve raw ``<binary>/<src>`` paths (as collected by
        :func:`element_text` into ``ExtractedText.abbildungen``) against the
        shipped-image registry, in the order the ⟦ABB:...⟧ tokens appear in
        the text.  Per the interface contract, each entry carries the token,
        the shipped path (relative to the plugin root), the source URL, the
        PNG dimensions and the SHA-256 of the shipped file.

        A path that does not match the expected RIS shape, or an image the
        registry does not know about (not fetched/installed), is logged and
        skipped rather than raising -- ``abbildungen`` on a record is
        best-effort metadata, not a required field.
        """
        eintraege: list[dict] = []
        for pfad in pfade:
            m = ABB.IMAGE_SRC_RE.match(pfad)
            if not m:
                self.issues.add(
                    "abbildung_pfad_unerwartet",
                    f"<binary>/<src> path does not match the expected RIS "
                    f"shape: {pfad!r}",
                    index,
                )
                continue
            nor, dateiname = m.group("nor"), m.group("filename")
            rec = self._abbildungen.get((nor, dateiname))
            if rec is None:
                self.issues.add(
                    "abbildung_nicht_installiert",
                    f"{dateiname!r} (nor={nor!r}) is referenced in the source "
                    f"but not found under plugin/data/abbildungen/{nor}/ -- "
                    f"image not shipped",
                    index,
                )
                continue
            eintraege.append(
                {
                    "token": abbildung_token(dateiname),
                    "datei": dateiname,
                    "nor": nor,
                    "pfad": rec.pfad,
                    "quelle_url": rec.quelle_url,
                    "breite_px": rec.breite_px,
                    "hoehe_px": rec.hoehe_px,
                    "sha256": rec.sha256,
                }
            )
        return eintraege

    def _emit_kompetenzen(self, ev: Ereignis) -> None:
        if self.bereich is None or self.stufe is None:
            self.issues.add(
                "liste_ohne_kontext",
                "competence list without area and/or class year; skipped",
                ev.index,
            )
            return
        for el in ev.element.findall(".//" + NS + "listelem"):
            ex = element_text(el)
            self._require(ex.text, "text", ev.index)
            self._require(self.stufe, "stufe", ev.index)
            themen, offen, roh = self._resolve_super(ex.super_marker, ev.index)
            lfd = self._komp_ordinal + 1
            ident = self._make_id(self.bereich.slug, self.stufe, lfd, ev.index)
            self.kompetenzen.append(
                Kompetenz(
                    id=ident,
                    band=self.spec.band,
                    fach=self.spec.fach_code,
                    bereich_nummer=self.bereich.nummer,
                    bereich_name=self.bereich.name,
                    stufe=self.stufe,
                    ordinal=self._komp_ordinal,
                    text=ex.text,
                    text_roh=ex.roh,
                    uebergreifende_themen=themen,
                    themen_marker_roh=roh,
                    fussnoten_unaufgeloest=offen,
                    abbildungen=self._abbildung_eintraege(ex.abbildungen, ev.index),
                    quell_index=ev.index,
                )
            )
            self._komp_ordinal += 1

    def _emit_anwendungsitems(self, ev: Ereignis) -> None:
        if self.stufe is None:
            self.issues.add(
                "anwendungsliste_ohne_stufe",
                "application list before any class-year marker; skipped",
                ev.index,
            )
            return
        block = self._offener_block
        digital = self._digital_offen
        if block is None and not digital:
            self.issues.add(
                "anwendungsliste_ohne_satz",
                "application list with neither a competence sentence nor a "
                "digital-technology heading before it; kept as unattached",
                ev.index,
            )
        bereich_slug = self.bereich.slug if self.bereich else "ALLGEMEIN"
        art = "digitale_technologien" if digital else "praezisierung"
        praefix = "DT." if digital else "AB."
        for el in ev.element.findall(".//" + NS + "listelem"):
            ex = element_text(el)
            self._require(ex.text, "text", ev.index)
            lfd = len([i for i in self.anwendungsitems
                       if i.stufe == self.stufe and i.art == art
                       and i.bereich_name == (self.bereich.name if self.bereich else "")]) + 1
            ident = self._make_id(bereich_slug, self.stufe, lfd, ev.index, praefix)
            item = Anwendungsitem(
                id=ident,
                band=self.spec.band,
                fach=self.spec.fach_code,
                bereich_nummer=self.bereich.nummer if self.bereich else None,
                bereich_name=self.bereich.name if self.bereich else "",
                stufe=self.stufe,
                ordinal=len(block.items) if block is not None else 0,
                text=ex.text,
                text_roh=ex.roh,
                verbindlich=self._verbindlich(ex.text),
                art=art,
                ist_wiederholung=bool(WIEDERHOLUNG_RE.match(ex.text)),
                abbildungen=self._abbildung_eintraege(ex.abbildungen, ev.index),
                quell_index=ev.index,
            )
            self.anwendungsitems.append(item)
            if block is not None:
                block.items.append(item)
        if digital:
            self._digital_offen = False
        else:
            self._close_block()

    def _close_block(self) -> None:
        if self._offener_block is not None:
            self.bloecke.append(self._offener_block)
            self._offener_block = None
        self._digital_offen = False

    # -- containment attachment (bindung 'bereich' | 'stufe' | 'prosa') --

    def _verbindlich(self, text: str) -> bool:
        """Whether an application item is binding.

        The ``allenfalls`` marker is SEK1.M-only (measured 2026-07-29: zero
        occurrences in the competence/application sections of the other five
        subjects). Per :attr:`SubjectSpec.allenfalls_pruefen`, the regex is
        not even evaluated for those subjects -- ``verbindlich`` is simply
        always ``True``, rather than reporting a meaningless 0/N split."""
        if not self.spec.allenfalls_pruefen:
            return True
        return not bool(ALLENFALLS_RE.search(text))

    def _oeffne_ab_block(self, ev: Ereignis) -> None:
        """Open the AB-BLOCK following an ``Anwendungsbereiche`` marker.

        Keyed per :attr:`SubjectSpec.anwendungsbereiche_bindung`:

        * ``bereich`` -- attaches to the current ``(bereich, stufe)``. The
          area may have no competence list of its own (SEK1.D's
          'Integrativer Kompetenzbereich Sprachbewusstsein und
          Sprachreflexion', mirroring GZINTEGRATIV) -- ``self.bereich`` is
          set unconditionally by the BEREICH token handler regardless of
          whether a competence list followed, so this never mis-binds to a
          stale, previously-seen area.
        * ``stufe`` -- attaches to ``(stufe)`` only; the area is deliberately
          ignored even though ``self.bereich`` is normally non-``None`` here
          (the block follows the *last* area of the year) -- attaching it to
          an area the source does not scope it to would be exactly the
          per-competence misattribution the join-honesty rule forbids.
        * ``prosa`` -- no block object at all; only a ``ParseIssue`` records
          that the section was seen (matches the measured "0 blocks / 4
          prose heads" shape, not a phantom zero-item block).
        """
        self._schliesse_ab_block()
        bindung = self.spec.anwendungsbereiche_bindung
        if bindung == "prosa":
            self.issues.add(
                "anwendungsbereiche_prosa",
                "Anwendungsbereiche heading followed by descriptive prose "
                "only; no items captured for bindung='prosa'",
                ev.index,
            )
            self._ab_block_prosa_offen = True
            return
        if bindung == "stufe":
            bereich_nummer: int | None = None
            bereich_name = ""
        else:  # "bereich" (or an unrecognised value -- fall back safely)
            if bindung != "bereich":
                self.issues.add(
                    "unbekannte_anwendungsbereiche_bindung",
                    f"anwendungsbereiche_bindung={bindung!r} not recognised; "
                    "treating as 'bereich'",
                    ev.index,
                )
            if self.bereich is None:
                self.issues.add(
                    "ab_block_ohne_bereich",
                    "Anwendungsbereiche block (bindung='bereich') with no "
                    "preceding area heading",
                    ev.index,
                )
            bereich_nummer = self.bereich.nummer if self.bereich else None
            bereich_name = self.bereich.name if self.bereich else ""
        self._offener_ab_block = Anwendungsblock(
            stufe=self.stufe or "",
            bereich_nummer=bereich_nummer,
            bereich_name=bereich_name,
            ordinal=self._block_ordinal,
            satz="",
            quell_index=ev.index,
        )
        self._block_ordinal += 1

    def _schliesse_ab_block(self) -> None:
        if self._offener_ab_block is not None:
            self.bloecke.append(self._offener_ab_block)
            self._offener_ab_block = None
        self._ab_block_prosa_offen = False

    def _emit_ab_items(self, ev: Ereignis) -> None:
        """Emit items for an open containment-attachment AB-BLOCK.

        Deliberately does **not** set ``kompetenz_id``/``join_methode`` --
        those stay at their ``None`` default. Per notes/deviations.md
        (2026-07-29): synthesising a per-competence link here, where the
        regulation makes none, would be a factual misstatement about a legal
        text."""
        block = self._offener_ab_block
        if block is None:  # pragma: no cover - guarded by the caller
            self.issues.add(
                "anwendungsliste_ohne_block",
                "Anwendungsbereiche list with no open AB block; skipped",
                ev.index,
            )
            return
        if self.stufe is None:
            self.issues.add(
                "anwendungsliste_ohne_stufe",
                "application list before any class-year marker; skipped",
                ev.index,
            )
            return
        bereich_obj = self.bereiche.get(block.bereich_name) if block.bereich_name else None
        bereich_slug = bereich_obj.slug if bereich_obj else "ALLGEMEIN"
        for el in ev.element.findall(".//" + NS + "listelem"):
            ex = element_text(el)
            self._require(ex.text, "text", ev.index)
            # Counted across *all* items sharing (bereich_name, stufe), not
            # just this block's own -- if bindung='stufe' ever sees more than
            # one AB-BLOCK per school year (the malformed shape the
            # 'ab_block_anzahl_unerwartet' check in _finish flags), this
            # keeps numbering sequential instead of colliding with the first
            # block's IDs.
            lfd = len([
                i for i in self.anwendungsitems
                if i.stufe == block.stufe and i.bereich_name == block.bereich_name
            ]) + 1
            ident = self._make_id(bereich_slug, block.stufe, lfd, ev.index, "AB.")
            item = Anwendungsitem(
                id=ident,
                band=self.spec.band,
                fach=self.spec.fach_code,
                bereich_nummer=block.bereich_nummer,
                bereich_name=block.bereich_name,
                stufe=block.stufe,
                ordinal=len(block.items),
                text=ex.text,
                text_roh=ex.roh,
                verbindlich=self._verbindlich(ex.text),
                art="praezisierung",
                ist_wiederholung=bool(WIEDERHOLUNG_RE.match(ex.text)),
                abbildungen=self._abbildung_eintraege(ex.abbildungen, ev.index),
                quell_index=ev.index,
            )
            self.anwendungsitems.append(item)
            block.items.append(item)

    # -- cross-cutting themes -------------------------------------------

    def _parse_themen_satz(self, liste: str) -> list[str]:
        """Parse ``Entrepreneurship Education2, Informatische Bildung4, ...``.

        Also seeds :attr:`_themen_map`; the trailing legend table (parsed later)
        overrides it, being the complete 13-entry list.
        """
        themen: list[str] = []
        # Split only on a comma that follows the footnote number, never on the
        # commas *inside* a theme name ("Wirtschafts-, Finanz- und ...").
        for stueck in re.split(r"(?<=\d),\s*", liste.strip().rstrip(".")):
            m = re.match(r"^(?P<name>.+?)(?P<nr>\d{1,2})$", stueck.strip())
            if not m:
                self.issues.add("thema_ohne_nummer", f"cannot parse theme item {stueck!r}")
                continue
            name = m.group("name").strip()
            themen.append(name)
            self._themen_map.setdefault(m.group("nr"), name)
        return themen

    def _parse_themen_tabelle(self, table: ET.Element) -> dict[str, str]:
        """Parse the per-subject footnote legend table (``4Informatische Bildung``).

        The number lives in a ``<super>``, so the *roh* text is required here --
        the clean text would have the digit stripped out.
        """
        gefunden: dict[str, str] = {}
        for td in table.findall(".//" + NS + "td"):
            zelle = element_text(td).roh
            if not zelle:
                continue
            m = THEMA_ZELLE_RE.match(zelle)
            if m:
                gefunden[m.group("nr")] = m.group("name").strip()
        return gefunden

    def _resolve_super(
        self, marker: Sequence[str], index: int
    ) -> tuple[list[str], list[str], list[str]]:
        """Resolve ``<super>`` contents against the theme map.

        A single ``<super>`` may read ``"6, 7"``.  Numbers that do not resolve
        are ordinary footnotes and are kept in ``fussnoten_unaufgeloest``.
        """
        themen: list[str] = []
        offen: list[str] = []
        for raw in marker:
            for stueck in re.split(r"[,;\s]+", raw.strip()):
                if not stueck:
                    continue
                name = self._themen_map.get(stueck.lstrip("0") or stueck)
                if name and name not in themen:
                    themen.append(name)
                elif not name:
                    offen.append(stueck)
        return themen, offen, list(marker)

    # -- finish ----------------------------------------------------------

    def _finish(self) -> ParseResult:
        self._close_block()
        self._schliesse_ab_block()
        if self.spec.anwendungsbereiche_bindung == "stufe":
            # Discriminator vs 'bereich' is the spec value, not a heuristic --
            # but assert internal consistency: a 'stufe'-bound AB-BLOCK
            # attaches once per school year (after its last area), so no
            # stufe should ever end up with more than one block.
            je_stufe: dict[str, int] = {}
            for b in self.bloecke:
                je_stufe[b.stufe] = je_stufe.get(b.stufe, 0) + 1
            for stufe, anzahl in je_stufe.items():
                if anzahl > 1:
                    self.issues.add(
                        "ab_block_anzahl_unerwartet",
                        f"bindung='stufe' but {anzahl} AB blocks attached to "
                        f"{stufe!r} (expected at most 1 per school year)",
                    )
        if not self._themen_map:
            self.issues.add("keine_themenlegende", "no cross-cutting-theme legend found")
        else:
            # Re-resolve now that the trailing legend table has been read.
            for k in self.kompetenzen:
                themen, offen, _ = self._resolve_super(k.themen_marker_roh, k.quell_index)
                k.uebergreifende_themen = themen
                k.fussnoten_unaufgeloest = offen
        if not self.kompetenzen:
            self.issues.add("keine_kompetenzen", "no competences extracted")
        return ParseResult(
            spec=self.spec,
            fach_name=self.spec.fach_ueberschrift.title(),
            bereiche=sorted(self.bereiche.values(), key=lambda b: (b.nummer or 99, b.name)),
            kompetenzen=self.kompetenzen,
            anwendungsitems=self.anwendungsitems,
            bloecke=self.bloecke,
            themen_map=dict(sorted(self._themen_map.items(), key=lambda kv: int(kv[0]))),
            uebergreifende_themen_fach=self._themen_fach,
            issues=self.issues,
            zusatzbloecke=self._zusatz,
        )


# --------------------------------------------------------------------------
# The join: application-area block -> competence
# --------------------------------------------------------------------------

FUZZY_SCHWELLE = 0.90
"""Minimum ``SequenceMatcher`` ratio accepted as a fuzzy join.

Measured on Sek I Mathematik: the two non-exact pairs score 0.964 and 0.965,
the best *wrong* candidate in the same (year, area) bucket scores well below
0.80.  0.90 sits comfortably in the gap.
"""


def join_anwendungen(result: ParseResult, issues: IssueLog | None = None) -> dict[str, float | int]:
    """Attach every application block to its competence.

    Three strategies in order, each logged:

    1. **exact** -- stem-stripped, normalised strings are identical;
    2. **fuzzy** -- ``difflib.SequenceMatcher`` ratio >= :data:`FUZZY_SCHWELLE`
       within the same (class year, competence area) bucket;
    3. **positional** -- same bucket, same ordinal.

    The source repeats competence sentences with small editorial drift
    ("sowie" -> "und", a dropped noun), which is why 1 alone is insufficient.

    Only meaningful for ``anwendungsbereiche_bindung == "kompetenz"``
    (SEK1.M). For ``bereich``/``stufe``/``prosa``/``keine`` this is a no-op:
    there is no text-repetition join to run (measured 2026-07-29, see
    notes/deviations.md) and running the exact/fuzzy/positional cascade
    against those blocks' empty ``satz`` would risk a spurious positional
    match, i.e. synthesising exactly the per-competence link the source does
    not make.
    """
    log = issues if issues is not None else result.issues
    if result.spec.anwendungsbereiche_bindung != "kompetenz":
        stats = {
            "bloecke": len(result.bloecke),
            "kompetenzen": len(result.kompetenzen),
            "exact": 0,
            "fuzzy": 0,
            "positional": 0,
            "unmatched": 0,
            "exact_rate": 0.0,
            "fuzzy_rate": 0.0,
            "positional_rate": 0.0,
            "unmatched_rate": 0.0,
        }
        result.join_stats = stats
        return stats

    eimer: dict[tuple[str, int | None], list[Kompetenz]] = {}
    for k in result.kompetenzen:
        eimer.setdefault((k.stufe, k.bereich_nummer), []).append(k)

    zaehler = {"exact": 0, "fuzzy": 0, "positional": 0, "unmatched": 0}
    for block in result.bloecke:
        kandidaten = eimer.get((block.stufe, block.bereich_nummer), [])
        ziel = normalise_for_match(block.satz)

        treffer = [k for k in kandidaten if normalise_for_match(k.text) == ziel]
        if len(treffer) == 1:
            _assign(block, treffer[0], "exact", 1.0)
            zaehler["exact"] += 1
            continue
        if len(treffer) > 1:
            log.add(
                "mehrdeutiger_exakter_treffer",
                f"{len(treffer)} competences normalise identically; taking the first",
                block.quell_index,
                block.satz[:100],
            )
            _assign(block, treffer[0], "exact", 1.0)
            zaehler["exact"] += 1
            continue

        bewertet = sorted(
            ((difflib.SequenceMatcher(None, normalise_for_match(k.text), ziel).ratio(), k)
             for k in kandidaten),
            key=lambda t: -t[0],
        )
        if bewertet and bewertet[0][0] >= FUZZY_SCHWELLE:
            score, k = bewertet[0]
            _assign(block, k, "fuzzy", score)
            zaehler["fuzzy"] += 1
            log.add(
                "join_fuzzy",
                f"fuzzy join at ratio {score:.3f}",
                block.quell_index,
                f"AB: {block.satz[:110]!r} <-> KB: {k.text[:110]!r}",
            )
            continue

        nach_position = [k for k in kandidaten if k.ordinal == block.ordinal]
        if nach_position:
            best = bewertet[0][0] if bewertet else 0.0
            _assign(block, nach_position[0], "positional", best)
            zaehler["positional"] += 1
            log.add(
                "join_positional",
                f"positional fallback (best fuzzy ratio was {best:.3f})",
                block.quell_index,
                f"AB: {block.satz[:110]!r} <-> KB: {nach_position[0].text[:110]!r}",
            )
            continue

        zaehler["unmatched"] += 1
        log.add(
            "join_fehlgeschlagen",
            f"no competence in bucket ({block.stufe}, {block.bereich_nummer})",
            block.quell_index,
            block.satz[:120],
        )

    gesamt = len(result.bloecke) or 1
    stats = {
        "bloecke": len(result.bloecke),
        "kompetenzen": len(result.kompetenzen),
        **zaehler,
        "exact_rate": zaehler["exact"] / gesamt,
        "fuzzy_rate": zaehler["fuzzy"] / gesamt,
        "positional_rate": zaehler["positional"] / gesamt,
        "unmatched_rate": zaehler["unmatched"] / gesamt,
    }
    result.join_stats = stats

    ohne = [k.id for k in result.kompetenzen
            if not any(b.kompetenz_id == k.id for b in result.bloecke)]
    for kid in ohne:
        log.add("kompetenz_ohne_anwendungsblock", f"no application block joined to {kid}")
    stats["kompetenzen_ohne_block"] = len(ohne)
    return stats


def _assign(block: Anwendungsblock, k: Kompetenz, methode: str, score: float) -> None:
    block.kompetenz_id = k.id
    block.join_methode = methode
    block.join_score = score
    for item in block.items:
        item.kompetenz_id = k.id
        item.join_methode = methode
        item.join_score = score


# --------------------------------------------------------------------------
# Wiederholen und Festigen backlinks
# --------------------------------------------------------------------------


def link_wiederholungen(result: ParseResult, issues: IssueLog | None = None) -> int:
    """Point every ``Wiederholen und Festigen:`` item at the previous year.

    The source gives no ID, only the phrase; the backlink is therefore
    positional -- same competence area, class year *n* - 1.  (Primary has no
    such phrase at all, so primary progression will be purely positional.)
    """
    log = issues if issues is not None else result.issues
    nach_stufe_bereich: dict[tuple[str, int | None], list[Kompetenz]] = {}
    for k in result.kompetenzen:
        nach_stufe_bereich.setdefault((k.stufe, k.bereich_nummer), []).append(k)

    praefix = result.spec.stufen_praefix
    verlinkt = 0
    for item in result.anwendungsitems:
        if not item.ist_wiederholung:
            continue
        m = re.match(rf"^{re.escape(praefix)}(\d+)$", item.stufe or "")
        if not m:
            log.add("wiederholung_ohne_stufe", f"cannot derive previous level from {item.stufe!r}",
                    item.quell_index)
            continue
        nr = int(m.group(1))
        if nr <= 1:
            log.add(
                "wiederholung_in_erster_stufe",
                f"'Wiederholen und Festigen' in {item.stufe} has no predecessor level",
                item.quell_index,
                item.text[:90],
            )
            continue
        vorige = nach_stufe_bereich.get((f"{praefix}{nr - 1}", item.bereich_nummer), [])
        if not vorige:
            log.add(
                "wiederholung_ohne_ziel",
                f"no competences in {praefix}{nr - 1} / area {item.bereich_nummer}",
                item.quell_index,
                item.text[:90],
            )
            continue
        item.wiederholung_von = [k.id for k in vorige]
        verlinkt += 1

    # Mirror the year-over-year progression onto the competences themselves.
    for k in result.kompetenzen:
        m = re.match(rf"^{re.escape(praefix)}(\d+)$", k.stufe)
        if not m:
            continue
        nr = int(m.group(1))
        k.vorlaeufer = [p.id for p in nach_stufe_bereich.get((f"{praefix}{nr - 1}", k.bereich_nummer), [])]
        k.folge = [p.id for p in nach_stufe_bereich.get((f"{praefix}{nr + 1}", k.bereich_nummer), [])]
    return verlinkt


# --------------------------------------------------------------------------
# Top level
# --------------------------------------------------------------------------


def parse_lehrplan(
    path: str | Path,
    spec: SubjectSpec = SEK1_MATHEMATIK,
    abbildungen_registry: dict[tuple[str, str], ABB.AbbildungRecord] | None = None,
) -> ParseResult:
    """Parse *path* for *spec* and run the join and backlink passes.

    *abbildungen_registry* is normally left ``None`` (scans the real shipped
    ``plugin/data/abbildungen/``); tests inject a synthetic registry instead.
    """
    parser = LehrplanParser(spec, abbildungen_registry=abbildungen_registry)
    result = parser.parse_file(path)
    join_anwendungen(result)
    link_wiederholungen(result)
    return result


def result_to_dict(result: ParseResult) -> dict:
    """Serialisable view of a :class:`ParseResult`."""
    return {
        "meta": {
            "band": result.spec.band,
            "fach": {"code": result.spec.fach_code, "name": result.fach_name},
            "anwendungsbereiche_status": result.spec.anwendungsbereiche_status,
            "lehrstoff_quelle": result.spec.lehrstoff_quelle,
            "uebergreifende_themen_fach": result.uebergreifende_themen_fach,
            "uebergreifende_themen_legende": result.themen_map,
            "join": result.join_stats,
        },
        "kompetenzbereiche": [dataclasses.asdict(b) for b in result.bereiche],
        "kompetenzen": [dataclasses.asdict(k) for k in result.kompetenzen],
        "anwendungsitems": [dataclasses.asdict(a) for a in result.anwendungsitems],
        "zusatzbloecke": result.zusatzbloecke,
        "issues": result.issues.as_dicts(),
    }


#: Measured on NOR40271471 (Mittelschule, in force 2025-09-01), Sek I Mathematik.
#: ``kompetenzen`` is 42, not 40: the 4 numbered Kompetenzbereiche contribute
#: 40 (4 areas x ~2.5 avg across 4 class years, always 10 per class year),
#: plus the 2 promoted "integrative Führung von Geometrisches Zeichnen"
#: competences (1 for K3, 1 for K4) -- see GZ_INTEGRATIV_RE and
#: notes/deviations.md. ``kompetenzbereiche`` stays 4: the promoted pair
#: gets a synthetic area *label* on the Kompetenz records but is not added
#: as a 5th entry to ParseResult.bereiche.
ERWARTET_SEK1_M = {
    "kompetenzen": 42,
    "anwendungsitems": 237,
    "allenfalls": 32,
    "wiederholen_und_festigen": 16,
    "kompetenzen_mit_super": 10,
    "kompetenzbereiche": 4,
}


def actual_counts(result: ParseResult) -> dict[str, int]:
    return {
        "kompetenzen": len(result.kompetenzen),
        "anwendungsitems": len(result.anwendungsitems),
        "allenfalls": sum(1 for a in result.anwendungsitems if not a.verbindlich),
        "wiederholen_und_festigen": sum(1 for a in result.anwendungsitems if a.ist_wiederholung),
        "kompetenzen_mit_super": sum(1 for k in result.kompetenzen if k.themen_marker_roh),
        "kompetenzbereiche": len(result.bereiche),
    }


def _cli(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    here = Path(__file__).resolve().parent
    ap.add_argument("--source", default=str(here / "resources/mittelschule/NOR40271471.xml"))
    ap.add_argument("--spec", default="SEK1.M", choices=sorted(SUBJECT_SPECS))
    ap.add_argument("--out", help="write JSON here instead of stdout")
    ap.add_argument("--summary", action="store_true", help="print counts instead of JSON")
    ap.add_argument("--verify", action="store_true", help="exit non-zero if counts deviate")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.ERROR,
                        format="%(levelname)s %(message)s")

    result = parse_lehrplan(args.source, SUBJECT_SPECS[args.spec])
    ist = actual_counts(result)

    if args.summary or args.verify:
        soll = ERWARTET_SEK1_M if args.spec == "SEK1.M" else {}
        print(f"{args.spec}  {Path(args.source).name}")
        for key, wert in ist.items():
            erw = soll.get(key)
            mark = "" if erw is None else ("  OK" if erw == wert else f"  MISMATCH (erwartet {erw})")
            print(f"  {key:28s} {wert:5d}{mark}")
        j = result.join_stats
        print(f"  join exact/fuzzy/positional/unmatched: "
              f"{j['exact']}/{j['fuzzy']}/{j['positional']}/{j['unmatched']} "
              f"({j['exact_rate']:.1%}/{j['fuzzy_rate']:.1%}/"
              f"{j['positional_rate']:.1%}/{j['unmatched_rate']:.1%})")
        print(f"  issues: {len(result.issues)}")
        for issue in result.issues:
            print(f"    {issue}")
        if args.verify:
            soll = ERWARTET_SEK1_M
            bad = {k: (v, ist[k]) for k, v in soll.items() if ist.get(k) != v}
            if bad or result.join_stats["unmatched"]:
                print("VERIFY FAILED", bad, file=sys.stderr)
                return 1
            print("VERIFY OK")
        return 0

    payload = json.dumps(result_to_dict(result), ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(payload + "\n", encoding="utf-8")
    else:
        sys.stdout.write(payload + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
