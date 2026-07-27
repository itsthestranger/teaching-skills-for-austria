# Structure of the RIS curriculum XML

Reference for anyone extending `data-pipeline/parse_lehrplan.py`.
Everything here was **measured** against the checked-in sources, not assumed.

| Key | File | Bytes | Children of `<abschnitt>` |
|---|---|---|---|
| `mittelschule` | `resources/mittelschule/NOR40271471.xml` | 1 113 412 | 2 409 |
| `volksschule` | `resources/volksschule/NOR40271469.xml` | 867 732 | 2 261 |
| `bildungsstandards` | `resources/bildungsstandards/NOR40255561.xml` | 81 009 | — (not covered here) |

Namespace: `http://www.bka.gv.at` — every element is namespaced, so use
`{http://www.bka.gv.at}tag` throughout.

---

## 1. The document is flat presentation markup

```
<risdok>
  <metadaten/>
  <nutzdaten>
    <abschnitt nr="1" typ="ns">      <-- exactly one; everything lives here
      ~2400 direct children
```

There is **no nesting** by TEIL, by subject, or by competence area. Hierarchy is
carried entirely by attributes on the flat children. That is why the parser is a
**sequential state machine**, not a tree walk.

Child-element census (Mittelschule):

```
absatz/abs        1230    liste             443    ueberschrift/erll  396
absatz/erltext     181    abstand            60    ueberschrift/g1     36
table               32    ueberschrift/titel 12    ueberschrift/g2      9
ueberschrift/g1min   3    absatz/satz         1    ueberschrift/erlz    1
```

### Attribute → meaning

| Signal | Meaning | Caveats |
|---|---|---|
| `ueberschrift/@typ="g1"` | TEIL boundary **and** subject boundary | Also used for `A. PFLICHTGEGENSTÄNDE`, `LEHRPLAN DER MITTELSCHULE`, `LEHRPLANZUSATZ …`. Sek I subject names are ALL CAPS; **primary ones are not always** (`Deutsch`, `Musik`, `Rhythmik`, `Technik und Design`). Do not use capitalisation as the test. |
| `ueberschrift/@typ="g1min"` | Same role, smaller print | `VERTIEFUNG BZW. ERGÄNZUNG …`, `DEUTSCH IN DER DEUTSCHFÖRDERKLASSE`. Treat as `g1`. |
| `ueberschrift/@typ="g2"` | Section title under a TEIL | `LEHRPLÄNE DER EINZELNEN UNTERRICHTSGEGENSTÄNDE` |
| `ueberschrift/@typ="erll"` | In-subject heading | `Bildungs- und Lehraufgabe:`, `Kompetenzbereiche (…):`, `Anwendungsbereiche (…):`, `Kompetenzbereich 1: …` — **and, in the primary document, the school-year marker** (see §4). |
| `absatz/@typ="erltext"` | Class-year / school-year marker | `1. Klasse:`, `2. Schulstufe:`. Dominant form in Sek I (57 of 61); rare in primary (5 of 40). |
| `absatz/@typ="abs"` | Body text | **Also carries competence-area headings inside the Anwendungsbereiche section** — see §3. |
| `absatz/@typ="tabtext"` | Text inside a table cell | |
| `liste` → `aufzaehlung` → `listelem` | Competence descriptions and application-area items | |
| `table` → `tr` → `td` | Timetables, the themes matrix, the footnote legend — **never competence content**. See §6. |
| `abstand` | Vertical spacing | Ignore. |

### Inline elements inside text

| Element | What it is | What the parser does |
|---|---|---|
| `<symbol stellen="1">–</symbol>` | The list bullet glyph, first child of every `listelem` | Dropped. It is presentation, not text. |
| `<super>4</super>`, `<super>6, 7</super>` | Superscript footnote marker referring to the 13 cross-cutting themes. **One `<super>` may hold several numbers.** | Removed from the quotable `text`; preserved in `text_roh` and in `themen_marker_roh`; resolved against the theme map. |
| `<binary><src>/Dokumente/…/hauptdokument.img1is.png</src></binary>` | An inline PNG — fractions and formulae are shipped as images | **Trap:** `itertext()` splices the *file path* into the sentence. Replaced by `[Abbildung]`; paths kept in `abbildungen`. 25 Sek I maths application items are affected. |
| `<feld>`, `<tab>` | Page furniture in headers/footers | Outside the content range. |

---

## 2. Where each band's curricula live

### Mittelschule (Sek I) — NOR40271471

| Child index | Heading |
|---|---|
| 21 / 40 / 52 / 74 / 194 / 296 / 366 | ERSTER … SIEBENTER TEIL (general part, timetables, religion) |
| **392** | **ACHTER TEIL** → `LEHRPLÄNE DER EINZELNEN UNTERRICHTSGEGENSTÄNDE` |
| 394 | `A. PFLICHTGEGENSTÄNDE` |
| 395 | DEUTSCH |
| 617 | `(ERSTE) LEBENDE FREMDSPRACHE` — *not* "Englisch" |
| **854 – 1071** | **MATHEMATIK** |
| 1072 | GEOMETRISCHES ZEICHNEN |
| 2103 / 2160 / 2260 / 2267 / 2269 | B. VERBINDLICHE ÜBUNGEN / C. FREIGEGENSTÄNDE / D / E / F |

### Volksschule (primary) — NOR40271469

| Child index | Heading |
|---|---|
| **367** | **ACHTER TEIL** → Vorschulstufe curricula (`Deutsch`, `MATHEMATISCHE FRÜHERZIEHUNG`, `SACHBEGEGNUNG`, …) |
| **798** | **NEUNTER TEIL** → `LEHRPLÄNE DER EINZELNEN UNTERRICHTSGEGENSTÄNDE (1. BIS 4. SCHULSTUFE)` |
| 802 | DEUTSCH |
| 1005 | `LEBENDE FREMDSPRACHE (3. UND 4. SCHULSTUFE)` |
| **1197** | **MATHEMATIK** |
| **1293** | **SACHUNTERRICHT** |
| 2022 | ZEHNTER TEIL → Deutschförderklassen |

> **Subject names repeat across TEILs.** `BEWEGUNG UND SPORT` occurs at 755
> (Vorschulstufe), 1700 (Grundschule) and 1945 (Freigegenstände); `KUNST UND
> GESTALTUNG` at 569 and 1493. Matching only on the heading text picks the
> wrong one. `SubjectSpec.teil_ueberschrift` pins the enclosing TEIL and the
> parser logs `fachueberschrift_im_falschen_teil` for the occurrences it skips.

---

## 3. The two-section shape of Sek I Mathematik

The subject body runs, in order:

```
ueberschrift/g1     MATHEMATIK                                       [854]
ueberschrift/erll   Bildungs- und Lehraufgabe (1. – 4.Klasse):       [855]
ueberschrift/erll   Kompetenzmodell und Kompetenzbereiche (…):       [863]
ueberschrift/erll   Zentrale fachliche Konzepte (…):                 [871]
ueberschrift/erll   Didaktische Grundsätze (…):                      [881]
    absatz/abs      Dieser Lehrplan greift folgende übergreifende
                    Themen auf: Entrepreneurship Education2, …       [894]
ueberschrift/erll   Kompetenzbereiche (1. bis 4. Klasse):            [895]  <== SECTION 1
ueberschrift/erll   Anwendungsbereiche (1. bis 4. Klasse):           [948]  <== SECTION 2
ueberschrift/erll   Kompetenzen … bei integrativer Führung von
                    Geometrisches Zeichnen (1. bis 4. Klasse):       [1063] <== appendix
table               the 13-theme footnote legend                     [1071]
```

### Section 1 — `Kompetenzbereiche` (the competence descriptions)

Repeating pattern, four class years × four areas:

```
absatz/erltext      1. Klasse:                                       [896]
ueberschrift/erll   Kompetenzbereich 1: Zahlen und Maße              [897]
absatz/abs          Die Schülerinnen und Schüler können              [898]   <- bare stem
liste                 listelem × n  = the competence descriptions    [899]
ueberschrift/erll   Kompetenzbereich 2: Variablen und Funktionen     [900]
…
```

The competence `listelem` **omits** the `Die Schülerinnen und Schüler können`
stem — the stem lives in the preceding `absatz`.

### Section 2 — `Anwendungsbereiche` (the *Lehrstoff*, precisifying the above)

```
absatz/abs          Präzisierung der Kompetenzbeschreibungen         [949]
absatz/abs          … Die mit „allenfalls" gekennzeichneten Inhalte
                    sind nicht verbindlich. …                        [950]   <- the legend
absatz/erltext      1. Klasse:                                       [951]
absatz/abs          Kompetenzbereich 1: Zahlen und Maße              [953]   <== THE TRAP
absatz/abs          Die Schülerinnen und Schüler können natürliche
                    Zahlen … vergleichen.                            [954]   <- stem INLINE
liste                 listelem × n = the precisifying items          [955]
absatz/abs          Die Schülerinnen und Schüler können Rechen…      [956]
liste                 …                                              [957]
…
absatz/abs          Vorschläge für den Einsatz digitaler
                    Technologien4 in der 1. Klasse                   [977]
liste                 listelem × n                                   [978]
```

### 🪤 The element-type trap

`Kompetenzbereich 1: Zahlen und Maße` is:

* `ueberschrift/@typ="erll"` in the **Kompetenzbereiche** section, and
* `absatz/@typ="abs"` in the **Anwendungsbereiche** section.

Identical string, different element type, same logical meaning. A parser that
only looks at `ueberschrift` puts all 237 application items into one bucket.
The state machine therefore accepts an area heading from **either** element
type, disambiguated by the state it is in (`_classify` only treats an
`absatz/@typ="abs"` as an area heading while `State.ANWENDUNGSBEREICHE` is
active — otherwise ordinary prose mentioning a *Kompetenzbereich* would fire).

---

## 4. Level markers differ by band

| Document | `absatz/@typ="erltext"` | `ueberschrift/@typ="erll"` |
|---|---|---|
| Mittelschule | **57** | 4 |
| Volksschule | 5 | **35** |

The validated fact table said `absatz/@typ="erltext"`. That is true for Sek I
and **false for primary**, where `1. Schulstufe:` is normally an `erll` heading
(e.g. child 1237 in the VS document). The parser classifies a level marker from
*either* element type whenever the text matches
`^\d+\.\s*(Klasse|Schulstufe)\s*:?$`. Logged as a deviation.

Level codes: Sek I `K1..K4`, primary `SCH1..SCH4`. `GS1`/`GS2` do **not** occur
in the Grundstufe curricula.

---

## 5. The competence ↔ application-area join

There is **no ID**. The Anwendungsbereiche section links back to a competence by
repeating its sentence verbatim, with the stem inlined:

> Section 1 `listelem`: *„Größen ein- und mehrnamig anschreiben, Maßangaben
> interpretieren und Umrechnungen durchführen."*
> Section 2 `absatz`: *„**Die Schülerinnen und Schüler können** Größen ein- und
> mehrnamig anschreiben, Maßangaben interpretieren und Umrechnungen
> durchführen."*

The join therefore needs, in this order (all implemented in
`join_anwendungen`, all bucketed by *(class year, area number)* so a match can
never cross a year or an area):

1. **exact** — after stem stripping, `<super>` removal, unicode dash/quote/space
   folding, whitespace collapsing, trailing-punctuation and case folding;
2. **fuzzy** — `difflib.SequenceMatcher` ratio ≥ `0.90`;
3. **positional** — same bucket, same ordinal.

### Measured rates, Sek I Mathematik, all 40 competences

| Strategy | Count | Rate |
|---|---|---|
| exact | 38 | **95.0 %** |
| fuzzy (≥ 0.90) | 2 | **5.0 %** |
| positional fallback | 0 | 0.0 % |
| unmatched | 0 | 0.0 % |

exact + fuzzy = **100 %**. Every competence receives exactly one application
block and every block finds exactly one competence — the grid is a clean 1:1.

The two fuzzy pairs (both logged as `join_fuzzy` issues):

| Child | Section 1 text | Section 2 text | Ratio |
|---|---|---|---|
| 905/968 | „… Formeln für den Umfang und den Flächeninhalt **von Rechtecken** begründen und anwenden;" | „… Formeln für den Umfang und den Flächeninhalt begründen und anwenden." | 0.964 |
| 918/998 | „achsensymmetrische Figuren **sowie** zueinander kongruente Figuren …" | „achsensymmetrische Figuren **und** zueinander kongruente Figuren …" | 0.965 |

Threshold choice: the best *wrong* candidate inside a bucket scores well below
0.80 in this subject, so 0.90 sits in a wide gap. Re-measure when adding a
subject; do not assume the gap holds.

The live document contains no case that needs the positional fallback, so the
mini fixture supplies one deliberately.

---

## 6. V-44 — do `table`/`td` elements ever carry competence content? **No.**

Answered by scanning every `td` in both documents for
`Die Schülerinnen und Schüler können`, `allenfalls`, `Kompetenzbereich`,
`Wiederholen und Festigen`, `Kompetenzbeschreibung` and `Anwendungsbereich`:

| Document | Tables | `td` | non-empty `td` | cells containing any of those needles |
|---|---|---|---|---|
| Volksschule | 21 | 852 | 544 | **0** |
| Mittelschule | 32 | 2 040 | 1 215 | **0** |

The longest cell in either document is 91 characters (a Deutschförderung column
label). Every table falls into exactly one of three kinds:

1. **The ÜBERGREIFENDE THEMEN matrix** — one per document, in the VIERTER TEIL
   (VS child 88, 322 cells; MS child 81, 448 cells). Descriptive prose about
   the 13 themes, not competences.
2. **Stundentafeln and administrative tables** — VS children 277–335,
   MS children 286–361. Subject names and weekly-hour numbers.
3. **The per-subject footnote legend** — one 18-cell table at the *end* of each
   subject (13 filled + 5 empty), e.g. MS child 1071:
   `¹Bildungs-, Berufs- und Lebensorientierung`, `⁴Informatische Bildung`, …

**Consequence for the design:** the parser needs **no table path for content**.
It does need a *narrow* one: kind 3 is the authoritative number → theme map for
`<super>` resolution, and is parsed by `_parse_themen_tabelle`. Note the number
in those cells sits in a `<super>`, so the *raw* text (`ExtractedText.roh`) is
required — the cleaned text has the digit stripped and the map comes back empty.

The per-subject sentence at child 894 (`Dieser Lehrplan greift folgende
übergreifende Themen auf: …`) is a second, narrower source: it lists only the
10 themes this subject picks up. It seeds the map; the legend table (all 13)
overrides it. Split that sentence on a comma **following a digit** — splitting
on "comma before a capital" tears `Wirtschafts-, Finanz- und
Verbraucher/innenbildung` in half.

---

## 7. Verified counts, Sek I Mathematik

Reproduced by `python3 parse_lehrplan.py --verify`:

| Quantity | Count |
|---|---|
| competence areas | 4 |
| competence descriptions | 40 (4 areas × 4 class years) |
| application-area `listelem`s | 237 |
| … of which precisifications joined to a competence | 198 |
| … of which `Vorschläge für den Einsatz digitaler Technologien` | 39 |
| items containing `allenfalls` (⇒ `verbindlich: false`) | 32 |
| items beginning `Wiederholen und Festigen:` (K2–K4 only) | 16 |
| competences carrying a `<super>` theme marker | 10 |
| competence `listelem`s outside the four areas (GZ appendix) | 2 |

**The 237 is a section total, not a count of precisifications.** 39 of them are
the per-class-year digital-technology suggestion lists, which precisify no
competence. They are emitted with `art: "digitale_technologien"` and
`kompetenz_id: null`. None of them contains `allenfalls`.

`Wiederholen und Festigen` backlinks are positional: same area, class year − 1.
The source gives no identifier. It is Sek-I-only — **zero** occurrences in the
primary document, so primary progression must be derived positionally.

---

## 8. State machine, tolerance, and hard failures

States: `VOR_FACH → FACH_PRAEAMBEL → KOMPETENZBEREICHE ⇄ ANWENDUNGSBEREICHE →
FACH_ANHANG → NACH_FACH`. Every element is first classified into a `Token`,
then handled by exactly one per-state handler; there are no implicit
transitions.

**Tolerated (logged as a `ParseIssue`, parsing continues):**

| `art` | Trigger |
|---|---|
| `unbekannte_ueberschrift` | An `erll` heading inside a section that is neither an area nor a known section → leaves the section into `FACH_ANHANG`, content kept in `zusatzbloecke`. Fires once on the live document (the GZ appendix at 1063). |
| `bereich_ohne_slug` | Area name with no configured ID segment → deterministic slug derived |
| `unerwartete_stufeneinheit` | `Schulstufe` seen where `Klasse` expected, or vice versa |
| `bereichsnummer_wechselt` | Same area name appears with a different number |
| `liste_ohne_kontext`, `anwendungsliste_ohne_stufe`, `anwendungsliste_ohne_satz` | Structural surprise around a list |
| `join_fuzzy`, `join_positional`, `join_fehlgeschlagen` | Every non-exact join |
| `fachueberschrift_im_falschen_teil` | Subject heading found under the wrong TEIL |
| `thema_ohne_nummer`, `keine_themenlegende` | Theme map incomplete |

**Hard failures (`ParseError`):** a missing required field (`id`, `stufe`,
`text`), an ID collision, a document without `<nutzdaten>`/`<abschnitt>`, and
the configured subject heading not occurring at all.

### ID scheme

`AT.LP23.<Band>.<Fach>.<Bereich>.<Stufe>.<lfd>` (plan §4.8), e.g.
`AT.LP23.SEK1.M.ZAHLEN.K1.03`. Application items add a kind segment:
`AT.LP23.SEK1.M.AB.ZAHLEN.K2.05` (precisification),
`AT.LP23.SEK1.M.DT.ZAHLEN.K1.01` (digital-technology suggestion).
Area segments for Sek I maths: `ZAHLEN`, `VARIABLEN`, `FIGUREN`, `DATEN`.

---

## 9. What will be hard when extending to primary

Do not fan out before reading this list.

1. **Sections are merged.** Sek I has two headings; primary has one combined
   heading whose wording varies *by subject within the band*:
   * primary Mathematik: `Kompetenzbeschreibungen, Lehrstoff (1. bis 4. Schulstufe):`
     — **no Anwendungsbereiche at all** (`anwendungsbereiche_status` needs a
     third value, `keine`);
   * primary Deutsch and Sachunterricht:
     `Kompetenzbeschreibungen und Anwendungsbereiche, Lehrstoff (1. bis 4. Schulstufe):`.
   With one merged section, the element-type disambiguation of §3 has nothing
   to disambiguate *with* — competence descriptions and application items may
   sit in sibling `liste` elements under the same area heading. Expect to
   distinguish them by list position or by the presence of a repeated stem
   sentence, and re-measure the join from scratch.
2. **Sachunterricht area headings are adjective-first** —
   `Sozialwissenschaftlicher Kompetenzbereich`, `Naturwissenschaftlicher …`,
   `Geografischer …`, `Historischer …`, `Technischer …`, `Wirtschaftlicher …`
   (six, not four). `^Kompetenzbereich ` matches **zero** of them. Primary
   Mathematik meanwhile uses `Kompetenzbereich Zahlen und Daten` — the word
   first but **no number and no colon**. Three different shapes in the same
   band. `SubjectSpec.bereich_re` exists for exactly this; give each subject
   its own pattern rather than one clever regex, and make sure `nummer` is
   allowed to be `None` (the ID slug then has to come from `bereich_slugs`).
3. **Area headings also appear in prose.** In Sachunterricht the six area names
   occur first as `absatz/@typ="abs"` paragraphs inside the *Kompetenzmodell*
   subsection (VS children 1319–1329), before the competence section starts.
   A "contains *Kompetenzbereich* and is an `absatz`" rule fires on all of them.
   Keep the state guard: only treat an `absatz` as an area heading inside the
   application/competence section.
4. **Level markers are `ueberschrift/@typ="erll"` in primary** (§4). Already
   handled, but it means a level marker and an area heading are now the *same*
   element type in the *same* state — ordering of the checks in `_classify`
   matters and is load-bearing.
5. **Subject headings repeat across TEILs and are not always ALL CAPS** (§2).
   Set `teil_ueberschrift` on every primary `SubjectSpec`.
6. **No `Wiederholen und Festigen` in primary** — zero occurrences. Progression
   must come from the positional `vorlaeufer`/`folge` links, which the parser
   already fills for every competence.
7. **`<super>` markers are far more numerous in primary** (577 across the VS
   document vs a handful per Sek I subject) and there they genuinely mix theme
   references with ordinary footnotes. `fussnoten_unaufgeloest` is empty for
   Sek I maths; expect it not to be for primary, and expect the per-subject
   theme sentence to be the better filter than the 13-entry legend table.
8. **Primary Anwendungsbereiche are optional as a whole**, not item-by-item —
   `anwendungsbereiche_status: "optional_sektion"`, so `verbindlich` per item
   is meaningless there. Do not reuse the `allenfalls` flag blindly.

---

## 10. Running it

```bash
python3 data-pipeline/parse_lehrplan.py --summary     # counts + issue log
python3 data-pipeline/parse_lehrplan.py --verify      # non-zero exit on drift
python3 data-pipeline/parse_lehrplan.py --out out.json
python3 -m unittest discover -s data-pipeline/tests -t data-pipeline/tests
```

Fixtures in `tests/fixtures/`:

* `sek1_mathematik.xml` (98 KB) — the real MATHEMATIK span (children 854–1071)
  copied byte-for-byte, wrapped in a stub TEIL and flanked by trimmed neighbour
  subjects so the boundary logic is exercised. Regenerate it by re-extracting
  that span if the source is re-fetched.
* `sek1_mathematik_mini.xml` (7 KB) — synthetic, same shape at 1/50th the size,
  and carries the cases the live document lacks (notably a join only the
  positional fallback can resolve).
