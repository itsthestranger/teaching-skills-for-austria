"""Tests for shipped data integrity (E12-01).

This module enforces that shipped data files have not drifted due to
unintended changes in the parser or build pipeline. The guard exists to make
any drift visible and reviewed, not to forbid deliberate improvements.

A change that legitimately alters output updates shipped_shards.sha256 in
the same commit; a change that should not alter output must leave it untouched.

Run: .venv/bin/python -m pytest data-pipeline/tests -q

Regenerate the manifest (run from the repo root, after a deliberate change to
shipped data). Rewrites the hash lines and keeps the comment header intact:

    M=data-pipeline/tests/shipped_shards.sha256
    { sed -n '1,/^$/p' "$M"; \
      sha256sum $(find plugin/data/kompetenzen -type f -name '*.json' | sort) \
                plugin/data/abbildungen/registry.json | sort -k2; \
    } > "$M.tmp" && mv "$M.tmp" "$M"

Do not append (``>>``) — that duplicates entries and leaves stale hashes in
place, which the tests below would then report as a mismatch against a file
that is in fact correct.
"""

from __future__ import annotations

import hashlib
import unittest
from pathlib import Path


_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
_MANIFEST_PATH = _HERE / "shipped_shards.sha256"
_KOMPETENZEN_ROOT = _REPO_ROOT / "plugin" / "data" / "kompetenzen"
_REGISTRY_PATH = _REPO_ROOT / "plugin" / "data" / "abbildungen" / "registry.json"


def _compute_sha256(file_path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


def _load_manifest() -> dict[str, str]:
    """Load manifest as {repo_relative_path: expected_sha256_hex}.

    Skips comment lines (starting with #) and whitespace.
    """
    manifest = {}
    with open(_MANIFEST_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                hex_hash, path = parts[0], parts[1]
                manifest[path] = hex_hash
    return manifest


def _discover_shipped_json_files() -> set[str]:
    """Discover all shipped *.json files.

    Returns set of repo-relative paths:
    - All *.json under plugin/data/kompetenzen/
    - plugin/data/abbildungen/registry.json (if it exists)
    """
    files = set()

    # Kompetenzen JSONs
    if _KOMPETENZEN_ROOT.exists():
        for fpath in _KOMPETENZEN_ROOT.rglob("*.json"):
            rel_path = fpath.relative_to(_REPO_ROOT)
            files.add(str(rel_path))

    # Registry
    if _REGISTRY_PATH.exists():
        rel_path = _REGISTRY_PATH.relative_to(_REPO_ROOT)
        files.add(str(rel_path))

    return files


class TestShippedBytes(unittest.TestCase):
    """Enforce manifest integrity and discover drift."""

    def test_every_manifest_entry_matches_its_hash(self) -> None:
        """Test A: Every file listed in the manifest has the expected SHA-256."""
        manifest = _load_manifest()

        failures = []
        for rel_path, expected_hex in manifest.items():
            file_path = _REPO_ROOT / rel_path

            if not file_path.exists():
                failures.append(
                    f"Manifest entry points to missing file: {rel_path}"
                )
                continue

            actual_hex = _compute_sha256(file_path)
            if actual_hex != expected_hex:
                failures.append(
                    f"Hash mismatch for {rel_path}:\n"
                    f"  Expected: {expected_hex}\n"
                    f"  Actual:   {actual_hex}\n"
                    f"If the change was intended, regenerate data-pipeline/tests/shipped_shards.sha256 "
                    f"in the same commit. If it was not intended, the build has silently altered shipped data."
                )

        self.assertEqual([], failures, "\n".join(failures))

    def test_no_unlisted_shipped_json_file(self) -> None:
        """Test B: Every shipped *.json file is listed in the manifest."""
        manifest = _load_manifest()
        discovered = _discover_shipped_json_files()

        manifest_files = set(manifest.keys())
        unlisted = discovered - manifest_files

        self.assertEqual(
            set(),
            unlisted,
            f"Found shipped JSON files not in manifest: {sorted(unlisted)}\n"
            f"Add them to data-pipeline/tests/shipped_shards.sha256 and update the test."
        )

    def test_manifest_entries_point_to_existing_files(self) -> None:
        """Test C: No manifest entry points to a missing file."""
        manifest = _load_manifest()

        missing = []
        for rel_path in manifest.keys():
            file_path = _REPO_ROOT / rel_path
            if not file_path.exists():
                missing.append(rel_path)

        self.assertEqual(
            [],
            missing,
            f"Manifest entries point to missing files: {missing}"
        )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(unittest.main())
