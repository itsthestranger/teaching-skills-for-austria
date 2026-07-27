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
| SaaS References | US ed-tech platforms removed from `.mcp.json` and docs | Not applicable in Austrian educational context |
| Render Blocks | Added: `kompetenzbezug` | Reference competency standards in lesson plans |
| Render Blocks | Added: `uebergreifende_themen_tag` | Cross-curricular theme tags per Lehrplan 2023 |
| Render Blocks | Added: `niveau_spalte` | Tiered proficiency levels for differentiation |
| Document Types | `lesson_plan`, `student_materials`, `hint_cards`, `observation_template` → `unterrichtsplanung`, `schueler_material`, `beobachtungsbogen` | German terminology aligned with Lehrplan 2023 |
