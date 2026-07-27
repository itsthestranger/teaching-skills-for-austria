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

The files above were originally verified byte-identical to the pinned upstream commit
(via `diff -r` at vendoring time). Since then, both skills' `scripts/lesson_common.py`,
`render_lesson_html.py`, and `render_lesson_docx.py` have been Germanised and extended:

- Hardcoded English UI text emitted into rendered documents (e.g. "Target standard",
  "Builds on", "Mathematical practices", "Students see", "Materials:", the default
  "Lesson Plan" title) was translated to German, using the colon gender form
  (`Schüler:innen`) for our own UI strings. Code identifiers, block-type names, and
  file names were left ASCII/unchanged; code comments were left in English (engineering
  docs, not user-facing).
- Two Austrian block types were added to both renderers: `kompetenzbezug` (a verbatim,
  citation-bearing quotation of the curriculum competence a lesson is anchored in) and
  `uebergreifende_themen_tag` (a compact chip row for cross-cutting curriculum themes).
  Both reuse existing callout/labeled machinery rather than introducing new OOXML
  geometry — see `CALLOUT_KINDS["kompetenz"]` and `kompetenz_citation()` in
  `lesson_common.py`.
- Document type ids: `lesson_plan` → `unterrichtsplanung`, `student_materials` →
  `schueler_material`, `observation_template` → `beobachtungsbogen` are now the agreed
  Austrian names and are used as-is in `references/example_lesson.json`.
  **Decided 2026-07-27:** upstream's fourth document type, `hint_cards`, is **dropped**.
  The Austrian document set is exactly the three above, per the specification. Nothing in
  the renderer hardcodes document ids — they are free-form JSON `id`s — so the drop was a
  fixture-only change and the renderer retains no dead code for it. Tiered support material
  for `at-differenzierung` is served by the `niveau_spalte` block, not by a separate
  document type.

`at-differenzierung/scripts/render_all.sh` and `at-unterrichtsplanung/scripts/render_all.sh`
were not touched — they differ from each other only in filenames/comments (inherited from
vendoring) and carry no user-facing document text.

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
