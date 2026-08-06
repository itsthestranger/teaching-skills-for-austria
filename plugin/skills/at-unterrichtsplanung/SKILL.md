---
name: at-unterrichtsplanung
description: >
  Erstellt eine kompetenzorientierte Unterrichtsplanung, Schüler:innen-Material und einen
  Beobachtungsbogen nach dem österreichischen Lehrplan 2023 (Primarstufe und Sekundarstufe I).
  Diese Skill VOR jeder Rückfrage zu Schulstufe, Fach, Thema oder Kompetenz laden. Einsetzen, wenn
  eine Lehrkraft eine Unterrichtseinheit für Deutsch, Mathematik, Sachunterricht/NAWI oder
  Gesellschaft neu erstellen will — auch wenn Fach, Stufe oder Thema noch nicht genannt sind.
  NICHT laden für Beurteilung, Schularbeit/Test, reine Kompetenz-Nachschlage (direkt beantworten)
  oder das Differenzieren einer bestehenden Einheit (dafür at-differenzierung). Eine neue Einheit,
  die differenzierte/mehrstufige Materialien verlangt, ist EINE Planungsanfrage — diese Skill
  erzeugt sie im Paket; nicht zusätzlich at-differenzierung aufrufen.
license: Complete terms in LICENSE
---

# at-unterrichtsplanung

Erstellt eine kompetenzorientierte Unterrichtsplanung, Schüler:innen-Material und einen
Beobachtungsbogen für den österreichischen Lehrplan 2023 (Primarstufe und Sekundarstufe I).
Jedes Fach hat eigene Kompetenzbereiche und eine eigene Differenzierungsachse — diese leben in
eigenen Referenzdateien, auf die diese Skill routet. Alle amtlichen Inhalte stammen aus dem
RIS-Kompetenzdatensatz (`plugin/data/kompetenzen/`), nie aus Wissen "aus dem Kopf".

"Die Lehrkraft" ist durchgehend die Person, mit der gerade gesprochen wird — nie eine dritte
Person. "Lehrkraft-seitig" bezeichnet die Zielgruppe eines Dokuments, im Unterschied zu
"Schüler:innen-seitig".

---

## Schritt 0 — Routen (still, vor allem anderen)

1. **Fach und Fachgruppe bestimmen** aus Anfrage und bisherigem Gespräch:

   | Fachgruppe | Referenzdatei | Shard(s) (`Band.Fach`) |
   |---|---|---|
   | Sprachen | `references/sprachen.md` | `PRIM.D`, `SEK1.D`, `SEK1.E` |
   | Mathematik | `references/mathematik.md` | `PRIM.M`, `SEK1.M` |
   | Naturwissenschaften & Sachunterricht | `references/nawi.md` | `PRIM.SU` (Biologie/Physik/Chemie Sek I: noch kein Shard) |
   | Gesellschaft | `references/gesellschaft.md` | noch kein eigener Shard (siehe Datei) |

   Dann **sofort** die passende Referenzdatei laden. Das Laden ist **Pflicht**, bevor irgendeine
   Rückfrage zu Thema oder Kompetenz gestellt wird — eine Planung ohne die geladene Fachreferenz
   ist ein Fehler. Die Fachreferenz trägt die fachspezifischen Kompetenzbereiche, die
   Differenzierungsachse und die Besonderheiten dieses Fachs (z. B. wo Anwendungsbereiche fehlen
   oder anders gebunden sind).
2. **Schulstufe.** Primarstufe verwendet `SCH1`–`SCH4` (1.–4. Schulstufe), Sekundarstufe I
   verwendet `K1`–`K4` (1.–4. Klasse). Diese Formate sind nicht austauschbar — die Fachreferenz
   und `references/kompetenzdaten.md` nennen, welches für welchen Shard gilt.
3. **Datenzugriff.** Alle amtlichen Kompetenzen, Anwendungsbereiche, Progression,
   Bildungsstandard-Bezug, übergreifende Themen und die Differenzierungsachse werden ausschließlich
   über `plugin/scripts/kompetenz.py` gelesen (die neun `finde_*`-Funktionen). Der volle
   Funktionsvertrag steht in `references/kompetenzdaten.md` — vor dem ersten Aufruf lesen, auch
   wenn die Fachreferenz schon geladen ist, denn dort steht der eigentliche Vertrag, nicht in der
   Fachreferenz.

---

## Dokumenten-Set

Diese Skill erzeugt aus einer einzigen Material-Quelle (`lesson.json`) bis zu drei Dokumente in
einem Ausgabe-Turn:

- **`unterrichtsplanung`** (Lehrkraft) — der eigentliche Stundenverlauf, verankert in mindestens
  einer wörtlichen Kompetenzbeschreibung mit RIS-Quelle.
- **`schueler_material`** (Schüler:innen) — **optional**: nur ausgeben, wenn die Stunde
  tatsächlich ein eigenständiges Schüler:innen-Dokument erzeugt (Arbeitsblatt, Sortieraufgabe,
  abzugebendes Exit-Ticket). Eine reine Plenums- oder Gesprächsstunde ohne eigenes
  Schüler:innen-Dokument liefert **kein** `schueler_material` — das Weglassen ist die korrekte
  Antwort, kein unvollständiges Ergebnis.
- **`beobachtungsbogen`** (Lehrkraft) — für jede reguläre, kompetenztragende Stunde (Schritt 2
  wurde durchlaufen). Die Look-fors sind unverändert die bereits abgefragten
  `finde_anwendungsbereiche(id, nur_verbindlich=True)`-Items bzw., bei `lehrstoff_quelle:
  eigen_ausgewiesen`, die `finde_lehrstoff(id)`-Rückgabe — nichts wird für den Bogen neu
  formuliert oder erfunden. Die Leistungsniveau-Angabe (`Standard`/`Standard AHS`) erscheint
  **ausschließlich**, wenn `finde_differenzierung(id)["niveaus"]` für die gewählte Kompetenz
  tatsächlich nicht leer ist. Das ist die Achse aus `meta.differenzierungs_achse`
  (`references/kompetenzdaten.md` §8) — sie greift je nach `gilt_ab_stufe` erst ab einer
  bestimmten Schulstufe (bei SEK1 M/D/E ab K2, nicht schon K1) und wird **nie** aus einer
  festverdrahteten Fachliste angenommen. Ist `niveaus` für die konkrete Stufe leer, entfällt der
  Abschnitt ersatzlos, statt eine Unterscheidung zu behaupten, die die Quelle dort nicht trifft.
  Auch wenn er erscheint, bleibt `Standard AHS` eine Metadaten-Einstufung (Fließtext im Lehrplan)
  — der Bogen darf nie suggerieren, einzelne Anwendungsbereiche-Items seien selbst als
  `Standard`/`Standard AHS` markiert.

Herkunft ist in jedem Dokument sichtbar getrennt: amtlicher Lehrplantext vs. optionales
Lehrkraft-Material aus `docs/` (nie als amtlich ausgewiesen, siehe `references/kompetenzdaten.md`).

---

## Schritt 1 — Klären und sofort einen brauchbaren Entwurf anbieten

Nach Schritt 0 prüfen, ob Fach, Stufe, Thema bzw. Kompetenz und ein für die Stunde brauchbarer
Rahmen schon klar sind. Eine Dauer darf, wenn sie fehlt, mit **50 Minuten** vorgeschlagen werden;
sie ist keine Pflicht-Rückfrage.

- Sind diese Angaben ausreichend klar, **keine Rückfrage** stellen: direkt mit Schritt 2
  fortfahren und noch in derselben Antwort die Dokumente erzeugen.
- Fehlt etwas Entscheidendes, höchstens **zwei** gezielte Fragen stellen. Fach und Stufe dürfen
  in einer Frage zusammengefasst werden. Nie erst allgemein nach "mehr Details" fragen.
- Jede Rückfrage enthält bereits einen konkreten, sofort nutzbaren Entwurf: Fach, Stufe,
  Thema, vorgeschlagene Dauer, einen aus der Abfrage stammenden Kompetenzvorschlag und eine
  grobe Phasenfolge. Beispiel: „Für Mathematik, 2. Klasse Sek I, schlage ich 50 Minuten zum
  Vergleichen von Bruchzahlen vor. Passt das — und arbeiten die Schüler:innen mit
  Bruchstreifen oder am Zahlenstrahl?“
- Ist ein Stichwort mehrdeutig oder liefert `finde_kompetenz` nichts, vor einer Absage
  `stichwort_abdeckung(fach, begriff)` verwenden. Die Antwort darf nicht behaupten, ein Thema
  komme im Lehrplan nicht vor, nur weil keine Kompetenzbeschreibung gefunden wurde.

Nach der Antwort auf höchstens diese zwei Fragen wird nicht erneut geklärt: den vorgeschlagenen
Rahmen mit den bestätigten Änderungen übernehmen und den vollständigen Planungs-Turn ausführen.

## Schritt 2 — Amtlich verankern (vor dem Schreiben des Plans)

Die Planung wird ausschließlich mit den Funktionen aus `plugin/scripts/kompetenz.py` aufgebaut.
Für eine reguläre, kompetenztragende Stunde ist diese Abfragefolge Pflicht:

1. `finde_kompetenz(fach, stufe=…, kompetenzbereich=… oder stichworte=[…])` aufrufen und eine
   passende Kompetenz auswählen. Bei mehreren gleich passenden Treffern den Entwurf aus Schritt
   1 als Auswahl anbieten; keine Kompetenz-ID erraten.
2. Für die gewählte ID `finde_progression(id, "zurueck")` aufrufen. Diese echten
   Vorläuferkompetenzen sind die Grundlage für die Aktivierung im Einstieg.
3. `finde_anwendungsbereiche(id, nur_verbindlich=True)` und
   `finde_anwendungsbereiche(id, nur_verbindlich=False)` **getrennt** aufrufen. Die erste Liste
   ist Kernstoff. Die zweite enthält nur `allenfalls`-Inhalte und darf ausschließlich als klar
   beschriftete, nicht verpflichtende Erweiterung erscheinen. Eine leere zweite Liste ist kein
   Anlass, optionale Inhalte zu erfinden.
4. `finde_lehrstoff(id)` aufrufen und den Rückgabewert mit seiner `quelle` dokumentieren. Bei
   `eigen_ausgewiesen` ist die vollständige Kompetenz selbst der Lehrstoff; bei
   `aus_anwendungsbereichen` nur die zurückgegebenen Präzisierungen verwenden.
5. `finde_bildungsstandard_bezug(id)` und `finde_uebergreifende_themen(kompetenz_id=id)`
   aufrufen. Hat die Kompetenz keine eigenen Themenmarkierungen, darf ergänzend nur aus
   `finde_uebergreifende_themen(fach=fach)` ein tatsächlich in die Stunde eingebundenes Thema
   gewählt werden. Drei Ergebnisformen sind zu unterscheiden (voller Vertrag in
   `references/kompetenzdaten.md`): bei **mapped** (`abgedeckt: true` mit Deskriptoren) ist der
   mitgelieferte `hinweis` die methodische Präzisierung — er steht bei **jedem** erfolgreichen
   Treffer und bedeutet **nicht** einen ausstehenden Crosswalk; bei **covered-but-unmapped**
   (`abgedeckt: true`, leere Deskriptoren) nennt ein *eigener*, anderer `hinweis`, dass für
   diesen Bereich keine Zuordnung besteht; bei **defined-empty** (`abgedeckt: false`, nur
   `PRIM.SU`) fehlt `hinweis` ganz, stattdessen steht `grund`. In allen drei Fällen die
   jeweilige Aussage transparent an die Lehrkraft weitergeben, nie einen
   Bildungsstandard-Deskriptor erfinden.

Für die wörtliche Verankerung stets `volltext` oder `voller_wortlaut(kompetenz)` verwenden,
nie `text` allein. Die `provenienz` des zurückgegebenen Objekts wird unverändert in den
`kompetenzbezug.quelle`-Block übernommen. Das gilt auch für NOR, Kundmachung und Stand.

## Schritt 3 — Stundenstruktur als Spirale

Der Stundenverlauf macht den Zusammenhang mit dem Vorläufer sichtbar, statt die neue Kompetenz
als isoliertes Thema zu behandeln:

1. **Aktivieren (ca. 10 %):** eine kurze Diagnose- oder Wiederholungsaufgabe aus einer
   zurückgegebenen Vorläuferkompetenz. Wenn keine Vorläufer existieren, vorhandenes Alltags- und
   Begriffsverständnis diagnostizieren und dies ausdrücklich als Einstieg ohne Datenvorläufer
   kennzeichnen.
2. **Anknüpfen und problematisieren (ca. 15 %):** die bekannte Vorstellung in einer neuen,
   anspruchsvolleren Situation einsetzen lassen. Die Lernfrage muss auf die gewählte Kompetenz
   hinführen.
3. **Erarbeiten (ca. 40 %):** Lernhandlungen aus den verbindlichen Anwendungsbereichen bzw. dem
   Lehrstoff ableiten. Amtliche Zitate nicht umformulieren, wenn sie als Lehrstoffnachweis
   erscheinen.
4. **Sichern und vernetzen (ca. 25 %):** Ergebnis, Darstellung oder Verfahren mit dem Einstieg
   vergleichen lassen: „Was aus der Vorstufe hilft hier, und was ist neu?“
5. **Transfer/Exit (ca. 10 %):** eine beobachtbare Aufgabe, die genau die Zielkompetenz prüft;
   sie wird im Plan als Grundlage für spätere Beobachtung festgehalten.

Die vorgeschlagenen Methoden, Aufgaben und Sprachhilfen sind pädagogische Ausgestaltung. Sie
werden klar von den amtlichen RIS-Zitaten getrennt und nie als Lehrplantext ausgegeben.

## Schritt 4 — In einem Turn `lesson.json` und DOCX ausgeben

Sobald die Angaben ausreichend sind, den gesamten folgenden Ablauf in **einer** Antwort und ohne
Bestätigungsrunde ausführen:

1. Eine vollständige `lesson.json` schreiben: immer das Dokument `{"id": "unterrichtsplanung",
   "audience": "teacher", …}`, für jede reguläre kompetenztragende Stunde zusätzlich
   `{"id": "beobachtungsbogen", "audience": "teacher", …}`, und `{"id": "schueler_material",
   "audience": "student", …}` nur dann, wenn die Stunde tatsächlich ein eigenständiges
   Schüler:innen-Dokument braucht (siehe Dokumenten-Set oben — Weglassen ist hier die korrekte
   Antwort). Die Datei enthält `shared` und `documents`; jeder Abschnitt enthält `heading` und
   `blocks`. Die amtliche Verankerung (`kompetenzbezug` mitsamt `quelle`) gehört in `shared` und
   wird von jedem Dokument, das sie zeigt, per `from_shared` referenziert — nie in einem zweiten
   Dokument erneut abgetippt, damit Wortlaut und Provenienz nicht zwischen den Dokumenten
   auseinanderlaufen können.
2. Die Verankerung als `kompetenzbezug` schreiben: `kompetenz_id`, vollständiger wörtlicher Text
   und die unveränderte `provenienz` als `quelle`. Übergreifende Themen als
   `uebergreifende_themen_tag` ausgeben, sobald mindestens eines vorliegt.
3. Verbindliche Präzisierungen und die optionale `allenfalls`-Erweiterung in getrennten,
   eindeutig beschrifteten Blöcken ausgeben. Ohne optionale Treffer steht dort ausdrücklich,
   dass für diese Kompetenz keine verknüpfte optionale Präzisierung vorliegt.
4. Den Spiralverlauf einschließlich Vorläufer, Aktivierung, Erarbeitung, Sicherung und Exit in
   den Blöcken konkret abbilden. Die aus der Abfrage ermittelte Bildungsstandard-Antwort als
   Hinweis darstellen, nie durch eine freie Zuordnung ersetzen.
5. **Verankerung prüfen, bevor der Turn als fertig gilt:**

   ```bash
   python3 plugin/scripts/pruefe_verankerung.py <pfad>/lesson.json
   ```

   Bei Exit-Code ungleich 0 die gemeldeten Verletzungen beheben (Schritt 2 erneut, nie den
   Checker umgehen) und danach erneut prüfen. Kein Plan wird ausgegeben, der diesen Checker
   nicht besteht.
6. Unmittelbar danach den vorhandenen Renderer ausführen — keine Rendererlogik kopieren:

   ```bash
   python3 plugin/skills/at-unterrichtsplanung/scripts/render_documents.py \
     <pfad>/lesson.json --format docx --outdir <ausgabeordner>
   ```

   Der Befehl erzeugt die editierbare `.docx` und ihre HTML-Vorschau. In der Antwort die
   tatsächlich geschriebenen Pfade nennen und nur dann Erfolg melden, wenn der Renderer mit
   Status 0 beendet wurde.

Diese Aufgabe erzeugt die `unterrichtsplanung` und, für jede kompetenztragende Stunde, den
`beobachtungsbogen`; das `schueler_material` kommt hinzu, sobald die Stunde ein eigenständiges
Schüler:innen-Dokument braucht. Die vollständige `docs/`-Ingestion (PDF/DOCX-Konvertierung,
`docs/.cache/`, Größen-/Anzahl-/Token-Grenzen) ist dagegen eine nachgelagerte Erweiterung und
wird hier nicht als bereits geliefert behauptet — `finde_lernaufgaben` liest heute nur native
`.md`/`.txt`-Dateien.
