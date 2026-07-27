# RIS Data Deviations Log

This file records every divergence between the written specification for competence and curriculum data and what is actually found in the official RIS (Rechtsinformationssystem des Bundes) source materials. 

When data is ingested or a mismatch is discovered, the resolution (adapted spec, manual correction, note for users, etc.) is documented here to maintain traceability and justify decisions made during data processing.

| Date | Source | Expected | Actual | Resolution |
|------|--------|----------|--------|------------|
| 2026-07-27 | live RIS discovery, GN 20007850 (Mittelschule), NOR40271471 | `Data.Dokumentliste.ContentReference` is a single object (per validated API facts) | `ContentReference` is a **list**: one `ContentType: "MainDocument"` entry plus several `ContentType: "EmbeddedAttachment"` entries (inline PNG images referenced by the curriculum text) | `fetch_ris_resources.py::get_content_urls` normalises `ContentReference` to a list (same treatment as the documented `ContentUrl` quirk) and selects the entry with `ContentType == "MainDocument"` before reading its `Urls.ContentUrl`. Embedded attachments are not downloaded by this pipeline. |
| 2026-07-27 | live RIS discovery, GN 20006166 (Bildungsstandards), NOR40255561 | `Kurztitel` = "Bildungsstandards-Verordnung" (per task's regulation table) | Live `Data.Metadaten.Bundesrecht.Kurztitel` = "Bildungsstandardsverordnung" (no hyphen, single word) | Not a functional issue -- `fetch_ris_resources.py` records the live `Kurztitel` verbatim in the manifest (source wins); the hyphenated spelling was only ever a task-doc convenience label. |
