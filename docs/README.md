# Teacher's Personal Documentation Folder

This folder is for your own teaching materials, lesson notes, curriculum planning, and professional development resources. 

**Important**: This folder is **never shipped** with the plugin and is **never labelled as official**. It is a private workspace for your personal use only.

## Folder Convention

Organize materials by subject and grade/level:

```
docs/<fach>/<stufe>/file.md
```

`<stufe>` is optional; without it, the material is treated as subject-wide (any level). Only two
level families are recognised: `SCH1`–`SCH4` for **Primarstufe** (1st–4th Schulstufe) and
`K1`–`K4` for **Sekundarstufe I** (1st–4th Klasse). They are not interchangeable, and no other
spelling (e.g. `S1`, `2.Klasse`) is recognised — an unrecognised level is simply treated as if no
level were given.

### Examples

- `docs/mathematik/SCH2/bruchrechnen.md` — lesson notes on fractions (Primarstufe, 2. Schulstufe)
- `docs/deutsch/K1/schreibfertigkeiten.md` — writing skills resource (Sekundarstufe I, 1. Klasse)
- `docs/englisch/K3/vokabeln.md` — vocabulary exercises (Sekundarstufe I, 3. Klasse; English is
  Sekundarstufe I only, there is no PRIM.E)
- `docs/sachunterricht/SCH4/oekosysteme.md` — ecosystems unit (Primarstufe, 4. Schulstufe)
- `docs/mathematik/aufgabenpool.md` — no level folder: applies to every Mathematik level

### Subject Aliases

The following subject folder names are recognized and mapped to standard abbreviations:

| Folder Name | Abbreviation | Subject |
|-------------|--------------|---------|
| mathematik | M | Mathematics |
| deutsch | D | German Language & Literature |
| englisch | E | English |
| sachunterricht | SU | Natural & Social Studies |

### Unrecognized Subjects

If you create a folder for a subject that isn't in the alias list above, your materials will be listed under "Unassigned" rather than under a specific subject. They are never discarded—you can always find them.

## Supported Formats

- `.md` — Markdown (native, full support)
- `.txt` — Plain text (native, full support)
- `.pdf` — PDF documents (converted on ingestion, see caveat below)
- `.docx` — Word documents (converted on ingestion)

When you add PDF or DOCX files, they are converted to Markdown-ish text on first use and cached
under `docs/.cache/` (your original file is never modified). **PDF caveat:** no PDF text-extraction
library ships with this plugin today, so every `.pdf` file is currently logged as "not extractable"
and skipped rather than used — this is expected, not an error, and applies especially to
scanned/image-only PDFs even once a library is added later. `.md`/`.txt`/`.docx` are unaffected.

## Optional: Binding a File to One Official Competence

You can link a file to one specific official competence (`kompetenz_id`) instead of relying on the
folder alone — either as a filename suffix (`bruchrechnen__AT.LP23.SEK1.M.ZAHLEN.K2.03.md`) or as
YAML frontmatter (`kompetenz_id: AT.LP23.SEK1.M.ZAHLEN.K2.03` at the top of the file, between two
`---` lines). This binding always takes precedence over the folder location.

## Limits

Per request: max 2 MB per file, max 20 files, and a conservative total token budget (roughly 4,000
tokens) so your own material never crowds out the official curriculum text. If more of your files
match than the limits allow, the most relevant ones (by explicit binding, then subject, then level)
are kept and the rest are left out — never silently, always reported.

## Never Official

Nothing under `docs/` is ever presented as official curriculum text — it is always clearly marked
as your own, teacher-supplied material, kept visually and textually separate from the amtlich
(official) RIS Lehrplan content in anything this plugin generates.
