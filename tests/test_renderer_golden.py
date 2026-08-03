"""Golden DOCX coverage for both Austrian teaching-skill renderers.

The renderer writes an ordinary .docx ZIP whose member timestamps reflect the
render time.  Tests therefore compare the byte content of every named OOXML
package member, deliberately ignoring ZIP timestamps and member ordering.
"""
from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pytest


pytest.importorskip("docx", reason="python-docx is optional; DOCX golden tests are skipped")


REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_ROOT = Path(__file__).parent / "fixtures" / "renderer_goldens"
AUSTRIAN_BLOCK_TYPES = frozenset({
    "kompetenzbezug",
    "uebergreifende_themen_tag",
    "niveau_spalte",
    "herkunftsblock",
})
SYNCED_RENDERER_FILES = (
    "lesson_common.py",
    "render_lesson_docx.py",
    "render_lesson_html.py",
    "theme.css",
)


@dataclass(frozen=True)
class RendererCase:
    skill: str
    document_ids: tuple[str, ...]

    @property
    def fixture(self) -> Path:
        return REPO_ROOT / "plugin" / "skills" / self.skill / "references" / "example_lesson.json"

    @property
    def renderer(self) -> Path:
        return REPO_ROOT / "plugin" / "skills" / self.skill / "scripts" / "render_documents.py"

    @property
    def golden_dir(self) -> Path:
        return GOLDEN_ROOT / self.skill


CASES = (
    RendererCase(
        skill="at-unterrichtsplanung",
        document_ids=("unterrichtsplanung", "schueler_material", "beobachtungsbogen"),
    ),
    RendererCase(
        skill="at-differenzierung",
        document_ids=("differenzierungsplan",),
    ),
)


def docx_parts(path: Path) -> dict[str, bytes]:
    """Return the OOXML payload map, excluding unstable ZIP container metadata."""
    with zipfile.ZipFile(path) as source:
        names = source.namelist()
        assert len(names) == len(set(names)), f"duplicate DOCX member name in {path}"
        return {name: source.read(name) for name in names}


def _render(case: RendererCase, outdir: Path) -> dict[str, dict[str, bytes]]:
    result = subprocess.run(
        [
            sys.executable,
            str(case.renderer),
            str(case.fixture),
            "--format",
            "docx",
            "--outdir",
            str(outdir),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return {
        document_id: docx_parts(outdir / f"{document_id}.docx")
        for document_id in case.document_ids
    }


def _block_types(value: object) -> set[str]:
    if isinstance(value, dict):
        found = {value["type"]} if isinstance(value.get("type"), str) else set()
        for child in value.values():
            found.update(_block_types(child))
        return found
    if isinstance(value, list):
        return set().union(*(_block_types(child) for child in value)) if value else set()
    return set()


def test_fixtures_cover_all_austrian_block_types() -> None:
    """Keep the fixtures that feed the goldens from silently losing new blocks."""
    types_by_skill = {
        case.skill: _block_types(json.loads(case.fixture.read_text(encoding="utf-8")))
        for case in CASES
    }
    assert {"kompetenzbezug", "uebergreifende_themen_tag", "herkunftsblock"} <= (
        types_by_skill["at-unterrichtsplanung"]
    )
    assert AUSTRIAN_BLOCK_TYPES <= types_by_skill["at-differenzierung"]
    assert AUSTRIAN_BLOCK_TYPES <= set().union(*types_by_skill.values())


def test_paired_renderer_sources_stay_byte_identical() -> None:
    planning = REPO_ROOT / "plugin" / "skills" / "at-unterrichtsplanung" / "scripts"
    differentiation = REPO_ROOT / "plugin" / "skills" / "at-differenzierung" / "scripts"
    for filename in SYNCED_RENDERER_FILES:
        assert (planning / filename).read_bytes() == (differentiation / filename).read_bytes()


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.skill)
def test_fixture_docx_matches_byte_stable_golden(case: RendererCase, tmp_path: Path) -> None:
    """Render each skill twice, then fail on any OOXML payload byte difference."""
    first = _render(case, tmp_path / "first")
    second = _render(case, tmp_path / "second")
    for document_id in case.document_ids:
        assert first[document_id] == second[document_id], (
            f"{case.skill}/{document_id}.docx is not deterministic in its OOXML payload"
        )
        expected = docx_parts(case.golden_dir / f"{document_id}.docx")
        assert first[document_id] == expected, (
            f"{case.skill}/{document_id}.docx differs from its golden file"
        )
