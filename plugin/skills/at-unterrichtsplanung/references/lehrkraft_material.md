# Lehrkraft-Material aus `docs/` — Ingestion-Vertrag

Ergänzt `kompetenzdaten.md` um den `docs/`-Teil von Funktion 5, `finde_lernaufgaben`. `docs/` ist
das private Arbeitsverzeichnis der Lehrkraft (gitignored, nie ausgeliefert). Alles daraus ist
**Lehrkraft-Material, nie amtlich** — siehe Abschnitt „Herkunft" unten.

## Ordnerkonvention (Plan §6.6)

```
docs/<fach>/<stufe>/…     z. B. docs/mathematik/K2/bruchrechnen.md
docs/<fach>/…             fachweit, alle Stufen
docs/…                    unassigned (fach = stufe = None)
```

Alias-Tabelle (`plugin/scripts/docs_ingest.FACH_ALIAS`): `mathematik→M`, `deutsch→D`,
`englisch→E`, `sachunterricht→SU` (plus die kurzen Fachcodes selbst). Ein **unbekannter**
Ordnername wird als *unassigned* gelistet, nie verworfen — nur eine Fach-gefilterte Abfrage zeigt
ihn folgerichtig nicht. `<stufe>` muss `SCH1`–`SCH4` oder `K1`–`K4` sein; jeder andere Wert bleibt
`None` (fachweit gültig). `docs/` kennt kein Band — `fach="SEK1.M"` wird auf den bloßen Fachcode
`M` reduziert, da ein Ordner nie Primarstufe/Sek I unterscheidet.

## Formate

- `.md`, `.txt` — nativ gelesen.
- `.pdf`, `.docx` — auf Markdown-ähnlichen Text konvertiert, unter `docs/.cache/` zwischengespeichert
  (Quelldatei bleibt unverändert; Cache wird über den Änderungszeitstempel invalidiert). `.docx`
  läuft über `python-docx` (bereits akzeptierte Laufzeit-Abhängigkeit, Entscheidung E5-11).
- **PDF-Extraktion ist eine Anschlussstelle, keine feste Bibliothek**
  (`docs_ingest._PDF_EXTRAKTOREN`). Im ausgelieferten Zustand ist **keine** PDF-Bibliothek
  installiert — jedes PDF wird daher heute als nicht extrahierbar geloggt und übersprungen, **nie
  fatal**. Das gilt auch für gescannte/bildbasierte PDFs, sobald eine Bibliothek ergänzt wird: leerer
  Extraktionstext zählt ebenfalls als „nicht extrahierbar", nicht als leerer Treffer.
- Nicht konvertierbare Dateien (kaputtes `.docx`, nicht extrahierbares `.pdf`) landen nie im
  Ergebnis und nie stillschweigend im Nichts — sie werden geloggt (siehe unten).

## Limits (Vorgaben, überschreibbar)

Pro Anfrage: max. **2 MB** je Datei, max. **20** Dateien, ~**4.000** Token Gesamtbudget
(`len(utf-8-Bytes) / 4`, dieselbe Heuristik wie `data-pipeline/build_dataset.approx_tokens`).
Werden mehr Dateien gefunden als die Limits erlauben, entscheidet die Relevanz — explizite
`kompetenz_id`-Bindung zuerst, dann Fach-Treffer, dann Stufen-Treffer vor fachweitem Material —
und **jede verworfene Datei wird geloggt**, nie still weggelassen. `finde_lernaufgaben` selbst gibt
nur die Treffer zurück; für den vollständigen, beobachtbaren Bericht (was übersprungen/verworfen
wurde und warum) `docs_ingest.sammle(...)` direkt aufrufen — liefert ein `Ingestionsbericht` mit
`treffer`, `uebersprungen`, `verworfen`.

## Kompetenz-Bindung — nie erfinden

Eine Datei kann sich explizit an eine amtliche Kompetenz binden:

- **Dateiname-Suffix** (Vorrang): `…__AT.LP23.SEK1.M.ZAHLEN.K2.03.md`
- **YAML-Frontmatter**: `kompetenz_id: AT.LP23.SEK1.M.ZAHLEN.K2.03` im `---`-Block am Dateianfang

Eine so gebundene Datei erscheint auch dann, wenn ihr Ordner-Fach/-Stufe von der Anfrage abweicht —
die explizite Bindung hat Vorrang vor dem Ordner. **Ohne** eine dieser beiden Bindungen bleibt
`kompetenz_id` im Ergebnis `None`. Es wird **nie** eine Bindung aus Stichworten oder Dateiname
geraten — das wäre eine erfundene amtliche Zuordnung.

## Herkunft — nie als amtlich ausweisen

Jeder Treffer trägt `herkunft: "docs"` und `amtlich: False`. Beim Einbetten in ein Dokument einen
`herkunftsblock` verwenden (`lesson_common.resolve_herkunft`, bereits vom Renderer unterstützt):
`{"type": "herkunftsblock", "amtlich": false, "quelle_hinweis": "<titel> (<pfad>)", "blocks": […]}`.
Nur `amtlich is True` rendert als amtliche RIS-Quelle — hier also nie. Fehlendes/leeres `docs/` →
`finde_lernaufgaben` gibt `[]` zurück, der Ablauf läuft normal weiter, kein Fehler.

## Aufruf

```python
finde_lernaufgaben(fach=None, stufe=None, kompetenz_id=None, docs_root=None) -> list[dict]
```

Jeder Eintrag: `titel`, `pfad`, `fach`, `stufe`, `kompetenz_id`, `format` (`md`/`txt`/`pdf`/`docx`),
`konvertiert` (bool), `text`, `bytes`, `tokens_approx`, `herkunft`, `amtlich`. `docs_root` ist nur
für Tests/abweichende Wurzeln gedacht; im Normalbetrieb weglassen.
