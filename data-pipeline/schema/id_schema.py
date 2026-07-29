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

Three ID grammars are in scope. The first two are produced by
``LehrplanParser._make_id`` (``praefix=""`` for competences, ``"AB."``/``"DT."``
for application items -- the trailing dot in the prefix is what turns the
segment count from 7 into 8); the third is the area-free application-item
form added in E-P3 for ``anwendungsbereiche_bindung: "stufe"`` items
(PRIM.D, PRIM.SU), which attach to a whole school year and no area at all:

    Kompetenz:                AT.LP23.<Band>.<Fach>.<Bereich>.<Stufe>.<lfd>       (7 segments)
    Anwendungsitem:            AT.LP23.<Band>.<Fach>.<Art>.<Bereich>.<Stufe>.<lfd> (8 segments)
    Anwendungsitem (area-free) AT.LP23.<Band>.<Fach>.<Art>.<Stufe>.<lfd>          (7 segments)

    Band  = PRIM | SEK1
    Fach  = M | D | E | SU                    (scoped per band, see BAND_FAECHER)
    Art   = AB (Praezisierung) | DT (digitale Technologien)
    Bereich = subject x band specific area code, see AREA_CODES -- never
              literally "AB"/"DT" (reserved for Art, see BEREICH_CODE_RE),
              which is what keeps the two 7-segment grammars unambiguous
    Stufe = K1..K4 (SEK1) | SCH1..SCH4 (PRIM)  -- GS1/GS2/VOR are NOT in scope
            (V-22: primary is per school year, not per Grundstufe)
    lfd   = two digits, zero-padded, scoped per (stufe, art, bereich)

Examples::

    AT.LP23.SEK1.M.ZAHLEN.K1.01              # competence
    AT.LP23.SEK1.M.AB.ZAHLEN.K2.05           # application item, precisification
    AT.LP23.SEK1.M.DT.ZAHLEN.K1.01           # application item, digital tech
    AT.LP23.SEK1.M.GZINTEGRATIV.K3.01        # synthetic area (V-57)
    AT.LP23.PRIM.SU.NATURWISS.SCH2.03
    AT.LP23.PRIM.SU.AB.SCH1.01               # area-free application item (E-P3)
    AT.LP23.PRIM.D.AB.SCH3.07                # area-free application item (E-P3)

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

#: The two ``Art`` literals for application items. Reserved out of the
#: ``Bereich`` code space (see ``_BEREICH_SEGMENT`` below) so a 7-segment
#: area-free application-item ID (``AT.LP23.<Band>.<Fach>.<Art>.<Stufe>.<lfd>``,
#: E-P3) can never be misparsed as a 7-segment competence ID
#: (``AT.LP23.<Band>.<Fach>.<Bereich>.<Stufe>.<lfd>``) with ``Bereich`` equal
#: to the literal string ``AB`` or ``DT`` -- the two grammars would otherwise
#: overlap exactly on that one segment value. No area code in AREA_CODES is
#: (or may ever be) exactly "AB" or "DT"; see test_area_codes_never_shadow_art.
_ART_ALT = "AB|DT"

#: One ``Bereich`` (area code) segment, used inside a full ID pattern (not
#: anchored -- see BEREICH_CODE_RE below for the standalone validator).
#: ASCII uppercase letters/digits, starting with a letter, and -- the
#: disambiguation load-bearing part -- never exactly "AB" or "DT" (those are
#: reserved for the application-item ``Art`` segment; see ``_ART_ALT``).
_BEREICH_SEGMENT = rf"(?!(?:{_ART_ALT})\.)[A-Z][A-Z0-9]*"

#: One area code: ASCII uppercase letters/digits, starting with a letter.
#: Readable and stable by construction (see notes/id-schema.md for the
#: minting rationale of each one); generous upper bound so a long minted
#: name (``GZINTEGRATIV``, 12 chars) still fits comfortably. Excludes the two
#: reserved ``Art`` literals ``AB``/``DT`` (see ``_ART_ALT``) -- a bereich
#: code must never collide with an application-item Art marker, or the
#: 7-segment competence grammar and the 7-segment area-free application-item
#: grammar (E-P3) would become ambiguous.
BEREICH_CODE_RE = re.compile(rf"^(?!(?:{_ART_ALT})$)[A-Z][A-Z0-9]{{0,23}}$")

#: Competence ID -- 7 segments: AT.LP23.<Band>.<Fach>.<Bereich>.<Stufe>.<lfd>
KOMPETENZ_ID_RE = re.compile(
    rf"^AT\.LP23\.(?P<band>{_BAND_ALT})\.(?P<fach>{_FACH_ALT})\."
    rf"(?P<bereich>{_BEREICH_SEGMENT})\.(?P<stufe>{_STUFE_ALT})\.(?P<lfd>\d{{2}})$"
)

#: Application-item ID -- 8 segments:
#: AT.LP23.<Band>.<Fach>.<Art>.<Bereich>.<Stufe>.<lfd>, Art in {AB, DT}.
ANWENDUNGSITEM_ID_RE = re.compile(
    rf"^AT\.LP23\.(?P<band>{_BAND_ALT})\.(?P<fach>{_FACH_ALT})\."
    rf"(?P<art>{_ART_ALT})\.(?P<bereich>[A-Z][A-Z0-9]*)\.(?P<stufe>{_STUFE_ALT})\.(?P<lfd>\d{{2}})$"
)

#: Area-free application-item ID (E-P3) -- 7 segments, used only for
#: ``anwendungsbereiche_bindung: "stufe"`` items (PRIM.D, PRIM.SU), which
#: attach to a whole school year and no area at all -- inventing one would
#: assert a scoping the regulation does not make (see
#: data-pipeline/notes/deviations.md, 2026-07-29 rows):
#: AT.LP23.<Band>.<Fach>.<Art>.<Stufe>.<lfd>, Art in {AB, DT}.
#:
#: Deliberately the same *segment count* (7) as KOMPETENZ_ID_RE, since a
#: competence ID also has no Art segment. The two are kept unambiguous by
#: construction: this pattern requires the 5th segment to be exactly "AB" or
#: "DT" (reserved, never a valid Bereich code -- see BEREICH_CODE_RE), and
#: KOMPETENZ_ID_RE's Bereich group excludes exactly those two literals. A
#: given 7-segment string can therefore match at most one of the two
#: grammars, never both -- see test_id_forms_never_both_match.
ANWENDUNGSITEM_AREA_FREI_ID_RE = re.compile(
    rf"^AT\.LP23\.(?P<band>{_BAND_ALT})\.(?P<fach>{_FACH_ALT})\."
    rf"(?P<art>{_ART_ALT})\.(?P<stufe>{_STUFE_ALT})\.(?P<lfd>\d{{2}})$"
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
    """A parsed application-item ID -- either the 8-segment area-bearing form
    or the 7-segment area-free form (E-P3, ``bindung: "stufe"`` items)."""

    band: str
    fach: str
    art: str
    """``AB`` (Praezisierung) | ``DT`` (digitale Technologien)."""

    bereich: str | None
    """``None`` for the area-free form -- inventing an area would assert a
    scoping the regulation does not make (PRIM.D / PRIM.SU ``stufe``-bound
    items). Existing callers that only ever saw the area-bearing form keep
    working unchanged: this stays a plain string for every ID parsed before
    E-P3, since only the new 7-segment form ever produces ``None`` here."""

    stufe: str
    lfd: int
    raw: str


ParsedId = Union[KompetenzId, AnwendungsitemId]


def _stufe_passt_zu_band(band: str, stufe: str) -> bool:
    return stufe.startswith(STUFEN_PRAEFIX[band])


def parse_id(s: str) -> ParsedId:
    """Parse *s* against all three frozen grammars.

    Tries the competence form, then the area-bearing application-item form,
    then the area-free application-item form (E-P3, ``bereich=None``,
    ``bindung: "stufe"`` items). Raises :class:`IdSchemaError` if none of the
    three regexes matches, or if the ``stufe`` prefix does not agree with
    ``band`` (e.g. ``SEK1`` with a ``SCH`` stufe) -- a case the independent
    regex alternations cannot rule out by construction.

    The competence form and the area-free application-item form are both
    7-segment, but never both match the same string: a ``Bereich`` segment
    can never equal the literal ``AB``/``DT`` (reserved for ``Art``, see
    ``BEREICH_CODE_RE``), and the area-free form requires exactly that
    literal in the corresponding position. See
    ``test_id_forms_never_both_match`` for the explicit collision-freedom
    check.
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

    m = ANWENDUNGSITEM_AREA_FREI_ID_RE.match(s)
    if m:
        band, stufe = m.group("band"), m.group("stufe")
        if not _stufe_passt_zu_band(band, stufe):
            raise IdSchemaError(f"{s!r}: stufe {stufe!r} does not match band {band!r}")
        return AnwendungsitemId(
            band=band,
            fach=m.group("fach"),
            art=m.group("art"),
            bereich=None,
            stufe=stufe,
            lfd=int(m.group("lfd")),
            raw=s,
        )

    raise IdSchemaError(
        f"{s!r} matches neither the competence, the application-item, "
        "nor the area-free application-item grammar"
    )


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


def format_item_id(
    band: str, fach: str, art: str, bereich: str | None, stufe: str, lfd: int
) -> str:
    """Build an application-item ID, ``art`` in ``{AB, DT}``.

    ``bereich`` a string builds the 8-segment area-bearing form:
    ``AT.LP23.<Band>.<Fach>.<Art>.<Bereich>.<Stufe>.<lfd>``.

    ``bereich=None`` builds the 7-segment area-free form (E-P3):
    ``AT.LP23.<Band>.<Fach>.<Art>.<Stufe>.<lfd>`` -- for
    ``anwendungsbereiche_bindung: "stufe"`` items (PRIM.D, PRIM.SU), which
    attach to a whole school year and no area at all.
    """
    if art not in ("AB", "DT"):
        raise IdSchemaError(f"art must be 'AB' or 'DT', got {art!r}")
    if fach not in FAECHER:
        raise IdSchemaError(f"unknown fach {fach!r}")
    if band not in BAENDER:
        raise IdSchemaError(f"unknown band {band!r}")
    if stufe not in stufen_werte(band):
        raise IdSchemaError(f"stufe {stufe!r} not valid for band {band!r}")
    if not (0 <= lfd <= 99):
        raise IdSchemaError(f"lfd {lfd!r} out of range 0..99")
    if bereich is None:
        ident = f"AT.LP23.{band}.{fach}.{art}.{stufe}.{lfd:02d}"
    else:
        if not BEREICH_CODE_RE.match(bereich):
            raise IdSchemaError(f"bereich {bereich!r} does not look like a valid area code")
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
