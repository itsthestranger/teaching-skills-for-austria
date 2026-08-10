# Mathematik

Zwei Shards: `PRIM.M` (`SCH1`–`SCH4`) und `SEK1.M` (`K1`–`K4`). Grundvertrag und Funktionsliste
stehen in `at-unterrichtsplanung/references/kompetenzdaten.md`; die Fach-Grundlagen (Bereiche,
`allenfalls` vs. verbindlich, Bildungsstandard-Bezug) in
`at-unterrichtsplanung/references/mathematik.md`. Hier nur, welche Datenfelder je Stufe
(unter/auf/über) tatsächlich befüllt werden und woher jedes Feld stammt — kein Aufgabentyp-Rezept,
sondern die Datenquelle je Stufe.

Alle Aussagen unten sind Vertragsaussagen von `finde_differenzierung`/`finde_anwendungsbereiche`
(siehe `plugin/scripts/kompetenz.py`), gemessen am Beispiel `AT.LP23.SEK1.M.ZAHLEN.K2.03`
(„Rechenoperationen mit nichtnegativen Bruchzahlen durchführen und interpretieren; …“): **8**
verbindliche Anwendungsbereich-Items (`.12`–`.20`, ohne `.17`), **1** `allenfalls`-Item (`.17`),
**3** Vorklasse-Stützungen (`ZAHLEN.K1.01`–`.03`). Andere Kompetenzen können andere Zähler haben;
diese Zahlen sind ein Beleg, keine Konstante.

## Auf-Stufe

Quelle: `voller_wortlaut(kompetenz)` (`stammsatz` + `text`) plus
`finde_anwendungsbereiche(kompetenz_id, nur_verbindlich=True)`. Für `SEK1.M` sind das echte,
verbindliche Präzisierungs-Items direkt an der Kompetenz. Für `PRIM.M`
(`anwendungsbereiche_bindung: "keine"`) gibt es keinen Anwendungsbereiche-Abschnitt; dort liefert
`finde_lehrstoff` `{quelle: "eigen_ausgewiesen", items: [volltext]}` — die Kompetenzbeschreibung
selbst ist der Lehrstoff, kein separates Item zu erfinden.

## Unter-Stufe

**Zwei amtlich unterschiedliche Quellen, getrennt auszuweisen — nie zusammengelegt:**

1. **`vorklasse_stuetzen`** — echte, positionale Vorgänger-*Kompetenzen* aus
   `finde_progression(kompetenz_id, "zurueck")`, gleicher Bereich, Vorjahresstufe. Jede trägt ihren
   eigenen `volltext` und ihre eigene `provenienz`. Für `SEK1.M.ZAHLEN.K2.03` sind das
   `ZAHLEN.K1.01`–`.03`.
2. **`Wiederholen und Festigen`-Items** — echte *Anwendungsbereich*-Items, deren Text wörtlich mit
   `"Wiederholen und Festigen:"` beginnt (V-10), erreichbar über
   `finde_anwendungsbereiche(kompetenz_id, nur_verbindlich=True)`, nicht über
   `finde_differenzierung`. Sie sind verbindlicher Kernstoff der *aktuellen* Stufe, formuliert als
   Rückgriff auf Vorwissen — keine Kompetenz-Records und kein Ersatz für 1. `finde_differenzierung`
   liefert sie nicht mit; sie müssen separat abgefragt werden.

Diese zwei Quellen sind bewusst getrennt (siehe `finde_differenzierung`-Docstring): ein Item darf
nie als „Vorklasse-Stützung“ ausgegeben werden, und eine Vorgänger-Kompetenz nie als „Wiederholen
und Festigen“. Für `PRIM.M` existiert die zweite Quelle nicht (kein Anwendungsbereiche-Abschnitt);
die Unter-Stufe stützt sich dort ausschließlich auf `vorklasse_stuetzen`.

## Über-Stufe

Quelle: `enrichment_items` aus `finde_differenzierung` — **nur befüllt, wenn die Achse
`enrichment_quelle: "allenfalls"` trägt (gemessen: `SEK1.M` allein)**. Jedes Item ist echter
amtlicher `allenfalls`-Text, `verbindlich: false`, und muss so beschriftet werden — nie
stillschweigend als Kernstoff. Für jeden anderen Shard (inkl. `PRIM.M`) ist `enrichment_items`
immer `[]`; die Über-Stufe ist dort ausschließlich skill-eigene, fachlich begründete Vertiefung auf
`stammsatz` + `text` der Zielkompetenz — **nie** eine behauptete Abfrage von „Standard-AHS-Inhalt“
aus dem Datensatz, weil ein solches Feld nirgends existiert (siehe nächster Abschnitt).

**Falle (V-88):** `enrichment_items` hängt einzig an `enrichment_quelle`, nicht an `niveaus`. Eine
`K1`-Kompetenz von `SEK1.M` kann echten `allenfalls`-Inhalt tragen, obwohl `niveaus` dort leer ist
(gemessen: `AT.LP23.SEK1.M.FIGUREN.K1.01`). Dieser Inhalt darf die Über-Stufe füllen — aber ohne
jede Standard/Standard-AHS-Beschriftung, siehe K1-Regel unten.

## `niveaus` ist Metadaten, nie eine Item-Markierung (V-42/V-60)

`"Standard"`/`"Standard AHS"` kommt ausschließlich als Fließtext im Lehrplan vor. Der Datensatz
markiert **kein einzelnes** Kompetenz- oder Anwendungsbereich-Item mit einem dieser Labels, und es
gibt keine Abfragefunktion, die das täte. `niveaus` (aus `finde_differenzierung`) ist eine
**stufenweite Einstufung** — informativ für den Differenzierungsplan, aber nie eine Zeile, die
sagt „dieses Item ist Standard AHS“. Kein erzeugter Satz darf suggerieren, `finde_anwendungsbereiche`
oder ein anderer Funktionsaufruf könne Standard von Standard AHS pro Item unterscheiden. Das gilt
für **jede** Stufe (unter/auf/über) und für beide Shards.

## K1-Regel (V-78)

`niveaus` ist für jede `K1`-Kompetenz von `SEK1.M` (und ebenso `SEK1.D`/`SEK1.E`) leer, weil die
Standard/Standard-AHS-Unterscheidung laut Lehrplan erst ab der 2. Klasse (`gilt_ab_stufe: "K2"`)
gilt. Für eine `K1`-Einheit darf kein Dokument dieser Skill „Standard“ oder „Standard AHS“ als
Stufen-Label drucken — auch nicht andeutungsweise. Das gilt unabhängig von `enrichment_items`
(siehe Falle oben): reale `K1`-`allenfalls`-Inhalte dürfen die Vertiefung inhaltlich speisen, aber
nie mit „Standard AHS“ überschrieben werden, nur weil zufällig Erweiterungsstoff existiert.
`PRIM.M` hat ohnehin keine Standard/Standard-AHS-Achse (`lehrplan_generisch`), also stellt sich die
Frage dort nicht.

## Datenzugriff

`fach="PRIM.M"` bzw. `fach="SEK1.M"`. Reihenfolge pro Kompetenz:
`finde_differenzierung(kompetenz_id)` für `achse`/`niveaus`/`enrichment_items`/
`vorklasse_stuetzen`, dann zusätzlich `finde_anwendungsbereiche(kompetenz_id, nur_verbindlich=True)`
für die Auf-Stufe und für die `Wiederholen und Festigen`-Items der Unter-Stufe (letztere per
Textfilter auf `"Wiederholen und Festigen:"`, da `finde_differenzierung` sie nicht zurückgibt).
Vollständiger Funktionsvertrag: `at-unterrichtsplanung/references/kompetenzdaten.md`.
