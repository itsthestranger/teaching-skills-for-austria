#!/usr/bin/env python3
"""Build ``plugin/data/kompetenzen/<band>/<fach>/*.json`` shard parts (E3-04).

Reads a subject via :mod:`parse_lehrplan`, transforms the parser's *flat*
result shape (``kompetenzbereiche`` / ``kompetenzen`` / ``anwendungsitems`` as
sibling lists -- see ``parse_lehrplan.result_to_dict``) into the *nested*
shard shape defined by ``schema/kompetenzen.schema.json``, and writes it as
one file **per Kompetenzbereich**, plus a ``zusatz.json`` and an
``index.json`` (layout below). This split superseded a single monolithic
``<fach>.json`` file -- see the dated row in ``notes/deviations.md`` for why.

The transformation (plan section 4.9, amended by FINDINGS.md / deviations.md
where the source disagreed):

* Each :class:`~parse_lehrplan.Kompetenz` nests under its
  :class:`~parse_lehrplan.Kompetenzbereich` (matched by ``bereich_nummer``).
  The 2 GZ-integrative competences (``bereich_nummer is None``, FINDINGS
  V-57) route to ``zusatz.json``'s ``zusatzkompetenzen[]`` instead --
  ``kompetenzbereiche`` always stays exactly the official area count (4 for
  Sek I Mathematik).
* Each application item with ``art == "praezisierung"`` nests under the
  competence its ``kompetenz_id`` points at. Every item with
  ``art == "digitale_technologien"`` (``kompetenz_id`` is always ``None``,
  FINDINGS V-54) routes to ``zusatz.json``'s
  ``digitale_technologien_vorschlaege[]`` instead -- these precisify no
  competence and must never be attributed to one (E2-19).
* ``verbindlich`` (the ``allenfalls`` flag) and ``vorlaeufer``/``folge``/
  ``wiederholung_von`` (the progression backlinks) are carried through
  unchanged.
* **Verbatim text is sacred.** ``text``/``text_roh`` are copied straight
  through from the parser -- no normalisation, re-encoding, ASCII-folding or
  stripping. See ``tests/test_build_dataset.py`` for the byte-equality guard.

Record slimming (plan section 6.7 / B1 context-loading budget)
----------------------------------------------------------------
A ``SKILL.md`` loads a shard file **directly into context** (plan section 5,
B1). At ~65k approx. tokens the single-file shard was unusable for that
purpose. Three lossless slimming rules apply to every record:

1. **``text_roh`` is omitted when it is byte-identical to ``text``**
   (measured: 248 of 279 Sek I Mathematik records). *An absent ``text_roh``
   means "identical to ``text``" -- this is a contract consumers must be
   able to rely on, not just an implementation detail.* Only the 31 records
   where footnote digits are actually inlined (``text_roh`` differs from
   ``text``) carry the field.
2. **``band``, ``fach``, ``bereich_name``, ``bereich_nummer`` are omitted**
   from records nested inside a Kompetenzbereich file -- all four are
   already implied by that file's ``meta`` block and by the record's
   position inside the file's single ``kompetenzbereiche[0]``.
   ``zusatzkompetenzen[]`` and ``digitale_technologien_vorschlaege[]``
   entries (which live in ``zusatz.json``, structurally outside any single
   Kompetenzbereich) are the exception: they keep ``bereich_name`` and
   ``bereich_nummer`` because that is the only place their area is recorded
   at all.
3. **``abbildungen[]`` entries carry only ``token``, ``datei``, ``pfad``.**
   Verified against the actual renderers
   (``plugin/skills/at-unterrichtsplanung/scripts/render_lesson_docx.py``,
   ``render_lesson_html.py``, and the shared helpers in ``lesson_common.py``
   -- ``split_abbildungen``, ``resolve_abbildung_path``,
   ``abbildung_missing_marker``, ``abbildung_alt``): those three fields are
   the only ones read at render time. Image sizing is computed from the
   theme's ``body_size`` and a fixed px/dpi ratio, never from
   ``breite_px``/``hoehe_px``; ``nor``/``quelle_url``/``sha256`` are not
   read at all. ``schema/kompetenzen.schema.json``'s ``$defs/abbildung``
   originally required all eight fields, which blocked this slimming on
   the first pass (records kept full width, see the superseded row in
   ``notes/deviations.md``); the schema now requires only
   ``["token", "datei", "pfad"]`` on the strength of the same renderer
   audit, keeping the other five as valid-but-optional properties. Those
   five now live **only** in ``plugin/data/abbildungen/registry.json``,
   keyed by filename -- :func:`build_parts` asserts, before dropping
   anything, that every ``datei`` referenced by an inline ``abbildungen``
   entry resolves in the registry with all five fields present; a gap
   there aborts the build rather than silently losing provenance.

Provenance (E3-03) is built from real metadata -- ``resources/manifest.json``
for NOR / Kundmachungsorgan / Anlage / retrieval date, and the subject's
``SubjectSpec.teil_ueberschrift`` for TEIL -- never typed-in literals. Every
part file carries the **complete** ``meta`` block (including ``provenienz``)
so it is self-contained and directly loadable on its own -- that is the
point of the split. Records themselves stay provenance-free by default
(``--provenienz-modus meta``, recommended -- see the E3-03 measurement in
the build report) since every record in one shard shares identical
provenance; ``--provenienz-modus je_datensatz`` still stamps every record
for the case a future record genuinely diverges.

Shard layout
------------
::

    plugin/data/kompetenzen/<band>/<fach>/<bereich-slug-lowercase>.json
    plugin/data/kompetenzen/<band>/<fach>/zusatz.json
    plugin/data/kompetenzen/<band>/<fach>/index.json

CLI mirrors ``parse_lehrplan.py``'s conventions (``--spec``, ``--out``,
``--verify``, ``--summary``) rather than inventing new ones. ``--single-file``
combines every part back into one in-memory document for validation --
requires an explicit ``--out`` and never replaces the shipped split files.

Usage
-----
    python3 build_dataset.py --spec SEK1.M
    python3 build_dataset.py --spec SEK1.M --summary
    python3 build_dataset.py --spec SEK1.M --verify
    python3 build_dataset.py --spec SEK1.M --report build_report.txt
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Iterator, Sequence

import parse_lehrplan as PL

HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parent / "plugin"
DEFAULT_MANIFEST = HERE / "resources" / "manifest.json"
ABBILDUNGEN_REGISTRY_PATH = PLUGIN_ROOT / "data" / "abbildungen" / "registry.json"

LOG = logging.getLogger("build_dataset")

#: Band -> the key this band's regulation is filed under in manifest.json.
BAND_MANIFEST_KEY: dict[str, str] = {
    "SEK1": "mittelschule",
    "PRIM": "volksschule",
}

def default_source(spec_key: str) -> Path | None:
    """Default RIS XML source for *spec_key*, or ``None`` if unregistered.

    Delegates to :func:`parse_lehrplan.default_source` rather than keeping a
    second band->document table here (E12-13): two tables would be two things
    to keep in step, and the parser's is the one the parser CLI already uses.
    """
    if spec_key not in PL.SUBJECT_SPECS:
        return None
    return PL.default_source(spec_key)

#: Differentiation axis per <band>.<fach>. **From the regulation, not plan
#: section 4.7** (V-61, E12-11): the plan assigned `gers` to "the language
#: subjects" and `standard_standardplus` to mathematics alone. NOR40271471 says
#: otherwise, verbatim:
#:
#:   "In den differenzierten Pflichtgegenständen Deutsch, Mathematik und Lebende
#:    Fremdsprache erfolgt ab der 6. Schulstufe eine Unterscheidung nach den zwei
#:    Leistungsniveaus "Standard" und "Standard AHS"."
#:
#: So all three Sek I subjects carry `standard_standardplus`, and it applies from
#: the 6. Schulstufe -- K2..K4, never K1, hence `gilt_ab_stufe`. CEFR is an
#: *additional* axis for SEK1.E, not a replacement. Primary subjects have no such
#: axis in the source and take the generic curriculum axis explicitly, rather
#: than by falling through to a warned fallback.
_SEK1_LEISTUNGSNIVEAUS: dict = {
    "typ": "standard_standardplus",
    "niveaus": ["Standard", "Standard AHS"],
    "gilt_ab_stufe": "K2",
}

DIFFERENZIERUNGS_ACHSEN: dict[str, dict] = {
    "SEK1.M": {
        **_SEK1_LEISTUNGSNIVEAUS,
        "enrichment_quelle": "allenfalls",
        "spiralprinzip_backlinks": True,
    },
    "SEK1.D": dict(_SEK1_LEISTUNGSNIVEAUS),
    "SEK1.E": {
        **_SEK1_LEISTUNGSNIVEAUS,
        # The CEFR sub-axis. `niveaus` here is the subject-level statement the
        # regulation makes outright ("orientiert sich an den ... Kompetenzniveaus
        # A1 und A2 sowie an ausgewählten Deskriptoren des Kompetenzniveaus B1"),
        # measured 2026-08-02.
        #
        # It is deliberately NOT a per-class-year mapping. The source does state
        # a target level per class year in prose ("In allen vier
        # Kompetenzbereichen wird das Zielniveau A2+ angestrebt"), with values
        # A1/A2, A2, A2+ and "A2+ mit ausgewählten Deskriptoren aus B1" -- but
        # nothing extracts those paragraphs yet, and inventing the year->level
        # assignment here would assert an attribution the dataset cannot support.
        # That extraction is V-41 / E8.
        "gers": {
            "typ": "gers",
            "referenzrahmen": "Gemeinsamer Europäischer Referenzrahmen (GeR)",
            "niveaus": ["A1", "A2", "B1"],
            "je_stufe_ausgewiesen": False,
        },
    },
    "PRIM.D": {},   # filled from GENERISCHE_ACHSE below
    "PRIM.M": {},
    "PRIM.SU": {},
}

#: Which shards have a Bildungsstandard verordnet at all, so
#: `finde_bildungsstandard_bezug` reads a data fact instead of hardcoding the
#: Sachunterricht exception (E4-05). **Measured 2026-08-02** against
#: `resources/bildungsstandards/NOR40255561.xml`: "Sachunterricht" occurs **0**
#: times in the whole regulation, while Deutsch, Mathematik and (Erste) Lebende
#: Fremdsprache / Englisch all appear (V-13: D4/M4/D8/M8/E8).
BILDUNGSSTANDARD_BEZUG: dict[str, str] = {
    "SEK1.M": "verordnet",
    "SEK1.D": "verordnet",
    "SEK1.E": "verordnet",
    "PRIM.D": "verordnet",
    "PRIM.M": "verordnet",
    "PRIM.SU": "keine_verordnung",
}

GENERISCHE_ACHSE: dict = {
    "typ": "lehrplan_generisch",
    "niveaus": ["grundlegend", "erweitert", "vertiefend"],
    "quelle": "Kompetenzbeschreibungen + Anwendungsbereiche je Schulstufe",
    "optional_material": "docs/",
}

# The three primary shards take the generic axis by an explicit registration,
# not by falling through the unregistered-subject fallback: the source really
# has no Leistungsniveaus axis for them, which is a finding, whereas the
# fallback means "nobody has looked yet" and warns. Registering them keeps the
# warning meaningful (V-61, E12-11).
for _fach in ("PRIM.D", "PRIM.M", "PRIM.SU"):
    DIFFERENZIERUNGS_ACHSEN[_fach] = dict(GENERISCHE_ACHSE)
del _fach

#: Measured on NOR40271471, Sek I Mathematik (mirrors parse_lehrplan.py's
#: ERWARTET_SEK1_M, expressed in the shard's own vocabulary for --verify).
ERWARTET_SEK1_M: dict[str, int] = {
    "kompetenzbereiche": 4,
    "kompetenzen_gesamt": 42,
    "kompetenzen_in_bereichen": 40,
    "zusatzkompetenzen": 2,
    "anwendungsitems_gesamt": 237,
    "praezisierung": 198,
    "digitale_technologien": 39,
    "allenfalls": 32,
    "wiederholen_und_festigen": 16,
}

#: Expected build counts per shard, in the build's own vocabulary (E12-13).
#: **Measured 2026-08-02** against both live documents, and reproduced exactly
#: from the committed fixtures in `tests/fixtures/` -- the two agree for all six
#: shards on every key, so a fresh clone verifies the same numbers as a run
#: against `resources/`.
#:
#: Reading the shape: `kompetenzen_gesamt` = `kompetenzen_in_bereichen` +
#: `zusatzkompetenzen`, and the 2 zusatzkompetenzen are SEK1.M's GZ-integrative
#: pair (V-57) -- every other shard has 0, because "zusatzkompetenz" means
#: "belongs to no official Kompetenzbereich" (V-59/E12-09), not "has no area
#: number". `allenfalls` and `wiederholen_und_festigen` are 0 outside SEK1.M by
#: construction: both markers are SEK1.M-only (measured), and
#: `SubjectSpec.allenfalls_pruefen` is False elsewhere. `digitale_technologien`
#: is 0 outside SEK1.M for the same reason (V-54/V-64) -- so `praezisierung`
#: equals `anwendungsitems_gesamt` there.
ERWARTET_BUILD: dict[str, dict[str, int]] = {
    "SEK1.M": ERWARTET_SEK1_M,
    "SEK1.D": {
        "kompetenzbereiche": 4, "kompetenzen_gesamt": 40, "kompetenzen_in_bereichen": 40,
        "zusatzkompetenzen": 0, "anwendungsitems_gesamt": 54, "praezisierung": 54,
        "digitale_technologien": 0, "allenfalls": 0, "wiederholen_und_festigen": 0,
    },
    "SEK1.E": {
        "kompetenzbereiche": 4, "kompetenzen_gesamt": 37, "kompetenzen_in_bereichen": 37,
        "zusatzkompetenzen": 0, "anwendungsitems_gesamt": 0, "praezisierung": 0,
        "digitale_technologien": 0, "allenfalls": 0, "wiederholen_und_festigen": 0,
    },
    "PRIM.D": {
        "kompetenzbereiche": 4, "kompetenzen_gesamt": 40, "kompetenzen_in_bereichen": 40,
        "zusatzkompetenzen": 0, "anwendungsitems_gesamt": 37, "praezisierung": 37,
        "digitale_technologien": 0, "allenfalls": 0, "wiederholen_und_festigen": 0,
    },
    "PRIM.M": {
        "kompetenzbereiche": 4, "kompetenzen_gesamt": 40, "kompetenzen_in_bereichen": 40,
        "zusatzkompetenzen": 0, "anwendungsitems_gesamt": 0, "praezisierung": 0,
        "digitale_technologien": 0, "allenfalls": 0, "wiederholen_und_festigen": 0,
    },
    "PRIM.SU": {
        "kompetenzbereiche": 6, "kompetenzen_gesamt": 48, "kompetenzen_in_bereichen": 48,
        "zusatzkompetenzen": 0, "anwendungsitems_gesamt": 40, "praezisierung": 40,
        "digitale_technologien": 0, "allenfalls": 0, "wiederholen_und_festigen": 0,
    },
}

#: §6.7 soft targets, checked per **part** file now that the shard is split
#: (each part must be independently loadable). Exceeding these is a
#: *review* trigger, never a build failure (E3-07).
SHARD_BYTES_ZIEL = 50_000
SHARD_TOKENS_ZIEL = 15_000


class BuildError(Exception):
    """A build precondition failed (bad manifest, unknown spec, ...)."""


# --------------------------------------------------------------------------
# Manifest / provenance (E3-03)
# --------------------------------------------------------------------------


def load_manifest(path: Path) -> dict:
    if not path.exists():
        raise BuildError(f"manifest not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def build_provenienz(spec: PL.SubjectSpec, manifest: dict) -> dict:
    """Build the provenance block from real manifest metadata (E3-03).

    NOR, Kundmachungsorgan, Anlage and retrieval date come from
    ``resources/manifest.json``; TEIL comes from the SubjectSpec. Nothing
    here is a typed-in literal.
    """
    schluessel = BAND_MANIFEST_KEY.get(spec.band)
    if schluessel is None or schluessel not in manifest:
        raise BuildError(f"no manifest entry for band {spec.band!r} (key {schluessel!r})")
    eintrag = manifest[schluessel]
    # The live Kundmachungsorgan value carries trailing whitespace (an
    # artefact of manifest generation, not part of the citation's official
    # wording) -- stripped here; see notes/deviations.md for the row
    # recording this and the plan's abbreviated "idF" form not matching the
    # live "zuletzt geändert durch" wording (source wins).
    kundmachung = eintrag["kundmachungsorgan"].strip()
    return {
        "quelle": "RIS Bundesrecht konsolidiert",
        "kurztitel": eintrag["kurztitel"],
        "nor": eintrag["nor"],
        "kundmachung": kundmachung,
        "anlage": eintrag["artikel_paragraph_anlage"],
        "teil": spec.teil_ueberschrift or "",
        "stand": eintrag["retrieval_date"],
    }


# --------------------------------------------------------------------------
# Abbildungen registry (moved out of individual records -- see module
# docstring point 3). Keyed by bare filename ("datei").
# --------------------------------------------------------------------------


#: The five fields moved out of inline abbildungen entries and into
#: registry.json -- provenance and dimensions, nothing a renderer reads.
ABBILDUNG_REGISTRY_FELDER = ("nor", "quelle_url", "breite_px", "hoehe_px", "sha256")


def _abbildungen_slim(abbildungen: list[dict]) -> list[dict]:
    """Slim ``abbildungen[]`` entries to exactly what a renderer reads at
    render time: ``token`` (matches the ⟦ABB:...⟧ token in text), ``pfad``
    (resolved to an absolute path), ``datei`` (fallback label for a
    missing-image marker / alt text). Verified against
    render_lesson_docx.py / render_lesson_html.py / lesson_common.py.
    ``schema/kompetenzen.schema.json``'s ``$defs/abbildung`` now requires
    only these three; the other five (``nor``, ``quelle_url``,
    ``breite_px``, ``hoehe_px``, ``sha256``) live in
    ``plugin/data/abbildungen/registry.json`` instead -- see
    :func:`assert_abbildungen_registry_complete`, which must run and pass
    before this function is ever called on real data."""
    return [{"token": a["token"], "datei": a["datei"], "pfad": a["pfad"]} for a in abbildungen]


def collect_abbildungen_registry_eintraege(result: PL.ParseResult) -> dict[str, dict]:
    """Every distinct image referenced by *result*, keyed by filename, with
    exactly the fields dropped from the inline record: ``nor``,
    ``quelle_url``, ``breite_px``, ``hoehe_px``, ``sha256``."""
    eintraege: dict[str, dict] = {}
    quellen = list(result.kompetenzen) + list(result.anwendungsitems)
    for q in quellen:
        for a in q.abbildungen:
            eintraege.setdefault(
                a["datei"],
                {
                    "nor": a["nor"],
                    "quelle_url": a["quelle_url"],
                    "breite_px": a["breite_px"],
                    "hoehe_px": a["hoehe_px"],
                    "sha256": a["sha256"],
                },
            )
    return eintraege


def load_or_build_abbildungen_registry(
    result: PL.ParseResult, path: Path = ABBILDUNGEN_REGISTRY_PATH
) -> dict[str, dict]:
    """The registry that *would* be written for *result*: whatever is
    already on disk at *path*, merged with every image *result* references,
    sorted by filename. Does not write anything -- see
    :func:`persist_abbildungen_registry`. Kept as a separate step so
    :func:`assert_abbildungen_registry_complete` can check completeness
    against the exact dict that is about to be persisted, before any
    record is slimmed."""
    bestehend: dict[str, dict] = {}
    if path.exists():
        bestehend = json.loads(path.read_text(encoding="utf-8"))
    bestehend.update(collect_abbildungen_registry_eintraege(result))
    return dict(sorted(bestehend.items()))


def persist_abbildungen_registry(registry: dict[str, dict], path: Path = ABBILDUNGEN_REGISTRY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_abbildungen_registry(
    result: PL.ParseResult, path: Path = ABBILDUNGEN_REGISTRY_PATH
) -> dict[str, dict]:
    """Merge *result*'s images into ``plugin/data/abbildungen/registry.json``
    and write it back, sorted by filename. Merges rather than overwrites so
    building one shard never drops another shard's already-registered
    images. Convenience wrapper combining :func:`load_or_build_abbildungen_registry`
    and :func:`persist_abbildungen_registry`."""
    registry = load_or_build_abbildungen_registry(result, path)
    persist_abbildungen_registry(registry, path)
    return registry


def assert_abbildungen_registry_complete(result: PL.ParseResult, registry: dict[str, dict]) -> None:
    """Hard-fail guard: before any inline ``abbildungen`` entry is slimmed
    down to ``token``/``datei``/``pfad``, every ``datei`` it references
    must resolve in *registry* with all five moved fields present.
    Dropping provenance the registry doesn't have would be data loss, not
    slimming -- this raises :class:`BuildError` (aborting the build) rather
    than silently shipping an incomplete registry."""
    quellen = list(result.kompetenzen) + list(result.anwendungsitems)
    for q in quellen:
        for a in q.abbildungen:
            datei = a["datei"]
            eintrag = registry.get(datei)
            if eintrag is None:
                raise BuildError(
                    f"abbildung {datei!r} (referenced by {q.id}) is not registered in "
                    f"{ABBILDUNGEN_REGISTRY_PATH} -- refusing to slim its inline entry "
                    f"(would be provenance data loss)"
                )
            fehlend = [feld for feld in ABBILDUNG_REGISTRY_FELDER if not eintrag.get(feld)]
            if fehlend:
                raise BuildError(
                    f"registry entry for {datei!r} is missing {fehlend!r} -- refusing to slim "
                    f"its inline entry (would be provenance data loss)"
                )


# --------------------------------------------------------------------------
# Record transforms (flat parser shape -> slim nested shard records)
# --------------------------------------------------------------------------


def _kompetenz_zu_dict(
    k: PL.Kompetenz,
    anwendungsbereiche: list[dict],
    provenienz: dict,
    modus: str,
    *,
    ist_zusatz: bool,
    kompetenz_gebundene_items: bool,
) -> dict:
    """One Kompetenz record, slimmed. Verbatim text copied straight through.

    *ist_zusatz* is decided by the caller on **area identity** and passed in,
    not re-derived here from ``bereich_nummer is None`` (V-59, E12-09): only
    SEK1.M numbers its areas, so that test would mark every competence of the
    other five shards as a zusatzkompetenz and write a null ``bereich_nummer``
    onto all of them.
    """
    d: dict = {"id": k.id}
    if ist_zusatz:
        # zusatzkompetenzen[] lives in zusatz.json, outside any single
        # Kompetenzbereich file -- this is the only place its area survives.
        d["bereich_nummer"] = k.bereich_nummer
        d["bereich_name"] = k.bereich_name
    d["stufe"] = k.stufe
    d["ordinal"] = k.ordinal
    # The competence stem, verbatim (E12-06 captures it; E12-11 ships it). It is
    # never prepended to `text`: a faithful quotation is stammsatz + text, and
    # fusing them would make the two indistinguishable. Omitting it entirely is
    # what made SEK1.E's CEFR performance conditions vanish from the product
    # (V-58) -- the whole point of capturing it was that it reaches a shard.
    if k.stammsatz:
        d["stammsatz"] = k.stammsatz
    d["text"] = k.text
    if k.text_roh != k.text:
        d["text_roh"] = k.text_roh
    d["uebergreifende_themen"] = list(k.uebergreifende_themen)
    d["themen_marker_roh"] = list(k.themen_marker_roh)
    d["fussnoten_unaufgeloest"] = list(k.fussnoten_unaufgeloest)
    d["vorlaeufer"] = list(k.vorlaeufer)
    d["folge"] = list(k.folge)
    d["abbildungen"] = _abbildungen_slim(k.abbildungen)
    # A competence nested under an official Kompetenzbereich always carries
    # the key (possibly empty) -- the source *has* an Anwendungsbereiche
    # section for it. A zusatzkompetenz (GZINTEGRATIV) has no such section
    # in the source at all (FINDINGS V-57 / deviations.md) and omits the
    # key entirely unless items were nevertheless joined to it.
    #
    # Under the coarse binding axes the key is omitted outright unless items
    # really were joined: the source attaches those items to an area or a
    # school year (they live in meta.anwendungsbereiche_bloecke), so an empty
    # per-competence array would imply the regulation looked for items for
    # *this* competence and found none -- an attribution it never makes.
    if anwendungsbereiche or (kompetenz_gebundene_items and not ist_zusatz):
        d["anwendungsbereiche"] = anwendungsbereiche
    if modus == "je_datensatz":
        d["provenienz"] = provenienz
    return d


def _anwendungsitem_zu_dict(
    a: PL.Anwendungsitem, provenienz: dict, modus: str, *, mit_bereich_attribution: bool
) -> dict:
    """One Anwendungsitem record, slimmed (precisification or
    digitale_technologien). ``mit_bereich_attribution`` is True exactly for
    items routed to zusatz.json (digitale_technologien), which -- like
    zusatzkompetenzen -- have nowhere else to record their area."""
    d: dict = {"id": a.id}
    if mit_bereich_attribution:
        d["bereich_nummer"] = a.bereich_nummer
        d["bereich_name"] = a.bereich_name
    d["stufe"] = a.stufe
    d["ordinal"] = a.ordinal
    d["text"] = a.text
    if a.text_roh != a.text:
        d["text_roh"] = a.text_roh
    if a.uebergreifende_themen:
        d["uebergreifende_themen"] = list(a.uebergreifende_themen)
    if a.themen_marker_roh:
        d["themen_marker_roh"] = list(a.themen_marker_roh)
    if a.fussnoten_unaufgeloest:
        d["fussnoten_unaufgeloest"] = list(a.fussnoten_unaufgeloest)
    d["verbindlich"] = a.verbindlich
    d["art"] = a.art
    d["kompetenz_id"] = a.kompetenz_id
    d["wiederholung_von"] = list(a.wiederholung_von)
    d["abbildungen"] = _abbildungen_slim(a.abbildungen)
    if modus == "je_datensatz":
        d["provenienz"] = provenienz
    return d


# --------------------------------------------------------------------------
# Meta block (shared verbatim across every part file)
# --------------------------------------------------------------------------


def build_meta(
    spec: PL.SubjectSpec, result: PL.ParseResult, provenienz: dict, dataset_version: str | None
) -> dict:
    meta = {
        "lehrplan_fassung": provenienz["kundmachung"],
        "dataset_version": dataset_version or provenienz["stand"],
        "band": spec.band,
        "fach": {"code": spec.fach_code, "name": result.fach_name},
        "uebergreifende_themen_fach": list(result.uebergreifende_themen_fach),
        "uebergreifende_themen_legende": dict(result.themen_map),
        "differenzierungs_achse": DIFFERENZIERUNGS_ACHSEN.get(
            f"{spec.band}.{spec.fach_code}", GENERISCHE_ACHSE
        ),
        "anwendungsbereiche_status": spec.anwendungsbereiche_status,
        # Mirrors SubjectSpec.anwendungsbereiche_bindung verbatim, so a consumer
        # can tell "the regulation offers only prose / nothing here" from "the
        # build dropped the items" without guessing from which fields happen to
        # be present (E12-11; deviations.md, 2026-07-30).
        "anwendungsbereiche_bindung": spec.anwendungsbereiche_bindung,
        "bildungsstandard_bezug": BILDUNGSSTANDARD_BEZUG.get(
            f"{spec.band}.{spec.fach_code}", "keine_verordnung"
        ),
        "lehrstoff_quelle": spec.lehrstoff_quelle,
        "provenienz": provenienz,
    }
    if f"{spec.band}.{spec.fach_code}" not in BILDUNGSSTANDARD_BEZUG:
        LOG.warning(
            "no Bildungsstandard-Bezug registered for %s.%s -- assuming keine_verordnung",
            spec.band, spec.fach_code,
        )
    if f"{spec.band}.{spec.fach_code}" not in DIFFERENZIERUNGS_ACHSEN:
        LOG.warning(
            "no plan-section-4.7 differentiation axis registered for %s.%s -- using the generic fallback",
            spec.band, spec.fach_code,
        )
    return meta


# --------------------------------------------------------------------------
# Split build: one part per Kompetenzbereich + zusatz.json + index.json
# --------------------------------------------------------------------------


#: The one area slug *expected* to fall outside ``result.bereiche`` and so route
#: to ``zusatzkompetenzen`` without a warning: the synthetic SEK1.M area that is
#: deliberately not a fifth Kompetenzbereich (FINDINGS V-57).
#:
#: Note ``ALLGEMEIN`` -- the sentinel an area-less record carries (E12-04) -- is
#: deliberately **not** listed. Measured across all six shards, no competence
#: carries it, so warning costs no noise; and a competence the parser could
#: attribute to no area is exactly the structural surprise that should stay
#: visible rather than being quietly absorbed into zusatzkompetenzen.
_ERWARTETE_ZUSATZ_SLUGS = frozenset({PL.GZ_INTEGRATIV_BEREICH_SLUG})


def _block_key(block: PL.Anwendungsblock, bindung: str, slug: str | None) -> str:
    """Key for one ``meta.anwendungsbereiche_bloecke`` entry.

    ``bindung: stufe`` -- the school year alone (``SCH1``): PRIM.D and PRIM.SU
    have exactly one block per year, so the year is already unique.

    ``bindung: bereich`` -- ``<SLUG>.<STUFE>`` (``LESEN.K1``). **Measured
    2026-08-02:** SEK1.D has 16 blocks, four per class year (one per area), so
    the plain school-year key the schema description assumed collides four ways
    the moment a document holds more than one area's blocks -- which the
    recombined document always does. The area is stated inside the entry too
    (``bereich_slug``, required by the schema for this binding), so the composite
    key is redundant-but-unique rather than load-bearing, and part files and the
    recombined document can share one shape. See notes/deviations.md.
    """
    if bindung == "bereich":
        return f"{slug}.{block.stufe}"
    return block.stufe


def build_anwendungsbereiche_bloecke(
    result: PL.ParseResult,
    spec: PL.SubjectSpec,
    provenienz: dict,
    modus: str,
    *,
    nur_bereich_slug: str | None = None,
) -> dict[str, dict]:
    """``meta.anwendungsbereiche_bloecke`` for one part file.

    Only the two *coarse* binding axes produce entries. Under
    ``bindung: kompetenz`` (SEK1.M) every item already nests under the competence
    it precisifies, and under ``prosa``/``keine`` there are no items at all --
    all three return ``{}``.

    *nur_bereich_slug* restricts the result to one area's blocks, which is what
    ``bindung: bereich`` wants: each area part file carries its own blocks and no
    others. For ``bindung: stufe`` it is ignored -- those blocks attach to the
    school year across all areas, so the **complete** set is repeated verbatim in
    every area part file (decision of 2026-07-29): a skill loading a single part
    under the plan section 5 B1 contract must see all of that year's items
    without reading a second file.
    """
    bindung = spec.anwendungsbereiche_bindung
    if bindung not in ("bereich", "stufe"):
        return {}

    slug_je_name = {b.name: b.slug for b in result.bereiche}
    bloecke: dict[str, dict] = {}
    for block in result.bloecke:
        slug = slug_je_name.get(block.bereich_name) if bindung == "bereich" else None
        if bindung == "bereich":
            if slug is None:
                # Never invent an area code: an unmapped area name would ship a
                # made-up attribution. Loud, and skipped rather than guessed.
                LOG.warning(
                    "anwendungsblock (stufe %s) has area %r with no matching Kompetenzbereich -- skipped",
                    block.stufe, block.bereich_name,
                )
                continue
            if nur_bereich_slug is not None and slug != nur_bereich_slug:
                continue
        eintrag: dict = {"bindung": bindung}
        if bindung == "bereich":
            eintrag["bereich_name"] = block.bereich_name
            eintrag["bereich_slug"] = slug
        eintrag["items"] = [
            _anwendungsitem_zu_dict(a, provenienz, modus, mit_bereich_attribution=False)
            for a in block.items
        ]
        schluessel = _block_key(block, bindung, slug)
        if schluessel in bloecke:
            LOG.warning("duplicate anwendungsbereiche_bloecke key %r -- entries merged", schluessel)
            bloecke[schluessel]["items"] += eintrag["items"]
        else:
            bloecke[schluessel] = eintrag
    return bloecke


def build_parts(
    result: PL.ParseResult,
    spec: PL.SubjectSpec,
    manifest: dict,
    registry: dict[str, dict],
    modus: str = "meta",
    dataset_version: str | None = None,
) -> dict[str, dict]:
    """Build every part file's JSON-serialisable document.

    *registry* is the (already merged, about-to-be-persisted) abbildungen
    registry -- see :func:`load_or_build_abbildungen_registry`. Checked for
    completeness via :func:`assert_abbildungen_registry_complete` before any
    inline ``abbildungen`` entry is slimmed; a gap raises :class:`BuildError`
    instead of silently dropping provenance.

    Returns ``{"<bereich-slug-lowercase>.json": {...}, "zusatz.json": {...}}``
    -- ``index.json`` is not included here (see :func:`build_index`, which
    needs the already-built parts to measure their size).
    """
    if modus not in ("meta", "je_datensatz"):
        raise BuildError(f"unknown provenienz-modus {modus!r}")

    assert_abbildungen_registry_complete(result, registry)

    provenienz = build_provenienz(spec, manifest)
    meta = build_meta(spec, result, provenienz, dataset_version)

    # --- Partition application items three ways (V-64, E12-10):
    #
    #   art == digitale_technologien -> zusatz.json, top-level (precisify
    #     nothing, E2-19).
    #   bindung == kompetenz         -> nested under the competence they
    #     precisify, via kompetenz_id.
    #   bindung bereich/stufe        -> meta.anwendungsbereiche_bloecke; the
    #     source attaches them to an area or a school year, never to one
    #     competence, so they are never pushed onto a record.
    #
    # ``art`` **alone** decides digitale_technologien. The old test also treated
    # ``kompetenz_id is None`` as digital, which is true of every item under the
    # coarse binding axes: all 54 SEK1.D + 37 PRIM.D + 40 PRIM.SU items would
    # have shipped as digital-technology suggestions, none of which carries that
    # art (V-64). Only the V-59 crash stopped it.
    items_je_kompetenz: dict[str, list[dict]] = {}
    digitale_technologien: list[dict] = []
    for a in result.anwendungsitems:
        if a.art == "digitale_technologien":
            digitale_technologien.append(
                _anwendungsitem_zu_dict(a, provenienz, modus, mit_bereich_attribution=True)
            )
        elif spec.anwendungsbereiche_bindung == "kompetenz":
            if a.kompetenz_id is None:
                # Under bindung: kompetenz an unjoined praezisierung has no
                # home at all -- surfacing it beats silently dropping it.
                LOG.warning("praezisierung %s has no kompetenz_id -- routed to zusatz.json", a.id)
                digitale_technologien.append(
                    _anwendungsitem_zu_dict(a, provenienz, modus, mit_bereich_attribution=True)
                )
            else:
                items_je_kompetenz.setdefault(a.kompetenz_id, []).append(
                    _anwendungsitem_zu_dict(a, provenienz, modus, mit_bereich_attribution=False)
                )
        # else: emitted through meta.anwendungsbereiche_bloecke below.

    # --- Kompetenzbereiche: exactly the official areas, order preserved.
    #
    # Routing keys on the area **slug**, not on bereich_nummer (V-59, E12-09):
    # only SEK1.M numbers its Kompetenzbereiche, so for the other five every
    # nummer is None and a number-keyed dict collapses all areas into one
    # bucket -- or, as it did before this change, raises KeyError(None).
    # The slug is the area's identity in every shard; it is also what the ID
    # scheme and the progression buckets already key on (E12-04).
    kompetenzen_je_bereich: dict[str, list[dict]] = {b.slug: [] for b in result.bereiche}
    bereich_infos = [(b.nummer, b.slug, b.name) for b in result.bereiche]

    zusatzkompetenzen: list[dict] = []
    for k in result.kompetenzen:
        # "zusatzkompetenz" means *belongs to no official Kompetenzbereich* --
        # not "has no area number". For SEK1.M that is still exactly the 2
        # GZ-integrative competences: they carry the synthetic GZINTEGRATIV
        # slug, which is deliberately not in result.bereiche (FINDINGS V-57),
        # so they route here on identity rather than on a null number. For the
        # other five it is 0: every competence sits under a real area.
        ziel = kompetenzen_je_bereich.get(k.bereich_slug)
        rec = _kompetenz_zu_dict(
            k, items_je_kompetenz.get(k.id, []), provenienz, modus,
            ist_zusatz=ziel is None,
            kompetenz_gebundene_items=spec.anwendungsbereiche_bindung == "kompetenz",
        )
        if ziel is None:
            if k.bereich_slug not in _ERWARTETE_ZUSATZ_SLUGS:
                # Tolerant fallback: an area slug with no matching
                # Kompetenzbereich header is a structural surprise, not a hard
                # failure -- keep the competence discoverable in
                # zusatzkompetenzen rather than silently dropping it.
                LOG.warning(
                    "kompetenz %s references unknown bereich_slug %r -- routed to zusatzkompetenzen",
                    k.id, k.bereich_slug,
                )
            zusatzkompetenzen.append(rec)
        else:
            ziel.append(rec)

    dateien: dict[str, dict] = {}
    for nummer, slug, name in bereich_infos:
        dateiname = f"{slug.lower()}.json"
        # meta is per-part, not one shared object: under bindung: bereich each
        # area file carries only its own blocks, so the meta blocks differ file
        # by file. Under bindung: stufe every file carries the same complete set.
        bloecke = build_anwendungsbereiche_bloecke(
            result, spec, provenienz, modus, nur_bereich_slug=slug
        )
        teil_meta = {**meta, "anwendungsbereiche_bloecke": bloecke} if bloecke else meta
        dateien[dateiname] = {
            "meta": teil_meta,
            "kompetenzbereiche": [
                {
                    "nummer": nummer,
                    "slug": slug,
                    "name": name,
                    "kompetenzen": kompetenzen_je_bereich[slug],
                }
            ],
        }

    # zusatz.json deliberately carries no anwendungsbereiche_bloecke: it holds no
    # Kompetenzbereich, and the B1 contract is about a skill loading an *area*
    # part. Repeating every block here would add bytes no consumer of this file
    # reads.
    dateien["zusatz.json"] = {
        "meta": meta,
        "kompetenzbereiche": [],
        "zusatzkompetenzen": zusatzkompetenzen,
        "digitale_technologien_vorschlaege": digitale_technologien,
    }
    return dateien


def combine_parts(dateien: dict[str, dict]) -> dict:
    """Recombine every part back into one in-memory document. Used by
    ``--single-file`` (validation) and by tests to assert the split
    reproduces the complete dataset exactly."""
    bereiche = []
    meta = None
    bloecke: dict[str, dict] = {}
    zusatzkompetenzen: list[dict] = []
    digitale_technologien: list[dict] = []
    for dateiname in sorted(dateien):
        doc = dateien[dateiname]
        if meta is None:
            meta = doc["meta"]
        # Merge the block containers across parts (E12-10). The two axes differ:
        # under bindung: stufe every area file repeats the *same* complete set,
        # so identical keys must collapse to one entry (else PRIM.D's 37 items
        # would recombine to 4x37); under bindung: bereich the files hold
        # *disjoint* areas, so their keys union. The composite <SLUG>.<STUFE>
        # key makes both cases the same dict update -- a plain school-year key
        # would silently overwrite three of SEK1.D's four areas per year.
        for schluessel, eintrag in doc["meta"].get("anwendungsbereiche_bloecke", {}).items():
            vorhanden = bloecke.get(schluessel)
            if vorhanden is not None and vorhanden != eintrag:
                raise BuildError(
                    f"anwendungsbereiche_bloecke key {schluessel!r} appears in more than one part "
                    f"with different content -- refusing to recombine"
                )
            bloecke[schluessel] = eintrag
        if dateiname == "zusatz.json":
            zusatzkompetenzen = doc.get("zusatzkompetenzen", [])
            digitale_technologien = doc.get("digitale_technologien_vorschlaege", [])
        else:
            bereiche.extend(doc["kompetenzbereiche"])
    # Numbered areas first, in number order (SEK1.M); unnumbered areas after,
    # in slug order. The second element must never be a bare None: for the five
    # unnumbered shards *every* nummer is None, and (True, None) < (True, None)
    # raises TypeError on the None comparison (V-59, E12-09).
    bereiche.sort(key=lambda b: (b["nummer"] is None, b["nummer"] or 0, b["slug"]))
    if bloecke:
        meta = {**meta, "anwendungsbereiche_bloecke": bloecke}
    return {
        "meta": meta,
        "kompetenzbereiche": bereiche,
        "zusatzkompetenzen": zusatzkompetenzen,
        "digitale_technologien_vorschlaege": digitale_technologien,
    }


# --------------------------------------------------------------------------
# stichwort_index (E12-12, FINDINGS V-67)
#
# V-67: index.json carried per-part counts/sizes but nothing mapping a search
# term to a part, so the plan's own worked example --
# finde_kompetenz(fach=M, stufe=K2, stichworte=["Bruch"]) -- forced loading
# every part of a shard to answer a single keyword lookup. This section adds
# a term -> part-filenames map built from the same text a shard ships (never
# from anything not already in the parts), so that lookup can resolve without
# reading a single part file.
# --------------------------------------------------------------------------

#: Word tokens: runs of Unicode letters, no digits/underscore. `re` is
#: Unicode-aware by default for `str` patterns, so this splits German words
#: (incl. umlauts/ß) correctly without a hand-rolled character class.
_WORT_RE = re.compile(r"[^\W\d_]+")

#: Minimum token length, kept deliberately short. Measured on SEK1.M
#: (mittelschule/NOR40271471.xml, all 4 area parts + zusatz.json, 818 distinct
#: tokens before this filter): every token of length <= 3 is either a German
#: function word (der, die, das, und, mit, von, aus, bei, dem, den, des, ein,
#: für, wie, ist, zur, als, ...) or a stray artifact from an unstripped
#: ⟦ABB:...⟧ marker (abb, img, png -- see the marker-stripping note below); no
#: legitimate curriculum term in that shard is <= 3 letters. 4 is the floor,
#: not e.g. 5, because it is the shortest length that still keeps "Bruch" --
#: the plan's own V-67 worked example -- indexable.
STICHWORT_MIN_LEN = 4

#: Curated German function/connector words, dropped regardless of measured
#: document frequency. STICHWORT_MAX_DATEIEN below already removes most
#: cross-part boilerplate statistically, but that is a per-shard measurement;
#: this list is a fixed backstop for a shard small enough, or a term rare
#: enough, that a function word could otherwise slip under the cap by chance.
#: Assembled from the words actually observed at document-frequency ==
#: n_parts or n_parts-1 on SEK1.M (23 and 31 terms respectively, measured
#: 2026-08-02), generalised to their other inflected forms.
STICHWORT_STOPWORDS = frozenset(
    """
    aber alle allem allen aller alles allenfalls allgemeinen also anhand
    auch bzw dabei dadurch dafür damit dass dessen deren dieser diese
    dieses diesem diesen dies doch durch eben einem einen einer eines
    einige einigen einiger etwa gegebenenfalls gegen gemäß gilt hierzu
    hierbei hinsichtlich ihre ihrem ihren ihrer immer indem insbesondere
    jede jedem jeden jeder jedes jeweils jeweilige kann können mithilfe
    muss müssen nach ohne schüler schülerinnen sich sind sofern sollen
    sowie sowohl soweit über unter unterschiedlichen unterschiedlicher
    verschiedene verschiedenen verschiedener viele vielen wenn werden
    wird wobei wodurch wurde wurden zwischen
    """.split()
)

#: A term whose postings would name more than this many part files is
#: dropped entirely -- never silently truncated to this many, which would
#: make the index claim completeness it does not have. Measured on SEK1.M (5
#: parts): 23 terms occur in literally every part and 31 more occur in 4 of
#: 5 -- both boilerplate ("schülerinnen", "können", generic verbs like
#: "berechnen"/"darstellen") that cannot route a lookup anywhere useful. The
#: effect is stronger on the two "stufe"-bound shards (PRIM.D, PRIM.SU):
#: their meta.anwendungsbereiche_bloecke are repeated verbatim in every area
#: part (decision of 2026-07-29), so without this cap 169 of PRIM.D's 480
#: distinct terms and 94 of PRIM.SU's 440 would resolve to "every area part",
#: which is not routing. 2 is chosen over 1 because 1 would also drop terms
#: that legitimately span exactly two areas -- e.g. SEK1.M's "bruch", found
#: in both daten.json and zahlen.json.
STICHWORT_MAX_DATEIEN = 2


def _stichworte_aus_text(text: str) -> Iterator[str]:
    """Yield normalised candidate index terms from one text field.

    Casefolding mirrors :func:`parse_lehrplan.normalise_for_match` (NFC, then
    ``casefold()``) -- reused rather than reinvented -- but applied per token:
    that function's dash/quote/space-folding and competence-stem stripping
    operate on whole sentences and are meaningless once text has already been
    split into single-word tokens by ``_WORT_RE``.

    ⟦ABB:<dateiname>⟧ inline image markers (parse_lehrplan.ABBILDUNG_TOKEN_RE)
    are stripped first: left in, they seed the index with junk terms from the
    embedded filename -- measured on SEK1.M/figuren.json, whose text contains
    literal ``⟦ABB:hauptdokument.img45is.png⟧`` tokens, which without this
    strip would contribute "abb"/"hauptdokument"/"img45is"/"png" as if they
    were curriculum vocabulary.
    """
    text = PL.ABBILDUNG_TOKEN_RE.sub(" ", text)
    for wort in _WORT_RE.findall(text):
        if len(wort) < STICHWORT_MIN_LEN:
            continue
        normalisiert = unicodedata.normalize("NFC", wort).casefold()
        if normalisiert in STICHWORT_STOPWORDS:
            continue
        yield normalisiert


def _stichworte_je_datei(doc: dict) -> set[str]:
    """Every candidate index term appearing anywhere in one part document.

    Walks every text field a part actually carries: competence text and
    stammsatz, their nested anwendungsbereiche (bindung=kompetenz), the
    zusatz.json zusatzkompetenzen and their nested items,
    digitale_technologien_vorschlaege, and this part's own copy of
    meta.anwendungsbereiche_bloecke (bindung=bereich/stufe). Deliberately not
    narrowed per :data:`parse_lehrplan.SubjectSpec.anwendungsbereiche_bindung`
    -- which fields are populated already varies by axis (see
    tests/test_build_six_shards.py), and STICHWORT_MAX_DATEIEN is what prunes
    the axis-specific non-discriminating case (the "stufe" blocks, identical
    in every area part) rather than a special case here.
    """
    begriffe: set[str] = set()

    def _sammle(text: str) -> None:
        begriffe.update(_stichworte_aus_text(text))

    for bereich in doc.get("kompetenzbereiche", []):
        for k in bereich["kompetenzen"]:
            _sammle(k.get("text", ""))
            _sammle(k.get("stammsatz", ""))
            for a in k.get("anwendungsbereiche", []):
                _sammle(a.get("text", ""))
    for k in doc.get("zusatzkompetenzen", []):
        _sammle(k.get("text", ""))
        _sammle(k.get("stammsatz", ""))
        for a in k.get("anwendungsbereiche", []):
            _sammle(a.get("text", ""))
    for a in doc.get("digitale_technologien_vorschlaege", []):
        _sammle(a.get("text", ""))
    for eintrag in doc.get("meta", {}).get("anwendungsbereiche_bloecke", {}).values():
        for item in eintrag.get("items", []):
            _sammle(item.get("text", ""))
    return begriffe


def _baue_stichwort_index(dateien: dict[str, dict]) -> dict[str, str]:
    """term -> comma-joined, sorted part filenames that contain it.

    A plain comma-joined string, not a JSON array: the whole index.json is
    written with ``indent=2`` (see :func:`write_parts`/:func:`_dump`), under
    which a list value explodes onto one line per element while a string
    value stays on the key's own line. Measured on SEK1.M at the thresholds
    above (673 kept terms): list-encoded postings serialise to ~31KB,
    string-encoded to ~23KB for the identical content. Filenames never
    contain a comma, so the join is unambiguous and needs no escaping.

    Sorted at every level (dict comprehension over ``sorted(...)``, postings
    joined from a sorted list) so the output is byte-identical for identical
    input.
    """
    df: dict[str, set[str]] = defaultdict(set)
    for dateiname in sorted(dateien):
        for begriff in _stichworte_je_datei(dateien[dateiname]):
            df[begriff].add(dateiname)
    return {
        begriff: ",".join(sorted(dateinamen))
        for begriff, dateinamen in sorted(df.items())
        if len(dateinamen) <= STICHWORT_MAX_DATEIEN
    }


def build_index(spec: PL.SubjectSpec, dateien: dict[str, dict]) -> dict:
    """The discovery file: meta + per-part filename/area/counts/size, so a
    skill can decide which part to load without loading any of them. Also
    carries ``stichwort_index`` (E12-12, V-67): term -> parts containing it,
    so a keyword lookup can resolve to a part without loading any part either."""
    # index.json is the *discovery* file: it is read first, on every query, to
    # decide which part to load. meta.anwendungsbereiche_bloecke is therefore
    # dropped here -- it carries the full verbatim application items, which is
    # exactly what the reader is trying to avoid paying for until it has picked
    # a part. Measured 2026-08-02: it was 20,460 of PRIM.D's 23,382-byte index
    # meta, 12,505 of PRIM.SU's and 7,035 of SEK1.D's. The items are not lost --
    # every area part file carries the complete container (plan section 5 B1),
    # which is where a consumer reads them.
    meta = {k: v for k, v in next(iter(dateien.values()))["meta"].items()
            if k != "anwendungsbereiche_bloecke"}
    teile: list[dict] = []
    for dateiname in sorted(dateien):
        doc = dateien[dateiname]
        payload = _dump(doc)
        groesse = len(payload.encode("utf-8"))
        tokens = approx_tokens(payload)
        if dateiname == "zusatz.json":
            teile.append(
                {
                    "datei": dateiname,
                    "typ": "zusatz",
                    "zusatzkompetenzen": len(doc.get("zusatzkompetenzen", [])),
                    "digitale_technologien_vorschlaege": len(doc.get("digitale_technologien_vorschlaege", [])),
                    "bytes": groesse,
                    "tokens_approx": tokens,
                }
            )
        else:
            bereich = doc["kompetenzbereiche"][0]
            anwendungsitems = sum(len(k.get("anwendungsbereiche", [])) for k in bereich["kompetenzen"])
            teile.append(
                {
                    "datei": dateiname,
                    "typ": "kompetenzbereich",
                    "nummer": bereich["nummer"],
                    "slug": bereich["slug"],
                    "name": bereich["name"],
                    "kompetenzen": len(bereich["kompetenzen"]),
                    "anwendungsitems": anwendungsitems,
                    "bytes": groesse,
                    "tokens_approx": tokens,
                }
            )
    return {"meta": meta, "teile": teile, "stichwort_index": _baue_stichwort_index(dateien)}


# --------------------------------------------------------------------------
# Counts / report (E3-07)
# --------------------------------------------------------------------------


def _offizielle_slugs(result: PL.ParseResult) -> frozenset[str]:
    """The slugs of the official Kompetenzbereiche of this shard.

    A competence belongs to an area iff its ``bereich_slug`` is in here; this
    is the single identity test shared by :func:`build_parts` and
    :func:`zaehle`, so the report can never disagree with what was written
    (V-59, E12-09).
    """
    return frozenset(b.slug for b in result.bereiche)


def zaehle(result: PL.ParseResult) -> dict[str, int]:
    """Record counts and join statistics for the build report."""
    offiziell = _offizielle_slugs(result)
    return {
        "kompetenzbereiche": len(result.bereiche),
        "kompetenzen_gesamt": len(result.kompetenzen),
        # Area identity, not area number -- same rule as build_parts (V-59).
        "kompetenzen_in_bereichen": sum(1 for k in result.kompetenzen if k.bereich_slug in offiziell),
        "zusatzkompetenzen": sum(1 for k in result.kompetenzen if k.bereich_slug not in offiziell),
        "anwendungsitems_gesamt": len(result.anwendungsitems),
        "praezisierung": sum(1 for a in result.anwendungsitems if a.art == "praezisierung"),
        "digitale_technologien": sum(1 for a in result.anwendungsitems if a.art == "digitale_technologien"),
        "allenfalls": sum(1 for a in result.anwendungsitems if not a.verbindlich),
        "wiederholen_und_festigen": sum(1 for a in result.anwendungsitems if a.wiederholung_von),
    }


def approx_tokens(payload: str) -> int:
    """Approximate token count for the §6.7 budget check.

    Method: ``len(utf-8 bytes) / 4``. This is a defensible order-of-magnitude
    approximation for mixed German-prose/JSON-punctuation content (common
    LLM tokenizers average roughly 3.5-4.5 UTF-8 bytes per token for
    Latin-script text; JSON's heavy quote/brace/comma punctuation tends to
    tokenize slightly denser than prose, so this likely *overestimates*
    tokens a little, which is the conservative direction for a budget
    check). Not an exact count -- state the method, do not claim precision.
    """
    return max(1, len(payload.encode("utf-8")) // 4)


def _dump(shard: dict) -> str:
    return json.dumps(shard, ensure_ascii=False, indent=2)


def build_report(
    spec: PL.SubjectSpec,
    source: Path,
    result: PL.ParseResult,
    dateien_meta: dict[str, dict],
    dateien_je_datensatz: dict[str, dict],
    gewaehlter_modus: str,
) -> str:
    """Build the E3-07 report: counts, join stats, per-part size against the
    §6.7 target, and the two provenance-shape size measurements. Oversize is
    a review trigger, never a failure -- checked per part now that the
    shard is split (each part must be independently loadable, plan section
    5 / B1)."""
    ist = zaehle(result)
    soll = ERWARTET_BUILD.get(f"{spec.band}.{spec.fach_code}", {})

    def gesamt_bytes(dateien: dict[str, dict]) -> int:
        return sum(len(_dump(doc).encode("utf-8")) for doc in dateien.values())

    def gesamt_tokens(dateien: dict[str, dict]) -> int:
        return sum(approx_tokens(_dump(doc)) for doc in dateien.values())

    bytes_meta, bytes_je = gesamt_bytes(dateien_meta), gesamt_bytes(dateien_je_datensatz)
    tok_meta, tok_je = gesamt_tokens(dateien_meta), gesamt_tokens(dateien_je_datensatz)
    dateien_gewaehlt = dateien_meta if gewaehlter_modus == "meta" else dateien_je_datensatz

    zeilen = [
        f"{spec.band}.{spec.fach_code}  {source.name}",
        "",
        "Counts:",
    ]
    for key, wert in ist.items():
        erw = soll.get(key)
        mark = "" if erw is None else ("  OK" if erw == wert else f"  MISMATCH (erwartet {erw})")
        zeilen.append(f"  {key:28s} {wert:5d}{mark}")

    j = result.join_stats
    if j:
        zeilen.append(
            f"  join exact/fuzzy/positional/unmatched: "
            f"{j['exact']}/{j['fuzzy']}/{j['positional']}/{j['unmatched']} "
            f"({j['exact_rate']:.1%}/{j['fuzzy_rate']:.1%}/"
            f"{j['positional_rate']:.1%}/{j['unmatched_rate']:.1%})"
        )
    zeilen.append(f"  issues: {len(result.issues)}")

    zeilen += [
        "",
        f"Per-part size, provenienz-modus={gewaehlter_modus} "
        f"(§6.7 soft target: <= 50 KB / <= 15k approx. tokens per part; "
        f"a review trigger, never a build failure):",
    ]
    schlechtester = "PASS"
    for dateiname in sorted(dateien_gewaehlt):
        payload = _dump(dateien_gewaehlt[dateiname])
        groesse = len(payload.encode("utf-8"))
        tokens = approx_tokens(payload)
        verdict = "PASS" if (groesse <= SHARD_BYTES_ZIEL and tokens <= SHARD_TOKENS_ZIEL) else "REVIEW"
        if verdict == "REVIEW":
            schlechtester = "REVIEW"
        zeilen.append(f"  {dateiname:16s} {groesse:7d} bytes  ~{tokens:6d} tokens  {verdict}")

    kleiner = "meta" if bytes_meta <= bytes_je else "je_datensatz"
    delta_bytes = bytes_je - bytes_meta
    delta_pct = (delta_bytes / bytes_je * 100) if bytes_je else 0.0
    zeilen += [
        "",
        "Total across all parts, both provenance shapes:",
        f"  provenienz-modus=meta          {bytes_meta:7d} bytes  ~{tok_meta:6d} tokens",
        f"  provenienz-modus=je_datensatz  {bytes_je:7d} bytes  ~{tok_je:6d} tokens",
        f"  duplication cost of je_datensatz over meta: +{delta_bytes} bytes (+{delta_pct:.1f}%)",
        f"  smaller variant: {kleiner}",
        f"  recommendation: ship 'meta' (per-record provenienz is duplication of "
        f"identical data, not new information; every record in this shard shares "
        f"the same NOR/Kundmachungsorgan/Anlage/TEIL/retrieval date) unless a "
        f"future record genuinely needs its own provenienz.",
        "",
        f"Selected build: provenienz-modus={gewaehlter_modus}  -> {schlechtester} (worst part)",
    ]
    if schlechtester == "REVIEW":
        zeilen.append(
            "  OVERSIZE: at least one part exceeds the §6.7 soft target. This is a "
            "sharding-review trigger, NOT a build failure."
        )
    return "\n".join(zeilen)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def default_out_dir(spec: PL.SubjectSpec) -> Path:
    return PLUGIN_ROOT / "data" / "kompetenzen" / spec.band.lower() / spec.fach_code.lower()


def write_parts(out_dir: Path, dateien: dict[str, dict], index: dict) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    gesamt_bytes = 0
    for dateiname, doc in dateien.items():
        payload = _dump(doc)
        (out_dir / dateiname).write_text(payload + "\n", encoding="utf-8")
        gesamt_bytes += len(payload.encode("utf-8"))
    index_payload = _dump(index)
    (out_dir / "index.json").write_text(index_payload + "\n", encoding="utf-8")
    gesamt_bytes += len(index_payload.encode("utf-8"))
    return gesamt_bytes


def _cli(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec", default="SEK1.M", choices=sorted(PL.SUBJECT_SPECS))
    ap.add_argument("--source", help="RIS XML source (defaults to the spec's registered resource)")
    ap.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="resources/manifest.json path")
    ap.add_argument(
        "--out", help="directory to write the split shard into "
        "(default: plugin/data/kompetenzen/<band>/<fach>/); with --single-file, the combined file path"
    )
    ap.add_argument(
        "--provenienz-modus", choices=["meta", "je_datensatz"], default="meta",
        help="meta (default, recommended): meta.provenienz only. je_datensatz: also per-record.",
    )
    ap.add_argument("--dataset-version", help="override meta.dataset_version (defaults to the retrieval date)")
    ap.add_argument(
        "--single-file", action="store_true",
        help="write one combined document instead of the split layout (validation only; requires --out)",
    )
    ap.add_argument("--no-registry", action="store_true", help="skip updating plugin/data/abbildungen/registry.json")
    ap.add_argument("--summary", action="store_true", help="print the build report only; do not write anything")
    ap.add_argument(
        "--verify", action="store_true",
        help="like --summary, plus exit non-zero on a count mismatch (never on shard size -- E3-07)",
    )
    ap.add_argument("--report", help="also write the build report text to this file")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.ERROR,
                        format="%(levelname)s %(message)s")

    if args.single_file and not args.out:
        print("error: --single-file requires --out", file=sys.stderr)
        return 2

    spec = PL.SUBJECT_SPECS[args.spec]
    source = Path(args.source) if args.source else default_source(args.spec)
    if source is None:
        print(f"error: no default source registered for {args.spec!r}; pass --source", file=sys.stderr)
        return 2
    if not source.exists():
        print(f"error: source not found: {source}", file=sys.stderr)
        return 2

    try:
        manifest = load_manifest(Path(args.manifest))
        result = PL.parse_lehrplan(source, spec)
        # Merge in-memory first (existing registry.json + this result's
        # images); build_parts asserts completeness against *this* dict
        # before slimming anything, and it is only persisted to disk below,
        # once the whole build has actually succeeded.
        registry = load_or_build_abbildungen_registry(result, ABBILDUNGEN_REGISTRY_PATH)
        dateien_meta = build_parts(
            result, spec, manifest, registry, modus="meta", dataset_version=args.dataset_version
        )
        dateien_je = build_parts(
            result, spec, manifest, registry, modus="je_datensatz", dataset_version=args.dataset_version
        )
    except BuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    dateien_gewaehlt = dateien_meta if args.provenienz_modus == "meta" else dateien_je
    report = build_report(spec, source, result, dateien_meta, dateien_je, args.provenienz_modus)
    print(report)
    if args.report:
        Path(args.report).write_text(report + "\n", encoding="utf-8")

    if args.verify:
        ist = zaehle(result)
        soll = ERWARTET_BUILD.get(args.spec, {})
        if not soll:
            # An empty table used to mean "no mismatches", so --verify printed
            # VERIFY OK for five of the six shards without checking anything
            # (E12-13). Silence is the one thing a verifier must never do.
            print(f"VERIFY FAILED: no expected build counts for {args.spec}", file=sys.stderr)
            return 1
        bad = {k: (v, ist.get(k)) for k, v in soll.items() if ist.get(k) != v}
        if bad:
            print("VERIFY FAILED", bad, file=sys.stderr)
            return 1
        print("VERIFY OK")
        return 0

    if args.summary:
        return 0

    if args.single_file:
        combined = combine_parts(dateien_gewaehlt)
        payload = _dump(combined)
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload + "\n", encoding="utf-8")
        print(f"\nwrote {out_path}  ({len(payload.encode('utf-8'))} bytes, combined, "
              f"provenienz-modus={args.provenienz_modus})")
        return 0

    out_dir = Path(args.out) if args.out else default_out_dir(spec)
    index = build_index(spec, dateien_gewaehlt)
    gesamt = write_parts(out_dir, dateien_gewaehlt, index)
    print(f"\nwrote {len(dateien_gewaehlt) + 1} files to {out_dir}  "
          f"({gesamt} bytes total, provenienz-modus={args.provenienz_modus})")

    if not args.no_registry:
        persist_abbildungen_registry(registry, ABBILDUNGEN_REGISTRY_PATH)
        print(f"updated {ABBILDUNGEN_REGISTRY_PATH}  ({len(registry)} images)")

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
