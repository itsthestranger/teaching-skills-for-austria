# Kompetenzdaten — Tool-Vertrag & Datenzugriff

Gemeinsame Referenz für alle Fachgruppen. Zugriff auf die amtlichen Kompetenzdaten läuft
**ausschließlich** über `plugin/scripts/kompetenz.py`. Nie den Inhalt der Shards aus Wissen
"aus dem Kopf" ergänzen oder erraten — jede Aussage über eine Kompetenz, ein Anwendungsbereich-Item
oder eine Differenzierungsachse kommt aus einem Aufruf dieser Funktionen.

## Die sechs Shards

Shard-Schlüssel sind `"<BAND>.<FACH>"`, immer groß geschrieben: `PRIM.D`, `PRIM.M`, `PRIM.SU`,
`SEK1.D`, `SEK1.E`, `SEK1.M`. `SEK1.E` ist `(Erste) Lebende Fremdsprache` — nicht "Englisch"
als eigener Fachcode; die deutsche Anzeige nennt trotzdem die amtliche Fachbezeichnung. Es gibt
**kein** `PRIM.E`. Primarstufe zählt Schulstufen `SCH1`–`SCH4`, Sekundarstufe I Klassen `K1`–`K4`.

Dispatch ist überall **metadaten-gesteuert**: welche Funktion welchen Pfad nimmt, hängt von
`meta.anwendungsbereiche_bindung`, `meta.lehrstoff_quelle`, `meta.bildungsstandard_bezug` und
`meta.differenzierungs_achse` ab — nie von einer festverdrahteten Fachliste. Eine Fachreferenz,
die "weil das Fach X ist" statt "weil die Achse Y ist" begründet, ist falsch.

## Die neun Vertragsfunktionen (plus Zusatz)

Alle in `plugin/scripts/kompetenz.py`, pure stdlib, offline, deterministisch.

1. **`finde_kompetenz(fach, stufe=None, kompetenzbereich=None, code=None, stichworte=None) → list[Kompetenz]`**
   Sucht Kompetenzbeschreibungen in einem Shard. `code` ist ein exakter `kompetenz_id`-Lookup.
   `stichworte` routet über den Stichwortindex (siehe unten). **Leere Liste heißt nicht
   "Begriff kommt im Lehrplan nicht vor"** — sie heißt nur, dass keine *Kompetenzbeschreibung*
   den Begriff enthält. Der Begriff kann ausschließlich in einem Lehrstoff-Item stehen; vor einer
   Absage an die Lehrkraft `stichwort_abdeckung` prüfen.
2. **`finde_progression(kompetenz_id, richtung: "zurueck"|"vor") → list[Kompetenz]`**
   Vorläufer/Nachfolger derselben Kompetenz, positionsbasiert über Schulstufe × Kompetenzbereich.
3. **`finde_anwendungsbereiche(kompetenz_id=None, nur_verbindlich=None, *, fach=None, stufe=None, bereich=None) → list[Item]`**
   Anwendungsbereich-Items, die eine Kompetenz präzisieren. Entweder `kompetenz_id` **oder**
   Koordinaten (`fach` + je nach Bindung `stufe`/`bereich`) — nie beides gemischt. Welche
   Koordinaten nötig sind, hängt von `meta.anwendungsbereiche_bindung` ab (siehe unten).
   `nur_verbindlich=True/False` filtert auf das `verbindlich`-Flag; nur bei `SEK1.M` ist das ein
   echter Split (32 `allenfalls`-Items von 198), bei den anderen fünf Shards ist alles verbindlich.
4. **`finde_lehrstoff(kompetenz_id=None, *, fach=None, stufe=None, bereich=None) → {quelle, items: list[str]}`**
   `quelle` ist `"aus_anwendungsbereichen"` (fünf Shards) oder `"eigen_ausgewiesen"` (nur `PRIM.M`,
   siehe `mathematik.md`). Dieselben Koordinaten-Regeln wie oben.
5. **`finde_lernaufgaben(fach=None, stufe=None, kompetenz_id=None, docs_root=None) → list[dict]`**
   Lehrkraft-Material aus `docs/`. Jeder Treffer trägt `herkunft: "docs"`, `amtlich: False` — nie
   als amtlich ausweisen. Fehlendes/leeres `docs/` → `[]`, kein Fehler. **Interimsleser**: nur
   `.md`/`.txt`; die volle Ingestion (`.pdf`/`.docx`, `docs/.cache/`, Limits) ist eine eigene,
   noch offene Aufgabe.
6. **`finde_bildungsstandard_bezug(kompetenz_id) → dict`**
   Der Deskriptor-Crosswalk ist seit E8-03 gebaut (50 Bereichszuordnungen, V-82). Drei
   verschiedene, gemessene Ergebnisformen — keine zwei, keine ist ein ausstehender Zustand:
   - **Mapped** (die 197 gewöhnlichen Nicht-SU-Kompetenzen, z. B. `SEK1.M.ZAHLEN.K2.01`):
     `{"abgedeckt": True, "deskriptoren": […], "zuordnungen": […], "methodik": …, "hinweis":
     "Bereichsbezug; keine 1:1-Zuordnung von Lehrplan-Kompetenzen zu
     Bildungsstandard-Deskriptoren."}`. Dieser `hinweis` ist die methodische Präzisierung und
     steht bei **jedem** erfolgreichen Treffer — er ist kein Zeichen für einen fehlenden
     Crosswalk.
   - **Covered-but-unmapped** (die zwei synthetischen `GZINTEGRATIV`-Kompetenzen):
     `{"abgedeckt": True, "deskriptoren": [], "zuordnungen": [], "methodik": …, "hinweis": "Für
     diesen Zusatzbereich besteht keine Bereichszuordnung; es wird keine Deskriptoridentität
     erfunden."}`. Anderer `hinweis`-Text als oben; transparent als "für diesen Bereich keine
     Zuordnung" nennen.
   - **Defined-empty** (`PRIM.SU`, alle Kompetenzen — die *einzige* Fachgruppe ohne
     Bildungsstandardsverordnung): `{"abgedeckt": False, "grund": "keine BiSt verordnet"}` — kein
     `deskriptoren`-Feld, kein `hinweis`; ehrlich als Nichtvorhandensein, nicht als Bug.

   Nie einen Bildungsstandard-Deskriptor erfinden, in keiner der drei Formen.
7. **`finde_uebergreifende_themen(fach=None, kompetenz_id=None, thema=None) → list`**
   Genau eines der drei Argumente angeben. Übergreifende Themen sind Lehrplan-Querschnittsthemen
   (z. B. "Medienbildung"), keine freie Verschlagwortung.
8. **`finde_differenzierung(kompetenz_id) → {achse, niveaus, enrichment_items, vorklasse_stuetzen, docs_material}`**
   `achse` ist die Metadaten-Achse verbatim; `niveaus` sind die an dieser Stufe *wirksamen* Labels
   (vor `gilt_ab_stufe` ist die Liste leer, siehe je Fachreferenz). `enrichment_items` ist nur bei
   `SEK1.M` befüllt (Quelle: `allenfalls`). `vorklasse_stuetzen` ist immer die positionale
   Vorjahres-Kompetenz, nie ein rohes Anwendungsbereich-Item.
9. **`finde_typische_fehlvorstellungen(kompetenz_id) → []`**
   Liefert **immer** `[]` — kuratierte Fehlvorstellungsdaten existieren noch nicht und werden nie
   vom Modell selbst erfunden.

Zusätzlich, nicht Teil der neun, aber wichtig:

- **`kompetenz_nach_id(kompetenz_id) → Kompetenz`** — Einzel-Lookup nach voller ID.
- **`voller_wortlaut(kompetenz) → str`** — verbindet `stammsatz` + `text` korrekt. **Immer diese
  Funktion (oder das mitgelieferte `volltext`-Feld) für ein Zitat verwenden, nie `text` allein** —
  bei manchen Fächern (z. B. `SEK1.E`) trägt `stammsatz` eine Bedingung, die zur Kompetenz gehört.
- **`stichwort_abdeckung(fach, begriff) → dict`** — Introspektions-Helfer für den Stichwortindex:
  meldet, ob der Treffer eine Kompetenzbeschreibung, nur ein Lehrstoff-Item oder gar nichts war
  (`suchstatus` + deutscher `hinweis`). Vor jeder "kommt im Lehrplan nicht vor"-Aussage aufrufen.
- **Exceptions:** `KompetenzFehler` (Basisklasse), `UnbekannterFachSchluessel` (ungültiger
  Shard-Schlüssel), `KompetenzNichtGefunden` (ID existiert nicht). `finde_*` werfen sonst nicht
  für "keine Treffer" — nur für einen malformten `fach`.

## Die fünf Bindungsarten für Anwendungsbereiche

`meta.anwendungsbereiche_bindung` hat genau fünf Werte, jede Fachreferenz sagt, welche ihr Fach
hat: `kompetenz` (an eine Kompetenz genäht), `bereich` (an Kompetenzbereich + Schulstufe),
`stufe` (nur an die Schulstufe, fachbereichsübergreifend), `prosa` (Abschnitt existiert, ist aber
Fließtext — immer `[]`), `keine` (kein Abschnitt vorhanden — immer `[]`). `prosa`/`keine` sind
**definiert-leer**, kein Zeichen für einen Bug.

## Stichwortsuche — bekannte Grenze

Der Index (`index.json`, `stichwort_index`) matcht auf ganze Token; deutsche Komposita wie
"Bruchtermen" sind ein eigener Schlüssel neben "Bruch". `finde_kompetenz` vereinigt exakte und
Substring-Treffer über die Indexschlüssel, prüft die Kandidaten aber danach am echten Text nach —
Präzision bleibt erhalten, aber ein Substring-Treffer im Index bedeutet noch keinen Texttreffer.

## Herkunft

Jedes von `kompetenz.py` zurückgegebene Objekt trägt `provenienz` (NOR, Kundmachung, Stand) —
diese Angaben, nicht eine selbst zusammengebaute Zitierung, in jede `kompetenzbezug`-Quelle
übernehmen.
