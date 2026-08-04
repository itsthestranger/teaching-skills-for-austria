# Mathematik

Zwei Shards: `PRIM.M` (Schulstufen `SCH1`–`SCH4`) und `SEK1.M` (Klassen `K1`–`K4`). Grundvertrag
und Funktionsliste stehen in `references/kompetenzdaten.md` — hier nur, was für dieses Fach
anders läuft als im Standardfall.

## Kompetenzbereiche

- **`PRIM.M`** (4): `ZAHLENDATEN` (Zahlen und Daten), `OPERATIONEN` (Operationen), `GROESSEN`
  (Größen), `EBENERAUM` (Ebene und Raum).
- **`SEK1.M`** (4): `ZAHLEN` (Zahlen und Maße), `FIGUREN` (Figuren und Körper), `VARIABLEN`
  (Variablen und Funktionen), `DATEN` (Daten und Zufall) — **plus** eine synthetische, nicht
  gezählte fünfte Gruppe `GZINTEGRATIV` ("Kompetenzen bei integrativer Führung von Geometrisches
  Zeichnen", nur `K3`/`K4`, 2 Kompetenzen, `bereich_nummer: null`). `kompetenzbereiche` bleibt
  amtlich bei 4; `GZINTEGRATIV` erscheint nur in `zusatzkompetenzen`/`zusatz.json`, nie in der
  Bereichsliste.

## `PRIM.M` ist der Sonderfall im ganzen Datensatz

`PRIM.M` ist das **einzige** Fach mit `anwendungsbereiche_bindung: "keine"` — es gibt **keinen**
Anwendungsbereiche-Abschnitt im Lehrplan. `finde_anwendungsbereiche` liefert für `PRIM.M` immer
`[]`; das ist keine Lücke, sondern die amtliche Textstruktur. Entsprechend ist
`lehrstoff_quelle: "eigen_ausgewiesen"`: `finde_lehrstoff` gibt für `PRIM.M` **die Kompetenz
selbst** zurück (`{quelle: "eigen_ausgewiesen", items: [volltext]}`) — die Kompetenzbeschreibung
IST hier der Lehrstoff, es gibt keinen separaten Präzisierungstext. Eine Planung für `PRIM.M`
zitiert also nur die Kompetenzbeschreibung selbst als Lehrstoffnachweis, nie ein erfundenes
Anwendungsbereich-Item.

## `SEK1.M`: verbindlich vs. `allenfalls`

`anwendungsbereiche_bindung: "kompetenz"` — Items hängen direkt an `Kompetenz.anwendungsbereiche`.
Von den items mit `art: "praezisierung"` sind **166 verbindlich, 32 `allenfalls`** (nicht
verbindlich, Erweiterungsstoff). Weitere Items mit `art: "digitale_technologien"` sind
**keine** Lehrstoff-Präzisierungen — `finde_anwendungsbereiche`/`finde_lehrstoff` filtern sie
bereits heraus; sie in einer Unterrichtsplanung als Lehrstoff zu zitieren wäre falsch.
`nur_verbindlich=True` liefert die bindende Teilmenge, `nur_verbindlich=False` die
`allenfalls`-Teilmenge — für **at-unterrichtsplanung** zählt die verbindliche Teilmenge als
Kernstoff; `allenfalls`-Inhalte gehören in eine Erweiterung, nicht ins Pflichtprogramm einer
neuen Einheit (Erweiterungstiefe ist das Thema von `at-differenzierung`, nicht dieser Skill).

## Differenzierungsachse

- **`SEK1.M`**: `standard_standardplus`, `niveaus: ["Standard", "Standard AHS"]`, gültig **erst
  ab `K2`** (`gilt_ab_stufe: "K2"`). Für `K1` liefert `finde_differenzierung` `niveaus: []` — in
  einer `K1`-Einheit gibt es keine Standard/Standard-AHS-Unterscheidung, das nie behaupten.
  Zusätzlich `enrichment_quelle: "allenfalls"`: die `allenfalls`-Items sind die Datenquelle für
  vertiefende Inhalte.
- **`PRIM.M`**: `lehrplan_generisch`, `niveaus: ["grundlegend", "erweitert", "vertiefend"]`, ohne
  Stufengrenze — Primarstufe hat keine Standard/Standard-AHS-Achse.

## Bildungsstandard-Bezug

Beide Shards: `bildungsstandard_bezug: "verordnet"` — eine Bildungsstandardsverordnung existiert,
der Deskriptor-Crosswalk ist aber noch nicht gebaut (`finde_bildungsstandard_bezug` gibt
`deskriptoren: []` mit Hinweis zurück, siehe `kompetenzdaten.md`).

## Datenzugriff

`fach="PRIM.M"` bzw. `fach="SEK1.M"` an jede `finde_*`-Funktion. Vollständiger Vertrag:
`references/kompetenzdaten.md`.
