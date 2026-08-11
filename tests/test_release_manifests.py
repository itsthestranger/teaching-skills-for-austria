"""The two plugin manifests must agree on the release version.

`plugin.json` carries the plugin's own `version`; `marketplace.json` repeats it
in its `plugins[]` entry.  Nothing forced them to agree, and a drift is a silent
release bug: plan §2 records that Claude Code only delivers updates when
`plugin.json`'s `version` is bumped, while the marketplace entry is what a user
sees before installing.  A mismatch therefore ships an install that advertises
one version and reports another, with every test still green.

The CI `plugin-manifest` job checks the manifests *parse* and that release
placeholders are gone; it does not compare them to each other.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_MANIFEST = REPO_ROOT / "plugin" / ".claude-plugin" / "plugin.json"
MARKETPLACE_MANIFEST = REPO_ROOT / "plugin" / ".claude-plugin" / "marketplace.json"

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def _plugin() -> dict:
    return json.loads(PLUGIN_MANIFEST.read_text(encoding="utf8"))


def _marketplace_entry() -> dict:
    daten = json.loads(MARKETPLACE_MANIFEST.read_text(encoding="utf8"))
    eintraege = daten["plugins"]
    assert len(eintraege) == 1, f"expected exactly one marketplace entry, got {len(eintraege)}"
    return eintraege[0]


def test_both_manifests_declare_the_same_version():
    plugin_version = _plugin()["version"]
    markt_version = _marketplace_entry()["version"]
    assert plugin_version == markt_version, (
        f"plugin.json says {plugin_version!r} but marketplace.json says {markt_version!r} -- "
        "a user would install one version and be told another"
    )


def test_version_is_semver():
    for label, version in (("plugin", _plugin()["version"]),
                           ("marketplace", _marketplace_entry()["version"])):
        assert SEMVER.match(version), f"{label} version {version!r} is not MAJOR.MINOR.PATCH"


def test_plugin_name_matches_the_marketplace_entry():
    assert _plugin()["name"] == _marketplace_entry()["name"]
