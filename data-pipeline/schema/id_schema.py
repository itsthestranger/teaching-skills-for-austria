#!/usr/bin/env python3
"""Frozen ID scheme for ``AT.LP23`` competence and application-item identifiers.

**This scheme is frozen (task E3-02).** IDs are the plan's only hard-fail
condition (ID collisions abort the pipeline -- see
``parse_lehrplan.py::LehrplanParser._make_id``). Once a shard ships, its IDs
must never be re-minted; adding a subject or an area means *adding* a table
entry here, never renaming or renumbering an existing one. The four Sek I
Mathematik area codes (``ZAHLEN``, ``VARIABLEN``, ``FIGUREN``, ``DATEN``) and
the synthetic ``GZINTEGRATIV`` code are reused verbatim from
``parse_lehrplan.py`` because they are already in shipped IDs.

Two ID grammars are in scope, both produced by
``LehrplanParser._make_id`` (``praefix=""`` for competences, ``"AB."``/``"DT."``
for application items -- the trailing dot in the prefix is what turns the
segment count from 7 into 8):

    Kompetenz:       AT.LP23.<Band>.<Fach>.<Bereich>.<Stufe>.<lfd>            (7 segments)
    Anwendungsitem:  AT.LP23.<Band>.<Fach>.<Art>.<Bereich>.<Stufe>.<lfd>      (8 segments)

    Band  = PRIM | SEK1
    Fach  = M | D | E | SU                    (scoped per band, see BAND_FAECHER)
    Art   = AB (Praezisierung) | DT (digitale Technologien)
    Bereich = subject x band specific area code, see AREA_CODES
    Stufe = K1..K4 (SEK1) | SCH1..SCH4 (PRIM)  -- GS1/GS2/VOR are NOT in scope
            (V-22: primary is per school year, not per Grundstufe)
    lfd   = two digits, zero-padded, scoped per (stufe, art, bereich)

Examples::

    AT.LP23.SEK1.M.ZAHLEN.K1.01              # competence
    AT.LP23.SEK1.M.AB.ZAHLEN.K2.05           # application item, precisification
    AT.LP23.SEK1.M.DT.ZAHLEN.K1.01           # application item, digital tech
    AT.LP23.SEK1.M.GZINTEGRATIV.K3.01        # synthetic area (V-57)
    AT.LP23.PRIM.SU.NATURWISS.SCH2.03

stdlib only. See ``notes/id-schema.md`` for the full code table, the
rationale behind each minted area code, and the frozen-scheme rationale.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence, Union

# --------------------------------------------------------------------------
# Bands and Stufen
# --------------------------------------------------------------------------

#: The two bands in scope. Order matches the plan's presentation order.
BAENDER: tuple[str, ...] = ("PRIM", "SEK1")

#: Level prefix per band. Primary uses ``SCH`` (Schulstufe); Sek I uses ``K``
#: (Klasse). V-22 closed this: both bands are per *school year* / *class
#: year*, 1..4 -- ``GS1``/``GS2`` (Grundstufe) and ``VOR`` (Vorschulstufe) do
#: not occur in the Grundstufe curricula and are removed from the scheme.
STUFEN_PRAEFIX: dict[str, str] = {"PRIM": "SCH", "SEK1": "K"}

#: Number of class/school years per band -- both are 1..4.
STUFEN_ANZAHL = 4


def stufen_werte(band: str) -> tuple[str, ...]:
    """Return the ordered, valid ``stufe`` values for *band* (e.g. ``K1..K4``)."""
    praefix = STUFEN_PRAEFIX[band]
    return tuple(f"{praefix}{n}" for n in range(1, STUFEN_ANZAHL + 1))


# --------------------------------------------------------------------------
# Subjects
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class FachEintrag:
    """One subject code, with the official RIS heading and a German display name."""

    code: str
    """``M`` | ``D`` | ``E`` | ``SU`` -- the ID-segment value."""

    amtliche_ueberschrift: str
    """The exact ``ueberschrift/@typ="g1"`` text that opens the subject in the
    RIS XML (case-sensitive, matched in full by ``SubjectSpec.fach_ueberschrift``)."""

    anzeige_name: str
    """German display name for product surfaces (teacher-facing)."""


#: Subject-code registry. ``E`` maps to *(Erste) Lebende Fremdsprache*
#: (V-29) -- the second foreign language (``(ZWEITE) LEBENDE FREMDSPRACHE``)
#: is explicitly out of scope. Headings are ALL CAPS in both source
#: documents for every subject in scope (verified against both XMLs; do not
#: assume case from the general "primary headings aren't always caps" note
#: in notes/ris-xml-structure.md -- that applies to *other* primary subjects,
#: not to M/D/SU).
FAECHER: dict[str, FachEintrag] = {
    "M": FachEintrag("M", "MATHEMATIK", "Mathematik"),
    "D": FachEintrag("D", "DEUTSCH", "Deutsch"),
    "E": FachEintrag("E", "(ERSTE) LEBENDE FREMDSPRACHE", "(Erste) Lebende Fremdsprache"),
    "SU": FachEintrag("SU", "SACHUNTERRICHT", "Sachunterricht"),
}

#: The exact six subject x band shards in scope (plan Executive Summary /
#: FINDINGS scope). ``E`` never appears under ``PRIM``; ``SU`` never appears
#: under ``SEK1``. Order matches the task's shard list.
BAND_FAECHER: dict[str, tuple[str, ...]] = {
    "SEK1": ("M", "D", "E"),
    "PRIM": ("M", "D", "SU"),
}


def ist_gueltige_kombination(band: str, fach: str) -> bool:
    """Whether *band* x *fach* is one of the six shards in scope."""
    return fach in BAND_FAECHER.get(band, ())


# --------------------------------------------------------------------------
# Competence-area code table -- the frozen part
# --------------------------------------------------------------------------
#
# Keyed "<BAND>.<FACH>". Area *names* are the real ``Kompetenzbereich``
# headings read from the live RIS XML (see notes/id-schema.md for the
# extraction and notes/deviations.md for every place the plan's assumed
# names were wrong). Area *codes* must be unique within one band.fach entry;
# collisions across different band.fach entries are fine and expected (e.g.
# "LESEN" is minted independently for SEK1.D, SEK1.E and PRIM.D).
#
# SEK1.M reuses parse_lehrplan.py's SEK1_MATHEMATIK.bereich_slugs and the
# GZ_INTEGRATIV_BEREICH_SLUG verbatim -- those codes are already in shipped
# IDs and are frozen by definition, not re-derived here.

AREA_CODES: dict[str, dict[str, str]] = {
    "SEK1.M": {
        "Zahlen und Maße": "ZAHLEN",
        "Variablen und Funktionen": "VARIABLEN",
        "Figuren und Körper": "FIGUREN",
        "Daten und Zufall": "DATEN",
        # Synthetic area for the 2 promoted GZ-integrative competences
        # (FINDINGS V-57, deviations.md). Not one of the four numbered
        # Kompetenzbereiche; already minted by parse_lehrplan.py and shipped.
        "Integrative Führung von Geometrisches Zeichnen": "GZINTEGRATIV",
    },
    "SEK1.D": {
        "Zuhören und Sprechen": "HOERENSPRECHEN",
        "Lesen": "LESEN",
        "Schreiben": "SCHREIBEN",
        # Folds into the three areas above (no competence list of its own --
        # "Die Beschreibungen der zu erreichenden Kompetenzen werden in den
        # Bereichen Zuhören und Sprechen, Lesen, Schreiben integrativ
        # formuliert.") but carries its own Anwendungsbereiche items, so it
        # still needs an ID segment -- the mirror image of GZINTEGRATIV
        # (competences with no application block vs. an application block
        # with no competence of its own).
        "Integrativer Kompetenzbereich Sprachbewusstsein und Sprachreflexion": "SPRACHREFLEXION",
    },
    "SEK1.E": {
        "Hören": "HOEREN",
        "Lesen": "LESEN",
        "Sprechen (an Gesprächen teilnehmen und zusammenhängend sprechen)": "SPRECHEN",
        "Schreiben": "SCHREIBEN",
    },
    "PRIM.M": {
        "Zahlen und Daten": "ZAHLENDATEN",
        "Operationen": "OPERATIONEN",
        "Größen": "GROESSEN",
        "Ebene und Raum": "EBENERAUM",
    },
    "PRIM.D": {
        "(Zu-)Hören und Sprechen": "HOERENSPRECHEN",
        "Lesen": "LESEN",
        "Verfassen von Texten": "VERFASSEN",
        "(Recht-)Schreiben und Sprachbetrachtung": "RECHTSCHREIBEN",
    },
    "PRIM.SU": {
        "Sozialwissenschaftlicher Kompetenzbereich": "SOZIALWISS",
        "Naturwissenschaftlicher Kompetenzbereich": "NATURWISS",
        "Geografischer Kompetenzbereich": "GEOGRAFIE",
        "Historischer Kompetenzbereich": "HISTORISCH",
        "Technischer Kompetenzbereich": "TECHNIK",
        "Wirtschaftlicher Kompetenzbereich": "WIRTSCHAFT",
    },
}


def bereich_codes(band: str, fach: str) -> dict[str, str]:
    """Area name -> area code table for one band x fach shard."""
    schluessel = f"{band}.{fach}"
    if schluessel not in AREA_CODES:
        raise KeyError(f"no area-code table for {schluessel!r} -- not one of the six shards")
    return AREA_CODES[schluessel]


def alle_bereich_codes(band: str, fach: str) -> frozenset[str]:
    """The set of valid area codes for one band x fach shard."""
    return frozenset(bereich_codes(band, fach).values())


# --------------------------------------------------------------------------
# Regexes
# --------------------------------------------------------------------------

_BAND_ALT = "|".join(BAENDER)
_FACH_ALT = "|".join(sorted(FAECHER, key=len, reverse=True))
_STUFE_ALT = r"K[1-4]|SCH[1-4]"

#: One area code: ASCII uppercase letters/digits, starting with a letter.
#: Readable and stable by construction (see notes/id-schema.md for the
#: minting rationale of each one); generous upper bound so a long minted
#: name (``GZINTEGRATIV``, 12 chars) still fits comfortably.
BEREICH_CODE_RE = re.compile(r"^[A-Z][A-Z0-9]{0,23}$")

#: Competence ID -- 7 segments: AT.LP23.<Band>.<Fach>.<Bereich>.<Stufe>.<lfd>
KOMPETENZ_ID_RE = re.compile(
    rf"^AT\.LP23\.(?P<band>{_BAND_ALT})\.(?P<fach>{_FACH_ALT})\."
    rf"(?P<bereich>[A-Z][A-Z0-9]*)\.(?P<stufe>{_STUFE_ALT})\.(?P<lfd>\d{{2}})$"
)

#: Application-item ID -- 8 segments:
#: AT.LP23.<Band>.<Fach>.<Art>.<Bereich>.<Stufe>.<lfd>, Art in {AB, DT}.
ANWENDUNGSITEM_ID_RE = re.compile(
    rf"^AT\.LP23\.(?P<band>{_BAND_ALT})\.(?P<fach>{_FACH_ALT})\."
    rf"(?P<art>AB|DT)\.(?P<bereich>[A-Z][A-Z0-9]*)\.(?P<stufe>{_STUFE_ALT})\.(?P<lfd>\d{{2}})$"
)


class IdSchemaError(ValueError):
    """An ID does not conform to either frozen grammar."""


# --------------------------------------------------------------------------
# Parsed results
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class KompetenzId:
    """A parsed 7-segment competence ID."""

    band: str
    fach: str
    bereich: str
    stufe: str
    lfd: int
    raw: str


@dataclass(frozen=True)
class AnwendungsitemId:
    """A parsed 8-segment application-item ID."""

    band: str
    fach: str
    art: str
    """``AB`` (Praezisierung) | ``DT`` (digitale Technologien)."""

    bereich: str
    stufe: str
    lfd: int
    raw: str


ParsedId = Union[KompetenzId, AnwendungsitemId]


def _stufe_passt_zu_band(band: str, stufe: str) -> bool:
    return stufe.startswith(STUFEN_PRAEFIX[band])


def parse_id(s: str) -> ParsedId:
    """Parse *s* against both frozen grammars.

    Tries the competence form first, then the application-item form. Raises
    :class:`IdSchemaError` if neither regex matches, or if the ``stufe``
    prefix does not agree with ``band`` (e.g. ``SEK1`` with a ``SCH`` stufe)
    -- a case the two independent alternations in the regex cannot rule out
    by construction.
    """
    m = KOMPETENZ_ID_RE.match(s)
    if m:
        band, stufe = m.group("band"), m.group("stufe")
        if not _stufe_passt_zu_band(band, stufe):
            raise IdSchemaError(f"{s!r}: stufe {stufe!r} does not match band {band!r}")
        return KompetenzId(
            band=band,
            fach=m.group("fach"),
            bereich=m.group("bereich"),
            stufe=stufe,
            lfd=int(m.group("lfd")),
            raw=s,
        )

    m = ANWENDUNGSITEM_ID_RE.match(s)
    if m:
        band, stufe = m.group("band"), m.group("stufe")
        if not _stufe_passt_zu_band(band, stufe):
            raise IdSchemaError(f"{s!r}: stufe {stufe!r} does not match band {band!r}")
        return AnwendungsitemId(
            band=band,
            fach=m.group("fach"),
            art=m.group("art"),
            bereich=m.group("bereich"),
            stufe=stufe,
            lfd=int(m.group("lfd")),
            raw=s,
        )

    raise IdSchemaError(f"{s!r} matches neither the competence nor the application-item grammar")


# --------------------------------------------------------------------------
# Constructors (the inverse of parse_id)
# --------------------------------------------------------------------------


def format_id(band: str, fach: str, bereich: str, stufe: str, lfd: int) -> str:
    """Build a 7-segment competence ID: ``AT.LP23.<Band>.<Fach>.<Bereich>.<Stufe>.<lfd>``."""
    if fach not in FAECHER:
        raise IdSchemaError(f"unknown fach {fach!r}")
    if band not in BAENDER:
        raise IdSchemaError(f"unknown band {band!r}")
    if stufe not in stufen_werte(band):
        raise IdSchemaError(f"stufe {stufe!r} not valid for band {band!r}")
    if not BEREICH_CODE_RE.match(bereich):
        raise IdSchemaError(f"bereich {bereich!r} does not look like a valid area code")
    if not (0 <= lfd <= 99):
        raise IdSchemaError(f"lfd {lfd!r} out of range 0..99")
    ident = f"AT.LP23.{band}.{fach}.{bereich}.{stufe}.{lfd:02d}"
    parse_id(ident)  # self-check: constructed ID must round-trip
    return ident


def format_item_id(band: str, fach: str, art: str, bereich: str, stufe: str, lfd: int) -> str:
    """Build an 8-segment application-item ID:
    ``AT.LP23.<Band>.<Fach>.<Art>.<Bereich>.<Stufe>.<lfd>``, ``art`` in ``{AB, DT}``."""
    if art not in ("AB", "DT"):
        raise IdSchemaError(f"art must be 'AB' or 'DT', got {art!r}")
    if fach not in FAECHER:
        raise IdSchemaError(f"unknown fach {fach!r}")
    if band not in BAENDER:
        raise IdSchemaError(f"unknown band {band!r}")
    if stufe not in stufen_werte(band):
        raise IdSchemaError(f"stufe {stufe!r} not valid for band {band!r}")
    if not BEREICH_CODE_RE.match(bereich):
        raise IdSchemaError(f"bereich {bereich!r} does not look like a valid area code")
    if not (0 <= lfd <= 99):
        raise IdSchemaError(f"lfd {lfd!r} out of range 0..99")
    ident = f"AT.LP23.{band}.{fach}.{art}.{bereich}.{stufe}.{lfd:02d}"
    parse_id(ident)  # self-check: constructed ID must round-trip
    return ident


# --------------------------------------------------------------------------
# Uniqueness / validation -- what the E3-02 test drives
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidationResult:
    """Result of :func:`validate_ids`."""

    total: int
    malformed: tuple[str, ...]
    """IDs that match neither frozen grammar (or fail the band/stufe check)."""

    duplicates: tuple[str, ...]
    """IDs that occur more than once, each listed once."""

    @property
    def ok(self) -> bool:
        return not self.malformed and not self.duplicates

    def __bool__(self) -> bool:  # pragma: no cover - convenience only
        return self.ok


def validate_ids(ids: Sequence[str]) -> ValidationResult:
    """Validate a collection of IDs: malformed IDs and duplicates are both
    hard-fail conditions per the plan's robustness principle.

    Every ID is parsed with :func:`parse_id`; anything that raises
    :class:`IdSchemaError` is malformed. Duplicate detection runs over the
    raw strings (a malformed ID cannot also be flagged a duplicate of
    itself, but two identical malformed strings are still reported once
    each as malformed and are not additionally listed as duplicates --
    duplicate tracking only applies to strings that parsed successfully).
    """
    malformed: list[str] = []
    seen: set[str] = set()
    duplicates: list[str] = []
    for ident in ids:
        try:
            parse_id(ident)
        except IdSchemaError:
            malformed.append(ident)
            continue
        if ident in seen:
            duplicates.append(ident)
        else:
            seen.add(ident)
    return ValidationResult(total=len(ids), malformed=tuple(malformed), duplicates=tuple(duplicates))
