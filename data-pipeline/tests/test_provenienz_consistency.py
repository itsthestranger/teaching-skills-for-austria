"""E11-04: every shipped dataset carries its retrieval date, under one field name.

Before this was pinned, the two pipelines named the same manifest field differently: the
curriculum shards mapped ``retrieval_date`` to ``provenienz.stand`` (``build_dataset.py``) while
the Bildungsstandards shards kept ``retrieval_date`` verbatim. Nothing failed, because nothing
asserted either name -- which is also how the rename could land with the suite green.

The consequence is not cosmetic: ``lesson_common.kompetenz_citation()`` builds the legal citation
line from ``nor`` and ``stand``, so a Bildungsstandards source passed to it would have rendered
without its ``Stand:`` half -- a silently shortened citation on the product's own legal promise.
The last test in this file is that regression, pinned directly.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
KOMPETENZEN_ROOT = REPO_ROOT / "plugin" / "data" / "kompetenzen"
BIST_ROOT = REPO_ROOT / "plugin" / "data" / "bildungsstandards"
CROSSWALK = BIST_ROOT / "crosswalk.json"
MANIFEST = REPO_ROOT / "data-pipeline" / "resources" / "manifest.json"

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

sys.path.insert(0, str(REPO_ROOT / "plugin" / "skills" / "at-unterrichtsplanung" / "scripts"))
import lesson_common  # noqa: E402  pylint: disable=wrong-import-position


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _curriculum_files() -> list[Path]:
    return sorted(KOMPETENZEN_ROOT.glob("*/*/*.json"))


def _bist_shards() -> list[Path]:
    return sorted(p for p in BIST_ROOT.glob("*.json") if p.name != "crosswalk.json")


def test_the_dataset_shape_is_what_these_tests_assume() -> None:
    """A guard against the assertions below quietly becoming vacuous: if a shard is removed or
    a glob stops matching, an empty file list would make every parametrised test pass."""
    assert len(_curriculum_files()) == 38, "expected the 38 shipped curriculum files"
    assert len(_bist_shards()) == 5, "expected the five shipped Bildungsstandards shards"
    assert CROSSWALK.is_file()
    assert MANIFEST.is_file(), "manifest.json is committed even though resources/ is gitignored"


@pytest.mark.parametrize("path", _curriculum_files(), ids=lambda p: f"{p.parent.parent.name}.{p.parent.name}/{p.name}")
def test_every_curriculum_file_carries_provenienz_stand(path: Path) -> None:
    stand = _load(path)["meta"]["provenienz"]["stand"]
    assert ISO_DATE.match(stand), f"{path.name}: stand is not an ISO date: {stand!r}"


@pytest.mark.parametrize("path", _bist_shards(), ids=lambda p: p.name)
def test_every_bist_shard_carries_provenienz_stand_and_not_the_manifest_name(path: Path) -> None:
    provenienz = _load(path)["meta"]["provenienz"]
    assert "stand" in provenienz, f"{path.name}: no provenienz.stand"
    assert ISO_DATE.match(provenienz["stand"])
    assert "retrieval_date" not in provenienz, (
        f"{path.name}: still carries the manifest's field name alongside/instead of `stand`"
    )


def test_the_crosswalk_dates_both_of_the_sources_it_maps() -> None:
    """The crosswalk is authored, not retrieved -- `meta.dataset_version` records when it was
    written. What needs a retrieval date is each source it maps."""
    quellen = _load(CROSSWALK)["meta"]["quellen"]
    for name in ("lehrplan", "bildungsstandards"):
        assert ISO_DATE.match(quellen[name]["stand"]), f"quellen.{name} carries no ISO `stand`"


def test_every_stand_matches_the_retrieval_date_recorded_in_the_manifest() -> None:
    """The date must be the one the fetcher actually recorded, not a plausible-looking value
    typed into the data by hand."""
    manifest = _load(MANIFEST)
    lehrplan_dates = {manifest[key]["retrieval_date"] for key in ("mittelschule", "volksschule")}
    bist_date = manifest["bildungsstandards"]["retrieval_date"]

    for path in _curriculum_files():
        assert _load(path)["meta"]["provenienz"]["stand"] in lehrplan_dates, path.name
    for path in _bist_shards():
        assert _load(path)["meta"]["provenienz"]["stand"] == bist_date, path.name

    quellen = _load(CROSSWALK)["meta"]["quellen"]
    assert quellen["lehrplan"]["stand"] in lehrplan_dates
    assert quellen["bildungsstandards"]["stand"] == bist_date


def test_one_field_name_across_both_datasets() -> None:
    """The point of the rename: a consumer reading provenance needs one name, not two."""
    names = set()
    for path in _curriculum_files() + _bist_shards():
        names.update(k for k in _load(path)["meta"]["provenienz"] if k in {"stand", "retrieval_date"})
    assert names == {"stand"}, f"provenance dates are still spelled several ways: {sorted(names)}"


def test_a_bist_provenienz_now_renders_a_complete_citation() -> None:
    """The regression the rename prevents. `kompetenz_citation` reads `stand`; under the old
    field name a Bildungsstandards source rendered a citation with no `Stand:` half at all, and
    no test would have noticed."""
    provenienz = _load(BIST_ROOT / "m4.json")["meta"]["provenienz"]
    citation = lesson_common.kompetenz_citation(provenienz)

    assert citation, "a Bildungsstandards provenienz produced no citation line"
    assert f"Stand: {provenienz['stand']}" in citation
    assert f"NOR: {provenienz['nor']}" in citation

    # Proof the assertion above is load-bearing: under the old field name the Stand half vanishes
    # while the citation still looks well-formed, which is exactly why this went unnoticed.
    alt = dict(provenienz)
    alt["retrieval_date"] = alt.pop("stand")
    degraded = lesson_common.kompetenz_citation(alt)
    assert degraded and "Stand:" not in degraded
