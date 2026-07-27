# Teacher's Personal Documentation Folder

This folder is for your own teaching materials, lesson notes, curriculum planning, and professional development resources. 

**Important**: This folder is **never shipped** with the plugin and is **never labelled as official**. It is a private workspace for your personal use only.

## Folder Convention

Organize materials by subject and grade/level:

```
docs/<fach>/<stufe>/file.md
```

### Examples

- `docs/mathematik/K2/bruchrechnen.md` — lesson notes on fractions (Primarystage 2)
- `docs/deutsch/S1/schreibfertigkeiten.md` — writing skills resource (Secondary 1)
- `docs/englisch/K3/vokabeln.md` — vocabulary exercises (Primary stage 3)
- `docs/sachunterricht/K4/oekosysteme.md` — ecosystems unit (Primary stage 4)

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
- `.pdf` — PDF documents (converted on ingestion)
- `.docx` — Word documents (converted on ingestion)

When you add PDF or DOCX files, they will be automatically converted to a usable format during the data ingestion pipeline.
