#!/usr/bin/env python3
"""Access layer for the shipped Kompetenzen dataset (plan §5, strategy B1).

Skills call the nine ``finde_*`` functions defined here and must stay
agnostic about the backend -- v1.0 is local JSON files under
``plugin/data/kompetenzen/<band>/<fach>/``; a future B2 (SQLite) migration
is meant to be non-breaking against this same contract.

Two constraints drive every function in this module and must never be
re-litigated by a future edit:

1. **Read a directory, never a single file.** Each shard is split into one
   JSON part per ``Kompetenzbereich`` (competence area), plus a catch-all
   ``zusatz.json`` (synthetic areas with no official Kompetenzbereich, and
   the SEK1.M-only ``digitale_technologien`` suggestions) and an
   ``index.json`` that lists every part, its byte/token cost and a
   ``stichwort_index`` for keyword routing. ``index.json`` is **not** a
   shard part -- it has its own shape and is read only for its ``meta``,
   ``teile`` and ``stichwort_index`` keys, never fed through the
   part-reading path.
2. **Dispatch on ``meta.anwendungsbereiche_bindung``, never on a hardcoded
   subject list.** Five values occur across the six shipped shards:

   ================  ========  ====================================
   ``bindung``       Shard(s)  What it means
   ================  ========  ====================================
   ``kompetenz``     SEK1.M    Items are joined to one competence and
                                ship nested on ``Kompetenz.anwendungsbereiche``.
   ``bereich``       SEK1.D    Items attach to (area, class year); look
                                them up in
                                ``meta.anwendungsbereiche_bloecke["<SLUG>.<STUFE>"]``.
   ``stufe``         PRIM.D,   Items attach to a school year only, never
                     PRIM.SU   an area; look them up in
                                ``meta.anwendungsbereiche_bloecke["<STUFE>"]``.
   ``prosa``         SEK1.E    An Anwendungsbereiche heading exists but
                                introduces prose, not a list -- zero items.
   ``keine``         PRIM.M    No Anwendungsbereiche section exists at all.
   ================  ========  ====================================

   ``prosa`` and ``keine`` legitimately yield **zero** application items --
   that is data, not a build failure, and the axis exists precisely so a
   consumer can tell the two apart. Every function here returns a
   defined-empty result for them; **none raises** on account of the axis
   value alone.

A third rule threads through the whole module: **quote ``stammsatz`` +
``text``, never ``text`` alone.** ``Kompetenz.stammsatz`` (schema-required
on every record) holds the verbatim stem paragraph (usually *"Die
Schülerinnen und Schüler können"*, sometimes carrying a performance
condition, e.g. SEK1.E's CEFR qualifiers). A faithful quotation is
``stammsatz`` + ``text``; neither alone is the sentence the regulation
actually contains. Every :class:`Kompetenz` dict returned by this module
therefore carries a precomputed ``volltext`` field with the two already
joined, in addition to the raw ``stammsatz``/``text`` fields -- use
``volltext`` (or join the two yourself) whenever you cite a competence to a
teacher; never cite ``text`` on its own.

Pure stdlib. Offline. Deterministic (no network, no randomness, no
wall-clock in any return value). Nothing here mutates the shipped JSON.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths and the frozen band/fach registry
# ---------------------------------------------------------------------------

#: ``plugin/scripts/kompetenz.py`` -> ``plugin/`` -> repo/plugin root.
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
KOMPETENZEN_ROOT = _PLUGIN_ROOT / "data" / "kompetenzen"

#: Directory names on disk are lower-case (``sek1/m``, ``prim/su``, ...);
#: shard *keys* used throughout this module and the rest of the codebase
#: (FINDINGS.md, the test suite) are upper-case ``"<BAND>.<FACH>"``, e.g.
#: ``"SEK1.M"``. Mirrors ``id_schema.BAND_FAECHER`` (data-pipeline) without
#: importing it: this module ships inside the plugin and must stay
#: self-contained, independent of the dev-only data-pipeline package.
GUELTIGE_FAECHER: dict[str, tuple[str, ...]] = {
    "SEK1": ("M", "D", "E"),
    "PRIM": ("M", "D", "SU"),
}

#: Every shipped shard key, in a stable order -- convenience for callers
#: (and this module's own tests) that need to iterate "all six".
ALLE_FAECHER: tuple[str, ...] = tuple(
    f"{band}.{fach}" for band in ("PRIM", "SEK1") for fach in GUELTIGE_FAECHER[band]
)


class KompetenzFehler(Exception):
    """Base class for this module's own errors."""


class UnbekannterFachSchluessel(KompetenzFehler, ValueError):
    """*fach* is not one of the six shipped ``"<BAND>.<FACH>"`` shards."""


class KompetenzNichtGefunden(KompetenzFehler, LookupError):
    """A ``kompetenz_id`` does not resolve to any shipped record."""


# ---------------------------------------------------------------------------
# ID parsing -- a minimal, self-contained mirror of data-pipeline's frozen
# grammar (data-pipeline/schema/id_schema.py), deliberately NOT imported:
# data-pipeline is dev-only tooling and never ships inside the plugin.
# ---------------------------------------------------------------------------


def _parse_id(ident: str) -> dict[str, Any]:
    """Parse an ``AT.LP23...`` ID into its segments.

    Three grammars are in scope (see ``data-pipeline/schema/id_schema.py``
    for the authoritative version and rationale):

        Kompetenz:                 AT.LP23.<Band>.<Fach>.<Bereich>.<Stufe>.<lfd>        (7 segments)
        Anwendungsitem:             AT.LP23.<Band>.<Fach>.<Art>.<Bereich>.<Stufe>.<lfd>  (8 segments)
        Anwendungsitem (area-free)  AT.LP23.<Band>.<Fach>.<Art>.<Stufe>.<lfd>            (7 segments)

    ``Art`` is always ``AB`` (Praezisierung) or ``DT`` (digitale
    Technologien) and is reserved out of the ``Bereich`` code space, which
    is what keeps the two 7-segment grammars unambiguous: a competence ID's
    5th segment is never literally ``AB``/``DT``.

    Returns a dict with keys ``band``, ``fach``, ``fach_schluessel``
    (``"<band>.<fach>"``), ``art`` (``None`` for a competence ID),
    ``bereich`` (``None`` for an area-free application-item ID), ``stufe``,
    ``lfd``. Raises :class:`KompetenzFehler` if *ident* matches none of the
    three grammars.
    """
    teile = ident.split(".")
    if len(teile) < 2 or teile[0] != "AT" or teile[1] != "LP23":
        raise KompetenzFehler(f"{ident!r} ist keine gültige AT.LP23-ID")
    rest = teile[2:]

    if len(rest) == 5:
        band, fach, bereich, stufe, lfd = rest
        art: str | None = None
        if bereich in ("AB", "DT"):
            # Area-free application-item form (7 segments, PRIM.D/PRIM.SU
            # "stufe"-bound items) -- the 5th segment is the Art literal,
            # not a Bereich code (a real Bereich code is never "AB"/"DT").
            art, bereich = bereich, None
    elif len(rest) == 6:
        band, fach, art, bereich, stufe, lfd = rest
        if art not in ("AB", "DT"):
            raise KompetenzFehler(f"{ident!r}: unerwartetes Art-Segment {art!r}")
    else:
        raise KompetenzFehler(f"{ident!r}: unerwartete Segmentanzahl ({len(teile)})")

    if band not in GUELTIGE_FAECHER:
        raise KompetenzFehler(f"{ident!r}: unbekanntes Band {band!r}")
    if fach not in GUELTIGE_FAECHER[band]:
        raise KompetenzFehler(f"{ident!r}: unbekanntes Fach {fach!r} für Band {band!r}")
    if not lfd.isdigit() or len(lfd) != 2:
        raise KompetenzFehler(f"{ident!r}: ungültiges lfd-Segment {lfd!r}")

    return {
        "band": band,
        "fach": fach,
        "fach_schluessel": f"{band}.{fach}",
        "art": art,
        "bereich": bereich,
        "stufe": stufe,
        "lfd": lfd,
    }


# ---------------------------------------------------------------------------
# Directory / file loading -- the B1 access strategy
# ---------------------------------------------------------------------------


def _shard_verzeichnis(fach_schluessel: str) -> Path:
    """``"<BAND>.<FACH>"`` (e.g. ``"SEK1.M"``, case-insensitive) -> the
    shard's directory, ``plugin/data/kompetenzen/<band>/<fach>/``."""
    schluessel = fach_schluessel.strip().upper()
    if "." not in schluessel:
        raise UnbekannterFachSchluessel(
            f"{fach_schluessel!r}: erwartet 'BAND.FACH', z.B. 'SEK1.M' oder 'PRIM.SU'"
        )
    band, fach = schluessel.split(".", 1)
    if band not in GUELTIGE_FAECHER or fach not in GUELTIGE_FAECHER.get(band, ()):
        raise UnbekannterFachSchluessel(
            f"{fach_schluessel!r} ist keiner der sechs Shards ({', '.join(ALLE_FAECHER)})"
        )
    verzeichnis = KOMPETENZEN_ROOT / band.lower() / fach.lower()
    if not verzeichnis.is_dir():
        raise UnbekannterFachSchluessel(f"{fach_schluessel!r}: Verzeichnis {verzeichnis} fehlt")
    return verzeichnis


def _datei_laden(pfad: Path) -> dict[str, Any]:
    return json.loads(pfad.read_text(encoding="utf-8"))


def _index_laden(shard_dir: Path) -> dict[str, Any]:
    """Load ``index.json``. Never treated as a shard part (constraint 4)."""
    return _datei_laden(shard_dir / "index.json")


def _teil_laden(shard_dir: Path, dateiname: str) -> dict[str, Any]:
    return _datei_laden(shard_dir / dateiname)


def _kompetenzbereich_dateien(index: dict[str, Any]) -> list[dict[str, Any]]:
    return [t for t in index["teile"] if t.get("typ") == "kompetenzbereich"]


def _zusatz_datei(index: dict[str, Any]) -> str | None:
    for t in index["teile"]:
        if t.get("typ") == "zusatz":
            return t["datei"]
    return None


def _slug_zu_datei(index: dict[str, Any]) -> dict[str, str]:
    return {t["slug"]: t["datei"] for t in _kompetenzbereich_dateien(index)}


# ---------------------------------------------------------------------------
# Record enrichment -- turns the raw shipped JSON into the public Kompetenz
# shape this module returns. Never mutates the JSON dict that was loaded
# from disk; always builds a fresh dict via `dict(record)`.
# ---------------------------------------------------------------------------


def voller_wortlaut(kompetenz: dict[str, Any]) -> str:
    """``stammsatz`` + ``text``, correctly joined -- the faithful quotation.

    ``kompetenz.stammsatz`` is schema-``required`` on every shipped record.
    Neither field alone is the sentence the regulation contains; this is
    the join every consumer must use instead of citing ``text`` alone."""
    stammsatz = (kompetenz.get("stammsatz") or "").strip()
    text = (kompetenz.get("text") or "").strip()
    if not stammsatz:
        return text
    return f"{stammsatz} {text}".strip()


def _anreichern(
    k: dict[str, Any],
    *,
    fach_schluessel: str,
    datei: str,
    bereich_nummer: int | None,
    bereich_slug: str | None,
    bereich_name: str | None,
    provenienz: dict[str, Any],
) -> dict[str, Any]:
    angereichert = dict(k)
    angereichert["fach"] = fach_schluessel
    angereichert["datei"] = datei
    angereichert["bereich_nummer"] = bereich_nummer
    angereichert["bereich_slug"] = bereich_slug
    angereichert["bereich_name"] = bereich_name
    # Provenance belongs to the part document rather than every individual
    # Kompetenz in the frozen JSON. Expose a copy on every public result so
    # callers can cite the official source without loading or knowing the
    # part-document shape themselves (Phase-1 / plan §5).
    angereichert["provenienz"] = dict(provenienz)
    angereichert["volltext"] = voller_wortlaut(k)
    return angereichert


def _kompetenzen_aus_teil(fach_schluessel: str, datei: str, doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Every Kompetenz record in one loaded part document (regular area
    competences plus, if present, ``zusatzkompetenzen``), enriched."""
    ergebnis: list[dict[str, Any]] = []
    provenienz = doc.get("meta", {}).get("provenienz", {})
    for bereich in doc.get("kompetenzbereiche", []):
        for k in bereich.get("kompetenzen", []):
            ergebnis.append(
                _anreichern(
                    k,
                    fach_schluessel=fach_schluessel,
                    datei=datei,
                    bereich_nummer=bereich.get("nummer"),
                    bereich_slug=bereich.get("slug"),
                    bereich_name=bereich.get("name"),
                    provenienz=provenienz,
                )
            )
    for zk in doc.get("zusatzkompetenzen", []):
        # zusatzkompetenzen carry bereich_nummer/bereich_name but not
        # bereich_slug (V-57) -- derive the slug from the ID's own Bereich
        # segment (never invented/guessed; the ID is the identity, see
        # constraint 5) rather than leaving it unset.
        try:
            bereich_slug = _parse_id(zk["id"])["bereich"]
        except KompetenzFehler:
            bereich_slug = None
        ergebnis.append(
            _anreichern(
                zk,
                fach_schluessel=fach_schluessel,
                datei=datei,
                bereich_nummer=zk.get("bereich_nummer"),
                bereich_slug=bereich_slug,
                bereich_name=zk.get("bereich_name"),
                provenienz=provenienz,
            )
        )
    return ergebnis


def kompetenz_nach_id(kompetenz_id: str) -> dict[str, Any]:
    """Resolve one competence record by its full ID.

    Routes via the ID's own Bereich segment against ``index.json``'s
    slug -> Datei map (never the whole fach), then ``zusatz.json`` (which
    catches synthetic areas such as SEK1.M's ``GZINTEGRATIV``), then --
    only if both miss, which should not happen against the shipped data --
    every part, as a correctness fallback. Raises
    :class:`KompetenzNichtGefunden` if no shipped record has this ID.
    """
    geparst = _parse_id(kompetenz_id)
    if geparst["art"] is not None:
        raise KompetenzFehler(
            f"{kompetenz_id!r} ist eine Anwendungsitem-ID (Art={geparst['art']}), "
            "keine Kompetenz-ID"
        )
    fach_schluessel = geparst["fach_schluessel"]
    shard_dir = _shard_verzeichnis(fach_schluessel)
    index = _index_laden(shard_dir)

    kandidaten: list[str] = []
    slug_map = _slug_zu_datei(index)
    if geparst["bereich"] in slug_map:
        kandidaten.append(slug_map[geparst["bereich"]])
    zdatei = _zusatz_datei(index)
    if zdatei and zdatei not in kandidaten:
        kandidaten.append(zdatei)

    geprueft = set()
    for datei in kandidaten:
        geprueft.add(datei)
        for k in _kompetenzen_aus_teil(fach_schluessel, datei, _teil_laden(shard_dir, datei)):
            if k["id"] == kompetenz_id:
                return k

    for teil in index["teile"]:
        datei = teil["datei"]
        if datei in geprueft:
            continue
        for k in _kompetenzen_aus_teil(fach_schluessel, datei, _teil_laden(shard_dir, datei)):
            if k["id"] == kompetenz_id:
                return k

    raise KompetenzNichtGefunden(f"{kompetenz_id!r} nicht gefunden in {fach_schluessel}")


# ---------------------------------------------------------------------------
# 1. finde_kompetenz
# ---------------------------------------------------------------------------


def _stichwort_dateien(index: dict[str, Any], begriff: str) -> tuple[list[str], bool, list[str]]:
    """Resolve one search term against ``index.json``'s ``stichwort_index``.

    **V-71: the index is exact-token.** German compounding means a term can
    have a real exact hit (e.g. ``"bruch"`` exact-matches ``daten.json`` and
    ``zahlen.json``, since "Bruch-" occurs standalone) *and still* miss real
    occurrences that tokenised as their own compound (``"bruchtermen"`` in
    ``variablen.json``). An implementation that only falls back to a
    broader match on a *miss* would therefore still miss compounds whenever
    an unrelated exact hit also exists -- so this function always unions the
    exact hit (if any) with every index *key* that contains *begriff* as a
    substring, never only on a miss. This trades routing precision for
    recall; the caller (``finde_kompetenz``) re-checks the actual
    competence text afterwards, so the final result stays precise even
    though this routing step is deliberately generous.

    Returns ``(dateien, exakt, treffer_schluessel)``: the union of part
    filenames to load, whether an *exact* key hit existed at all, and which
    index keys matched (useful for a caller that wants to tell a teacher
    the search was exact vs. compound-derived).
    """
    si = index.get("stichwort_index", {})
    b = begriff.strip().casefold()
    treffer_schluessel: set[str] = set()
    exakt = b in si
    if exakt:
        treffer_schluessel.add(b)
    if b:
        for schluessel in si:
            if schluessel != b and b in schluessel:
                treffer_schluessel.add(schluessel)
    dateien = sorted({d for s in treffer_schluessel for d in si[s].split(",") if d})
    return dateien, exakt, sorted(treffer_schluessel)


def stichwort_abdeckung(fach: str, begriff: str) -> dict[str, Any]:
    """Describe keyword coverage without changing ``finde_kompetenz``.

    This introspection helper is not one of the nine contract functions. It
    reports the existing index routing information plus the matching
    Kompetenz and Lehrstoff items in those candidate parts. Its
    ``suchstatus`` is one of:

    - ``"keine_indexkandidaten"``: the keyword index selected no parts;
      this is never evidence that the term is absent from the curriculum.
    - ``"kandidaten_ohne_texttreffer"``: candidate parts were searched but
      neither a competence description nor a Lehrstoff-Praezisierung
      matched; again, this is not a curriculum-wide absence claim.
    - ``"kompetenztreffer"``: at least one competence description matched.
    - ``"nur_lehrstofftreffer"``: no competence description matched, but
      one or more official Lehrstoff-Praezisierungen did (V-73).

    ``lehrstoff_items`` contains the latter summaries; it intentionally
    excludes ``art == "digitale_technologien"`` suggestions, which are not
    Lehrstoff-Praezisierungen. ``finde_kompetenz`` itself continues to
    return ``Kompetenz[]`` and consequently returns ``[]`` for the
    item-only case.

    Only files selected by ``stichwort_index`` are read; this never falls
    back to a whole-shard scan.
    """
    shard_dir = _shard_verzeichnis(fach)
    index = _index_laden(shard_dir)
    dateien, exakt, schluessel = _stichwort_dateien(index, begriff)
    kompetenz_ids: list[str] = []
    lehrstoff_items: list[dict[str, Any]] = []

    for datei in dateien:
        doc = _teil_laden(shard_dir, datei)
        kompetenz_ids.extend(
            k["id"]
            for k in _kompetenzen_aus_teil(fach.strip().upper(), datei, doc)
            if _enthaelt_stichwort(k, [begriff])
        )
        lehrstoff_items.extend(
            {
                "id": item["id"],
                "text": item["text"],
                "stufe": item["stufe"],
                "verbindlich": item["verbindlich"],
                "kompetenz_id": item["kompetenz_id"],
            }
            for item in _anwendungsbereiche_aus_teil(doc)
            if item.get("art") == "praezisierung" and _enthaelt_stichwort(item, [begriff])
        )

    kompetenz_ids = sorted(set(kompetenz_ids))
    lehrstoff_items.sort(key=lambda item: item["id"])
    if not dateien:
        suchstatus = "keine_indexkandidaten"
        hinweis = (
            "Der Stichwortindex hat keine Kandidatendatei geliefert; weder "
            "Kompetenzbeschreibungen noch Lehrstoff-Präzisierungen wurden durchsucht. "
            "Das ist keine Aussage darüber, ob der Begriff im Lehrplan vorkommt."
        )
    elif kompetenz_ids:
        suchstatus = "kompetenztreffer"
        hinweis = (
            "Durchsucht wurden die vom Stichwortindex gewählten Teile in "
            "Kompetenzbeschreibungen und Lehrstoff-Präzisierungen. "
            "Mindestens eine Kompetenzbeschreibung enthält den Begriff."
        )
    elif lehrstoff_items:
        suchstatus = "nur_lehrstofftreffer"
        hinweis = (
            "Durchsucht wurden die vom Stichwortindex gewählten Teile in "
            "Kompetenzbeschreibungen und Lehrstoff-Präzisierungen. Keine "
            "Kompetenzbeschreibung enthält den Begriff; er kommt jedoch in den "
            "ausgewiesenen Lehrstoff-Präzisierungen vor."
        )
    else:
        suchstatus = "kandidaten_ohne_texttreffer"
        hinweis = (
            "Die vom Stichwortindex gewählten Teile wurden in "
            "Kompetenzbeschreibungen und Lehrstoff-Präzisierungen durchsucht, "
            "ohne Texttreffer. Das ist keine Aussage darüber, ob der Begriff "
            "im Lehrplan vorkommt."
        )

    return {
        "dateien": dateien,
        "exakt": exakt,
        "index_schluessel": schluessel,
        "kompetenz_ids": kompetenz_ids,
        # Kept as an additive compatibility alias for callers added in
        # E4-02 before ``lehrstoff_items`` exposed the useful item detail.
        "anwendungsbereich_ids": [item["id"] for item in lehrstoff_items],
        "lehrstoff_items": lehrstoff_items,
        "suchstatus": suchstatus,
        "hinweis": hinweis,
    }


def _anwendungsbereiche_aus_teil(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Return each application item stored in one part document once.

    The five binding models place items either below the competence record
    itself or in ``meta.anwendungsbereiche_bloecke``. The helper deliberately
    reads both shapes, then de-duplicates on the frozen item ID, so keyword
    coverage remains data-driven rather than branching on a subject name.
    """
    items: list[dict[str, Any]] = []
    for bereich in doc.get("kompetenzbereiche", []):
        for kompetenz in bereich.get("kompetenzen", []):
            items.extend(kompetenz.get("anwendungsbereiche", []))
    for kompetenz in doc.get("zusatzkompetenzen", []):
        items.extend(kompetenz.get("anwendungsbereiche", []))
    for block in (doc.get("meta", {}).get("anwendungsbereiche_bloecke") or {}).values():
        items.extend(block.get("items", []))
    # SEK1.M keeps its non-Lehrstoff digital-technology suggestions in this
    # separate top-level collection. Include the shape here so the caller's
    # explicit ``art == 'praezisierung'`` filter, rather than an accidental
    # omission, is what keeps those suggestions out of Lehrstoff coverage.
    items.extend(doc.get("digitale_technologien_vorschlaege", []))

    eindeutig: dict[str, dict[str, Any]] = {}
    for item in items:
        ident = item.get("id")
        if ident:
            eindeutig[ident] = item
    return [eindeutig[ident] for ident in sorted(eindeutig)]


def _kompetenzbereich_dateien_fuer(index: dict[str, Any], kompetenzbereich: str) -> list[str]:
    ziel = kompetenzbereich.strip().casefold()
    dateien = [
        t["datei"]
        for t in _kompetenzbereich_dateien(index)
        if t.get("slug", "").casefold() == ziel or t.get("name", "").casefold() == ziel
    ]
    # Always also consider zusatz.json: synthetic areas (e.g. SEK1.M's
    # GZINTEGRATIV) have no entry among the "kompetenzbereich"-typed teile
    # at all, so a kompetenzbereich filter that never looked there could
    # never find them. Harmless when it doesn't match: the post-filter
    # below still narrows to an empty result.
    z = _zusatz_datei(index)
    if z:
        dateien.append(z)
    return dateien


def _stufe_filter(ergebnisse: list[dict[str, Any]], stufe: str | None) -> list[dict[str, Any]]:
    if not stufe:
        return ergebnisse
    s = stufe.strip().upper()
    return [k for k in ergebnisse if k.get("stufe") == s]


def _kompetenzbereich_filter(
    ergebnisse: list[dict[str, Any]], kompetenzbereich: str | None
) -> list[dict[str, Any]]:
    if not kompetenzbereich:
        return ergebnisse
    ziel = kompetenzbereich.strip().casefold()
    return [
        k
        for k in ergebnisse
        if (k.get("bereich_slug") or "").casefold() == ziel
        or (k.get("bereich_name") or "").casefold() == ziel
    ]


def _enthaelt_stichwort(k: dict[str, Any], stichworte: list[str]) -> bool:
    heuhaufen = " ".join(
        filter(None, [k.get("stammsatz"), k.get("text"), k.get("text_roh")])
    ).casefold()
    return any(s.strip().casefold() in heuhaufen for s in stichworte if s.strip())


def finde_kompetenz(
    fach: str,
    stufe: str | None = None,
    kompetenzbereich: str | None = None,
    code: str | None = None,
    stichworte: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Find competence records in one shard.

    ``fach`` is the shard key, ``"<BAND>.<FACH>"`` (case-insensitive), e.g.
    ``"SEK1.M"`` or ``"prim.su"`` -- see :data:`ALLE_FAECHER` for the six
    valid values. The plan's own ``fach`` parameter name conflates subject
    and band; this module's shard keys are the same ``"<BAND>.<FACH>"``
    convention already used throughout the dataset (index/meta, the test
    suite, FINDINGS.md), so a caller that already knows *which* of the six
    shards it wants (which every skill must, since band and fach are
    already both fixed by the time a lesson is being planned) passes it
    directly, with no separate ``band`` parameter needed.

    ``code``, if given, is an exact ``kompetenz_id`` lookup (routed via the
    ID's own Bereich segment, not a full-fach scan).

    ``stichworte``, if given, routes through ``index.json``'s
    ``stichwort_index`` (see :func:`_stichwort_dateien` for the V-71
    exact-token/compound-fallback semantics) and loads only the parts it
    names, never the whole fach (E4-02/V-67). Every candidate result is
    then re-checked against its own ``stammsatz``/``text``/``text_roh`` so
    the final list only contains competences that genuinely mention the
    term, even though the routing step above is deliberately generous.

    Returns ``[]`` if no *competence description* matches -- never raises
    for "no results", only for a malformed ``fach``. This does not mean a
    term is absent from the curriculum: it can occur solely in a Lehrstoff
    / Anwendungsbereiche item (V-73). Use :func:`stichwort_abdeckung` before
    presenting an empty result as a curriculum-wide miss.
    """
    fach_schluessel = fach.strip().upper()
    shard_dir = _shard_verzeichnis(fach_schluessel)
    index = _index_laden(shard_dir)

    if code is not None:
        try:
            treffer = kompetenz_nach_id(code)
        except KompetenzNichtGefunden:
            return []
        if treffer["fach"] != fach_schluessel:
            return []
        ergebnisse = _stufe_filter([treffer], stufe)
        ergebnisse = _kompetenzbereich_filter(ergebnisse, kompetenzbereich)
        return ergebnisse

    if stichworte:
        alle_dateien: set[str] = set()
        for begriff in stichworte:
            gefunden, _, _ = _stichwort_dateien(index, begriff)
            alle_dateien.update(gefunden)
        if not alle_dateien:
            return []
        dateien = sorted(alle_dateien)
    elif kompetenzbereich is not None:
        dateien = _kompetenzbereich_dateien_fuer(index, kompetenzbereich)
    else:
        dateien = [t["datei"] for t in index["teile"]]

    ergebnisse: list[dict[str, Any]] = []
    for datei in dateien:
        doc = _teil_laden(shard_dir, datei)
        ergebnisse.extend(_kompetenzen_aus_teil(fach_schluessel, datei, doc))

    ergebnisse = _stufe_filter(ergebnisse, stufe)
    ergebnisse = _kompetenzbereich_filter(ergebnisse, kompetenzbereich)
    if stichworte:
        ergebnisse = [k for k in ergebnisse if _enthaelt_stichwort(k, stichworte)]

    ergebnisse.sort(key=lambda k: (k.get("stufe") or "", k.get("bereich_slug") or "", k.get("ordinal") or 0))
    return ergebnisse


# ---------------------------------------------------------------------------
# 2. finde_progression
# ---------------------------------------------------------------------------


def finde_progression(kompetenz_id: str, richtung: str) -> list[dict[str, Any]]:
    """Predecessors (``richtung="zurueck"``) or successors
    (``richtung="vor"``) of one competence.

    Reads ``Kompetenz.vorlaeufer``/``.folge`` -- already computed at build
    time, bucketed on ``(stufe, bereich_slug)`` (V-59/E12-04), never on
    ``bereich_nummer`` (``None`` for five of six shards). This function
    additionally re-checks that defensively at the access layer: a link
    that would cross a Kompetenzbereich boundary is logged and dropped
    rather than trusted blindly, so a future data regression fails loud
    here too, not only in the build-time tests. Measured against all six
    shards: 0 such links exist, so this check never actually drops
    anything today.

    Textual "Wiederholen und Festigen" backlinks are SEK1.M-only; the
    ``vorlaeufer``/``folge`` arrays already fold in both the textual and
    the positional mechanism at build time, so no separate handling is
    needed here.
    """
    if richtung not in ("zurueck", "vor"):
        raise ValueError(f"richtung muss 'zurueck' oder 'vor' sein, nicht {richtung!r}")

    quelle = kompetenz_nach_id(kompetenz_id)
    ziel_ids = quelle.get("vorlaeufer", []) if richtung == "zurueck" else quelle.get("folge", [])

    ergebnisse: list[dict[str, Any]] = []
    for zid in ziel_ids:
        try:
            ziel = kompetenz_nach_id(zid)
        except KompetenzNichtGefunden:
            LOGGER.warning("finde_progression: %s verweist auf unbekannte ID %s", kompetenz_id, zid)
            continue
        if ziel.get("bereich_slug") != quelle.get("bereich_slug"):
            LOGGER.error(
                "finde_progression: %s -> %s würde den Kompetenzbereich verlassen (%s -> %s) "
                "-- übersprungen",
                kompetenz_id,
                zid,
                quelle.get("bereich_slug"),
                ziel.get("bereich_slug"),
            )
            continue
        ergebnisse.append(ziel)
    return ergebnisse


# ---------------------------------------------------------------------------
# 3. finde_anwendungsbereiche
# ---------------------------------------------------------------------------


def _koordinaten_modus_pruefen(
    kompetenz_id: str | None,
    fach: str | None,
    stufe: str | None,
    bereich: str | None,
) -> None:
    """Require exactly one public lookup mode.

    A competence ID is the usual, most precise route.  Coordinates are the
    complementary route for source blocks that genuinely have no competence
    owner (notably SEK1.D's structural Sprachreflexion area).  Mixing them
    would make it unclear which selector is authoritative.
    """
    if kompetenz_id is not None:
        if any(value is not None for value in (fach, stufe, bereich)):
            raise ValueError("kompetenz_id und Koordinaten duerfen nicht kombiniert werden")
        return
    if fach is None:
        raise ValueError("erwartet kompetenz_id oder mindestens fach fuer eine Koordinatenabfrage")


def _bereich_teil(index: dict[str, Any], bereich: str) -> dict[str, Any] | None:
    """Find one regular area part by its frozen slug or official name."""
    ziel = bereich.strip().casefold()
    for teil in _kompetenzbereich_dateien(index):
        if teil.get("slug", "").casefold() == ziel or teil.get("name", "").casefold() == ziel:
            return teil
    return None


def _anwendungsbereiche_aus_koordinaten(
    fach: str,
    stufe: str | None,
    bereich: str | None,
) -> list[dict[str, Any]]:
    """Resolve source-contained application items without inventing an owner.

    The dispatch is entirely data-driven.  In particular, ``bereich`` reads
    the addressed ``<SLUG>.<STUFE>`` source block directly, so it also covers
    areas that deliberately contain no Kompetenz records of their own.
    """
    shard_dir = _shard_verzeichnis(fach)
    index = _index_laden(shard_dir)
    bindung = index["meta"]["anwendungsbereiche_bindung"]

    if bindung == "kompetenz":
        raise ValueError("bindung 'kompetenz' erfordert eine kompetenz_id")

    if bindung == "bereich":
        if stufe is None or bereich is None:
            raise ValueError("bindung 'bereich' erfordert fach, stufe und bereich")
        teil = _bereich_teil(index, bereich)
        if teil is None:
            raise ValueError(f"unbekannter bereich {bereich!r} fuer {fach!r}")
        doc = _teil_laden(shard_dir, teil["datei"])
        slug = teil["slug"]
        block = (doc.get("meta", {}).get("anwendungsbereiche_bloecke") or {}).get(
            f"{slug}.{stufe.strip().upper()}"
        )
        if block is None:
            raise ValueError(f"kein Anwendungsbereiche-Block fuer {slug}.{stufe.strip().upper()}")
        return list(block["items"])

    if bindung == "stufe":
        if stufe is None:
            raise ValueError("bindung 'stufe' erfordert fach und stufe")
        if bereich is not None:
            raise ValueError(
                "bindung 'stufe' ist bereichsfrei; bereich wuerde eine nicht vorhandene Filterung behaupten"
            )
        teile = _kompetenzbereich_dateien(index)
        if not teile:
            return []
        doc = _teil_laden(shard_dir, teile[0]["datei"])
        block = (doc.get("meta", {}).get("anwendungsbereiche_bloecke") or {}).get(
            stufe.strip().upper()
        )
        if block is None:
            raise ValueError(f"kein Anwendungsbereiche-Block fuer {fach!r}/{stufe.strip().upper()}")
        return list(block["items"])

    if bindung in ("prosa", "keine"):
        return []

    raise KompetenzFehler(f"unbekannte anwendungsbereiche_bindung {bindung!r}")


def finde_anwendungsbereiche(
    kompetenz_id: str | None = None,
    nur_verbindlich: bool | None = None,
    *,
    fach: str | None = None,
    stufe: str | None = None,
    bereich: str | None = None,
) -> list[dict[str, Any]]:
    """Application-area items ("Anwendungsbereiche") precisifying one
    competence, resolved per ``meta.anwendungsbereiche_bindung`` (never a
    hardcoded subject list).  Existing callers pass ``kompetenz_id`` as the
    first positional argument exactly as before.  Coordinate mode is an
    additive, keyword-only alternative (``fach=…``, plus the selectors the
    source binding actually needs) for a source block with no competence
    owner:

    - ``kompetenz`` (SEK1.M): the items already nested on the competence
      record itself (the V-27 verbatim text-repetition join).
    - ``bereich`` (SEK1.D): looked up in
      ``meta.anwendungsbereiche_bloecke["<SLUG>.<STUFE>"]`` -- items attach
      to the competence's area *and* class year, shared by every competence
      of that (area, year), never invented as a per-competence link the
      source does not make.
    - ``stufe`` (PRIM.D, PRIM.SU): looked up in
      ``meta.anwendungsbereiche_bloecke["<STUFE>"]`` -- items attach to the
      class year only, shared across the whole year regardless of area.
    - ``prosa`` (SEK1.E), ``keine`` (PRIM.M): always ``[]`` -- the source
      makes no such link (V-27/V-54), not a lookup failure.

    Coordinate requirements reflect that structure: ``bereich`` needs
    ``fach``, ``stufe`` and ``bereich``; ``stufe`` needs ``fach`` and
    ``stufe`` and rejects ``bereich`` because the source does not attach its
    year-wide block to an area; ``kompetenz`` requires a competence ID;
    ``prosa``/``keine`` are defined-empty.  ``kompetenz_id`` and coordinates
    are mutually exclusive.

    ``nur_verbindlich=True``/``False`` filters on the item's own
    ``verbindlich`` flag. **This split is only meaningful for SEK1.M**: its
    ``allenfalls`` marker is the only source of non-binding items (32 of
    237); the other five shards mark every item ``verbindlich: true``, so
    ``nur_verbindlich=False`` legitimately returns ``[]`` there -- that is
    the true 0/N split, not a bug in this function, and callers must not
    read it as "the flag doesn't work here". ``nur_verbindlich=None``
    (default) returns every item regardless of the flag.
    """
    _koordinaten_modus_pruefen(kompetenz_id, fach, stufe, bereich)
    if kompetenz_id is not None:
        k = kompetenz_nach_id(kompetenz_id)
        fach_schluessel = k["fach"]
        shard_dir = _shard_verzeichnis(fach_schluessel)
        index = _index_laden(shard_dir)
        bindung = index["meta"]["anwendungsbereiche_bindung"]

        if bindung == "kompetenz":
            items = list(k.get("anwendungsbereiche", []))
        elif bindung in ("prosa", "keine"):
            items = []
        elif bindung in ("bereich", "stufe"):
            doc = _teil_laden(shard_dir, k["datei"])
            bloecke = doc.get("meta", {}).get("anwendungsbereiche_bloecke") or {}
            schluessel = (
                f"{k.get('bereich_slug')}.{k['stufe']}"
                if bindung == "bereich"
                else k["stufe"]
            )
            block = bloecke.get(schluessel)
            items = list(block["items"]) if block else []
        else:
            raise KompetenzFehler(f"unbekannte anwendungsbereiche_bindung {bindung!r}")
    else:
        # _koordinaten_modus_pruefen guarantees fach here.
        items = _anwendungsbereiche_aus_koordinaten(fach, stufe, bereich)  # type: ignore[arg-type]

    # V-54: an Anwendungsbereiche block can in principle carry
    # digitale_technologien-tagged entries alongside praezisierung ones
    # (measured: SEK1.M's 39 are never nested onto a competence at all, and
    # no other shard has any digitale_technologien items today) -- filter
    # explicitly rather than relying on that always being true.
    items = [i for i in items if i.get("art") == "praezisierung"]

    if nur_verbindlich is True:
        items = [i for i in items if i.get("verbindlich") is True]
    elif nur_verbindlich is False:
        items = [i for i in items if i.get("verbindlich") is False]
    return items


# ---------------------------------------------------------------------------
# 4. finde_lehrstoff
# ---------------------------------------------------------------------------


def finde_lehrstoff(
    kompetenz_id: str | None = None,
    *,
    fach: str | None = None,
    stufe: str | None = None,
    bereich: str | None = None,
) -> dict[str, Any]:
    """``{quelle, items}`` -- ``quelle`` from ``meta.lehrstoff_quelle``.

    ``aus_anwendungsbereichen`` (five of six shards): items are the
    precisifying Anwendungsbereiche item texts (:func:`finde_anwendungsbereiche`,
    which already filters to ``art == "praezisierung"`` -- V-54).

    ``eigen_ausgewiesen`` (PRIM.M only): **PRIM.M's Lehrstoff IS its
    competence records** -- there is no separate Lehrstoff field and none
    is missing (V-45, closed 2026-08-03). ``items`` is the single verbatim
    quotation of this competence itself (``stammsatz`` + ``text``, never
    ``text`` alone), not a placeholder and not an error.

    The same additive keyword-only coordinate mode as
    :func:`finde_anwendungsbereiche` is available only for
    ``aus_anwendungsbereichen`` source blocks.  ``eigen_ausgewiesen`` and
    ``kompetenz`` binding remain competence-specific and therefore require a
    competence ID rather than aggregating or inventing a quotation.
    """
    _koordinaten_modus_pruefen(kompetenz_id, fach, stufe, bereich)
    k = kompetenz_nach_id(kompetenz_id) if kompetenz_id is not None else None
    fach_schluessel = k["fach"] if k is not None else fach
    shard_dir = _shard_verzeichnis(fach_schluessel)  # type: ignore[arg-type]
    index = _index_laden(shard_dir)
    quelle = index["meta"]["lehrstoff_quelle"]

    if quelle == "eigen_ausgewiesen":
        if k is None:
            raise ValueError("lehrstoff_quelle 'eigen_ausgewiesen' erfordert eine kompetenz_id")
        items = [k["volltext"]]
    elif quelle == "aus_anwendungsbereichen":
        if k is not None:
            anwendungsbereiche = finde_anwendungsbereiche(kompetenz_id)
        else:
            anwendungsbereiche = finde_anwendungsbereiche(
                fach=fach_schluessel, stufe=stufe, bereich=bereich
            )
        items = [i["text"] for i in anwendungsbereiche]
    else:
        raise KompetenzFehler(f"unbekannte lehrstoff_quelle {quelle!r}")

    return {"quelle": quelle, "items": items}


# ---------------------------------------------------------------------------
# 5. finde_lernaufgaben (docs/ only)
# ---------------------------------------------------------------------------

#: Minimal folder-name -> Fachcode alias table (plan §6.6). Full ingestion
#: (pdf/docx conversion, docs/.cache/, size/count/token limits) is E6-05's
#: scope, not this task's -- see the 2026-08-03 deviations.md row.
_DOCS_FACH_ALIAS: dict[str, str] = {
    "mathematik": "M",
    "deutsch": "D",
    "englisch": "E",
    "sachunterricht": "SU",
    "m": "M",
    "d": "D",
    "e": "E",
    "su": "SU",
}

_STUFE_TOKENS = {f"K{n}" for n in range(1, 5)} | {f"SCH{n}" for n in range(1, 5)}


def _docs_stufe_normalisieren(roh: str) -> str | None:
    kandidat = roh.strip().upper()
    if kandidat in _STUFE_TOKENS:
        return kandidat
    return None


def finde_lernaufgaben(
    fach: str | None = None,
    stufe: str | None = None,
    kompetenz_id: str | None = None,
    docs_root: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Teacher-supplied material from ``docs/`` only -- never official/RIS.

    Missing or empty ``docs/`` returns ``[]`` and the calling flow
    continues normally (plan §6.6). This is a minimal, interim reader for
    E4-01: native ``.md``/``.txt`` files only, matched against the folder
    convention ``docs/<fach>/<stufe>/…`` | ``docs/<fach>/…`` | ``docs/…``
    (unassigned). PDF/DOCX conversion, ``docs/.cache/``, and the
    size/count/token limits are §6.6's full ingestion contract (backlog
    E6-05) and are **not** implemented here -- an unconvertible file is
    silently skipped rather than logged as unusable, which E6-05 must
    still add.

    Every returned entry carries ``herkunft: "docs"`` and ``amtlich:
    False`` -- teacher material is never presented as official.
    """
    if kompetenz_id is not None and fach is None:
        try:
            k = kompetenz_nach_id(kompetenz_id)
            fach = k["fach"]
            stufe = stufe or k["stufe"]
        except KompetenzNichtGefunden:
            LOGGER.warning("finde_lernaufgaben: kompetenz_id %s nicht gefunden", kompetenz_id)

    wurzel = Path(docs_root) if docs_root is not None else Path("docs")
    if not wurzel.is_dir():
        return []

    ziel_fach_code: str | None = None
    if fach:
        f = fach.strip().upper()
        ziel_fach_code = f.split(".", 1)[1] if "." in f else f

    ziel_stufe = stufe.strip().upper() if stufe else None

    ergebnisse: list[dict[str, Any]] = []
    for pfad in sorted(wurzel.rglob("*")):
        if not pfad.is_file():
            continue
        rel = pfad.relative_to(wurzel)
        teile = rel.parts
        if any(teil.startswith(".") for teil in teile):
            # Hidden files/dirs, notably docs/.cache/ (the §6.6 conversion
            # cache -- never source content) and dotfiles in general.
            continue
        if pfad.suffix.lower() not in (".md", ".txt"):
            continue
        if len(teile) == 1 and pfad.name.casefold() == "readme.md":
            # docs/README.md is this folder's own scaffolding/instructions
            # (the one non-.gitkeep file the repo commits at docs/ root,
            # see .gitignore), never a teacher-authored Lernaufgabe.
            continue

        erkannter_fach = _DOCS_FACH_ALIAS.get(teile[0].casefold()) if teile else None
        erkannte_stufe = None
        if erkannter_fach and len(teile) >= 3:
            erkannte_stufe = _docs_stufe_normalisieren(teile[1])

        if ziel_fach_code is not None and erkannter_fach != ziel_fach_code:
            # An unrecognised folder is listed as *unassigned* rather than
            # discarded (plan §6.6) when browsing docs/ without a fach
            # filter -- but it must not spuriously match a caller that asked
            # for one specific subject's material.
            continue
        if ziel_stufe is not None and erkannte_stufe is not None and erkannte_stufe != ziel_stufe:
            continue

        text = pfad.read_text(encoding="utf-8", errors="replace")
        titel = pfad.stem
        for zeile in text.splitlines():
            zeile = zeile.strip()
            if zeile.startswith("#"):
                titel = zeile.lstrip("#").strip() or titel
                break

        ergebnisse.append(
            {
                "titel": titel,
                "pfad": str(rel),
                "fach": f"?.{erkannter_fach}" if erkannter_fach else None,
                "stufe": erkannte_stufe,
                "text": text,
                "herkunft": "docs",
                "amtlich": False,
            }
        )

    return ergebnisse


# ---------------------------------------------------------------------------
# 6. finde_bildungsstandard_bezug
# ---------------------------------------------------------------------------


def finde_bildungsstandard_bezug(kompetenz_id: str) -> dict[str, Any]:
    """Read ``meta.bildungsstandard_bezug``.

    ``keine_verordnung`` (PRIM.SU, the *only* shard without a Bildungsstandard
    -- read from the data, never a hardcoded "Sachunterricht" special case):
    ``{"abgedeckt": False, "grund": "keine BiSt verordnet"}``, a
    defined-empty result, not an error.

    ``verordnet`` (the other five): a Bildungsstandard exists in law for
    this shard, but the per-competence descriptor crosswalk
    (``plugin/data/bildungsstandards/``, backlog E8) has not been built yet
    -- that directory ships only a ``.gitkeep`` today. This function
    reports that honestly (``abgedeckt: True``, empty ``deskriptoren``,
    plus a ``hinweis``) instead of fabricating descriptor content; see the
    2026-08-03 deviations.md row.
    """
    k = kompetenz_nach_id(kompetenz_id)
    shard_dir = _shard_verzeichnis(k["fach"])
    index = _index_laden(shard_dir)
    bezug = index["meta"]["bildungsstandard_bezug"]

    if bezug == "keine_verordnung":
        return {"abgedeckt": False, "grund": "keine BiSt verordnet"}
    if bezug == "verordnet":
        return {
            "abgedeckt": True,
            "deskriptoren": [],
            "hinweis": "Bildungsstandards-Crosswalk noch nicht erstellt (E8 offen)",
        }
    raise KompetenzFehler(f"unbekannter bildungsstandard_bezug {bezug!r}")


# ---------------------------------------------------------------------------
# 7. finde_uebergreifende_themen
# ---------------------------------------------------------------------------


def finde_uebergreifende_themen(
    fach: str | None = None,
    kompetenz_id: str | None = None,
    thema: str | None = None,
) -> list[Any]:
    """Cross-cutting themes ("übergreifende Themen"), in exactly one of
    three modes -- pass exactly one of ``fach``, ``kompetenz_id``, ``thema``:

    - ``kompetenz_id``: that competence's own ``uebergreifende_themen``
      array (``Thema[]``, a list of theme-name strings; omitted/empty on
      the shipped record means no theme is tagged there, not "unknown" --
      the optional array is only ever emitted when non-empty).
    - ``fach``: the full theme catalogue registered for that subject,
      ``meta.uebergreifende_themen_fach`` (``Thema[]``).
    - ``thema``: every shard (of all six) whose catalogue includes this
      theme (``Fach[]``, one dict per matching shard with its key, band and
      German display name) -- a cheap scan since it only reads each
      shard's ``index.json`` meta, never a full-fach load.
    """
    angegeben = [x for x in (fach, kompetenz_id, thema) if x is not None]
    if len(angegeben) != 1:
        raise ValueError(
            "finde_uebergreifende_themen erwartet genau eines von fach, kompetenz_id, thema"
        )

    if kompetenz_id is not None:
        k = kompetenz_nach_id(kompetenz_id)
        return list(k.get("uebergreifende_themen", []))

    if fach is not None:
        shard_dir = _shard_verzeichnis(fach)
        index = _index_laden(shard_dir)
        return list(index["meta"].get("uebergreifende_themen_fach", []))

    ziel = thema.strip().casefold() if thema else ""
    treffer: list[dict[str, Any]] = []
    for fach_schluessel in ALLE_FAECHER:
        shard_dir = _shard_verzeichnis(fach_schluessel)
        index = _index_laden(shard_dir)
        themen = [t.casefold() for t in index["meta"].get("uebergreifende_themen_fach", [])]
        if ziel in themen:
            treffer.append(
                {
                    "fach": fach_schluessel,
                    "band": index["meta"]["band"],
                    "name": index["meta"]["fach"]["name"],
                }
            )
    return treffer


# ---------------------------------------------------------------------------
# 8. finde_differenzierung
# ---------------------------------------------------------------------------


def _stufe_liegt_ab(stufe: str, grenze: str) -> bool:
    """Whether a stage is on/after a metadata-declared stage boundary.

    Shipped stages use a textual family plus an ordinal (``K1``..``K4`` or
    ``SCH1``..``SCH4``).  A boundary is meaningful only within its own
    family; unknown or incompatible forms are conservatively inactive
    rather than silently exposing labels too early.
    """
    muster = re.compile(r"^([A-Z]+)([1-9][0-9]*)$")
    aktuell = muster.fullmatch(stufe.upper())
    ab = muster.fullmatch(grenze.upper())
    if aktuell is None or ab is None or aktuell.group(1) != ab.group(1):
        LOGGER.warning(
            "Ungültige oder inkompatible Differenzierungsstufen: %r ab %r",
            stufe,
            grenze,
        )
        return False
    return int(aktuell.group(2)) >= int(ab.group(2))


def finde_differenzierung(kompetenz_id: str) -> dict[str, Any]:
    """``{achse, niveaus[], enrichment_items[], vorklasse_stuetzen[],
    docs_material[]}``, read from ``meta.differenzierungs_achse`` -- never
    re-derived, never a hardcoded subject list.

    ``achse`` is the axis dict verbatim (``typ`` is ``standard_standardplus``
    for SEK1 D/M/E, from K2 up, or ``lehrplan_generisch`` for the three
    primary shards; SEK1.E additionally carries a ``gers`` sub-axis whose
    ``je_stufe_ausgewiesen`` is ``False`` -- its A1/A2/B1 list is a
    subject-level statement, not a per-class-year mapping, and this
    function does not pretend otherwise). ``niveaus`` are labels (V-60),
    never a per-item filter.  They are the labels effective at the queried
    competence's stage: if the verbatim metadata has ``gilt_ab_stufe`` they
    are ``[]`` before that boundary (K1 for the Sek I axis) and the axis's
    labels at/after it; ``achse`` itself always remains verbatim metadata.

    ``enrichment_items`` is the ``allenfalls`` content -- **only present at
    all when the axis itself carries ``enrichment_quelle: "allenfalls"``**,
    which is true for SEK1.M alone (dispatched on that data field, not on
    "is this SEK1.M"). Every other shard returns ``[]`` here: the "above"
    tier elsewhere is skill-authored elaboration on binding text, not a
    dataset query (V-60).

    ``vorklasse_stuetzen`` is always the positional predecessor
    competence(s) (:func:`finde_progression`, ``richtung="zurueck"``),
    which is available for every shard because progression is a clean area
    x year grid everywhere (V-30).  SEK1.M's official "Wiederholen und
    Festigen" application-item backlinks are evidence for that graph, not
    a second, mixed-type support result; callers can obtain those items via
    :func:`finde_anwendungsbereiche`.

    ``docs_material`` is whatever :func:`finde_lernaufgaben` finds for this
    competence's fach/stufe in ``docs/`` -- ``[]`` when ``docs/`` is
    missing or has nothing relevant.
    """
    k = kompetenz_nach_id(kompetenz_id)
    shard_dir = _shard_verzeichnis(k["fach"])
    index = _index_laden(shard_dir)
    achse = index["meta"]["differenzierungs_achse"]
    gilt_ab_stufe = achse.get("gilt_ab_stufe")
    niveaus = list(achse.get("niveaus", []))
    if gilt_ab_stufe and not _stufe_liegt_ab(k["stufe"], gilt_ab_stufe):
        niveaus = []

    enrichment_items: list[dict[str, Any]] = []
    if achse.get("enrichment_quelle") == "allenfalls":
        enrichment_items = finde_anwendungsbereiche(kompetenz_id, nur_verbindlich=False)

    # E4-03 establishes one public, positional competence graph for all
    # six shards.  Do not replace its rich Kompetenz results with raw
    # SEK1.M application items merely because an official Wiederholen item
    # carries a matching backlink.
    vorklasse_stuetzen = finde_progression(kompetenz_id, "zurueck")

    docs_material = finde_lernaufgaben(fach=k["fach"], stufe=k["stufe"], kompetenz_id=kompetenz_id)

    return {
        "achse": achse,
        "niveaus": niveaus,
        "enrichment_items": enrichment_items,
        "vorklasse_stuetzen": vorklasse_stuetzen,
        "docs_material": docs_material,
    }


# ---------------------------------------------------------------------------
# 9. finde_typische_fehlvorstellungen
# ---------------------------------------------------------------------------


def finde_typische_fehlvorstellungen(kompetenz_id: str) -> list[Any]:
    """Human-curated misconception data (backlog E9) does not exist yet and
    is explicitly never agent-generated. Always returns ``[]`` -- a
    defined-empty, ``amtlich: false``-shaped result, never invented
    content -- regardless of whether *kompetenz_id* itself resolves (a
    lookup failure is logged, not raised, since the answer is the same
    either way: there is nothing to return)."""
    try:
        kompetenz_nach_id(kompetenz_id)
    except KompetenzNichtGefunden:
        LOGGER.warning("finde_typische_fehlvorstellungen: %s nicht gefunden", kompetenz_id)
    return []
