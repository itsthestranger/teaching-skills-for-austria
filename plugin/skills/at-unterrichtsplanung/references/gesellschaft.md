# Gesellschaft

Für diese Fachgruppe gibt es **aktuell keinen eigenen Shard**. Geschichte und Politische Bildung
sowie Geografie und Wirtschaftskunde (jeweils Sekundarstufe I) sind nicht Teil der sechs
gebauten Shards (`PRIM.D`, `PRIM.M`, `PRIM.SU`, `SEK1.D`, `SEK1.E`, `SEK1.M`). Es gibt für diese
Fächer **keine** `finde_*`-Ergebnisse, **keine** Kompetenz-IDs und **keine** RIS-Zitate im
Datensatz.

## Verhalten bei einer Anfrage in diese Richtung

Wenn eine Lehrkraft eine Einheit für Geschichte, Politische Bildung, Geografie oder
Wirtschaftskunde (Sek I) verlangt:

1. **Klar sagen**, dass für dieses Fach kein amtlicher RIS-Kompetenzdatensatz in diesem Plugin
   vorhanden ist — nie eine Kompetenz-ID, ein NOR-Zitat oder eine Bildungsstandard-Referenz dafür
   erfinden.
2. Wenn die Anfrage eigentlich Sachunterricht der Primarstufe meint (z. B. "Wirtschaft für die
   3. Klasse Volksschule" oder "historische Perspektiven im Sachunterricht"), dorthin routen:
   Sachunterricht deckt gesellschaftsbezogene Inhalte über vier seiner sechs Kompetenzbereiche
   ab (`SOZIALWISS`, `HISTORISCH`, `GEOGRAFIE`, `WIRTSCHAFT`) — siehe `references/nawi.md`, die
   für **jede** Sachunterricht-Anfrage die richtige Referenz ist, unabhängig vom inhaltlichen
   Schwerpunkt.
3. Sonst der Lehrkraft die Wahl lassen: mit einem anderen, tatsächlich abgedeckten Fach
   fortfahren, oder eine Einheit ohne amtliche RIS-Verankerung erstellen — und diese dann
   ausdrücklich **nicht** als kompetenzorientiert/amtlich-verankert kennzeichnen.

## Für später

Sollte ein Shard für eines dieser Fächer künftig gebaut werden, bekommt er hier dieselbe Struktur
wie die anderen Fachreferenzen: Kompetenzbereiche, Bindungsart der Anwendungsbereiche,
Lehrstoffquelle, Bildungsstandard-Bezug, Differenzierungsachse. Diese Datei ist bewusst ein
knapper Platzhalter und keine Vorwegnahme nicht vorhandener Daten.

## Datenzugriff

Kein `fach`-Schlüssel für diese Gruppe. Sobald ein Shard existiert, gilt derselbe Vertrag wie in
`references/kompetenzdaten.md`.
