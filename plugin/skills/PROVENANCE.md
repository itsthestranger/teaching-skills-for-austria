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

### `plugin/skills/at-differenzierung/`
Copied from `plugin/skills/k12-lesson-differentiation/` at the pinned commit:

- `scripts/lesson_common.py`
- `scripts/render_documents.py`
- `scripts/render_lesson_docx.py`
- `scripts/render_lesson_html.py`
- `scripts/render_all.sh`
- `scripts/theme.css`
- `LICENSE`

## Not copied (deliberately, separate later tasks)

- `references/learning-commons-kg.md` — the connector doc; being replaced.
- `references/ela.md`, `references/math.md`, `references/science.md`,
  `references/social_studies.md` — upstream subject reference files.
- `SKILL.md` — upstream skill definition.

## Removed after vendoring

- `references/NOTICE` (both skills) — upstream's Common Core State Standards
  attribution. It was copied at vendoring time, but the files it attributes
  (`references/ela.md`, `math.md`, `science.md`, `social_studies.md`) were
  deliberately not copied, and E10-08b removed the last imported framework
  vocabulary from the rubrics. No CCSS text ships in this repository, so the
  notice attributed content that is not present and made the plugin appear to
  carry US standards. Removed 2026-08-21.

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
- A third Austrian block type, `niveau_spalte`, was added to both renderers for
  `at-differenzierung`'s tiered material: `{"type": "niveau_spalte", "niveaus": [{"label":
  "unter"|"auf"|"über", "titel": ..., "blocks": [...]}]}` renders however many
  differentiation tiers side by side, each an independent nested block list. Unlike
  `kompetenzbezug`/`uebergreifende_themen_tag` (leaf blocks), `niveau_spalte` nests —
  implemented as its own emitter pair (`_emit_niveau_spalte` in `render_lesson_docx.py`,
  a `render_block` branch in `render_lesson_html.py`) rather than as an alias over
  `columns`, since `columns` is a fixed two-panel `left`/`right` shape with no per-panel
  label/title, and `niveau_spalte` needs an arbitrary tier count plus a label/titel head
  per tier. It is threaded through the same recursive passes `columns` already uses in
  `lesson_common.py` (`_repair_enum_breaks`, `_repair_pipe_tables`, `_repair_inline_bullets`,
  `expand_blocks`) so nested `from_shared` references inside a tier expand correctly. Tier
  labels resolve via `resolve_niveau_kind()`, which reuses existing callout accent colors
  (tnote amber / special green / kompetenz indigo) rather than a new palette.
- A fourth Austrian block type, `herkunftsblock`, was added to both renderers so a reader
  can never mistake teacher-supplied material for official regulation text:
  `{"type": "herkunftsblock", "amtlich": true|false, "quelle": {...}|"quelle_hinweis": ...,
  "blocks": [...]}` wraps an arbitrary block list and labels its origin. Like
  `niveau_spalte` it nests, so it is threaded through the same four recursive passes in
  `lesson_common.py` and expands nested `from_shared` references correctly. The official
  branch reuses `kompetenz_citation()` verbatim rather than inventing a second citation
  format, and the two origins are distinguished on three independent channels — icon
  (`§` vs `📁`), German label, and accent colour (indigo `#7A8CC4` vs ochre `#B2652E`,
  the latter carried in docx as a coloured cell border via the same `_cell_borders`
  mechanism `niveau_spalte` uses) — so the distinction survives black-and-white print
  and a docx round-trip.
  **Fail-safe by design:** `resolve_herkunft()` treats **only** `amtlich is True` as
  official; `False`, missing, `None`, `1`, `"true"` and any other stray value render as
  teacher-supplied. Origin marking must never default to claiming official status — a
  reader who cannot tell is shown "not official", never the reverse.
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
