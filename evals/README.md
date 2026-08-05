# Evaluations für österreichische Unterrichtsfähigkeiten

Dieses Verzeichnis enthält Bewertungs-Rubrics, die die Qualität generierter Unterrichtsmaterialien im Kontext des österreichischen Lehrplans 2023 (Primarstufe und Sekundarstufe I) und der Bildungsstandards beurteilen.

## Zweck

Die Rubrics dienen zur rigorosen Bewertung von Unterrichtseinheiten, Differenzierungsmaterialien und Unterrichtsplanungen, die mit Hilfe von Sprachmodellen generiert werden. Sie sollen sicherstellen, dass:

- Inhalte amtlichen österreichischen Kompetenzdarstellungen entsprechen
- Materiale pädagogisch fundiert sind und Rigor bewahren
- Schüler:innen-Materialien klar, praktikabel und universal zugänglich sind
- Differenzierungsansätze im Lehrplan verankert sind, nicht auf Lernstil-Mythologie basieren

## Verzeichnisstruktur

```
evals/
├── at-unterrichtsplanung/
│   └── rubrics/
│       ├── shared.csv          # Gemeinsame Kriterien für alle Fächer
│       ├── mathematik.csv      # Fachspezifische Kriterien Mathematik
│       ├── deutsch.csv         # Fachspezifische Kriterien Deutsch
│       └── sachunterricht.csv  # Fachspezifische Kriterien Sachunterricht (Naturwissenschaft + Gesellschaft)
└── at-differenzierung/
    └── rubrics/
        ├── differenzierung.csv # Rubrics für gestaffelte Differenzierungsmaterialien
        └── rueckfrage.csv      # Bewertung von Modell-Klärfragen vor Materialgenerierung
```

## Verwendung der Rubrics

Die Rubrics sind CSV-Dateien mit den folgenden Spalten:

| Spalte | Beschreibung |
| ------ | ----------- |
| `ID` | Eindeutige Kriterium-Identifikation (z.B. `P1`, `R3`, `P11-AT`) |
| `Bucket` | Übergeordnete Kategorie: `P` (Pädagogik), `R` (Rigor), `O` (Output/Formatierung), `M` (Modell-Gerüstbau) |
| `Criterion` | Kurzer Name des Kriteriums |
| `What pass requires` | Die spezifische, bewertbare Bedingung, die ein „Bestanden" ausmacht |
| `Notes` | Begründung oder Design-Notizen |
| `Conditional` | Falls nicht leer, gilt das Kriterium nur unter dieser Bedingung. Mehrere Bedingungen werden mit `; ` getrennt und gelten **konjunktiv** (alle müssen erfüllt sein), z. B. `PRIM.SU-Naturwissenschaft; PRIM.SU-SCH3-4-quantitative-daten` |

### Für Unterrichtspläne (at-unterrichtsplanung)

Wenden Sie zunächst die `shared.csv` an, dann die relevante fachspezifische Datei:

- Für einen **Mathematik-Stundenplan**: `shared.csv` + `mathematik.csv`
- Für einen **Deutsch-Stundenplan**: `shared.csv` + `deutsch.csv`
- Für einen **Sachunterricht-Stundenplan** (Naturwissenschaft oder Gesellschaft): `shared.csv` + `sachunterricht.csv`

Fach-spezifische Kriterien ergänzen die gemeinsamen Kriterien.

### Für Differenzierungsmaterialien (at-differenzierung)

- Nutzen Sie `differenzierung.csv` zur Bewertung von gestuften Arbeitsblättern (Unter-/Auf-/Über-Stufe)
- Nutzen Sie `rueckfrage.csv` zur Bewertung, ob das Modell vor der Materialgenerierung angemessene Klärfragen gestellt hat

## Durchführung der Bewertung

Die Rubrics sind für **manuelle oder periodische Bewertung** konzipiert, nicht für automatische Durchläufe bei jedem Commit. Ein typischer Arbeitsprozess ist:

1. **Generierung**: Unterrichtsmaterial wird mit einem KI-Modell generiert
2. **Manuelle Bewertung**: Ein:e Fachexpert:in oder Lehrkraft bewertet das Material gegen die relevanten Rubrics
3. **Feedback-Schleifen**: Defizite werden dem Modell zurückgemeldet, oder die Rubrics werden kalibriert
4. **Periodische Audits**: In regelmäßigen Abständen wird eine Stichprobe neu generierter Materialien gegen diese Rubrics bewertet

## Die neun österreichischen Bewertungsdimensionen

Diese neun Kriterien wurden speziell für den österreichischen Kontext hinzugefügt, um sicherzustellen, dass KI-generierte Unterrichtsmaterialien lokale Anforderungen erfüllen:

### 1. **Kompetenzverankerung** (P11-AT und weitere)
Die Zielkompetenz muss wörtlich aus dem **Lehrplan 2023** oder den **Bildungsstandards** zitiert sein, mit:
- Korrekter Kompetenz-ID (z.B. M3/1.1 in Mathematik)
- RIS-Quellenangabe mit Normenbeschreibung (NOR)
- Abrufdatum der Quelle

**Warum**: Garantiert, dass Unterrichtsmaterialien auf amtlichen Curriculumquellen verankert sind, nicht auf Paraphrasen oder Vermutungen.

### 2. **Progression** (P12-AT)
Die Lektion muss das **Spiralprinzip** und **Wiederholen-und-Festigen**-Phasen aus dem Lehrplan respektieren:
- Explizite Verbindungen zu Voraussetzungs-Kompetenzen
- Sichtbare Verknüpfung zu Folge-Kompetenzen
- Evidenz von zyklischer Wiederholung, nicht linearer einmaliger Präsentation

**Warum**: Stellt sicher, dass Unterricht Lernprogression und Langzeitgedächtnis unterstützt.

### 3. **Anwendungsbereiche** (P13-AT)
**Bindende** und **allenfalls** (nicht-bindende) Inhalte müssen sauber getrennt sein:
- Fokus auf bindende Kompetenzen (Kerninhalt)
- Optionale Erweiterungen deutlich gekennzeichnet
- Keine Vermischung oder Ablenkung auf optionale Inhalte

**Warum**: Hilft Lehrkräften, zu wissen, welche Inhalte nicht verhandelbar sind.

### 4. **Differenzierung** (P14-AT)
Differenzierungsachsen müssen **fachlich korrekt** und **aus dem Lehrplan selbst abgeleitet** sein:
- Nicht basierend auf Lernstil-Kategorien (visuell/auditiv/kinästhetisch)
- Nicht basierend auf oberflächlichen Vorlieben
- Abgeleitet aus inhaltlichen Schwierigkeitsgradationen der Kompetenz

**Warum**: Gewährleistet evidenzbasierte Differenzierung, nicht pädagogische Mythen.

### 5. **Übergreifende Themen** (P15-AT)
Übergreifende Themen (Demokratie, Umweltbildung, Sprachliche Bildung, etc.) müssen:
- Korrekt identifiziert sein (relevant zur Lektion)
- Sichtbar integriert sein (nicht nur in Notizen erwähnt)
- Mit dem Fach-Inhalt verflochten sein

**Warum**: Stellt sicher, dass Lehrende verstehen, welche crosscurricularen Verbindungen sie nutzen.

### 6. **Dokumentintegrität** (O16-AT)
Alle generierten Dokumente müssen:
- Vollständig angezeigt werden (kein Trunkieren)
- Korrekt formatiert sein (kein Formatierungsverlust)
- Alle Seiten oder Abschnitte beinhalten (kein Verlust von Inhalten)

**Warum**: Gewährleistet, dass generierte Materialien professionelle Qualität haben und im Klassenzimmer nutzbar sind.

### 7. **Fehlvorstellungen** (P16-AT)
Häufige Schüler:innen-Missverständnisse zu jeder Kompetenz müssen:
- Mit einer Quelle zitiert sein
- Mit **`amtlich: false`** gekennzeichnet sein, wenn sie nicht aus amtlichen Quellen stammen
- In eine kuratierte Datenbank eingehen

**Warum**: Verbessert die Qualität von Missverständnis-Ressourcen und gibt Lehrkräften vertrauenswürdige, sourced Informationen.

### 8. **Crosswalk** (O17-AT)
Wenn Bildungsstandards-Mapping vorhanden ist:
- Mapping auf **Kompetenzbereich-Ebene** durchführen (nicht nur einzelne Items)
- **Dokumentierte Begründung** für jede Zuordnung bereitstellen
- Transparenz zeigen, wie externe Standards mit Kompetenzen verknüpft sind

**Warum**: Unterstützt Lehrkräfte, die mit mehreren Standards-Frameworks arbeiten.

### 9. **Herkunftstrennung** (O18-AT)
Amtliche **RIS-Inhalte** müssen deutlich von **Lehrkraft-bereitgestellten** (`docs/`) Materialien unterschieden sein:
- Klare Quellenangaben in Markup oder Metadaten
- Lehrkräfte wissen sofort: Was ist amtlich? Was habe ich selbst gemacht?
- Keine Vermischung von Quellen ohne Kennzeichnung

**Warum**: Erhöht Transparenz und Vertrauenswürdigkeit; verhindert, dass Lehrkräfte versehentlich inoffizielle Inhalte als amtlich ausgeben.

---

## Notizen für Evaluatoren

- **Bedingte Kriterien**: Einige Kriterien gelten nur unter bestimmten Bedingungen (gekennzeichnet in der `Conditional`-Spalte). Überspringen Sie ein Kriterium, wenn seine Bedingung nicht erfüllt ist. Bei mehreren, mit `; ` getrennten Bedingungen muss **jede** erfüllt sein.
- **Geltungsbereich gehört in `Conditional`, nicht in `Notes`**: Wenn ein Kriterium nur für einen Fachbereich, eine Schulstufe oder eine Textsorte gilt, muss das in `Conditional` stehen. `Notes` ist reine Begründung und wird beim Überspringen **nicht** ausgewertet — ein dort formulierter Geltungsbereich bleibt wirkungslos. `tests/test_rubric_conditions.py` prüft das für die bekannten Geltungsbereiche.
- **Unabhängige Bewertung**: Jedes Kriterium wird isoliert bewertet — ein Versagen bei `R2` sagt etwas Spezifisches über kognitive Anforderungen aus, nicht nur „das Material ist schlecht".
- **Kalibrierung**: Erwägen Sie, mit Kolleg:innen zu kalibrieren, wenn Sie diese Rubrics zum ersten Mal verwenden. Die Grenzen zwischen „Pass" und „Fail" erfordern manchmal Urteilsvermögen.

## Weiterführende Ressourcen

- [RIS (Rechtsinformationssystem des Bundes)](https://www.ris.bka.gv.at/) — **einzige** amtliche Quelle für Lehrplan- und Bildungsstandards-Text in diesem Projekt
- Lehrplan der Volksschule: `NOR40271469` · Lehrpläne der Mittelschulen: `NOR40271471` · Bildungsstandards-Verordnung: `NOR40255561`

---

**Hintergrund**: Diese Rubrics wurden abgeleitet aus den Learning Commons/Anthropic K-12 Evals und adaptiert für die österreichische Primarstufe (1.–4. Schulstufe) und Sekundarstufe I (1.–4. Klasse, entspricht der 5.–8. Schulstufe). Sie spiegeln die Struktur des österreichischen Lehrplans 2023, die Bildungsstandards und Best Practices im österreichischen Unterricht wider.
