# Sachunterricht

Ein Shard: `PRIM.SU` (`SCH1`–`SCH4`). Grundvertrag und Funktionsliste stehen in
`at-unterrichtsplanung/references/kompetenzdaten.md`; die Fach-Grundlagen (sechs
Kompetenzbereiche, Bindungsart der Anwendungsbereiche, Bildungsstandard-Bezug) in
`at-unterrichtsplanung/references/nawi.md`. Hier nur, welche Datenfelder je Stufe
(grundlegend/erweitert/vertiefend) tatsächlich befüllt werden und woher jedes Feld stammt.

Alle Aussagen unten sind Vertragsaussagen von `finde_differenzierung`/`finde_anwendungsbereiche`
(siehe `plugin/scripts/kompetenz.py`), gemessen am Beispiel
`AT.LP23.PRIM.SU.NATURWISS.SCH3.01` („… sich über Naturereignisse und Wetterphänomene
informieren sowie die Bedeutung von Sonne, Luft, Wasser und Boden für Lebewesen erkennen,
darüber nachdenken und Zusammenhänge erklären.“): **10** Anwendungsbereich-Items an der
3. Schulstufe insgesamt (`AB.SCH3.01`–`.10`), **2** Vorklasse-Stützungen
(`NATURWISS.SCH2.01`–`.02`), **0** `enrichment_items`. Andere Kompetenzen können andere
Vorklasse-Zähler haben; die Anwendungsbereich-Zahl (10) ist für **jede** SCH3-Kompetenz von
`PRIM.SU` gleich, siehe unten.

## Die Achse: `lehrplan_generisch`, keine Stufengrenze

`finde_differenzierung(kompetenz_id)["achse"]` liefert für `PRIM.SU` verbatim:

```
{"typ": "lehrplan_generisch", "niveaus": ["grundlegend", "erweitert", "vertiefend"],
 "quelle": "Kompetenzbeschreibungen + Anwendungsbereiche je Schulstufe",
 "optional_material": "docs/"}
```

Anders als bei `standard_standardplus` (SEK1.D/M/E) trägt diese Achse **kein** `gilt_ab_stufe`.
Gemessen für alle 48 `PRIM.SU`-Kompetenzen: `niveaus` ist an **jeder** Schulstufe nicht-leer und
identisch mit `achse["niveaus"]`. Die K1-Aussetzungsregel der Sek-I-Achse (leere `niveaus` für die
1. Klasse) gilt hier **nicht** und darf nicht auf `PRIM.SU` übertragen werden — an keiner Stufe von
Sachunterricht entfällt ein Label. Ein generiertes Dokument liest die drei Labels trotzdem bei
jedem Aufruf aus `finde_differenzierung`, nicht aus dieser Aufzählung: Die Werte sind stabil
gemessen, aber die Funktion bleibt die einzige Quelle.

## Grundlegend-Stufe

Quelle: `vorklasse_stuetzen` aus `finde_differenzierung` (`finde_progression(id, "zurueck")`,
gleicher Kompetenzbereich, Vorjahresstufe). Für `NATURWISS.SCH3.01` sind das `NATURWISS.SCH2.01`
(Körper, Sinne) und `NATURWISS.SCH2.02` (Tiere und Pflanzen in Lebensräumen) — **thematisch nicht
identisch** mit Wetter, aber die amtlich vorgesehene Grundlage: Beide üben Beobachtungs- und
Beschreibungsfertigkeiten (sinnesgestütztes Beobachten; Beobachten und Dokumentieren), die auf das
neue Thema übertragen werden. Ist `vorklasse_stuetzen` für eine andere Kompetenz leer, gilt wie bei
den anderen Fächern: `stammsatz` + die verbindlichen Anwendungsbereiche der Zielkompetenz selbst
als Stützung nennen, nie eine Diagnose oder Förderkategorie annehmen.

## Erweitert-Stufe

Quelle: `voller_wortlaut(kompetenz)` (`stammsatz` + `text`) plus
`finde_anwendungsbereiche(kompetenz_id, nur_verbindlich=True)` — mit der stufenweiten Falle unten.
`lehrstoff_quelle` ist `aus_anwendungsbereichen` (wie bei den meisten Fächern, anders als `PRIM.M`):
kein separater Lehrstoff-Aufruf nötig, die Anwendungsbereich-Items selbst sind der Lehrstoff.

## Vertiefend-Stufe

Quelle: `enrichment_items` aus `finde_differenzierung` — **für `PRIM.SU` immer `[]`**, gemessen für
alle 48 Kompetenzen. Die Achse trägt kein `enrichment_quelle: "allenfalls"` (das ist ausschließlich
`SEK1.M`). Das ist der wahre Datenstand, keine Lücke, die zu kompensieren wäre.

Die Vertiefend-Stufe ist deshalb **ausschließlich skill-eigene, fachlich begründete Vertiefung**,
rückgebunden an `stammsatz` + `text` der Zielkompetenz — z. B. eine kleine eigene Untersuchung, ein
mehrtägiges Beobachtungsprotokoll oder eine Erklärkette zu einem Zusammenhang, den die Kompetenz
selbst benennt. Kein generiertes Dokument darf hier behaupten, Standard-AHS-Inhalt oder ein
amtliches `allenfalls`-Item aus dem Datensatz abzufragen: Ein solches Feld existiert für `PRIM.SU`
nicht, und `enrichment_items` bleibt an dieser Stelle immer `[]`. Ein `herkunftsblock` mit
`amtlich: false` und einem `quelle_hinweis`, der genau das sagt, macht die Grenze im Dokument
sichtbar (siehe `at-unterrichtsplanung/references/lehrkraft_material.md`).

## Die zentrale Falle: stufenweite Anwendungsbereiche, nicht kompetenzgebunden

`PRIM.SU` trägt `anwendungsbereiche_bindung: "stufe"`, nicht `kompetenz`. Gemessen für
`NATURWISS.SCH3.01`: `finde_anwendungsbereiche(id, nur_verbindlich=True)` liefert 10 Items
(`AT.LP23.PRIM.SU.AB.SCH3.01`–`.10`). Dieselben 10 Items — **byte-identisch** — liefert der Aufruf
für **jede andere** `PRIM.SU`-Kompetenz derselben Schulstufe, unabhängig vom Kompetenzbereich
(gemessen: `GEOGRAFIE.SCH3.xx` und `TECHNIK.SCH3.xx` liefern dieselbe Liste). Ihre Texte streuen
über alle sechs Kompetenzbereiche des Fachs, z. B. `AB.SCH3.02` „Kinderrechte und Diversität“
(sozialwissenschaftlich) oder `AB.SCH3.03` „Geografische Gegebenheiten und Orientierung“
(geografisch) neben `AB.SCH3.08` „Klima und Wetter“ (naturwissenschaftlich).

**Ein Sachunterricht-Material darf diese zehn Items deshalb nie vollständig als Präzisierung der
gewählten Einzelkompetenz ausgeben.** Sie sind eine amtliche, aber schulstufenweite Liste für das
ganze Fach — die Auswahl, welche Items zur konkreten Kompetenz passen, ist eine **pädagogische
Entscheidung dieser Skill**, keine amtliche Eins-zu-eins-Bindung. Jedes Dokument, das eine Teilmenge
zitiert, sagt das ausdrücklich (Beispiel-Formulierung: „Auswahl aus der stufenweiten Liste, die
inhaltlich zu dieser Kompetenz passt — die übrigen Items derselben Stufe gehören zu anderen
Kompetenzbereichen und sind hier keine Präzisierung dieser Kompetenz.“). Die zitierten Items selbst
bleiben echte, wortgetreue `finde_anwendungsbereiche`-Treffer — nur ihre Bindung an die Einzelkompetenz
wird nicht behauptet.

## Keine Bildungsstandardsverordnung

`PRIM.SU` ist der einzige der sechs Shards mit `bildungsstandard_bezug: "keine_verordnung"`.
`finde_bildungsstandard_bezug(kompetenz_id)` liefert `{"abgedeckt": False, "grund": "keine BiSt
verordnet"}` — kein Fehler, keine Datenlücke. Ein Sachunterricht-Differenzierungsdokument enthält
deshalb regulär keinen Bildungsstandard-Bezug-Abschnitt; das nie mit einer erfundenen Referenz
füllen (siehe `at-unterrichtsplanung/references/nawi.md`).

## Datenzugriff

`fach="PRIM.SU"`. Reihenfolge pro Kompetenz: `finde_differenzierung(kompetenz_id)` für
`achse`/`niveaus`/`enrichment_items`/`vorklasse_stuetzen`, dann zusätzlich
`finde_anwendungsbereiche(kompetenz_id, nur_verbindlich=True)` für die Erweitert-Stufe — mit der
stufenweiten Auswahl-Pflicht oben. `finde_bildungsstandard_bezug` liefert den defined-empty Befund;
kein weiterer Aufruf nötig. Vollständiger Funktionsvertrag:
`at-unterrichtsplanung/references/kompetenzdaten.md`.
