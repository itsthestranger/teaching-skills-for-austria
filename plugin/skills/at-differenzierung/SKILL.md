---
name: at-differenzierung
description: >
  Adaptiert eine bestehende Unterrichtseinheit (Deutsch, Mathematik, Sachunterricht/NAWI,
  Gesellschaft; Primarstufe/Sek I) in Niveaustufen (unter/auf/über) entlang der fachspezifischen
  amtlichen Differenzierungs-Achse (Mathematik: Standard/Standard AHS + „allenfalls"-Inhalte;
  Sprachen: GERS A1/A2/B1). Diese Skill VOR jeder Rückfrage zur Einheit oder den Niveaus laden.
  Erzeugt 1 Differenzierungsplan (Lehrkraft) + 3 Niveau-Materialien (Schüler:innen). NICHT für das
  Erstellen einer neuen Einheit (dafür at-unterrichtsplanung), nicht für Beurteilung/Tests.
license: Complete terms in LICENSE
---

# at-differenzierung

Adaptiert eine **bestehende** Unterrichtseinheit in drei Niveaustufen (unter/auf/über), entlang der
Differenzierungsachse, die der österreichische Lehrplan 2023 für das jeweilige Fach tatsächlich
vorgibt. Alle amtlichen Inhalte — die Zielkompetenz, ihr Wortlaut, die Achse selbst, verbindliche
Anwendungsbereiche, `allenfalls`-Inhalte und die Vorjahres-Stützung — stammen ausschließlich aus
`plugin/scripts/kompetenz.py`, nie aus Wissen "aus dem Kopf".

"Die Lehrkraft" ist durchgehend die Person, mit der gerade gesprochen wird. "Lehrkraft-seitig"
bezeichnet die Zielgruppe eines Dokuments, im Unterschied zu "Schüler:innen-seitig".

Diese Skill setzt eine **bestehende** Einheit voraus (hochgeladener Stundenverlauf, `lesson.json`
aus `at-unterrichtsplanung`, oder eine hinreichend konkrete Beschreibung mit erkennbarer
Zielkompetenz). Sie ersetzt keine Kompetenzwahl und erfindet keine.

---

## Schritt 0 — Routen (still, vor allem anderen)

1. **Routing gegenüber `at-unterrichtsplanung` klären.** Eine **neue** Einheit — auch eine, die
   von Anfang an nach Niveaus differenzieren soll — ist **eine** Planungsanfrage an
   `at-unterrichtsplanung`; jene Skill erzeugt die Niveaustufen im selben Paket. Diese Skill
   NICHT zusätzlich aufrufen, wenn eine neue Einheit erst entsteht. `at-differenzierung` wird nur
   geladen, wenn eine **bestehende** Einheit (mit bereits erkennbarer Zielkompetenz) in Stufen
   aufgeteilt werden soll. Ist unklar, ob die Einheit neu oder bestehend ist, das als Erstes klären
   — nicht raten.
2. **Zielkompetenz bestimmen.** Aus einer mitgelieferten `lesson.json` den vorhandenen
   `kompetenzbezug.kompetenz_id` übernehmen (nie neu erraten). Ohne strukturierte Quelle
   `finde_kompetenz(fach, stufe=…, stichworte=[…])` verwenden, um die vom Prompt beschriebene
   Kompetenz zu identifizieren; bei mehreren gleich passenden Treffern der Lehrkraft die Auswahl
   anbieten, keine ID erraten. Fach- und Stufenschlüssel folgen derselben Konvention wie überall im
   Datensatz (`"<BAND>.<FACH>"`, `SCH1`–`SCH4` bzw. `K1`–`K4`) — siehe
   `plugin/skills/at-unterrichtsplanung/references/kompetenzdaten.md`, Abschnitt "Die sechs
   Shards".
3. **Datenzugriff — Pflichtlektüre vor dem ersten Aufruf.**
   `plugin/skills/at-unterrichtsplanung/references/kompetenzdaten.md` trägt den vollständigen
   Funktionsvertrag für alle neun `finde_*`-Funktionen (diese Skill nutzt sie mit, statt sie
   zweitzuschreiben) und ist hier verbindlich mitzulesen, auch wenn schon eine Fachreferenz jener
   Skill bekannt ist. Diese Skill selbst hat keine eigene Fachreferenz-Tabelle, die eine Achse
   einem Fach fest zuordnet — genau das würde das Verbot aus Schritt 2 unterlaufen.

---

## Dokumenten-Set

Diese Skill erzeugt aus einer einzigen Material-Quelle (analog `lesson.json`: ein `shared`-Block
plus ein `documents`-Array, gerendert mit
`plugin/skills/at-differenzierung/scripts/render_documents.py`) in **einem** Ausgabe-Turn:

- **`differenzierungsplan`** (Lehrkraft) — der Stundenverlauf mit Stufen-Zuweisung, Begründung
  je Stufe und der amtlichen Verankerung der Zielkompetenz. Trägt `kompetenzbezug` mitsamt
  `quelle` genau wie `at-unterrichtsplanung`.
- **drei Niveau-Materialien** (Schüler:innen, unter/auf/über) — je ein eigenständiges
  Arbeitsblatt-Dokument, das dieselbe Zielkompetenz im selben Szenario bearbeitet (siehe Schritt 3);
  keine Stufe ersetzt Kompetenz, Fachgegenstand oder Kontext einer anderen.

Herkunft ist in jedem Dokument sichtbar getrennt: amtlicher Lehrplantext (`herkunftsblock` mit
`amtlich: true` und `quelle`) vs. optionales Lehrkraft-Material aus `docs/`
(`herkunftsblock` mit `amtlich: false` und `quelle_hinweis`; nie als amtlich ausgewiesen, siehe
`references/kompetenzdaten.md` und `at-unterrichtsplanung/references/lehrkraft_material.md`).
`allenfalls`-Inhalte sind real amtliche Daten, aber ausdrücklich nicht verpflichtend — nie
stillschweigend als Kernstoff dargestellt.

---

## Schritt 1 — Klären und sofort einen brauchbaren Entwurf anbieten

Nach Schritt 0 prüfen, ob die Zielkompetenz, ein grober Stufen-Umfang und die für die Adaption
nötigen Angaben zu Lernvoraussetzungen schon klar sind.

- Ist ein hochgeladener Stundenverlauf lesbar, ihn zuerst korrekt einlesen: die Zielkompetenz mit
  korrektem Code und Wortlaut (oder einer bedeutungserhaltenden Paraphrase) benennen, bevor
  irgendetwas erzeugt wird.
- **Konkrete Lernvoraussetzungen erfragen** (sprachliche Voraussetzungen, bereits gesicherte
  Vorgängerkompetenzen, benötigte Darstellungen, vereinbarte individuelle Fördermaßnahmen) — vor
  oder gleichzeitig mit der ersten Generierung. Fehlen Angaben: Hat `finde_progression(id,
  "zurueck")` mindestens eine Vorgängerkompetenz, das transparent als Stützung für die Unter-Stufe
  ankündigen. Ist das Ergebnis leer, das ausdrücklich sagen und stattdessen `stammsatz` + die
  verbindlichen Anwendungsbereiche der Zielkompetenz selbst als Stützung nennen. In keinem Fall
  eine Diagnose, eine rechtliche Förderkategorie oder ein ausländisches Referenzsystem annehmen.
- Ist der gewünschte Stufen-Umfang unklar (z. B. nur eine Stufe statt aller drei), danach fragen;
  ist er im Prompt bereits angegeben, nicht erneut fragen.
- Höchstens **zwei** gezielte Rückfragen insgesamt; jede enthält bereits einen konkreten,
  sofort nutzbaren Entwurf (Kompetenz, vorgeschlagene Stufenaufteilung). Nach der Antwort auf
  diese Fragen wird nicht erneut geklärt — der vollständige Turn wird ausgeführt.

## Schritt 2 — Amtlich verankern (vor dem Aufbau der Stufen)

Für die gewählte `kompetenz_id` ist diese Abfragefolge Pflicht — jede Aussage über die Achse, ein
Niveau oder eine Zusatzmenge stammt aus genau diesem Aufruf, nie aus Wissen über "welches Fach das
üblicherweise hat":

1. **`finde_differenzierung(kompetenz_id)`** aufrufen und alle fünf Felder lesen:
   - **`achse`** — die Metadaten-Achse **verbatim**, aus `meta.differenzierungs_achse` des
     Shards. `achse["typ"]` ist `standard_standardplus` (SEK1.D, SEK1.M, SEK1.E, ab der
     `gilt_ab_stufe`, gemessen `K2`) oder `lehrplan_generisch` (PRIM.D, PRIM.M, PRIM.SU). SEK1.E
     trägt zusätzlich eine `gers`-Sub-Achse. **Diese Skill liest `achse` bei jedem Aufruf neu aus
     dem Rückgabewert und leitet sie nie aus einer eigenen Fach→Achse-Tabelle ab** — die
     Beschreibung oben (Mathematik/Sprachen) ist Routing-Text für das Laden der Skill, keine
     Datenquelle. Tatsächlich gilt `standard_standardplus` für **alle drei** Sek-I-Fächer
     Deutsch, Mathematik und Lebende Fremdsprache, nicht nur Mathematik, und die GERS-Sub-Achse
     ist SEK1.E-spezifisch, nicht "die Sprachen" pauschal — nur der zurückgegebene `achse`-Wert
     entscheidet, nie diese Zusammenfassung.
   - **`niveaus`** — die an dieser Stufe **wirksamen** Labels, nicht die rohe Achse. Für alle
     SEK1-Kompetenzen der 1. Klasse (`K1`) ist diese Liste **leer**, weil die Unterscheidung laut
     Lehrplan erst ab der 2. Klasse gilt — für `K1` niemals "Standard" oder "Standard AHS"
     ausgeben, auch nicht andeutungsweise. Ist `niveaus` nicht leer, ist sie eine
     **Metadaten-Einstufung**: "Standard AHS" bleibt Fließtext im Lehrplan, nie eine Markierung an
     einem einzelnen Anwendungsbereich-Item. Kein erzeugter Text darf suggerieren, der Datensatz
     unterscheide Standard von Standard AHS pro Item.
   - **`enrichment_items`** — real amtliche `allenfalls`-Inhalte, aber **nur befüllt, wenn die
     Achse selbst `enrichment_quelle: "allenfalls"` trägt** (gemessen: SEK1.M). Für jeden anderen
     Shard ist diese Liste leer; das ist der wahre Datenstand, kein Fehler. Diese Prüfung hängt
     nicht an `niveaus`: auch bei `K1`-Kompetenzen von SEK1.M kann `enrichment_items` real befüllt
     sein (gemessen, z. B. `AT.LP23.SEK1.M.FIGUREN.K1.01`) — dieser Inhalt darf für die
     Über-Stufe verwendet werden, aber **nie** als "Standard AHS" beschriftet oder mit dem
     `niveaus`-Label verwechselt werden, das an dieser Stufe leer bleibt. Die Über-Stufe darf für
     Shards ohne `allenfalls`-Quelle nicht behaupten, "Standard-AHS-Inhalt" aus dem Datensatz
     abzufragen — dort ist sie ausschließlich skill-eigene, fachlich begründete Vertiefung auf der
     bindenden Kompetenz (`stammsatz` + `text`), niemals eine erfundene Datensatz-Abfrage.
   - **`vorklasse_stuetzen`** — echte Vorjahres-Kompetenzrecords (positionale Vorläufer über
     `finde_progression`), nie ein rohes Anwendungsbereich-Item. Grundlage für die Unter-Stufe.
   - **`docs_material`** — optionales Lehrkraft-Material aus `docs/` für Fach/Stufe/Kompetenz;
     `[]`, wenn `docs/` fehlt oder nichts Passendes enthält. Trägt immer `herkunft: "docs"`,
     `amtlich: false`.
2. **`finde_anwendungsbereiche(kompetenz_id, nur_verbindlich=True)`** für die verbindlichen
   Präzisierungen der Auf-Stufe. `finde_lehrstoff(kompetenz_id)` ergänzend, wenn `quelle` laut
   Rückgabewert `eigen_ausgewiesen` ist (PRIM.M): dort ist die volle Kompetenz selbst der
   Lehrstoff, keine separate Liste zu erfinden.
3. Für jedes Zitat **`volltext`** (bzw. `voller_wortlaut(kompetenz)`) verwenden, nie `text`
   allein — `stammsatz` trägt bei manchen Fächern eine Bedingung, die zur Kompetenz gehört
   (z. B. SEK1.E). Die `provenienz` des zurückgegebenen Objekts unverändert in den
   `kompetenzbezug.quelle`-Block übernehmen.
4. **SEK1.E / GERS**: existiert die `gers`-Sub-Achse, ist ihr `je_stufe_ausgewiesen` gemessen
   `False` — die A1/A2/B1-Angabe ist eine **fachweite** Aussage, keine Zuordnung pro Schulstufe.
   Sie darf genannt, aber nie als "diese Klasse liegt auf Niveau X" pro Jahrgang ausgegeben werden.

## Schritt 3 — Stufen aufbauen (unter/auf/über)

Alle drei Stufen bearbeiten **dieselbe** Zielkompetenz im **selben** Szenario/Kontext; Unterschiede
bleiben auf Wortlaut, Stützungen, Darstellung, Satzmuster oder Aufgabenanzahl begrenzt — keine
Stufe wechselt Thema, Kompetenz oder Aufgabenart. Die Konstruktion ist achsen-getrieben, nicht
fachgetrieben:

1. **Unter** — gegründet auf `vorklasse_stuetzen` (bzw., wenn leer, auf `stammsatz` + die
   verbindlichen Anwendungsbereiche der Zielkompetenz selbst, siehe Schritt 1). Mindestens eine
   konkrete Darstellung oder visuelle Stütze. Reduzierte, aber nicht gleichmäßig verteilte
   Stützungsdichte.
2. **Auf** — die bindende Kompetenz (`volltext`) plus die verbindlichen Anwendungsbereiche aus
   Schritt 2.2. Trägt das Niveau-Label aus `niveaus`, sofern diese Liste für die konkrete Stufe
   nicht leer ist (siehe K1-Regel oben); ist sie leer, entfällt jedes Niveau-Label ersatzlos.
3. **Über** — dieselbe Kompetenz vertieft. Wo `enrichment_items` befüllt ist (SEK1.M), diese
   explizit als `allenfalls`, nicht verpflichtend, kennzeichnen. Wo leer, ausschließlich
   skill-eigene, an `stammsatz`/`text` rückgebundene Vertiefung — nie eine behauptete
   Standard-AHS-Abfrage.

Jede Stufe enthält mindestens eine offene oder Selbstreflexions-Aufforderung und mindestens eine
Aufgabe, die über reines Rechnen/Abrufen hinausgeht. Stufen-Zuweisung wird im Differenzierungsplan
begründet und ausdrücklich als anhand formativer Evidenz revidierbar gekennzeichnet, nicht als
statischer Track.

Die konkrete fachspezifische Ausgestaltung je Stufe (z. B. Mathematik-Aufgabentypen, ein
generisches Achse-Beispiel für ein Nicht-Mathematik-Fach, die feinkörnige `niveau_spalte`-Layout-
Politur) ist fachspezifisches bzw. renderer-seitiges Referenzmaterial, das diese Skill nicht
mitliefert und hier nicht als bereits vorhanden behauptet — die Achse selbst bleibt aber, wie
oben beschrieben, in jedem Fall aus `finde_differenzierung` gelesen, nie angenommen.

## Schritt 4 — In einem Turn Material und DOCX ausgeben

Sobald die Angaben ausreichen, den gesamten folgenden Ablauf in **einer** Antwort ohne
Bestätigungsrunde ausführen:

1. Eine vollständige Materialdatei schreiben: `{"shared": {…}, "documents": […]}` mit
   `{"id": "differenzierungsplan", "audience": "teacher", …}` und je einem Dokument pro erzeugter
   Stufe (`audience: "student"`). Amtliche Verankerung (`kompetenzbezug` mitsamt `quelle`) gehört
   in `shared` und wird von jedem Dokument, das sie zeigt, per `from_shared` referenziert — nie in
   einem zweiten Dokument erneut abgetippt.
2. Verbindliche und `allenfalls`-Inhalte in getrennten, eindeutig beschrifteten Blöcken ausgeben,
   genau wie in Schritt 2/3 ermittelt.
3. **Verankerung prüfen, bevor der Turn als fertig gilt:**

   ```bash
   python3 plugin/scripts/pruefe_verankerung.py <pfad>/differenzierung.json
   ```

   Bei Exit-Code ungleich 0 die gemeldeten Verletzungen beheben (Schritt 2 erneut, nie den
   Checker umgehen) und danach erneut prüfen. Kein Material wird ausgegeben, das diesen Checker
   nicht besteht.
4. Unmittelbar danach den vorhandenen Renderer ausführen — keine Rendererlogik kopieren:

   ```bash
   python3 plugin/skills/at-differenzierung/scripts/render_documents.py \
     <pfad>/differenzierung.json --format docx --outdir <ausgabeordner>
   ```

   In der Antwort die tatsächlich geschriebenen Pfade nennen und nur dann Erfolg melden, wenn der
   Renderer mit Status 0 beendet wurde.
