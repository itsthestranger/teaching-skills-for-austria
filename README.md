# Unterricht Österreich (Lehrplan 2023)

Zwei Claude-Skills für kompetenzorientierten Unterricht nach dem österreichischen **Lehrplan 2023** —
mit den amtlichen Kompetenzbeschreibungen als mitgeliefertem Datensatz, direkt aus dem
**Rechtsinformationssystem des Bundes (RIS)**.

Die Skills erfinden keine Kompetenzen. Jede Kompetenzformulierung, jeder Anwendungsbereich und jeder
Lehrstoffbezug in einem erzeugten Dokument stammt wörtlich aus dem Lehrplantext und trägt seine
Herkunft (RIS-NOR, BGBl.-Fundstelle, Abrufdatum) mit.

---

## Für wen ist das?

Für Lehrkräfte der **Primarstufe (Volksschule)** und der **Sekundarstufe I (Mittelschule)**, die
Unterricht planen oder differenzieren und dabei nicht jedes Mal den Lehrplan aufschlagen wollen.

Sie brauchen keine Programmierkenntnisse. Sie brauchen Claude Code und einmal die drei
Installationsbefehle weiter unten.

---

## Die zwei Skills

### `at-unterrichtsplanung` — eine neue Einheit planen

Erzeugt aus einer Themenangabe ein vollständiges Paket:

| Dokument | Für wen |
|---|---|
| **Unterrichtsplanung** | Lehrkraft |
| **Schüler:innen-Material** | Klasse |
| **Beobachtungsbogen** | Lehrkraft |

Die Planung ist an eine konkrete amtliche Kompetenz gebunden, mit verbindlichen und
`allenfalls`-Anwendungsbereichen getrennt ausgewiesen, mit Rückgriff auf das Vorjahr (Spiralprinzip)
und mit den übergreifenden Themen verschlagwortet, die der Lehrplan für dieses Fach tatsächlich
nennt.

**Beispiel:**

> „Plane eine Einheit zu Bruchrechnen für die 2. Klasse Mathematik."

### `at-differenzierung` — eine bestehende Einheit in Niveaus bringen

Adaptiert eine **bestehende** Einheit in drei Niveaustufen (unter / auf / über) und erzeugt
1 Differenzierungsplan (Lehrkraft) + 3 Niveau-Materialien (Schüler:innen).

Entscheidend: Die Achse, entlang derer differenziert wird, ist **fachspezifisch und amtlich**, nicht
erfunden. Sie hängt an der Stufe, nicht am Fach:

| | Achse | Niveaus |
|---|---|---|
| **Primarstufe** (D, M, SU) | aus Kompetenzbeschreibungen und Anwendungsbereichen je Schulstufe | grundlegend · erweitert · vertiefend |
| **Sekundarstufe I** (D, E, M) | Standard / Standard AHS, **ab der 2. Klasse** | Standard · Standard AHS |

Zwei Ergänzungen kommen dazu, wo der Lehrplan sie hergibt: in **Mathematik Sek I** die
`allenfalls`-Inhalte als Anreicherung, in **Englisch** zusätzlich das GeR-Zielniveau, das der
Lehrplan pro Klasse eigens ausweist (1. Klasse A1/A2 · 2. Klasse A2 · 3. Klasse A2+ · 4. Klasse
A2+ mit ausgewählten Deskriptoren aus B1).

Die Skill übernimmt die Achse, die der Datensatz für die gewählte Kompetenz zurückgibt — keine
andere.

**Beispiel:**

> „Differenziere diese Einheit für eine heterogene 2. Klasse."

---

## Installation

```bash
git clone https://github.com/itsthestranger/teaching-skills-for-austria
claude plugin marketplace add ./teaching-skills-for-austria/plugin
claude plugin install teaching-skills-austria@teaching-skills-austria
```

Danach genügt eine Anfrage in natürlicher Sprache — die passende Skill wird automatisch geladen.
Sie müssen sie nicht namentlich aufrufen.

Für die **DOCX**-Ausgabe wird `python-docx` beim ersten Rendern nachinstalliert. Schlägt das fehl
(z. B. ohne Internetzugang), erzeugen die Skills weiterhin HTML — Sie verlieren die Word-Datei, nicht
die Inhalte.

---

## Welche Fächer sind abgedeckt?

Genau sechs Fach×Stufen-Kombinationen. Das ist bewusst so und wird in Version 1 nicht erweitert:

| | Deutsch | Mathematik | Englisch | Sachunterricht |
|---|:---:|:---:|:---:|:---:|
| **Primarstufe** (1.–4. Schulstufe) | ✓ | ✓ | — | ✓ |
| **Sekundarstufe I** (1.–4. Klasse) | ✓ | ✓ | ✓ | — |

Englisch ist als *(Erste) Lebende Fremdsprache* nur in der Sekundarstufe I enthalten;
Sachunterricht gibt es nur in der Primarstufe.

**Nicht enthalten:** Oberstufe, berufsbildende Schulen, iKMPLUS-Diagnostik, Deutschförderklassen.

---

## Die Datengrundlage

Mitgeliefert und vollständig offline nutzbar:

- **247 Kompetenzen** über sechs Shards, mit Anwendungsbereichen, Lehrstoffbezug,
  Vorläufer-/Folge-Verknüpfung und übergreifenden Themen
- **268 Deskriptoren** der Bildungsstandards (D4, M4, D8, M8, E8)
- **50 Zuordnungen** zwischen Lehrplankompetenzen und Bildungsstandards-Deskriptoren

Quellen — alle drei ausschließlich aus RIS, Abrufdatum **27. 07. 2026**:

| Quelle | RIS-NOR | Fassung |
|---|---|---|
| Lehrplan der Volksschule | `NOR40271469` | BGBl. Nr. 134/1963 i. d. F. BGBl. II Nr. 178/2025 |
| Lehrpläne der Mittelschulen | `NOR40271471` | BGBl. II Nr. 185/2012 i. d. F. BGBl. II Nr. 178/2025 |
| Bildungsstandards-Verordnung | `NOR40255561` | BGBl. II Nr. 1/2009 i. d. F. BGBl. II Nr. 262/2023 |

Lehrpläne und die Bildungsstandards-Verordnung sind **freie Werke nach § 7 UrhG** — Rechtsvorschriften
genießen keinen urheberrechtlichen Schutz. Ihr Wortlaut darf daher wörtlich wiedergegeben und
weitergegeben werden. Die Herkunft wird trotzdem durchgängig mitgeführt, weil sie fachlich zählt.

Bewusst **nicht** verwendet: aufbereitete Materialien des IQS, des Pädagogik-Pakets oder von
Universitätsprojekten. Das ist redaktionelle Arbeit Dritter, kein Verordnungstext — und damit
rechtlich eine andere Lage.

Der mitgelieferte Lehrplantext ist die **konsolidierte RIS-Fassung** und dient nur der
Information. Rechtsverbindlich ist ausschließlich die im Bundesgesetzblatt (BGBl.) kundgemachte
Fassung. Denselben Hinweis trägt auch die Fußzeile jedes erzeugten Dokuments.

---

## Ihr eigenes Material

Legen Sie eigene Unterlagen in den Ordner `docs/` Ihres Arbeitsverzeichnisses, nach Fach und Stufe:

```
docs/mathematik/K2/bruchrechnen.md
docs/sachunterricht/SCH4/oekosysteme.md
```

Die Skills lesen dieses Material und beziehen es ein — aber **niemals als amtlich**. Ihr Material
bleibt sichtbar von den Lehrplaninhalten getrennt, und es wird nie mitgeliefert oder weitergegeben.
Rechte und Autorschaft bleiben bei Ihnen.

Einzelheiten — Ordnerkonventionen, unterstützte Formate, Grenzen — stehen in
[`docs/README.md`](docs/README.md).

### `docs/` bedeutet zweierlei — nicht verwechseln

Das Wort `docs/` kommt in diesem Projekt in **zwei völlig verschiedenen Bedeutungen** vor:

| | Was | Wo | Wer liest es |
|---|---|---|---|
| **Ihr Material** | Ihre eigenen Unterlagen, die die Skills zur Laufzeit einbeziehen | `docs/` **in Ihrem Arbeitsverzeichnis** — dort, wo Sie Claude starten | die Skills, bei jeder Anfrage |
| **Projektnotizen** | Technische Aufzeichnungen darüber, **wie** der Datensatz aus RIS gebaut wurde | `data-pipeline/notes/` im Repository | Menschen, die am Projekt arbeiten |

Für Sie als Lehrkraft ist **nur die erste Zeile relevant.** Die Projektnotizen unter
`data-pipeline/notes/` sind kein Unterrichtsmaterial, werden von den Skills nie gelesen und müssen
Sie nicht interessieren.

Wichtig ist dabei: Der Ordner `docs/` wird **relativ zu Ihrem Arbeitsverzeichnis** aufgelöst, nicht
im installierten Plugin gesucht. Er gehört Ihnen, nicht dem Plugin. Wenn Sie Claude also direkt im
geklonten Repository starten, wird dessen mitgelieferter `docs/`-Ordner verwendet — der enthält nur
die Anleitung und sonst nichts. Arbeiten Sie am besten in einem eigenen Verzeichnis und legen Sie
`docs/` dort an.

---

## Zum Konnektor

Die Skills gehen auf Anthropics [`k12-teacher-skills`](https://github.com/anthropics/k12-teacher-skills)
zurück, die im Original auf den *Learning Commons Knowledge Graph* zugreifen. Dieser Konnektor deckt
Österreich nicht ab.

**Der gute Weg wäre ein offizieller Konnektor einer öffentlichen Stelle** — sinnvollerweise des
BMBWF —, der über RIS hinausreicht: mit Lehrplänen, Bildungsstandards, Diagnostik und geprüftem
Begleitmaterial aus einer Hand, gepflegt von der Stelle, die dafür zuständig ist.

Solange es den nicht gibt, ist dieses Plugin die **Zwischenlösung**: der amtliche Text, den RIS
offen bereitstellt, sauber aufbereitet und mitgeliefert. Der Zugriff läuft über eine
Werkzeugschnittstelle, die ein späterer offizieller Konnektor ohne Bruch bedienen könnte — die
Skills selbst müssten dafür nicht geändert werden. Das ist Absicht.

Diese Aufbereitung ist **kein amtliches Angebot** des BMBWF, des IQS oder einer anderen Behörde.
Sie ist ein privates Open-Source-Projekt.

---

## Ohne Gewähr

Dieses Plugin wird **ohne Gewähr** bereitgestellt — Nutzung auf eigene Verantwortung. Die erzeugten
Dokumente entstehen automatisiert und sind **vor dem Einsatz im Unterricht fachlich zu prüfen**. Es
wird keinerlei Zusicherung gegeben, dass ein Ergebnis fachlich richtig, vollständig, altersgemäß
oder für Ihre Klasse geeignet ist. Die pädagogische Verantwortung bleibt vollständig bei Ihnen als
Lehrkraft. Denselben Hinweis trägt die Fußzeile jedes erzeugten Dokuments.

Rechtlich gilt der Gewährleistungsausschluss der **Apache-2.0**-Lizenz (siehe
[`LICENSE`](LICENSE), Abschnitte 7 und 8).

Die Versionsnummer sagt dasselbe: dies ist ein **Vorab-Release (0.9.x)**, kein 1.0. Der Datensatz
und die beiden Skills sind vollständig und getestet, aber das Zusammenspiel ist noch nicht über
längere Zeit im echten Schulalltag erprobt. Rückmeldungen sind ausdrücklich willkommen.

---

## Grenzen — was dieses Plugin nicht tut

- **Es beurteilt nicht.** Keine Noten, keine Schularbeiten, keine Tests.
- **Es ersetzt die fachliche Entscheidung nicht.** Es liefert den Lehrplanbezug und einen
  belastbaren Entwurf; ob der zu Ihrer Klasse passt, entscheiden Sie.
- **Es kennt nur den Stand vom 27. 07. 2026.** Spätere Novellen sind nicht enthalten, bis der
  Datensatz neu erzeugt wird.
- **Typische Fehlvorstellungen sind noch nicht kuratiert.** Die Abfrage dazu gibt bewusst immer eine
  leere Liste zurück, solange keine fachdidaktisch belegten Einträge mit Quellenangabe vorliegen.
  Lieber leer als erfunden — generiert wird hier nichts.

---

## Lizenz

Code und Skills: **Apache-2.0** (siehe [`LICENSE`](LICENSE)).
Urheberrechtliche Hinweise und Danksagungen: [`NOTICE`](NOTICE).

Der Lehrplan- und Verordnungstext ist gemeinfrei (§ 7 UrhG). Ihr eigenes Material in `docs/` fällt
nicht darunter — es gehört Ihnen.
