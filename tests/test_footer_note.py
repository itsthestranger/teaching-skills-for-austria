# Copyright 2026 Anthropic, PBC
# Copyright 2026 Learning Commons
# SPDX-License-Identifier: Apache-2.0

"""Every generated document must carry the BGBl.-precedence legal notice, whether or not the
lesson data supplies a `footer_note`.

The renderer-side default lives once, as `DEFAULT_FOOTER_NOTE` in `lesson_common.py`, and both
the docx and html renderer of both skills (`at-differenzierung`, `at-unterrichtsplanung`) fall
back to it. This must not be contingent on model behaviour — nothing upstream is expected to set
`footer_note` — so these tests render from data that omits the key entirely and assert the notice
is present regardless, and that an explicit `footer_note` still overrides the default.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS = ("at-differenzierung", "at-unterrichtsplanung")

DEFAULT_FOOTER_NOTE = (
    "Konsolidierter RIS-Text, unverbindliche Fassung. Rechtsverbindlich ist die im "
    "Bundesgesetzblatt (BGBl.) kundgemachte Fassung."
)

MINIMAL_DATA = {"title": "Testdokument", "sections": []}
OVERRIDDEN_NOTE = "Interne Testfassung — nicht amtlich."


def _cli(skill: str, name: str) -> Path:
    return REPO_ROOT / "plugin" / "skills" / skill / "scripts" / name


def _run(cli: Path, data: dict, out_path: Path) -> None:
    src = out_path.with_suffix(".json")
    src.write_text(json.dumps(data), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(cli), str(src), "-o", str(out_path)],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


# ---------------------------------------------------------------------------
# docx
# ---------------------------------------------------------------------------

pytest.importorskip("docx", reason="python-docx is optional; DOCX footer tests are skipped")
from docx import Document  # noqa: E402


def _docx_paragraph_texts(path: Path) -> list[str]:
    return [p.text for p in Document(str(path)).paragraphs]


@pytest.mark.parametrize("skill", SKILLS)
def test_docx_carries_default_footer_when_data_has_no_footer_note(skill: str, tmp_path: Path):
    out = tmp_path / "doc.docx"
    _run(_cli(skill, "render_lesson_docx.py"), MINIMAL_DATA, out)
    texts = _docx_paragraph_texts(out)
    assert DEFAULT_FOOTER_NOTE in texts


@pytest.mark.parametrize("skill", SKILLS)
def test_docx_explicit_footer_note_overrides_default(skill: str, tmp_path: Path):
    out = tmp_path / "doc.docx"
    _run(_cli(skill, "render_lesson_docx.py"),
         {**MINIMAL_DATA, "footer_note": OVERRIDDEN_NOTE}, out)
    texts = _docx_paragraph_texts(out)
    assert OVERRIDDEN_NOTE in texts
    assert DEFAULT_FOOTER_NOTE not in texts


# ---------------------------------------------------------------------------
# html
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("skill", SKILLS)
def test_html_carries_default_footer_when_data_has_no_footer_note(skill: str, tmp_path: Path):
    out = tmp_path / "doc.html"
    _run(_cli(skill, "render_lesson_html.py"), MINIMAL_DATA, out)
    html = out.read_text(encoding="utf-8")
    assert DEFAULT_FOOTER_NOTE in html
    assert 'class="footer"' in html


@pytest.mark.parametrize("skill", SKILLS)
def test_html_explicit_footer_note_overrides_default(skill: str, tmp_path: Path):
    out = tmp_path / "doc.html"
    _run(_cli(skill, "render_lesson_html.py"),
         {**MINIMAL_DATA, "footer_note": OVERRIDDEN_NOTE}, out)
    html = out.read_text(encoding="utf-8")
    assert OVERRIDDEN_NOTE in html
    assert DEFAULT_FOOTER_NOTE not in html
