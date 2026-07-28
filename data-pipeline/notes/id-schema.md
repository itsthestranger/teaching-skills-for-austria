# The AT.LP23 ID scheme -- frozen (E3-02)

**This scheme is frozen.** IDs are the plan's only hard-fail condition (a
collision aborts the pipeline -- `parse_lehrplan.py::LehrplanParser._make_id`
raises `ParseError`). Once a shard ships, its IDs must never be re-minted:
adding a subject or an area means *adding* a table entry in
`data-pipeline/schema/id_schema.py`, never renaming, renumbering or
reassigning an existing one. The four Sek I Mathematik area codes (`ZAHLEN`,
`VARIABLEN`, `FIGUREN`, `DATEN`) and the synthetic `GZINTEGRATIV` code are
already in shipped IDs and are reused here verbatim, not re-derived.

Implementation: `data-pipeline/schema/id_schema.py` (stdlib only). Tests:
`data-pipeline/tests/test_id_schema.py`.

---

## 1. Grammar

Both forms are produced by `LehrplanParser._make_id(bereich_slug, stufe, lfd,
index, praefix="")` -- `praefix=""` for a competence, `"AB."`/`"DT."` for an
application item. The trailing dot inside the prefix string is what turns a
7-segment ID into an 8-segment one; it is not a separate template.

```
Kompetenz (competence), 7 segments:
    AT.LP23.<Band>.<Fach>.<Bereich>.<Stufe>.<lfd>

Anwendungsitem (application item), 8 segments:
    AT.LP23.<Band>.<Fach>.<Art>.<Bereich>.<Stufe>.<lfd>
```

| Segment | Values | Notes |
|---|---|---|
| `Band` | `PRIM` \| `SEK1` | |
| `Fach` | `M` \| `D` \| `E` \| `SU` | Scoped per band -- see §2. |
| `Art` | `AB` (Praezisierung) \| `DT` (digitale Technologien) | Application items only. `DT` items precisify no competence (`kompetenz_id: null` in the record) but still need a stable ID (FINDINGS V-54). |
| `Bereich` | subject x band specific area code | See §3 for the full table. |
| `Stufe` | `K1..K4` (SEK1) \| `SCH1..SCH4` (PRIM) | **`GS1`/`GS2` and `VOR` are removed.** FINDINGS V-22 closed this empirically: both bands are per school year / class year, not per Grundstufe. The plan's §4.8 line listing `VOR \| GS1 \| GS2 [\| SCH1..SCH4]` is superseded by the source. |
| `lfd` | two digits, zero-padded | Scoped per `(stufe, art, bereich)` -- see `LehrplanParser._emit_kompetenzen` / `_emit_anwendungsitems`. Not globally sequential. |

Examples (first two are real, shipped IDs; the rest are scheme-legal
examples for shards not yet built):

```
AT.LP23.SEK1.M.ZAHLEN.K1.01              competence, Sek I Mathematik
AT.LP23.SEK1.M.AB.ZAHLEN.K2.05           application item, precisification
AT.LP23.SEK1.M.DT.ZAHLEN.K1.01           application item, digital technology
AT.LP23.SEK1.M.GZINTEGRATIV.K3.01        synthetic area (V-57)
AT.LP23.PRIM.SU.NATURWISS.SCH2.03
AT.LP23.SEK1.D.AB.SPRACHREFLEXION.K1.01
```

Regexes (see `id_schema.py` for the exact compiled patterns):

```
KOMPETENZ_ID_RE        ^AT\.LP23\.(PRIM|SEK1)\.(M|D|E|SU)\.([A-Z][A-Z0-9]*)\.(K[1-4]|SCH[1-4])\.(\d{2})$
ANWENDUNGSITEM_ID_RE    ^AT\.LP23\.(PRIM|SEK1)\.(M|D|E|SU)\.(AB|DT)\.([A-Z][A-Z0-9]*)\.(K[1-4]|SCH[1-4])\.(\d{2})$
```

`parse_id()` additionally checks that the `Stufe` prefix agrees with `Band`
(`SEK1` implies a `K` stufe, `PRIM` implies `SCH`) -- a constraint the two
independent regex alternations cannot express by themselves.

---

## 2. Subjects in scope

Exactly six shards (plan Executive Summary, unchanged):

| Band | Fach codes |
|---|---|
| `SEK1` | `M`, `D`, `E` |
| `PRIM` | `M`, `D`, `SU` |

| Code | Official RIS heading (`ueberschrift/@typ="g1"`, verbatim) | German display name |
|---|---|---|
| `M` | `MATHEMATIK` | Mathematik |
| `D` | `DEUTSCH` | Deutsch |
| `E` | `(ERSTE) LEBENDE FREMDSPRACHE` | (Erste) Lebende Fremdsprache |
| `SU` | `SACHUNTERRICHT` | Sachunterricht |

`E` maps to *(Erste) Lebende Fremdsprache* (FINDINGS V-29), not "Englisch" --
the subject is language-neutral by design (any first living foreign
language a school offers), and BiSt calls it `(Erste) Lebende Fremdsprache
(Englisch)` only because English is what's actually taught. The second
foreign language (`(ZWEITE) LEBENDE FREMDSPRACHE`) is out of scope and never
gets a code. Both headings were confirmed ALL CAPS in both source XML
documents (VS `NOR40271469.xml` children 802/1197/1293; MS `NOR40271471.xml`
children 395/617) -- do not assume mixed case just because other primary
subject headings are mixed case (`Deutsch`, `Musik`, `Rhythmik` elsewhere in
the Vorschulstufe block; not the ones in scope here).

---

## 3. Competence-area code table

Extracted 2026-07-28 by reading the `Kompetenzbereich`/`Kompetenzmodell`
headings directly out of both source XML files (throwaway script, not
committed -- see the extraction method note at the end of this file). Counts
match FINDINGS' expectation exactly: 4 areas for primary Mathematik, 4 for
primary Deutsch, 6 for primary Sachunterricht, 4 for Sek I Mathematik.

| Band.Fach | Area name (verbatim from RIS) | Code | Rationale |
|---|---|---|---|
| `SEK1.M` | Zahlen und Maße | `ZAHLEN` | Reused verbatim from `parse_lehrplan.py::SEK1_MATHEMATIK.bereich_slugs` -- already shipped. |
| `SEK1.M` | Variablen und Funktionen | `VARIABLEN` | Reused verbatim, already shipped. |
| `SEK1.M` | Figuren und Körper | `FIGUREN` | Reused verbatim, already shipped. |
| `SEK1.M` | Daten und Zufall | `DATEN` | Reused verbatim, already shipped. |
| `SEK1.M` | *(synthetic)* Integrative Führung von Geometrisches Zeichnen | `GZINTEGRATIV` | Reused verbatim from `GZ_INTEGRATIV_BEREICH_SLUG` (FINDINGS V-57) -- the 2 promoted competences outside the four numbered areas. Already shipped. |
| `SEK1.D` | Zuhören und Sprechen | `HOERENSPRECHEN` | Concatenation of the two verb stems, umlaut folded (ü→ue), matching the plain-word style of the Sek I Mathematik codes. |
| `SEK1.D` | Lesen | `LESEN` | The area name itself is already a short, unambiguous ASCII word. |
| `SEK1.D` | Schreiben | `SCHREIBEN` | Same. |
| `SEK1.D` | *(structural)* Integrativer Kompetenzbereich Sprachbewusstsein und Sprachreflexion | `SPRACHREFLEXION` | Not a Kompetenzbereich with its own competence list -- the source states its competences "werden in den Bereichen Zuhören und Sprechen, Lesen, Schreiben integrativ formuliert" -- but it *does* carry its own `Anwendungsbereiche` item list (child 437-438 of the MS document), so it still needs an ID segment. This is the mirror image of `GZINTEGRATIV` (competences without an application block, vs. here an application block without competences of its own). See §4 for the full finding. |
| `SEK1.E` | Hören | `HOEREN` | Direct, ASCII-safe (ö→oe). |
| `SEK1.E` | Lesen | `LESEN` | Same code as `SEK1.D`'s -- collision across subjects is expected and harmless (different `Fach` segment disambiguates). |
| `SEK1.E` | Sprechen (an Gesprächen teilnehmen und zusammenhängend sprechen) | `SPRECHEN` | Head noun of the official heading; the parenthetical qualifier is dropped from the code (kept verbatim in the area *name*, only the code is shortened). |
| `SEK1.E` | Schreiben | `SCHREIBEN` | Same code as `SEK1.D`'s -- harmless collision, see above. |
| `PRIM.M` | Zahlen und Daten | `ZAHLENDATEN` | Plan's §4.2 "Mengen und Zahlen" was wrong (FINDINGS V-23); this is the corrected, verbatim area name, coded as a single concatenated word. |
| `PRIM.M` | Operationen | `OPERATIONEN` | Already ASCII, used as-is. |
| `PRIM.M` | Größen | `GROESSEN` | ß→ss, ö→oe folding of the plain area name. |
| `PRIM.M` | Ebene und Raum | `EBENERAUM` | Concatenation of the two head nouns. |
| `PRIM.D` | (Zu-)Hören und Sprechen | `HOERENSPRECHEN` | Same code as `SEK1.D`'s "Zuhören und Sprechen" -- the primary heading drops the "Zu-" into an optional parenthetical but names the same competence pair; harmless cross-subject collision, not cross-band reuse of a single ID (different `Band` segment disambiguates too). |
| `PRIM.D` | Lesen | `LESEN` | Direct. |
| `PRIM.D` | Verfassen von Texten | `VERFASSEN` | Head verb of the heading. |
| `PRIM.D` | (Recht-)Schreiben und Sprachbetrachtung | `RECHTSCHREIBEN` | The parenthetical "Recht-" is the semantically load-bearing part (distinguishes this area from the "Schreiben" of composition); folded into the code as one word, "Sprachbetrachtung" dropped from the code only (kept in the name). |
| `PRIM.SU` | Sozialwissenschaftlicher Kompetenzbereich | `SOZIALWISS` | Adjective-first heading (FINDINGS V-25); coded from the adjective stem, abbreviated to stay short and to leave room for `NATURWISS` to read as a clear sibling. |
| `PRIM.SU` | Naturwissenschaftlicher Kompetenzbereich | `NATURWISS` | Same pattern. |
| `PRIM.SU` | Geografischer Kompetenzbereich | `GEOGRAFIE` | Adjective stem, noun form (more readable than `GEOGRAFISCH`). |
| `PRIM.SU` | Historischer Kompetenzbereich | `HISTORISCH` | Adjective stem as-is (the noun "Geschichte" does not occur in the source heading, so the code follows the adjective actually used). |
| `PRIM.SU` | Technischer Kompetenzbereich | `TECHNIK` | Noun form of the adjective stem. |
| `PRIM.SU` | Wirtschaftlicher Kompetenzbereich | `WIRTSCHAFT` | Noun form of the adjective stem. |

Uniqueness requirement: codes are unique **within** one `Band.Fach` entry.
Cross-subject or cross-band reuse of the same code string (`LESEN`,
`SCHREIBEN`, `HOERENSPRECHEN`) is deliberate and harmless, since the `Fach`
and `Band` segments of the full ID always disambiguate.

---

## 4. Structural findings from the extraction (logged in `deviations.md`)

Two things surfaced while reading the real headings that go beyond what
FINDINGS.md/`notes/ris-xml-structure.md` had already recorded, both now
logged as new rows in `data-pipeline/notes/deviations.md`:

1. **Sek I Deutsch and (Erste) Lebende Fremdsprache do *not* use Sek I
   Mathematik's two-section shape.** Both use the primary-style single
   combined heading, `Kompetenzbeschreibungen und Anwendungsbereiche,
   Lehrstoff (1. bis 4. Klasse):`, with an inline `Anwendungsbereiche`
   sub-heading after each competence-area's list, not one top-level
   `Anwendungsbereiche (1. bis 4. Klasse):` section at the end. This
   resolves FINDINGS' open question V-40.
2. **Sek I Deutsch has an area that produces application items but no
   competences of its own** (`SPRACHREFLEXION`, see the table above) --
   the structural mirror of the already-known `GZINTEGRATIV` case
   (competences with no application items). Confirmed by reading the
   Anwendungsbereiche-only area's precise entries.

3. **The `DEUTSCH` g1 span contains two curricula, and the second one can
   collide.** After the main Deutsch curriculum ends (child 511), a complete
   `LEHRPLANZUSATZ DEUTSCH ALS ZWEITSPRACHE FÜR ORDENTLICHE SCHÜLERINNEN UND
   SCHÜLER` follows at child 515 with five further `Kompetenzbereich`
   headings (Hören, Sprechen, Lesen, Schreiben, Linguistische Kompetenzen).
   It is an `erll` heading, **not** a `g1`, so `@typ="g1"` subject
   segmentation (V-06) does not separate it out. Two of its area names
   (`Lesen`, `Schreiben`) are also main-curriculum area names, so an
   extractor that scans the whole g1 span mints those codes twice under
   `SEK1.D` and triggers the ID-collision hard fail. `AREA_CODES["SEK1.D"]`
   below contains **only the four main-curriculum areas**; the DaZ
   Lehrplanzusatz is out of v1 scope. The `SEK1.D` `SubjectSpec` must bound
   its competence section at child 515, not at the end of the g1 span.
   (This is a distinct document from the `… FÜR AUSSERORDENTLICHE …
   DEUTSCHFÖRDERKURS`, which does get its own `g1` at 563 and which the plan
   already skips.)

Neither finding required touching `parse_lehrplan.py` (out of scope for
E3-02) -- they are recorded so whoever writes the `SEK1.D` /`SEK1.E`
`SubjectSpec` later does not have to re-derive them.

---

## 5. Extraction method

Area names and counts were read with a throwaway stdlib script (not
committed) that walks the flat `<abschnitt>` children the same way
`parse_lehrplan.py` does (`localname`, `element_text`), scoped to each
subject's `g1` heading inside the correct `TEIL` (`NEUNTER TEIL` for
primary, `ACHTER TEIL` for Sek I -- `ACHTER TEIL` in the Volksschule
document is Vorschulstufe and was *not* used). Results, matching FINDINGS'
expected counts exactly:

| Shard | Areas found | Expected (FINDINGS) |
|---|---|---|
| `PRIM.M` | 4 (Zahlen und Daten, Operationen, Größen, Ebene und Raum) | 4 |
| `PRIM.D` | 4 ((Zu-)Hören und Sprechen, Lesen, Verfassen von Texten, (Recht-)Schreiben und Sprachbetrachtung) | 4 |
| `PRIM.SU` | 6 (Sozialwissenschaftlicher, Naturwissenschaftlicher, Geografischer, Historischer, Technischer, Wirtschaftlicher Kompetenzbereich) | 6 |
| `SEK1.M` | 4 (+ 1 synthetic, `GZINTEGRATIV`) | 4 |
| `SEK1.D` | 3 competence-bearing (Zuhören und Sprechen, Lesen, Schreiben) + 1 structural (Sprachbewusstsein und Sprachreflexion) | not stated in FINDINGS (V-40 was open) |
| `SEK1.E` | 4 (Hören, Lesen, Sprechen, Schreiben) | not stated in FINDINGS (V-40 was open) |
