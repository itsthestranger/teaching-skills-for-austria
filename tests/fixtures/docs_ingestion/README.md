# Fixture tree for `tests/test_docs_ingestion.py`

Mirrors the real (gitignored) `docs/` folder's contents just enough to test
the folder convention, competence bindings and the unassigned-folder path
without ever reading the real `docs/`. This file itself is excluded from
ingestion the same way `docs/README.md` is (top-level `README.md`, plan
§6.6's own scaffolding file).
