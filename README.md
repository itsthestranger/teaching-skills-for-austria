# Unterricht Österreich (Lehrplan 2023)

Zwei Claude-Skills für kompetenzorientierten Unterricht nach dem österreichischen **Lehrplan 2023**,
mit den amtlichen Kompetenzbeschreibungen als mitgeliefertem Datensatz aus dem
**Rechtsinformationssystem des Bundes (RIS)**.

Die Skills erfinden keine Kompetenzen. Jede Kompetenzformulierung, jeder Anwendungsbereich und jeder
Lehrstoffbezug in einem erzeugten Dokument stammt wörtlich aus dem Lehrplantext und trägt seine
Herkunft (RIS-NOR, BGBl.-Fundstelle, Abrufdatum) mit.

---

## Für wen ist das?

Für Lehrkräfte der **Primarstufe (Volksschule)** und der **Sekundarstufe I (Mittelschule)**, die
Unterricht planen oder differenzieren und dabei nicht jedes Mal den Lehrplan aufschlagen wollen.

Programmierkenntnisse brauchen Sie keine, aber zweierlei schon: ein **kostenpflichtiges Claude-Abo**
(Pro, Max, Team oder Enterprise, im Gratis-Tarif gibt es keine Plugins) und **Claude Code**. Claude
Code ist kein reines Terminal-Werkzeug, es steckt auch in der Claude-Desktop-App im Tab **Code**, ein
Terminal ist also nicht nötig. Im normalen Claude-Chat läuft das Plugin nicht, siehe
[Wo es läuft](#wo-es-läuft).

---

## Die zwei Skills

### `at-unterrichtsplanung` — eine neue Einheit planen

Erzeugt aus einer Themenangabe **Unterrichtsplanung** und **Beobachtungsbogen** für die Lehrkraft
sowie **Schüler:innen-Material** für die Klasse.

Die Planung ist an eine konkrete amtliche Kompetenz gebunden, mit verbindlichen und
`allenfalls`-Anwendungsbereichen getrennt ausgewiesen, mit Rückgriff auf das Vorjahr (Spiralprinzip)
und mit den übergreifenden Themen verschlagwortet, die der Lehrplan für dieses Fach nennt.

> „Plane eine Einheit zu Bruchrechnen für die 2. Klasse Mathematik."

### `at-differenzierung` — eine bestehende Einheit in Niveaus bringen

Adaptiert eine **bestehende** Einheit zu 1 Differenzierungsplan (Lehrkraft) + 3 Niveau-Materialien
(Schüler:innen). Entscheidend: Die Achse, entlang derer differenziert wird, ist **amtlich, nicht
erfunden**, und sie hängt an der Stufe, nicht am Fach:

| | Achse | Niveaus |
|---|---|---|
| **Primarstufe** (D, M, SU) | aus Kompetenzbeschreibungen und Anwendungsbereichen je Schulstufe | grundlegend · erweitert · vertiefend |
| **Sekundarstufe I** (D, E, M) | Standard / Standard AHS, **ab der 2. Klasse** | Standard · Standard AHS |

Dazu kommt, wo der Lehrplan es hergibt: in **Mathematik Sek I** die `allenfalls`-Inhalte als
Anreicherung, in **Englisch** das GeR-Zielniveau pro Klasse (1. A1/A2 · 2. A2 · 3. A2+ · 4. A2+ mit
ausgewählten B1-Deskriptoren). Die Skill übernimmt die Achse, die der Datensatz für die gewählte
Kompetenz zurückgibt, keine andere.

> „Differenziere diese Einheit für eine heterogene 2. Klasse."

---

## Wo es läuft

| Umgebung | |
|---|---|
| Claude Code im Terminal | ✓ |
| Claude-Desktop-App, Tab **Code** | ✓ |
| Claude Code über SSH | ✓ |
| Claude Code im Browser (Cloud-Sitzung) | ✓ nur über `.claude/settings.json`, siehe Weg C |
| **Cowork** (`Customize → Plugins`) | ✓ laut Anthropic-Doku, für dieses Plugin nicht getestet |
| Claude-Chat (Tab **Chat**, `claude.ai`) | — Chat verwendet keine Plugins |
| WSL-Sitzungen unter Windows | — dort sind Plugins nicht verfügbar |

---

## Installation

### A) Claude-Desktop-App, ohne Terminal

1. Claude-App öffnen, oben auf den Tab **Code** wechseln (die App hat **Chat**, **Cowork**, **Code**).
2. Einen Ordner auswählen, in dem Sie arbeiten möchten. Dort landen später Ihre Dokumente.
3. Neben dem Eingabefeld auf **+** klicken → **Plugins** → **Add plugin**.
4. Die Marketplace-Adresse hinzufügen: `itsthestranger/teaching-skills-for-austria`
5. Das Plugin **Unterricht Österreich (LP 2023)** installieren.

Bietet der Plugin-Browser kein Feld für eine Marketplace-Adresse an, führen Sie einmalig den ersten
Befehl aus Weg B aus. Desktop-App und CLI teilen sich dieselbe Konfiguration, danach steht der
Marketplace im Browser zur Auswahl. Über **+** → **Plugins** → **Manage plugins** können Sie das
Plugin später deaktivieren oder entfernen.

### B) Claude Code im Terminal

Zwei Befehle, ohne das Repository zu klonen:

```bash
claude plugin marketplace add itsthestranger/teaching-skills-for-austria
claude plugin install teaching-skills-austria@teaching-skills-austria
```

In einer laufenden Sitzung geht dasselbe mit `/plugin marketplace add …` und `/plugin install …`.
Meldet die Installation *„Run /reload-plugins to activate"*, führen Sie `/reload-plugins` aus.

### C) Claude Code im Browser (Cloud-Sitzungen)

Dort gibt es keinen Plugin-Browser, und lokal installierte Plugins gelten nicht. Tragen Sie das
Plugin stattdessen in dem Repository ein, mit dem Sie arbeiten, in `.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "teaching-skills-austria": {
      "source": { "source": "github", "repo": "itsthestranger/teaching-skills-for-austria" }
    }
  },
  "enabledPlugins": { "teaching-skills-austria@teaching-skills-austria": true }
}
```

Beim Start der Sitzung wird das Plugin dann aus dem angegebenen Marketplace installiert. Die
Sitzung braucht dafür Netzzugang. Beide Schlüssel sind Objekte, keine Listen: `enabledPlugins`
wird mit `plugin@marketplace` adressiert und auf `true` gesetzt. Als Liste geschrieben wird der
Eintrag kommentarlos ignoriert.

### Danach

Eine Anfrage in natürlicher Sprache genügt, die passende Skill wird automatisch geladen. Für die
**DOCX**-Ausgabe wird `python-docx` beim ersten Rendern nachinstalliert. Schlägt das fehl (z. B. ohne
Internetzugang), erzeugen die Skills weiterhin HTML. Sie verlieren die Word-Datei, nicht die Inhalte.

---

## Welche Fächer sind abgedeckt?

Genau sechs Fach×Stufen-Kombinationen. Das ist bewusst so und wird in Version 1 nicht erweitert:

| | Deutsch | Mathematik | Englisch | Sachunterricht |
|---|:---:|:---:|:---:|:---:|
| **Primarstufe** (1.–4. Schulstufe) | ✓ | ✓ | — | ✓ |
| **Sekundarstufe I** (1.–4. Klasse) | ✓ | ✓ | ✓ | — |

Englisch ist als *(Erste) Lebende Fremdsprache* nur in der Sekundarstufe I enthalten, Sachunterricht
nur in der Primarstufe. **Nicht enthalten:** Oberstufe, berufsbildende Schulen, iKMPLUS-Diagnostik,
Deutschförderklassen.

---

## Die Datengrundlage

Mitgeliefert und vollständig offline nutzbar: **247 Kompetenzen** über sechs Shards, mit
Anwendungsbereichen, Lehrstoffbezug, Vorläufer-/Folge-Verknüpfung und übergreifenden Themen, dazu
**268 Deskriptoren** der Bildungsstandards (D4, M4, D8, M8, E8) und **50 Zuordnungen** zwischen
beiden. Alle drei Quellen stammen ausschließlich aus RIS, Abrufdatum **27. 07. 2026**:

| Quelle | RIS-NOR | Fassung |
|---|---|---|
| Lehrplan der Volksschule | `NOR40271469` | BGBl. Nr. 134/1963 i. d. F. BGBl. II Nr. 178/2025 |
| Lehrpläne der Mittelschulen | `NOR40271471` | BGBl. II Nr. 185/2012 i. d. F. BGBl. II Nr. 178/2025 |
| Bildungsstandards-Verordnung | `NOR40255561` | BGBl. II Nr. 1/2009 i. d. F. BGBl. II Nr. 262/2023 |

Lehrpläne und Bildungsstandards-Verordnung sind **freie Werke nach § 7 UrhG**: Rechtsvorschriften
genießen keinen urheberrechtlichen Schutz, ihr Wortlaut darf wörtlich weitergegeben werden. Die
Herkunft wird trotzdem durchgängig mitgeführt, weil sie fachlich zählt. Bewusst **nicht** verwendet
sind aufbereitete Materialien des IQS, des Pädagogik-Pakets oder von Universitätsprojekten: das ist
redaktionelle Arbeit Dritter, kein Verordnungstext, und damit rechtlich eine andere Lage.

Der mitgelieferte Lehrplantext ist die **konsolidierte RIS-Fassung** und dient nur der Information.
Rechtsverbindlich ist ausschließlich die im Bundesgesetzblatt (BGBl.) kundgemachte Fassung.

---

## Ihr eigenes Material

Legen Sie eigene Unterlagen in den Ordner `docs/` **Ihres Arbeitsverzeichnisses**, nach Fach und
Stufe:

```
docs/mathematik/K2/bruchrechnen.md
docs/sachunterricht/SCH4/oekosysteme.md
```

Die Skills lesen dieses Material und beziehen es ein, aber **niemals als amtlich**: Es bleibt sichtbar
von den Lehrplaninhalten getrennt und wird nie mitgeliefert oder weitergegeben. Rechte und
Autorschaft bleiben bei Ihnen. Ordnerkonventionen, Formate und Grenzen stehen in
[`docs/README.md`](docs/README.md).

`docs/` wird **relativ zu Ihrem Arbeitsverzeichnis** aufgelöst, nicht im installierten Plugin
gesucht. Arbeiten Sie deshalb in Ihrem eigenen Verzeichnis und legen Sie `docs/` dort an. Zur
Installation müssen Sie dieses Repository nicht herunterladen. Nur falls Sie es zur Entwicklung doch
klonen: Starten Sie Claude nicht darin, sonst wird dessen eigener `docs/`-Ordner verwendet, der nur
die Anleitung enthält. Die technischen Aufzeichnungen zum Bau des Datensatzes liegen getrennt davon
in `data-pipeline/notes/` und werden von den Skills nie gelesen.

---

## Zum Konnektor

Die Skills gehen auf Anthropics [`k12-teacher-skills`](https://github.com/anthropics/k12-teacher-skills)
zurück, die im Original auf den *Learning Commons Knowledge Graph* zugreifen. Dieser Konnektor deckt
Österreich nicht ab.

**Der gute Weg wäre ein offizieller Konnektor einer öffentlichen Stelle**, sinnvollerweise des BMBWF,
der über RIS hinausreicht: Lehrpläne, Bildungsstandards, Diagnostik und geprüftes Begleitmaterial aus
einer Hand, gepflegt von der zuständigen Stelle. Solange es den nicht gibt, ist dieses Plugin die
**Zwischenlösung**: der amtliche Text, den RIS offen bereitstellt, sauber aufbereitet und
mitgeliefert. Der Zugriff läuft absichtlich über eine Werkzeugschnittstelle, die ein späterer
offizieller Konnektor ohne Bruch bedienen könnte, ohne dass die Skills geändert werden müssten.

Diese Aufbereitung ist **kein amtliches Angebot** des BMBWF, des IQS oder einer anderen Behörde,
sondern ein privates Open-Source-Projekt.

---

## Ohne Gewähr

Dieses Plugin wird **ohne Gewähr** bereitgestellt, Nutzung auf eigene Verantwortung. Die erzeugten
Dokumente entstehen automatisiert und sind **vor dem Einsatz im Unterricht fachlich zu prüfen**. Es
wird nicht zugesichert, dass ein Ergebnis fachlich richtig, vollständig, altersgemäß oder für Ihre
Klasse geeignet ist. Die pädagogische Verantwortung bleibt vollständig bei Ihnen als Lehrkraft.
Diesen Hinweis und den Verordnungsvorbehalt trägt auch die Fußzeile jedes erzeugten Dokuments.
Rechtlich gilt der Gewährleistungsausschluss der **Apache-2.0**-Lizenz ([`LICENSE`](LICENSE),
Abschnitte 7 und 8).

Die Versionsnummer sagt dasselbe: dies ist ein **Vorab-Release (0.9.x)**. Datensatz und Skills sind
vollständig und getestet, das Zusammenspiel aber noch nicht über längere Zeit im Schulalltag erprobt.
Rückmeldungen sind ausdrücklich willkommen.

**Was das Plugin nicht tut:** Es beurteilt nicht (keine Noten, Schularbeiten oder Tests) und ersetzt
die fachliche Entscheidung nicht. Es kennt nur den Stand vom 27. 07. 2026, spätere Novellen fehlen
bis zur Neuerzeugung des Datensatzes. Typische Fehlvorstellungen sind noch nicht kuratiert: Die
Abfrage dazu gibt bewusst immer eine leere Liste zurück, solange keine fachdidaktisch belegten
Einträge mit Quellenangabe vorliegen. Lieber leer als erfunden.

---

## Lizenz

Code und Skills: **Apache-2.0** ([`LICENSE`](LICENSE)). Urheberrechtliche Hinweise und Danksagungen:
[`NOTICE`](NOTICE). Der Lehrplan- und Verordnungstext ist gemeinfrei (§ 7 UrhG). Ihr eigenes Material
in `docs/` fällt nicht darunter, es gehört Ihnen.
