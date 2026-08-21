# Ihr persönlicher Materialordner

Dieser Ordner ist für Ihre eigenen Unterrichtsmaterialien, Stundennotizen, Planungsunterlagen und
Fortbildungsressourcen gedacht.

**Wichtig:** Dieser Ordner wird **nie mitgeliefert** und **nie als amtlich gekennzeichnet**. Er ist
ausschließlich Ihr privater Arbeitsbereich.

## Ordnerkonvention

Legen Sie Ihre Materialien nach Fach und Stufe ab:

```
docs/<fach>/<stufe>/datei.md
```

`<stufe>` ist optional; ohne Stufenordner gilt das Material für das gesamte Fach (alle Stufen).
Es werden nur zwei Stufenfamilien erkannt: `SCH1`–`SCH4` für die **Primarstufe** (1.–4. Schulstufe)
und `K1`–`K4` für die **Sekundarstufe I** (1.–4. Klasse). Sie sind nicht austauschbar, und keine
andere Schreibweise (etwa `S1` oder `2.Klasse`) wird erkannt — eine unbekannte Stufenangabe wird
einfach so behandelt, als wäre keine Stufe angegeben.

### Beispiele

- `docs/mathematik/SCH2/bruchrechnen.md` — Stundennotizen zum Bruchrechnen (Primarstufe,
  2. Schulstufe)
- `docs/deutsch/K1/schreibfertigkeiten.md` — Material zur Schreibkompetenz (Sekundarstufe I,
  1. Klasse)
- `docs/englisch/K3/vokabeln.md` — Vokabelübungen (Sekundarstufe I, 3. Klasse; Englisch gibt es nur
  in der Sekundarstufe I, ein `PRIM.E` existiert nicht)
- `docs/sachunterricht/SCH4/oekosysteme.md` — Einheit zu Ökosystemen (Primarstufe, 4. Schulstufe)
- `docs/mathematik/aufgabenpool.md` — ohne Stufenordner: gilt für jede Mathematik-Stufe

### Fachbezeichnungen

Diese Ordnernamen werden erkannt und auf die Fachkürzel abgebildet:

| Ordnername | Kürzel | Fach |
|---|---|---|
| `mathematik` oder `m` | M | Mathematik |
| `deutsch` oder `d` | D | Deutsch |
| `englisch` oder `e` | E | Englisch |
| `sachunterricht` oder `su` | SU | Sachunterricht |

Groß- und Kleinschreibung spielt dabei keine Rolle.

### Unbekannte Fächer

Legen Sie einen Ordner für ein Fach an, das nicht in der Tabelle steht, bleibt Ihr Material
erhalten, wird aber keinem Fach zugeordnet. Verworfen wird es nie — Sie finden es in jedem Fall
wieder.

## Unterstützte Formate

- `.md` — Markdown (nativ, voll unterstützt)
- `.txt` — reiner Text (nativ, voll unterstützt)
- `.pdf` — PDF-Dokumente (siehe Einschränkung unten)
- `.docx` — Word-Dokumente (werden beim Einlesen umgewandelt)

PDF- und DOCX-Dateien werden beim ersten Zugriff in Text umgewandelt und unter `docs/.cache/`
zwischengespeichert; Ihre Originaldatei wird dabei nie verändert. **Einschränkung bei PDF:** Dem
Plugin liegt derzeit keine Bibliothek zur PDF-Textextraktion bei. Jede `.pdf`-Datei wird deshalb als
„nicht auslesbar" protokolliert und übersprungen. Das ist so vorgesehen und kein Fehler; für
gescannte oder reine Bild-PDFs gilt es auch dann noch, wenn später eine Bibliothek dazukommt.
`.md`, `.txt` und `.docx` sind davon nicht betroffen.

## Optional: eine Datei an eine bestimmte amtliche Kompetenz binden

Sie können eine Datei an genau eine amtliche Kompetenz (`kompetenz_id`) binden, statt sich auf den
Ordner zu verlassen — entweder als Namenszusatz
(`bruchrechnen__AT.LP23.SEK1.M.ZAHLEN.K2.03.md`) oder als YAML-Frontmatter
(`kompetenz_id: AT.LP23.SEK1.M.ZAHLEN.K2.03` am Dateianfang, zwischen zwei `---`-Zeilen). Diese
Bindung hat immer Vorrang vor dem Ablageort.

## Grenzen

Pro Anfrage gilt: höchstens 2 MB je Datei, höchstens 20 Dateien und ein bewusst knappes
Token-Budget (rund 4.000 Token), damit Ihr eigenes Material den amtlichen Lehrplantext nie
verdrängt. Passen mehr Ihrer Dateien zur Anfrage, als die Grenzen zulassen, werden die
einschlägigsten behalten (zuerst ausdrückliche Bindung, dann Fach, dann Stufe) und der Rest bleibt
außen vor — nie stillschweigend, sondern immer ausgewiesen.

## Nie amtlich

Nichts aus `docs/` wird je als amtlicher Lehrplantext ausgegeben. Es ist immer klar als Ihr eigenes,
von der Lehrkraft beigestelltes Material gekennzeichnet und bleibt in allem, was dieses Plugin
erzeugt, sichtbar und sprachlich vom amtlichen RIS-Lehrplaninhalt getrennt.
