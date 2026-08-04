# Naturwissenschaften & Sachunterricht

Aktuell **ein** Shard: `PRIM.SU` (Sachunterricht, Primarstufe, `SCH1`–`SCH4`). Grundvertrag und
Funktionsliste: `references/kompetenzdaten.md`.

## Was verfügbar ist — und was (noch) nicht

Nur Sachunterricht der Primarstufe hat einen amtlichen RIS-Datensatz in diesem Plugin.
**Biologie, Physik und Chemie der Sekundarstufe I sind nicht Teil der sechs gebauten Shards** —
für diese Fächer gibt es keine `finde_*`-Ergebnisse, keine Kompetenz-IDs, keine RIS-Zitate. Fragt
eine Lehrkraft nach einer Einheit für eines dieser Fächer, das klar sagen (kein amtlicher
Kompetenzdatensatz verfügbar) statt eine Kompetenz-ID oder ein Zitat zu erfinden. Bis ein
entsprechender Shard existiert, ist das außerhalb des Leistungsumfangs dieser Skill.

## Kompetenzbereiche (`PRIM.SU`, sechs, nicht vier)

Sachunterricht hat **sechs** Kompetenzbereiche, alle adjektivisch benannt (nicht
"Kompetenzbereich <Name>", sondern "<Name> Kompetenzbereich"):

`SOZIALWISS` (Sozialwissenschaftlicher Kompetenzbereich), `NATURWISS` (Naturwissenschaftlicher
Kompetenzbereich), `GEOGRAFIE` (Geografischer Kompetenzbereich), `HISTORISCH` (Historischer
Kompetenzbereich), `TECHNIK` (Technischer Kompetenzbereich), `WIRTSCHAFT` (Wirtschaftlicher
Kompetenzbereich).

Sachunterricht ist **ein** Fach mit **einem** Shard — auch wenn `SOZIALWISS`/`HISTORISCH`/
`GEOGRAFIE`/`WIRTSCHAFT` inhaltlich gesellschaftsbezogen sind, gehören sie routing-technisch
hierher (`nawi.md`/`PRIM.SU`), nicht zu `references/gesellschaft.md`. Diese Skill lädt für jede
Sachunterricht-Anfrage `nawi.md`, unabhängig davon, welcher der sechs Bereiche gemeint ist.

## Keine Bildungsstandardsverordnung

`PRIM.SU` ist der **einzige** der sechs Shards mit `bildungsstandard_bezug: "keine_verordnung"`.
`finde_bildungsstandard_bezug` liefert dafür `{"abgedeckt": False, "grund": "keine BiSt
verordnet"}` — das ist die amtlich korrekte, ehrliche Antwort, **kein** Fehler und **keine**
Datenlücke, die zu kompensieren wäre. Eine Sachunterricht-Planung enthält deshalb regulär keinen
Bildungsstandard-Bezug-Abschnitt; das nie mit einer erfundenen Referenz füllen.

## Anwendungsbereiche & Lehrstoff

`anwendungsbereiche_bindung: "stufe"` — Items hängen nur an der Schulstufe, nicht an einem
einzelnen Kompetenzbereich; sie gelten für die ganze Schulstufe über alle sechs Bereiche hinweg.
Koordinaten-Modus akzeptiert deshalb nur `fach` + `stufe`, **kein** `bereich`-Filter (der
Lehrplan macht diese Filterung selbst nicht). `lehrstoff_quelle: "aus_anwendungsbereichen"` —
Lehrstoff kommt wie bei den meisten Fächern aus den Anwendungsbereich-Items, anders als bei
`PRIM.M` (siehe `mathematik.md`).

## Differenzierungsachse

`lehrplan_generisch`, `niveaus: ["grundlegend", "erweitert", "vertiefend"]`, keine
Stufengrenze — wie bei allen Primarstufenfächern gibt es hier keine Standard/Standard-AHS-Achse.

## Datenzugriff

`fach="PRIM.SU"`. Vollständiger Vertrag: `references/kompetenzdaten.md`.
