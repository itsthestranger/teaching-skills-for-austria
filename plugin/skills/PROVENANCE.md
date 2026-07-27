# Provenance

The document renderer used by the `at-unterrichtsplanung` and `at-differenzierung`
skills is vendored, byte-for-byte, from upstream:

- **Source**: https://github.com/anthropics/k12-teacher-skills
- **Commit**: `7c03c83db8223b050b6569ffbe14cd94e229396e`
- **License**: Apache License 2.0 (see each skill's `LICENSE` file)

## Files copied

### `plugin/skills/at-unterrichtsplanung/`
Copied from `plugin/skills/k12-lesson-planning/` at the pinned commit:

- `scripts/lesson_common.py`
- `scripts/render_documents.py`
- `scripts/render_lesson_docx.py`
- `scripts/render_lesson_html.py`
- `scripts/render_all.sh`
- `scripts/theme.css`
- `LICENSE`
- `references/NOTICE`

### `plugin/skills/at-differenzierung/`
Copied from `plugin/skills/k12-lesson-differentiation/` at the pinned commit:

- `scripts/lesson_common.py`
- `scripts/render_documents.py`
- `scripts/render_lesson_docx.py`
- `scripts/render_lesson_html.py`
- `scripts/render_all.sh`
- `scripts/theme.css`
- `LICENSE`
- `references/NOTICE`

## Not copied (deliberately, separate later tasks)

- `references/learning-commons-kg.md` — the connector doc; being replaced.
- `references/ela.md`, `references/math.md`, `references/science.md`,
  `references/social_studies.md` — upstream subject reference files.
- `SKILL.md` — upstream skill definition.

## Modification status at this stage

All files listed above are **unmodified** — verified with `diff -r` against the
pinned upstream commit at vendoring time; every file is byte-identical to its
upstream counterpart. No Germanisation, renaming, or new block-type work has been
done yet; that is scoped to later tasks.

## Note on the "pure stdlib" assumption

`render_lesson_html.py` and `lesson_common.py` are pure Python standard library,
as expected. **`render_lesson_docx.py`, however, imports the third-party
`python-docx` package** (`from docx import Document`, plus `docx.shared`,
`docx.enum.text`, `docx.enum.table`, `docx.oxml`) — it is not a hand-rolled
OOXML writer. This is upstream's actual behavior at the pinned commit, not a
modification introduced during vendoring. `scripts/render_all.sh` reflects this:
it attempts `pip install python-docx==1.1.2` if the import fails, renders HTML
either way, and only renders `.docx` (failing loudly otherwise) once the
import succeeds. See `PROVENANCE.md`'s sibling report for the full detail; no
third-party dependency was added by this port.
