# Upstream Reference

This project is derived from the upstream repository:

- **Upstream Repository**: https://github.com/anthropics/k12-teacher-skills
- **Pinned Commit**: `7c03c83db8223b050b6569ffbe14cd94e229396e`
- **Verified Date**: 2026-07-27 (HEAD of main)
- **License**: Apache-2.0

## Divergences from Upstream

| Area | Change | Reason |
|------|--------|--------|
| Skill Names | `k12-lesson-planning` → `at-unterrichtsplanung` | Austrian localization and naming convention |
| Skill Names | `k12-lesson-differentiation` → `at-differenzierung` | Austrian localization and naming convention |
| Product Language | English → German | Primary audience is Austrian teachers |
| Knowledge Graph | Learning Commons connector → Bundled RIS competence data | Local curriculum authority (BMBWF) data source preferred |
| MCP servers | Upstream's `plugin/.mcp.json` is **not carried over**; this project ships no `.mcp.json` and declares no MCP servers | That file declares nine US ed-tech HTTP servers (ASSISTments, Brisk Teaching, Canva, Coteach, Diffit, Eedi, MagicSchool, Snorkl, TeachFX). None serves the Austrian school context, and the plugin is designed to work offline from the bundled RIS dataset |
| Render Blocks | Added: `kompetenzbezug` | Reference competency standards in lesson plans |
| Render Blocks | Added: `uebergreifende_themen_tag` | Cross-curricular theme tags per Lehrplan 2023 |
| Render Blocks | Added: `niveau_spalte` | Tiered proficiency levels for differentiation |
| Document Types | `lesson_plan` → `unterrichtsplanung`, `student_materials` → `schueler_material`, `observation_template` → `beobachtungsbogen`; **`hint_cards` dropped** | German terminology aligned with Lehrplan 2023; the Austrian document set is exactly three, and tiered support material is served by the `niveau_spalte` block instead |
| Dependencies | `python-docx` install kept as upstream's runtime `pip install` in `render_all.sh` | Vendoring is not viable: `python-docx` requires `lxml`, which ships 7 compiled C extensions bound to a specific CPython version, architecture and libc. Portable vendoring would mean shipping a ~12 MB binary wheel per OS × arch × Python-minor combination. Upstream's fallback already degrades safely to HTML-only when the install fails |
