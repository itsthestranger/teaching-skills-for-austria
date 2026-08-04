#!/usr/bin/env python3
"""ID scheme for ``AT.BIST`` Bildungsstandards descriptor identifiers.

**Proposed 2026-08-04 (E8-01/E8-02) -- pending the same kind of orchestrator
review the AT.LP23 scheme received (see notes/id-schema.md).** This is a
*new*, separate namespace: it does not touch, extend or reuse
``data-pipeline/schema/id_schema.py``, whose ``AT.LP23`` grammar stays frozen
exactly as documented there. Bildungsstandards (BiSt, BGBl. II Nr. 1/2009,
Anl. 1, NOR40255561) is a different regulation with a different shape --
single-grade outcome checkpoints (4. and 8. Schulstufe), not a four-year
curriculum grid -- so it gets its own six-segment grammar rather than being
forced into the seven/eight-segment Lehrplan one.

Grammar::

    Deskriptor: AT.BIST.<Fach>.<Programmstufe>.<Bereich>.<lfd>   (6 segments)

    Fach          = D | M | E                          (no SU -- BiSt has no
                    Sachunterricht chapter, measured against the live XML;
                    see E8-04)
    Programmstufe = SCH4 | SCH8                         (the absolute
                    Schulstufe the checkpoint targets -- BiSt's own text
                    calls *both* checkpoints "Schulstufe" verbatim, unlike
                    the Lehrplan's per-band Klasse/Schulstufe split, so this
                    deliberately does *not* reuse AT.LP23's K1..K4/SCH1..SCH4
                    relative-year semantics)
    Bereich       = subject x grade specific competence-area code, see
                    BEREICH_CODES -- own table, not id_schema.AREA_CODES
    lfd           = two digits, zero-padded, scoped per
                    (Fach, Programmstufe, Bereich)

Examples::

    AT.BIST.D.SCH4.HOERENSPRECHEN.01
    AT.BIST.M.SCH8.DARSTELLENZAHLEN.03      # Handlungsbereich x Inhaltsbereich
    AT.BIST.E.SCH8.HOEREN.01

stdlib only. See ``notes/id-schema.md`` §... (BiSt addendum, to be added by
the orchestrator) and ``parse_bildungsstandards.py`` for the extraction that
produced ``BEREICH_CODES``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --------------------------------------------------------------------------
# Subjects and Programmstufen
# --------------------------------------------------------------------------

#: BiSt covers exactly three subjects -- measured against the live XML
#: (NOR40255561, 393 elements): only "Deutsch", "Mathematik" and
#: "(Erste) Lebende Fremdsprache (Englisch)" headings occur. There is no
#: Sachunterricht chapter (E8-04 ships the defined-empty result for it).
FAECHER: tuple[str, ...] = ("D", "M", "E")

#: The two BiSt checkpoints in scope, keyed by their source "N. Teil"
#: heading. Both are literally called "Schulstufe" in the source text (see
#: module docstring) -- SCH4 = 4. Schulstufe der Volksschule (1. Teil),
#: SCH8 = 8. Schulstufe der Volksschuloberstufe/Mittelschule/AHS (2. Teil).
PROGRAMMSTUFEN: tuple[str, ...] = ("SCH4", "SCH8")

TEIL_ZU_PROGRAMMSTUFE: dict[str, str] = {
    "1. Teil": "SCH4",
    "2. Teil": "SCH8",
}

#: The five shards in scope (FINDINGS.md V-13): D4, M4, D8, E8, M8.
#: ``E`` never occurs under SCH4 (no living-foreign-language BiSt checkpoint
#: at the end of primary) -- measured, not assumed: the 1. Teil span
#: (children 27-227) contains exactly two Abschnitte, Deutsch and
#: Mathematik, no third.
FACH_PROGRAMMSTUFE: dict[str, tuple[str, ...]] = {
    "SCH4": ("D", "M"),
    "SCH8": ("D", "E", "M"),
}


def ist_gueltige_kombination(fach: str, programmstufe: str) -> bool:
    """Whether *fach* x *programmstufe* is one of the five shards in scope."""
    return fach in FACH_PROGRAMMSTUFE.get(programmstufe, ())


def shard_name(fach: str, programmstufe: str) -> str:
    """``"D4"``/``"M4"``/``"D8"``/``"E8"``/``"M8"`` -- the plan/FINDINGS shorthand."""
    grade = programmstufe.removeprefix("SCH")
    return f"{fach}{grade}"


# --------------------------------------------------------------------------
# Competence-area code table -- own namespace, not id_schema.AREA_CODES
# --------------------------------------------------------------------------
#
# Extracted 2026-08-04 by reading every ``Kompetenzbereich:``/
# ``Handlungsbereich ... Inhaltsbereich ...`` heading directly out of the
# live NOR40255561.xml (measured, not projected -- see parse_bildungsstandards.py
# and the E8-01 report). Codes are unique *within* one Fach.Programmstufe
# entry; cross-shard reuse (e.g. "LESEN" in D4/D8/E8) is deliberate and
# harmless, exactly the AT.LP23 precedent (id-schema.md §3).
#
# M.SCH8 is two-dimensional: the BiSt Mathematik-8 Kompetenzmodell crosses
# 4 Handlungsbereiche (Darstellen/Modellbilden, Rechnen/Operieren,
# Interpretieren, Argumentieren/Begruenden) with 4 Inhaltsbereiche (Zahlen
# und Masse, Variable/funktionale Abhaengigkeiten, Geometrische Figuren und
# Koerper, Statistische Darstellungen und Kenngroessen) -- 16 combinations,
# each its own "Kompetenzbereich"-equivalent heading in the source. The code
# concatenates a short Handlungsbereich stem with a short Inhaltsbereich
# stem so the two axes stay legible in the ID.

BEREICH_CODES: dict[str, dict[str, str]] = {
    "D.SCH4": {
        "Hören, Sprechen und miteinander Reden": "HOERENSPRECHEN",
        "Lesen – Umgang mit Texten und Medien": "LESEN",
        "Verfassen von Texten": "VERFASSEN",
        "Rechtschreiben": "RECHTSCHREIBEN",
        "Einsicht in Sprache durch Sprachbetrachtung": "SPRACHBETRACHTUNG",
    },
    "M.SCH4": {
        "Modellieren": "MODELLIEREN",
        "Operieren": "OPERIEREN",
        "Kommunizieren": "KOMMUNIZIEREN",
        "Problemlösen": "PROBLEMLOESEN",
        "Arbeiten mit Zahlen": "ZAHLEN",
        "Arbeiten mit Operationen": "OPERATIONEN",
        "Arbeiten mit Größen": "GROESSEN",
        "Arbeiten mit Ebene und Raum": "EBENERAUM",
    },
    "D.SCH8": {
        "Zuhören und Sprechen": "ZUHOERENSPRECHEN",
        "Lesen": "LESEN",
        "Schreiben": "SCHREIBEN",
        "Sprachbewusstsein": "SPRACHBEWUSSTSEIN",
    },
    "E.SCH8": {
        "Hören": "HOEREN",
        "Lesen": "LESEN",
        "An Gesprächen Teilnehmen": "GESPRAECHE",
        "Zusammenhängend Sprechen": "SPRECHEN",
        "Schreiben": "SCHREIBEN",
    },
}

#: M.SCH8's two independent axes, coded separately (see module docstring).
#: Keys are the canonical Handlungsbereich/Inhaltsbereich label extracted by
#: ``parse_bildungsstandards.HANDLUNGSBEREICH_RE`` (glitch-tolerant: the live
#: heading text is inconsistent about the colon after "Handlungsbereich" and
#: one heading is missing its closing guillemet -- both are source quirks,
#: preserved verbatim in the record's ``bereich_ueberschrift_roh``, and kept
#: out of the code-minting path so a typo in the RIS text can never change a
#: minted ID).
HANDLUNGSBEREICH_CODES: dict[str, str] = {
    "Darstellen, Modellbilden": "DARSTELLEN",
    "Rechnen, Operieren": "RECHNEN",
    "Interpretieren": "INTERPRETIEREN",
    "Argumentieren, Begründen": "ARGUMENTIEREN",
}

INHALTSBEREICH_CODES: dict[str, str] = {
    "Zahlen und Maße": "ZAHLEN",
    "Variable, funktionale Abhängigkeiten": "VARIABLE",
    "Geometrische Figuren und Körper": "FIGUREN",
    "Statistische Darstellungen und Kenngrößen": "STATISTIK",
}


def m_sch8_bereich_code(handlungsbereich: str, inhaltsbereich: str) -> str:
    """Mint the combined M.SCH8 area code from its two axis labels.

    Raises :class:`KeyError` (via the underlying dict lookups) if either
    label is not one of the four measured axis values -- a genuinely new
    Handlungsbereich/Inhaltsbereich is a real surprise, not tolerated
    silently, since it would need a new table entry.
    """
    return HANDLUNGSBEREICH_CODES[handlungsbereich] + INHALTSBEREICH_CODES[inhaltsbereich]


def bereich_codes(fach: str, programmstufe: str) -> dict[str, str]:
    """Area name -> area code table for one fach x programmstufe shard."""
    schluessel = f"{fach}.{programmstufe}"
    if schluessel not in BEREICH_CODES:
        raise KeyError(f"no area-code table for {schluessel!r} -- not one of the five BiSt shards")
    return BEREICH_CODES[schluessel]


# --------------------------------------------------------------------------
# Regex / grammar
# --------------------------------------------------------------------------

_FACH_ALT = "|".join(FAECHER)
_PROGRAMMSTUFE_ALT = "|".join(PROGRAMMSTUFEN)

#: One Bereich (area code) segment: ASCII uppercase letters/digits, starting
#: with a letter. No reserved literals here (unlike AT.LP23's AB/DT) --
#: BiSt has no application-item concept, so there is only one ID form and
#: no disambiguation hazard.
BEREICH_CODE_RE = re.compile(r"^[A-Z][A-Z0-9]{0,29}$")

#: Deskriptor ID -- 6 segments:
#: AT.BIST.<Fach>.<Programmstufe>.<Bereich>.<lfd>
DESKRIPTOR_ID_RE = re.compile(
    rf"^AT\.BIST\.(?P<fach>{_FACH_ALT})\.(?P<programmstufe>{_PROGRAMMSTUFE_ALT})\."
    rf"(?P<bereich>[A-Z][A-Z0-9]{{0,29}})\.(?P<lfd>\d{{2}})$"
)


class BistIdSchemaError(ValueError):
    """An ID does not conform to the AT.BIST grammar."""


@dataclass(frozen=True)
class DeskriptorId:
    """A parsed 6-segment AT.BIST descriptor ID."""

    fach: str
    programmstufe: str
    bereich: str
    lfd: int
    raw: str


def parse_id(s: str) -> DeskriptorId:
    """Parse *s* against the AT.BIST grammar; raise :class:`BistIdSchemaError` on mismatch."""
    m = DESKRIPTOR_ID_RE.match(s)
    if not m:
        raise BistIdSchemaError(f"{s!r} does not match the AT.BIST descriptor grammar")
    return DeskriptorId(
        fach=m.group("fach"),
        programmstufe=m.group("programmstufe"),
        bereich=m.group("bereich"),
        lfd=int(m.group("lfd")),
        raw=s,
    )


def format_id(fach: str, programmstufe: str, bereich: str, lfd: int) -> str:
    """Build a 6-segment descriptor ID: ``AT.BIST.<Fach>.<Programmstufe>.<Bereich>.<lfd>``."""
    if fach not in FAECHER:
        raise BistIdSchemaError(f"unknown fach {fach!r}")
    if programmstufe not in PROGRAMMSTUFEN:
        raise BistIdSchemaError(f"unknown programmstufe {programmstufe!r}")
    if not BEREICH_CODE_RE.match(bereich):
        raise BistIdSchemaError(f"bereich {bereich!r} does not look like a valid area code")
    if not (0 <= lfd <= 99):
        raise BistIdSchemaError(f"lfd {lfd!r} out of range 0..99")
    ident = f"AT.BIST.{fach}.{programmstufe}.{bereich}.{lfd:02d}"
    parse_id(ident)  # self-check: constructed ID must round-trip
    return ident


# --------------------------------------------------------------------------
# Uniqueness / validation -- mirrors id_schema.validate_ids
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidationResult:
    total: int
    malformed: tuple[str, ...]
    duplicates: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.malformed and not self.duplicates

    def __bool__(self) -> bool:  # pragma: no cover - convenience only
        return self.ok


def validate_ids(ids: list[str]) -> ValidationResult:
    """Validate a collection of IDs: malformed and duplicate IDs are both hard-fail."""
    malformed: list[str] = []
    seen: set[str] = set()
    duplicates: list[str] = []
    for ident in ids:
        try:
            parse_id(ident)
        except BistIdSchemaError:
            malformed.append(ident)
            continue
        if ident in seen:
            duplicates.append(ident)
        else:
            seen.add(ident)
    return ValidationResult(total=len(ids), malformed=tuple(malformed), duplicates=tuple(duplicates))
