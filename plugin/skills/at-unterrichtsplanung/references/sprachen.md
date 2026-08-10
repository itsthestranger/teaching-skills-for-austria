# Sprachen

Drei Shards: `PRIM.D` (Deutsch, Primarstufe, `SCH1`–`SCH4`), `SEK1.D` (Deutsch, Sek I,
`K1`–`K4`), `SEK1.E` (`(Erste) Lebende Fremdsprache`, Sek I, `K1`–`K4`). **Es gibt kein `PRIM.E`**
— eine Fremdsprache ist im Datensatz erst ab der Sekundarstufe I vorhanden. Grundvertrag und
Funktionsliste: `references/kompetenzdaten.md`.

## Wichtigste Korrektur: die Differenzierungsachse ist NICHT primär GERS

Sprachen sind hier nicht automatisch "die GERS-Fächer". Amtlich gilt: `SEK1.D` **und** `SEK1.E`
tragen dieselbe Achse wie Mathematik — `standard_standardplus`, `niveaus: ["Standard",
"Standard AHS"]`, gültig **erst ab `K2`** (`gilt_ab_stufe: "K2"`; für `K1` liefert
`finde_differenzierung` `niveaus: []`). GERS (Gemeinsamer Europäischer Referenzrahmen) ist bei
`SEK1.E` eine **zusätzliche** Unter-Achse (`achse.gers`) mit zwei getrennten Angaben: `niveaus:
["A1", "A2", "B1"]` ist die **fachweite** Aussage aus dem Lehrplan. Seit E8-05 gibt es zusätzlich
eine echte **Zuordnung pro Klasse** (`je_stufe_ausgewiesen: True`, `achse.gers.je_stufe["K1"..
"K4"]`, auch direkt als `gers_stufe` im Rückgabewert der abgefragten Kompetenz) — pro Klasse
`niveau` (z. B. `"A2+ mit ausgewählten Deskriptoren aus B1"`), der amtliche Originalsatz (`satz`)
und Zitier-Provenienz (`abschnitt`, `quell_index`). Eine A1/A2/B1-Zuordnung für eine bestimmte
Klasse ist damit erlaubt, aber nur mit dieser Zitatgrundlage aus `gers_stufe`/`je_stufe` — nie ohne
`satz`, und nie für ein anderes Fach als `SEK1.E` (dort existiert `achse.gers` überhaupt nicht).

`PRIM.D` hat wie alle Primarstufenfächer `lehrplan_generisch`
(`niveaus: ["grundlegend", "erweitert", "vertiefend"]`), keine Standard/Standard-AHS-Achse.

## Kompetenzbereiche

- **`PRIM.D`** (4): `HOERENSPRECHEN` ((Zu-)Hören und Sprechen), `LESEN` (Lesen), `RECHTSCHREIBEN`
  ((Recht-)Schreiben und Sprachbetrachtung), `VERFASSEN` (Verfassen von Texten).
- **`SEK1.D`** (4): `HOERENSPRECHEN` (Zuhören und Sprechen), `LESEN` (Lesen), `SCHREIBEN`
  (Schreiben), `SPRACHREFLEXION` (Sprachbewusstsein und Sprachreflexion).
- **`SEK1.E`** (4): `HOEREN` (Hören), `LESEN` (Lesen), `SCHREIBEN` (Schreiben), `SPRECHEN`
  (Sprechen: an Gesprächen teilnehmen und zusammenhängend sprechen).

## `SEK1.D`s `SPRACHREFLEXION` ist strukturell, nicht kompetenz-tragend

Der Lehrplan formuliert Sprachbewusstsein/Sprachreflexion integrativ in den anderen drei
Bereichen — `SPRACHREFLEXION` hat **keine eigenen Kompetenz-Records**, aber **12 amtliche
Lehrstoff-Items** (3 pro Klassenjahr, `K1`–`K4`), die über keine `kompetenz_id` erreichbar sind.
Für diese Items **Koordinaten-Modus** verwenden:
`finde_anwendungsbereiche(fach="SEK1.D", stufe="K2", bereich="SPRACHREFLEXION")` (analog
`finde_lehrstoff`). Eine Planung, die Sprachreflexion behandelt, aber nie in Koordinaten-Modus
nachschlägt, findet diese 12 Items nie.

## `SEK1.E`: Anwendungsbereiche ist Fließtext

`anwendungsbereiche_bindung: "prosa"` — der Abschnitt existiert, ist aber Fließtext, kein
Item-Katalog. `finde_anwendungsbereiche`/`finde_lehrstoff` liefern für `SEK1.E` immer `[]`
(`lehrstoff_quelle` bleibt trotzdem formal `"aus_anwendungsbereichen"`) — das ist die amtliche
Textstruktur, kein Fehler.

## `SEK1.E`: den Stammsatz nie weglassen

Bei `SEK1.E` trägt `Kompetenz.stammsatz` bei zehn Kompetenzen eine echte Bedingung, z. B.
*"Die Schülerinnen und Schüler können, wenn sehr langsam, klar und deutlich in Standardsprache
gesprochen wird, …"* — diese Bedingung ist Teil der Kompetenz, nicht Beiwerk. Immer
`voller_wortlaut()`/`volltext` zitieren, nie `text` isoliert (siehe `kompetenzdaten.md`) — sonst
wird eine bedingte Kompetenz fälschlich als unbedingt dargestellt.

## Bildungsstandard-Bezug

Alle drei Shards: `bildungsstandard_bezug: "verordnet"` (Deskriptor-Crosswalk noch offen, siehe
`kompetenzdaten.md`).

## Datenzugriff

`fach="PRIM.D"`, `fach="SEK1.D"` bzw. `fach="SEK1.E"`. Vollständiger Vertrag:
`references/kompetenzdaten.md`.
