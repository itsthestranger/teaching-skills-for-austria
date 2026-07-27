#!/usr/bin/env python3
"""Shared PNG/Abbildung handling for the Sek I Mathematik pipeline.

The Mittelschule regulation (NOR40271471) embeds 64 inline PNG glyphs
(fraction and formula graphics) directly in the curriculum text -- see
``notes/ris-xml-structure.md`` and ``notes/deviations.md``. This module is
the one place that:

1. reads PNG width/height from the IHDR chunk with :mod:`struct` (no
   Pillow, no third-party dependency -- see module docstring rule: stdlib
   only throughout this pipeline);
2. installs images ``fetch_ris_resources.py`` has downloaded (into
   ``data-pipeline/resources/<key>/images/<nor>/``, gitignored) into
   ``plugin/data/abbildungen/<nor>/`` (shipped plugin data, committed);
3. builds the lookup registry :mod:`parse_lehrplan` uses to attach
   width/height/sha256 metadata to every record whose text carries an
   ``⟦ABB:...⟧`` token.

Usage:
    python3 abbildungen.py            # install fetched images, print summary
    python3 abbildungen.py --check    # verify installed images only, no copy

Python standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
RESOURCES_DIR = SCRIPT_DIR / "resources"
PLUGIN_ABBILDUNGEN_DIR = REPO_ROOT / "plugin" / "data" / "abbildungen"

#: Host that <binary>/<src> paths (e.g. "/Dokumente/Bundesnormen/NOR.../x.png")
#: are relative to. Same host fetch_ris_resources.py talks to.
RIS_HOST = "https://www.ris.bka.gv.at"

#: Shape of a <binary>/<src> path, e.g.
#: "/Dokumente/Bundesnormen/NOR40271471/hauptdokument.img1is.png". Shared by
#: fetch_ris_resources.py (deciding what to download) and parse_lehrplan.py
#: (resolving a reference back to its shipped-image metadata).
IMAGE_SRC_RE = re.compile(r"^/Dokumente/Bundesnormen/(?P<nor>[^/]+)/(?P<filename>[^/]+)$")

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

#: Measured fact (verified against all 64 live images): every inline glyph
#: is exactly this many pixels tall. Not enforced as a hard failure -- a
#: future amendment could legitimately add a taller diagram -- but logged
#: as a deviation if it stops holding, so a human notices.
ERWARTETE_HOEHE_PX = 17


class PngError(ValueError):
    """Raised when data is not a well-formed PNG (bad signature or IHDR)."""


def read_png_dimensions(data: bytes) -> tuple[int, int]:
    """Return (width, height) read from the IHDR chunk.

    PNG layout: 8-byte signature, then a sequence of chunks, each
    [4-byte length][4-byte type][data][4-byte CRC]. IHDR is always the
    first chunk; its data is [4-byte width][4-byte height][...], both
    big-endian unsigned ints. That is all we need -- no third-party image
    library required.
    """
    if len(data) < 24 or data[:8] != PNG_SIGNATURE:
        raise PngError("missing PNG signature (first 8 bytes)")
    chunk_type = data[12:16]
    if chunk_type != b"IHDR":
        raise PngError(f"expected IHDR as the first chunk, found {chunk_type!r}")
    width, height = struct.unpack(">II", data[16:24])
    return width, height


@dataclass(frozen=True)
class AbbildungRecord:
    """Everything downstream code needs to know about one shipped image."""

    nor: str
    dateiname: str
    pfad: str
    """Relative to the plugin root, e.g. 'data/abbildungen/NOR.../x.png' --
    the renderer resolves this against ${CLAUDE_PLUGIN_ROOT}."""

    quelle_url: str
    breite_px: int
    hoehe_px: int
    sha256: str
    groesse_bytes: int


def _record_for_file(nor: str, path: Path) -> AbbildungRecord:
    data = path.read_bytes()
    width, height = read_png_dimensions(data)
    return AbbildungRecord(
        nor=nor,
        dateiname=path.name,
        pfad=f"data/abbildungen/{nor}/{path.name}",
        quelle_url=f"{RIS_HOST}/Dokumente/Bundesnormen/{nor}/{path.name}",
        breite_px=width,
        hoehe_px=height,
        sha256=hashlib.sha256(data).hexdigest(),
        groesse_bytes=len(data),
    )


def iter_fetched_images(resources_dir: Path = RESOURCES_DIR) -> Iterator[tuple[str, str, Path]]:
    """Yield (key, nor, path) for every image fetch_ris_resources.py has
    downloaded into resources/<key>/images/<nor>/*.png."""
    if not resources_dir.exists():
        return
    for key_dir in sorted(resources_dir.iterdir()):
        images_dir = key_dir / "images"
        if not images_dir.is_dir():
            continue
        for nor_dir in sorted(images_dir.iterdir()):
            if not nor_dir.is_dir():
                continue
            for png in sorted(nor_dir.glob("*.png")):
                yield key_dir.name, nor_dir.name, png


def install_images(
    resources_dir: Path = RESOURCES_DIR,
    plugin_dir: Path = PLUGIN_ABBILDUNGEN_DIR,
) -> list[AbbildungRecord]:
    """Copy every fetched image into plugin/data/abbildungen/<nor>/.

    Dimensions and the SHA-256 are read back from the *installed* copy, not
    the source, so what gets recorded is exactly what ships.
    """
    installed: list[AbbildungRecord] = []
    for _key, nor, src in iter_fetched_images(resources_dir):
        dest_dir = plugin_dir / nor
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        dest.write_bytes(src.read_bytes())
        installed.append(_record_for_file(nor, dest))
    return installed


def build_registry(plugin_dir: Path = PLUGIN_ABBILDUNGEN_DIR) -> dict[tuple[str, str], AbbildungRecord]:
    """Registry of every shipped image, keyed by ``(nor, filename)``.

    :mod:`parse_lehrplan` uses this to attach width/height/sha256 metadata
    to every record whose text carries a matching ``⟦ABB:...⟧`` token.
    Missing directory or empty registry is not an error here -- the caller
    decides how to react to an unresolvable token (parse_lehrplan logs a
    ParseIssue rather than crashing).
    """
    registry: dict[tuple[str, str], AbbildungRecord] = {}
    if not plugin_dir.exists():
        return registry
    for nor_dir in sorted(plugin_dir.iterdir()):
        if not nor_dir.is_dir():
            continue
        nor = nor_dir.name
        for png in sorted(nor_dir.glob("*.png")):
            registry[(nor, png.name)] = _record_for_file(nor, png)
    return registry


def _cli(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--check",
        action="store_true",
        help="Only inspect plugin/data/abbildungen (no copy from resources/).",
    )
    args = ap.parse_args(argv)

    if args.check:
        registry = build_registry()
        print(f"[abbildungen] {len(registry)} image(s) installed under {PLUGIN_ABBILDUNGEN_DIR}")
        records = sorted(registry.values(), key=lambda r: (r.nor, r.dateiname))
    else:
        records = install_images()
        total_bytes = sum(r.groesse_bytes for r in records)
        print(f"[abbildungen] installed {len(records)} image(s), {total_bytes} bytes total")

    off_height = [r for r in records if r.hoehe_px != ERWARTETE_HOEHE_PX]
    for r in records:
        print(f"  {r.nor}/{r.dateiname}  {r.breite_px}x{r.hoehe_px}px  {r.sha256[:12]}...")
    if off_height:
        print(
            f"[abbildungen] NOTE: {len(off_height)} image(s) are not "
            f"{ERWARTETE_HOEHE_PX}px tall (measured-fact deviation; not fatal): "
            + ", ".join(f"{r.dateiname}={r.hoehe_px}px" for r in off_height),
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
