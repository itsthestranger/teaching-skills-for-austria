#!/usr/bin/env python3
"""Fetch Austrian curriculum regulations from the RIS (Rechtsinformationssystem
des Bundes) open-data API.

Python standard library only: urllib.request, json, hashlib, argparse,
pathlib, time. No third-party HTTP client.

For each of the three tracked regulations (Volksschule, Mittelschule,
Bildungsstandards-Verordnung) this script:

1. Queries the RIS OGD discovery endpoint (JSON) for the "Anl. 1" (annex 1)
   node that is currently in force.
2. Downloads the XML (primary, for parsing) and PDF (backup) content for
   that node into ``data-pipeline/resources/<key>/``.
3. Records provenance (NOR id, ELI, in-force dates, checksums, ...) in
   ``data-pipeline/resources/manifest.json``.

Usage:
    python3 fetch_ris_resources.py                 # fetch all three, write manifest
    python3 fetch_ris_resources.py --dry-run        # resolve only, write nothing
    python3 fetch_ris_resources.py --allow-fallback # permit direct-NOR path
    python3 fetch_ris_resources.py --self-test      # offline correctness check

Politeness: at most one HTTP request per second, exponential backoff with a
capped retry count on transient failures, and a descriptive User-Agent that
carries a contact address (see USER_AGENT below).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path
from typing import Any, Callable

from abbildungen import IMAGE_SRC_RE, RIS_HOST

DeviationSink = Callable[[str, str, str, str], None]

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
RESOURCES_DIR = SCRIPT_DIR / "resources"
MANIFEST_PATH = RESOURCES_DIR / "manifest.json"
DEVIATIONS_PATH = SCRIPT_DIR / "notes" / "deviations.md"
FIXTURE_PATH = SCRIPT_DIR / "tests" / "fixtures" / "ris_search_volksschule.json"

DISCOVERY_URL = "https://data.bka.gv.at/ris/api/v2.6/Bundesrecht"

# Direct-NOR fallback, used only when discovery fails and --allow-fallback
# is passed. Host is www.ris.bka.gv.at, NOT data.bka.gv.at (V-05).
FALLBACK_URL_TMPL = "https://www.ris.bka.gv.at/Dokumente/Bundesnormen/{nor}/{nor}.{ext}"

# Identity sent to RIS on every request: a real project URL and a reachable contact
# address, as the RIS terms of use expect for automated retrieval (plan Section 2).
USER_AGENT = (
    "teaching-skills-austria/0.1 "
    "(+https://github.com/itsthestranger/teaching-skills-for-austria; "
    "contact: ps@strangeprojects.com)"
)

# Politeness: max 1 request/second, exponential backoff, sane retry cap.
MIN_REQUEST_INTERVAL_SECONDS = 1.0
MAX_RETRIES = 5
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_MAX_SECONDS = 60.0
REQUEST_TIMEOUT_SECONDS = 30

# The three regulations this pipeline tracks, per FINDINGS.md V-03.
REGULATIONS: dict[str, dict[str, str]] = {
    "volksschule": {
        "gesetzesnummer": "10009275",
        "expected_nor": "NOR40271469",
        "kurztitel": "Lehrplan der Volksschule",
    },
    "mittelschule": {
        "gesetzesnummer": "20007850",
        "expected_nor": "NOR40271471",
        "kurztitel": "Lehrpläne der Mittelschulen",
    },
    "bildungsstandards": {
        "gesetzesnummer": "20006166",
        "expected_nor": "NOR40255561",
        "kurztitel": "Bildungsstandards-Verordnung",
    },
}

ANNEX_MARKER = "Anl. 1"

#: Namespace every RIS XML element lives in (same constant as parse_lehrplan.py).
XML_NS = "{http://www.bka.gv.at}"


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class RisDiscoveryError(Exception):
    """Raised when the discovery endpoint cannot be reached or parsed."""


class RisSelectionError(Exception):
    """Raised when the Anl. 1 in-force node cannot be selected unambiguously."""


# --------------------------------------------------------------------------
# Logging helpers
# --------------------------------------------------------------------------


def log(msg: str) -> None:
    print(f"[fetch_ris_resources] {msg}", file=sys.stderr)


def log_deviation(
    source: str,
    expected: str,
    actual: str,
    resolution: str,
    path: Path = DEVIATIONS_PATH,
) -> None:
    """Append a row to data-pipeline/notes/deviations.md.

    Only called when the live API contradicts a fact this script was built
    against -- e.g. an unexpected NOR id, or a selection ambiguity that had
    to be broken deterministically instead of matching cleanly.

    Callers that want to observe a deviation without touching the real file
    (self-test, unit checks) should pass their own ``deviation_sink``
    callable through to the functions below instead of calling this
    directly.
    """
    today = date.today().isoformat()
    row = f"| {today} | {source} | {expected} | {actual} | {resolution} |\n"
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(row)
        log(f"deviation logged: {source}: expected={expected!r} actual={actual!r}")
    except OSError as exc:  # pragma: no cover - defensive only
        log(f"WARNING: could not write deviation log: {exc}")


# --------------------------------------------------------------------------
# HTTP client: rate-limited, retrying, stdlib-only
# --------------------------------------------------------------------------


class HttpClient:
    """Thin wrapper around urllib.request enforcing politeness rules."""

    def __init__(
        self,
        min_interval: float = MIN_REQUEST_INTERVAL_SECONDS,
        max_retries: int = MAX_RETRIES,
        backoff_base: float = BACKOFF_BASE_SECONDS,
        backoff_max: float = BACKOFF_MAX_SECONDS,
        sleep_fn=time.sleep,
        clock_fn=time.monotonic,
    ) -> None:
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max
        self._sleep = sleep_fn
        self._clock = clock_fn
        self._last_request_at: float | None = None

    def _throttle(self) -> None:
        if self._last_request_at is None:
            return
        elapsed = self._clock() - self._last_request_at
        remaining = self.min_interval - elapsed
        if remaining > 0:
            self._sleep(remaining)

    def _retryable(self, exc: BaseException) -> bool:
        if isinstance(exc, urllib.error.HTTPError):
            return exc.code in (429, 500, 502, 503, 504)
        if isinstance(exc, (urllib.error.URLError, TimeoutError, OSError)):
            return True
        return False

    def get_bytes(self, url: str) -> bytes:
        last_exc: BaseException | None = None
        for attempt in range(self.max_retries + 1):
            self._throttle()
            self._last_request_at = self._clock()
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(
                    req, timeout=REQUEST_TIMEOUT_SECONDS
                ) as resp:
                    return resp.read()
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_exc = exc
                if attempt >= self.max_retries or not self._retryable(exc):
                    raise
                delay = min(
                    self.backoff_base * (2**attempt), self.backoff_max
                )
                log(
                    f"request failed ({exc}); retry {attempt + 1}/"
                    f"{self.max_retries} in {delay:.1f}s: {url}"
                )
                self._sleep(delay)
        assert last_exc is not None
        raise last_exc

    def get_json(self, url: str) -> Any:
        raw = self.get_bytes(url)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RisDiscoveryError(f"non-JSON response from {url}: {exc}") from exc


# --------------------------------------------------------------------------
# JSON navigation helpers
# --------------------------------------------------------------------------


def normalize_list(value: Any) -> list[Any]:
    """RIS quirk: a field that is documented as a list may come back as a
    single object when there is exactly one result. Always normalise to a
    list."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def get_technisch(ref: dict) -> dict:
    return ref["Data"]["Metadaten"]["Technisch"]


def get_nor(ref: dict) -> str:
    return get_technisch(ref)["ID"]


def get_bundesrecht(ref: dict) -> dict:
    return ref["Data"]["Metadaten"]["Bundesrecht"]


def get_brkons(ref: dict) -> dict:
    return get_bundesrecht(ref)["BrKons"]


def get_allgemein(ref: dict) -> dict:
    return ref["Data"]["Metadaten"]["Allgemein"]


def get_content_urls(ref: dict) -> dict[str, str]:
    """Return {DataType: Url} for a document reference's MainDocument.

    Defensively normalises two shapes:
    - ContentUrl (documented quirk): may be a single object instead of a list.
    - ContentReference (live deviation, see data-pipeline/notes/deviations.md):
      documented as a single object, but observed as a LIST for the
      Mittelschule Anl. 1 node -- one "MainDocument" entry plus several
      "EmbeddedAttachment" PNGs (inline images in the curriculum text).
      We must select the MainDocument entry, not just take the first one.
    """
    content_ref = ref["Data"]["Dokumentliste"]["ContentReference"]
    content_refs = normalize_list(content_ref)
    main_doc = next(
        (cr for cr in content_refs if cr.get("ContentType") == "MainDocument"),
        content_refs[0] if content_refs else {},
    )
    urls = normalize_list(main_doc.get("Urls", {}).get("ContentUrl"))
    return {u["DataType"]: u["Url"] for u in urls}


# --------------------------------------------------------------------------
# Discovery (paginated JSON search)
# --------------------------------------------------------------------------


def build_discovery_url(gesetzesnummer: str, fassung_vom: str, seitennummer: int) -> str:
    params = {
        "Applikation": "BrKons",
        "Gesetzesnummer": gesetzesnummer,
        "Fassung.FassungVom": fassung_vom,
        "Seitennummer": str(seitennummer),
    }
    return DISCOVERY_URL + "?" + urllib.parse.urlencode(params)


def fetch_all_hits(
    gesetzesnummer: str, fassung_vom: str, http: HttpClient
) -> list[dict]:
    """Fetch every document reference for a Gesetzesnummer, following
    pagination via Hits/@pageSize and @pageNumber, and guarding against
    duplicate/repeated pages (dedupe by NOR id; stop if a page adds no new
    ids even though more were expected)."""
    seen: dict[str, dict] = {}
    page = 1
    total = None
    while True:
        url = build_discovery_url(gesetzesnummer, fassung_vom, page)
        try:
            data = http.get_json(url)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RisDiscoveryError(
                f"discovery request failed for Gesetzesnummer={gesetzesnummer}: {exc}"
            ) from exc

        try:
            results = data["OgdSearchResult"]["OgdDocumentResults"]
            hits = results["Hits"]
            total = int(hits["#text"])
            page_size = int(hits["@pageSize"])
            page_number = int(hits["@pageNumber"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RisDiscoveryError(
                f"unexpected discovery response shape for Gesetzesnummer="
                f"{gesetzesnummer}: {exc}"
            ) from exc

        refs = normalize_list(results.get("OgdDocumentReference"))
        new_count = 0
        for ref in refs:
            try:
                nor = get_nor(ref)
            except KeyError as exc:
                raise RisDiscoveryError(
                    f"document reference missing NOR id: {exc}"
                ) from exc
            if nor not in seen:
                seen[nor] = ref
                new_count += 1

        if len(seen) >= total:
            break
        if new_count == 0:
            # Duplicate/repeated page: the API returned nothing new even
            # though we expect more hits. Stop instead of looping forever.
            log(
                f"WARNING: page {page_number} added no new hits "
                f"({len(seen)}/{total} collected) -- stopping pagination"
            )
            break
        if page_number * page_size >= total:
            break
        page += 1

    return list(seen.values())


# --------------------------------------------------------------------------
# Annex selection
# --------------------------------------------------------------------------


def select_annex_node(
    refs: list[dict], key: str, deviation_sink: DeviationSink = log_deviation
) -> tuple[dict, bool]:
    """Select the Anl. 1 node that is currently in force.

    Rule (FINDINGS V-04): among all hits for a Gesetzesnummer, the winning
    node has ArtikelParagraphAnlage == "Anl. 1" and an empty/missing
    Ausserkrafttretensdatum. Verified unambiguous for all three tracked
    regulations (exactly one match each).

    Zero matches is always an error (no valid in-force annex exists) and
    raises RisSelectionError.

    More than one match is not expected given the verified facts, but is
    handled deterministically rather than by raising outright: the newest
    node by Inkrafttretensdatum wins, and the disambiguation is logged to
    data-pipeline/notes/deviations.md so a human can review it. Returns
    (chosen_node, disambiguated).
    """
    anl1_nodes = [
        r for r in refs if get_brkons(r).get("ArtikelParagraphAnlage") == ANNEX_MARKER
    ]
    in_force = [r for r in anl1_nodes if not get_brkons(r).get("Ausserkrafttretensdatum")]

    if len(in_force) == 1:
        return in_force[0], False

    if len(in_force) == 0:
        raise RisSelectionError(
            f"{key}: no in-force '{ANNEX_MARKER}' node found among "
            f"{len(refs)} hits ({len(anl1_nodes)} matched the annex marker)"
        )

    # len(in_force) > 1: deterministic newest-wins tie-break.
    in_force_sorted = sorted(
        in_force,
        key=lambda r: get_brkons(r).get("Inkrafttretensdatum") or "",
        reverse=True,
    )
    chosen = in_force_sorted[0]
    candidate_nors = ", ".join(get_nor(r) for r in in_force_sorted)
    deviation_sink(
        f"annex selection ({key})",
        "exactly one in-force 'Anl. 1' node",
        f"{len(in_force)} candidates: {candidate_nors}",
        f"selected newest by Inkrafttretensdatum: {get_nor(chosen)}",
    )
    return chosen, True


# --------------------------------------------------------------------------
# Fetch + manifest for one regulation
# --------------------------------------------------------------------------


def resolve_regulation(
    key: str,
    cfg: dict[str, str],
    fassung_vom: str,
    http: HttpClient,
    allow_fallback: bool,
    deviation_sink: DeviationSink = log_deviation,
) -> dict[str, Any]:
    """Resolve (but do not download) the metadata for one regulation.

    Returns a dict describing the chosen node, the content URLs, and
    whether the fallback path was used.
    """
    gesetzesnummer = cfg["gesetzesnummer"]
    expected_nor = cfg["expected_nor"]

    try:
        refs = fetch_all_hits(gesetzesnummer, fassung_vom, http)
        chosen, disambiguated = select_annex_node(refs, key, deviation_sink=deviation_sink)
        nor = get_nor(chosen)
        brkons = get_brkons(chosen)
        bundesrecht = get_bundesrecht(chosen)
        allgemein = get_allgemein(chosen)
        content_urls = get_content_urls(chosen)

        if nor != expected_nor:
            deviation_sink(
                f"resolved NOR ({key})",
                expected_nor,
                nor,
                "resolved via live discovery; expected table is stale, "
                "proceeding with the live result",
            )

        return {
            "key": key,
            "nor": nor,
            "eli": bundesrecht.get("Eli"),
            "gesetzesnummer": brkons.get("Gesetzesnummer", gesetzesnummer),
            "kurztitel": bundesrecht.get("Kurztitel", cfg["kurztitel"]),
            "kundmachungsorgan": brkons.get("Kundmachungsorgan"),
            "artikel_paragraph_anlage": brkons.get("ArtikelParagraphAnlage"),
            "inkrafttretensdatum": brkons.get("Inkrafttretensdatum"),
            "ausserkrafttretensdatum": brkons.get("Ausserkrafttretensdatum"),
            "dokument_url": allgemein.get("DokumentUrl"),
            "content_urls": content_urls,
            "fallback_used": False,
            "disambiguated": disambiguated,
        }
    except (RisDiscoveryError, RisSelectionError) as exc:
        if not allow_fallback:
            raise
        log(f"discovery failed for {key} ({exc}); falling back to direct-NOR path")
        deviation_sink(
            f"discovery ({key})",
            "successful discovery response",
            str(exc),
            f"used direct-NOR fallback for {expected_nor}",
        )
        fallback_urls = {
            "Xml": FALLBACK_URL_TMPL.format(nor=expected_nor, ext="xml"),
            "Pdf": FALLBACK_URL_TMPL.format(nor=expected_nor, ext="pdf"),
        }
        return {
            "key": key,
            "nor": expected_nor,
            "eli": None,
            "gesetzesnummer": gesetzesnummer,
            "kurztitel": cfg["kurztitel"],
            "kundmachungsorgan": None,
            "artikel_paragraph_anlage": ANNEX_MARKER,
            "inkrafttretensdatum": None,
            "ausserkrafttretensdatum": None,
            "dokument_url": fallback_urls["Xml"],
            "content_urls": fallback_urls,
            "fallback_used": True,
            "disambiguated": False,
        }


# --------------------------------------------------------------------------
# Inline images (<binary>/<src>) -- formulae shipped as PNG, see FINDINGS.md
# V-53 and the corresponding row in notes/deviations.md and
# notes/ris-xml-structure.md.
# --------------------------------------------------------------------------


def find_image_refs(xml_bytes: bytes) -> list[str]:
    """Return every distinct ``<binary>/<src>`` path in *xml_bytes*, in
    document order. Deliberately scoped to ``binary/src`` (not any ``src``
    anywhere) -- narrower than the general element census, matching the
    same discipline as parse_lehrplan.py's element_text()."""
    root = ET.fromstring(xml_bytes)
    seen: set[str] = set()
    refs: list[str] = []
    for binary in root.iter(XML_NS + "binary"):
        src = binary.find(XML_NS + "src")
        if src is None or not (src.text or "").strip():
            continue
        path = src.text.strip()
        if path not in seen:
            seen.add(path)
            refs.append(path)
    return refs


def download_images(
    key: str,
    xml_bytes: bytes,
    output_dir: Path,
    http: HttpClient,
    deviation_sink: DeviationSink = log_deviation,
) -> dict[str, dict[str, Any]]:
    """Discover and download every inline image referenced by *xml_bytes*.

    Images are written to ``<output_dir>/<key>/images/<nor>/<filename>``,
    mirroring the eventual plugin layout (``plugin/data/abbildungen/<nor>/``)
    one level down, so installing them is a straight copy -- see
    abbildungen.py. Reuses *http* (same rate limiter, User-Agent, backoff as
    the XML/PDF downloads).

    Returns ``{filename: {"nor":, "src":, "url":, "sha256":, "size":}}``.
    """
    images: dict[str, dict[str, Any]] = {}
    for path in find_image_refs(xml_bytes):
        m = IMAGE_SRC_RE.match(path)
        if not m:
            deviation_sink(
                f"image src shape ({key})",
                "/Dokumente/Bundesnormen/<NOR>/<filename>",
                path,
                "skipped -- does not match the expected shape, not downloaded",
            )
            continue
        nor, filename = m.group("nor"), m.group("filename")
        url = RIS_HOST + path
        log(f"downloading image for {key} ({nor}): {url}")
        raw = http.get_bytes(url)
        dest_dir = output_dir / key / "images" / nor
        dest_dir.mkdir(parents=True, exist_ok=True)
        (dest_dir / filename).write_bytes(raw)
        images[filename] = {
            "nor": nor,
            "src": path,
            "url": url,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size": len(raw),
        }
    return images


def download_files(
    resolved: dict[str, Any], output_dir: Path, http: HttpClient
) -> dict[str, dict[str, Any]]:
    """Download the XML and PDF for a resolved regulation. Returns a dict
    of {"xml": {"sha256":..., "size":...}, "pdf": {...}}."""
    key = resolved["key"]
    nor = resolved["nor"]
    content_urls = resolved["content_urls"]
    key_dir = output_dir / key
    key_dir.mkdir(parents=True, exist_ok=True)

    files: dict[str, dict[str, Any]] = {}
    for data_type, ext in (("Xml", "xml"), ("Pdf", "pdf")):
        url = content_urls.get(data_type)
        if url is None:
            log(f"WARNING: no {data_type} URL for {key} ({nor}); skipping")
            continue
        log(f"downloading {data_type} for {key} ({nor}): {url}")
        raw = http.get_bytes(url)
        dest = key_dir / f"{nor}.{ext}"
        dest.write_bytes(raw)
        files[ext] = {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size": len(raw),
        }
    return files


# --------------------------------------------------------------------------
# Manifest
# --------------------------------------------------------------------------


def build_manifest_entry(
    resolved: dict[str, Any],
    files: dict[str, dict[str, Any]],
    retrieval_date: str,
    images: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "artikel_paragraph_anlage": resolved["artikel_paragraph_anlage"],
        "ausserkrafttretensdatum": resolved["ausserkrafttretensdatum"],
        "disambiguated": resolved["disambiguated"],
        "dokument_url": resolved["dokument_url"],
        "eli": resolved["eli"],
        "fallback_used": resolved["fallback_used"],
        "files": files,
        "gesetzesnummer": resolved["gesetzesnummer"],
        "images": images or {},
        "inkrafttretensdatum": resolved["inkrafttretensdatum"],
        "kundmachungsorgan": resolved["kundmachungsorgan"],
        "kurztitel": resolved["kurztitel"],
        "nor": resolved["nor"],
        "retrieval_date": retrieval_date,
    }


def write_manifest(manifest: dict[str, Any], path: Path) -> None:
    """Write the manifest with sorted keys and a trailing newline so it is
    stable and diff-friendly across runs."""
    text = json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# Self-test (fully offline)
# --------------------------------------------------------------------------


def run_self_test() -> bool:
    """Exercise discovery parsing and annex selection entirely offline
    against the checked-in fixture, plus a couple of in-memory edge cases.
    Returns True on success, False on any failure (caller exits non-zero)."""
    ok = True
    recorded_deviations: list[tuple[str, str, str, str]] = []

    def recording_sink(source: str, expected: str, actual: str, resolution: str) -> None:
        # Self-test must never touch the real deviations.md -- record
        # in-memory instead, so repeated --self-test runs are side-effect
        # free.
        recorded_deviations.append((source, expected, actual, resolution))
        log(f"(recorded, not written) deviation: {source}: {expected!r} vs {actual!r}")

    def check(condition: bool, msg: str) -> None:
        nonlocal ok
        if condition:
            log(f"PASS: {msg}")
        else:
            ok = False
            log(f"FAIL: {msg}")

    # 1. normalize_list handles both shapes of the "single result" quirk.
    check(normalize_list(None) == [], "normalize_list(None) == []")
    check(normalize_list([1, 2]) == [1, 2], "normalize_list(list) is identity")
    check(normalize_list({"a": 1}) == [{"a": 1}], "normalize_list(dict) wraps in a list")

    # 2. Load the fixture and parse it the same way fetch_all_hits does.
    if not FIXTURE_PATH.exists():
        log(f"FAIL: fixture missing at {FIXTURE_PATH}")
        return False

    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    results = data["OgdSearchResult"]["OgdDocumentResults"]
    hits = results["Hits"]
    total = int(hits["#text"])
    refs = normalize_list(results.get("OgdDocumentReference"))
    check(len(refs) == total, f"fixture Hits/#text ({total}) matches reference count ({len(refs)})")

    # 3. ContentUrl quirk: at least one fixture node has a single dict, at
    #    least one has a real list -- both must normalise correctly.
    content_url_shapes = [
        ref["Data"]["Dokumentliste"]["ContentReference"]["Urls"]["ContentUrl"]
        for ref in refs
    ]
    check(
        any(isinstance(c, dict) for c in content_url_shapes),
        "fixture exercises the single-object ContentUrl quirk",
    )
    check(
        any(isinstance(c, list) for c in content_url_shapes),
        "fixture also has a normal list-shaped ContentUrl",
    )
    for ref in refs:
        urls = get_content_urls(ref)
        check(isinstance(urls, dict) and "Xml" in urls, f"get_content_urls normalises for {get_nor(ref)}")

    # 4. Selection rule on the fixture: exactly one in-force Anl. 1 node,
    #    and it must be NOR40271469 (an expired Anl. 1 node -- NOR40200001 --
    #    must be excluded, exercising the Ausserkrafttretensdatum filter).
    chosen, disambiguated = select_annex_node(refs, "volksschule", deviation_sink=recording_sink)
    check(get_nor(chosen) == "NOR40271469", f"fixture selects NOR40271469, got {get_nor(chosen)}")
    check(disambiguated is False, "fixture selection is not a disambiguation case")

    excluded_expired = any(
        get_nor(r) == "NOR40200001" for r in refs
        if get_brkons(r).get("ArtikelParagraphAnlage") == ANNEX_MARKER
        and get_brkons(r).get("Ausserkrafttretensdatum")
    )
    check(excluded_expired, "fixture contains an expired Anl. 1 node (NOR40200001) to exercise the filter")

    # 5. Zero-match case must raise.
    non_annex_refs = [r for r in refs if get_brkons(r).get("ArtikelParagraphAnlage") != ANNEX_MARKER]
    try:
        select_annex_node(non_annex_refs, "no-annex-case", deviation_sink=recording_sink)
        check(False, "zero in-force Anl. 1 nodes must raise RisSelectionError")
    except RisSelectionError:
        check(True, "zero in-force Anl. 1 nodes raises RisSelectionError")

    # 6. Multiple-match case must deterministically pick the newest and
    #    mark disambiguated=True (in-memory synthetic case, still offline).
    def make_node(nor: str, inkrafttretensdatum: str) -> dict:
        return {
            "Data": {
                "Metadaten": {
                    "Technisch": {"ID": nor},
                    "Bundesrecht": {
                        "Kurztitel": "Test",
                        "Eli": f"https://example.invalid/{nor}",
                        "BrKons": {
                            "ArtikelParagraphAnlage": ANNEX_MARKER,
                            "Inkrafttretensdatum": inkrafttretensdatum,
                            "Gesetzesnummer": "00000000",
                        },
                    },
                    "Allgemein": {"DokumentUrl": f"https://example.invalid/{nor}"},
                },
                "Dokumentliste": {
                    "ContentReference": {
                        "Urls": {
                            "ContentUrl": [
                                {"DataType": "Xml", "Url": f"https://example.invalid/{nor}.xml"}
                            ]
                        }
                    }
                },
            }
        }

    ambiguous = [make_node("NOR_OLD", "2020-01-01"), make_node("NOR_NEW", "2024-01-01")]
    chosen2, disambiguated2 = select_annex_node(
        ambiguous, "synthetic-ambiguous", deviation_sink=recording_sink
    )
    check(get_nor(chosen2) == "NOR_NEW", "ambiguous case picks newest by Inkrafttretensdatum")
    check(disambiguated2 is True, "ambiguous case is flagged as disambiguated")
    check(
        len(recorded_deviations) >= 1,
        "ambiguous case recorded a deviation in-memory (not written to disk)",
    )
    check(
        "synthetic-ambiguous" not in DEVIATIONS_PATH.read_text(encoding="utf-8"),
        "self-test never writes to the real deviations.md",
    )

    # 7. Manifest determinism: building the same entry twice must be
    #    byte-identical once serialised with sorted keys.
    resolved = {
        "key": "volksschule",
        "nor": get_nor(chosen),
        "eli": get_bundesrecht(chosen).get("Eli"),
        "gesetzesnummer": get_brkons(chosen).get("Gesetzesnummer"),
        "kurztitel": get_bundesrecht(chosen).get("Kurztitel"),
        "kundmachungsorgan": get_brkons(chosen).get("Kundmachungsorgan"),
        "artikel_paragraph_anlage": get_brkons(chosen).get("ArtikelParagraphAnlage"),
        "inkrafttretensdatum": get_brkons(chosen).get("Inkrafttretensdatum"),
        "ausserkrafttretensdatum": get_brkons(chosen).get("Ausserkrafttretensdatum"),
        "dokument_url": get_allgemein(chosen).get("DokumentUrl"),
        "fallback_used": False,
        "disambiguated": False,
    }
    files = {"xml": {"sha256": "deadbeef", "size": 123}}
    entry_a = build_manifest_entry(resolved, files, "2026-07-27")
    entry_b = build_manifest_entry(resolved, files, "2026-07-27")
    serial_a = json.dumps(entry_a, indent=2, sort_keys=True, ensure_ascii=False)
    serial_b = json.dumps(entry_b, indent=2, sort_keys=True, ensure_ascii=False)
    check(serial_a == serial_b, "manifest entry serialisation is deterministic")

    # 8. Rate limiter enforces the minimum interval (using a fake clock, no
    #    real sleeping).
    fake_time = [0.0]

    def fake_clock() -> float:
        return fake_time[0]

    slept = []

    def fake_sleep(seconds: float) -> None:
        slept.append(seconds)
        fake_time[0] += seconds

    limiter_http = HttpClient(sleep_fn=fake_sleep, clock_fn=fake_clock)
    limiter_http._last_request_at = 0.0
    fake_time[0] = 0.3  # simulate 0.3s having elapsed since the last request
    limiter_http._throttle()
    check(
        len(slept) == 1 and abs(slept[0] - 0.7) < 1e-9,
        f"rate limiter sleeps the remainder of 1s (got {slept})",
    )

    # 9. Image discovery: find_image_refs() finds <binary>/<src> paths, in
    #    document order, deduplicated, and ignores unrelated <src>-shaped
    #    text elsewhere in the document.
    sample_xml = b"""<risdok xmlns="http://www.bka.gv.at"><nutzdaten><abschnitt>
      <liste><aufzaehlung><listelem>Wert 0,6<binary nr="1">
        <src>/Dokumente/Bundesnormen/NOR40271471/hauptdokument.img1is.png</src>
      </binary></listelem></aufzaehlung></liste>
      <liste><aufzaehlung><listelem>Wert 0,7<binary nr="2">
        <src>/Dokumente/Bundesnormen/NOR40271471/hauptdokument.img2is.png</src>
      </binary><binary nr="3">
        <src>/Dokumente/Bundesnormen/NOR40271471/hauptdokument.img1is.png</src>
      </binary></listelem></aufzaehlung></liste>
    </abschnitt></nutzdaten></risdok>"""
    refs = find_image_refs(sample_xml)
    check(
        refs == [
            "/Dokumente/Bundesnormen/NOR40271471/hauptdokument.img1is.png",
            "/Dokumente/Bundesnormen/NOR40271471/hauptdokument.img2is.png",
        ],
        f"find_image_refs dedupes and preserves document order (got {refs})",
    )

    # 10. IMAGE_SRC_RE extracts (nor, filename); an unexpected shape does not
    #     match and must be handled as a skip, not a crash.
    m = IMAGE_SRC_RE.match("/Dokumente/Bundesnormen/NOR40271471/hauptdokument.img1is.png")
    check(
        m is not None and m.group("nor") == "NOR40271471"
        and m.group("filename") == "hauptdokument.img1is.png",
        "IMAGE_SRC_RE extracts nor and filename from a well-formed path",
    )
    check(
        IMAGE_SRC_RE.match("/Dokumente/Bundesnormen/hauptdokument.img1is.png") is None,
        "IMAGE_SRC_RE rejects a path missing the NOR segment",
    )

    return ok


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve and report what would be fetched; write nothing.",
    )
    parser.add_argument(
        "--allow-fallback",
        action="store_true",
        help="Permit the direct-NOR fallback path when discovery fails.",
    )
    parser.add_argument(
        "--skip-images",
        action="store_true",
        help="Text-only run: fetch XML/PDF but do not discover or download "
        "inline <binary> images.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run fully offline correctness checks against the checked-in fixture.",
    )
    parser.add_argument(
        "--fassung-vom",
        default=date.today().isoformat(),
        help="Fassung.FassungVom date (YYYY-MM-DD); defaults to today.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=RESOURCES_DIR,
        help="Directory to write resources/manifest into (default: data-pipeline/resources).",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        ok = run_self_test()
        if ok:
            log("self-test: ALL CHECKS PASSED")
            return 0
        else:
            log("self-test: FAILURES DETECTED")
            return 1

    http = HttpClient()
    manifest: dict[str, Any] = {}
    retrieval_date = date.today().isoformat()

    for key, cfg in sorted(REGULATIONS.items()):
        log(f"resolving {key} (Gesetzesnummer={cfg['gesetzesnummer']})")
        try:
            resolved = resolve_regulation(
                key, cfg, args.fassung_vom, http, args.allow_fallback
            )
        except (RisDiscoveryError, RisSelectionError) as exc:
            log(f"ERROR: failed to resolve {key}: {exc}")
            return 1

        nor = resolved["nor"]
        expected_nor = cfg["expected_nor"]
        match_str = "matches expected" if nor == expected_nor else "DOES NOT MATCH expected"
        log(
            f"{key}: resolved NOR={nor} ({match_str} {expected_nor}); "
            f"fallback_used={resolved['fallback_used']} "
            f"disambiguated={resolved['disambiguated']}"
        )

        if args.dry_run:
            log(
                f"[dry-run] would fetch: "
                f"xml={resolved['content_urls'].get('Xml')} "
                f"pdf={resolved['content_urls'].get('Pdf')}"
            )
            continue

        files = download_files(resolved, args.output_dir, http)

        images: dict[str, dict[str, Any]] = {}
        if args.skip_images:
            log(f"{key}: --skip-images set, not scanning for inline images")
        else:
            xml_path = args.output_dir / key / f"{resolved['nor']}.xml"
            if "xml" in files and xml_path.exists():
                images = download_images(
                    key, xml_path.read_bytes(), args.output_dir, http
                )
                log(f"{key}: downloaded {len(images)} inline image(s)")
            else:
                log(f"{key}: no XML on disk, skipping image discovery")

        manifest[key] = build_manifest_entry(resolved, files, retrieval_date, images)

    if args.dry_run:
        log("dry-run complete; nothing written")
        return 0

    write_manifest(manifest, args.output_dir / "manifest.json")
    log(f"manifest written to {args.output_dir / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
