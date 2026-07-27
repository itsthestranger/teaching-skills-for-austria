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

# --------------------------------------------------------------------------
# XML primitives
# --------------------------------------------------------------------------

NS = "{http://www.bka.gv.at}"

#: Placeholder substituted for an inline ``<binary>`` image (formulae are
#: shipped as PNG in the RIS XML and have no textual representation at all).
ABBILDUNG_PLATZHALTER = "[Abbildung]"

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
    """Quotable sentence: bullets dropped, images replaced, superscripts removed."""

    roh: str
    """Same traversal but with superscript digits inlined; nothing is lost."""

    super_marker: tuple[str, ...] = ()
    """Raw contents of each ``<super>`` (a single one may read ``"6, 7"``)."""

    abbildungen: tuple[str, ...] = ()
    """``<binary>/<src>`` paths, in document order."""

    @property
    def hat_abbildung(self) -> bool:
        return bool(self.abbildungen)


def element_text(el: ET.Element) -> ExtractedText:
    """Extract text from *el* verbatim, with three documented interventions.

    1. ``<symbol>`` -- the list bullet glyph ("--").  Presentation, not text.
    2. ``<binary>`` -- an inline PNG (fraction/formula graphic).  ``itertext()``
       would otherwise splice the *file path* from ``<src>`` into the sentence.
       Replaced by :data:`ABBILDUNG_PLATZHALTER`; the paths are kept.
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
                bilder.append((src.text or "").strip() if src is not None else "")
                clean.append(ABBILDUNG_PLATZHALTER)
                roh.append(ABBILDUNG_PLATZHALTER)
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

#: ``Dieser Lehrplan greift folgende übergreifende Themen auf: …``
THEMEN_SATZ_RE = re.compile(r"^Dieser Lehrplan greift folgende (?:ü|ue)bergreifende Themen auf\s*:\s*(?P<liste>.+)$")

#: A cell of the per-subject footnote legend table: ``4Informatische Bildung``.
THEMA_ZELLE_RE = re.compile(r"^(?P<nr>\d{1,2})\s*(?P<name>\D.+)$")

#: ``ACHTER TEIL`` and friends -- a g1 heading that opens a part, not a subject.
TEIL_RE = re.compile(
    r"^(?:ERSTER|ZWEITER|DRITTER|VIERTER|F(?:Ü|UE)NFTER|SECHSTER|SIEBENTER"
    r"|ACHTER|NEUNTER|ZEHNTER|ELFTER|ZW(?:Ö|OE)LFTER)\s+TEIL$"
)


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
    abbildungen: list[str] = field(default_factory=list)
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
    abbildungen: list[str] = field(default_factory=list)
    quell_index: int = -1


@dataclass
class Anwendungsblock:
    """One repeated competence sentence plus the item list that follows it."""

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

    FACH_ANHANG = "fach_anhang"
    """Inside the subject, after both sections closed."""

    NACH_FACH = "nach_fach"
    """The next subject's g1 heading was seen; parsing is done."""


class Token(Enum):
    """Classification of one flat child element."""

    FACH_UEBERSCHRIFT = "fach_ueberschrift"
    SEKTION_KOMPETENZ = "sektion_kompetenz"
    SEKTION_ANWENDUNG = "sektion_anwendung"
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

    def __init__(self, spec: SubjectSpec, issues: IssueLog | None = None) -> None:
        self.spec = spec
        self.issues = issues if issues is not None else IssueLog()

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
                # THE TRAP: in the Anwendungsbereiche section the area heading
                # is an ordinary body paragraph, not an <ueberschrift>.
                m = self.spec.bereich_re.match(text)
                if m and self.state is State.ANWENDUNGSBEREICHE:
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
            if self.state in (State.KOMPETENZBEREICHE, State.ANWENDUNGSBEREICHE):
                self.issues.add(
                    "sektion_nicht_geschlossen",
                    f"subject ended while still in {self.state.value}",
                    ev.index,
                    ev.extracted.text[:80],
                )
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

        if state is State.FACH_PRAEAMBEL:
            self._praeambel(ev)
            return
        if state is State.KOMPETENZBEREICHE:
            self._kompetenzbereiche(ev)
            return
        if state is State.ANWENDUNGSBEREICHE:
            self._anwendungsbereiche(ev)
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
            self.stufe = self._stufe_code(ev)
            self.bereich = None
            return
        if ev.token is Token.BEREICH:
            self.bereich = self._bereich(ev)
            self._komp_ordinal = 0
            return
        if ev.token is Token.LISTE:
            self._emit_kompetenzen(ev)
            return
        if ev.token is Token.ANDERE_UEBERSCHRIFT:
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
                    abbildungen=list(ex.abbildungen),
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
                verbindlich=not bool(ALLENFALLS_RE.search(ex.text)),
                art=art,
                ist_wiederholung=bool(WIEDERHOLUNG_RE.match(ex.text)),
                abbildungen=list(ex.abbildungen),
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
    """
    log = issues if issues is not None else result.issues
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


def parse_lehrplan(path: str | Path, spec: SubjectSpec = SEK1_MATHEMATIK) -> ParseResult:
    """Parse *path* for *spec* and run the join and backlink passes."""
    parser = LehrplanParser(spec)
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
ERWARTET_SEK1_M = {
    "kompetenzen": 40,
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
