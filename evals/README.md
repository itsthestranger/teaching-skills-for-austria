# Bewertungs-Rubrics für die österreichischen Unterrichts-Skills

Dieses Verzeichnis enthält Bewertungs-Rubrics, die die Qualität generierter Unterrichtsmaterialien im Kontext des österreichischen Lehrplans 2023 (Primarstufe und Sekundarstufe I) und der Bildungsstandards beurteilen.

## Zweck

Die Rubrics dienen zur strengen Bewertung von Unterrichtseinheiten, Differenzierungsmaterialien und Unterrichtsplanungen, die mit Hilfe von Sprachmodellen generiert werden. Sie sollen sicherstellen, dass:

- Inhalte den amtlichen österreichischen Kompetenzbeschreibungen entsprechen
- Materialien pädagogisch fundiert sind und fachlichen Rigor wahren
- Schüler:innen-Materialien klar, praktikabel und durchgängig zugänglich sind
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
| `ID` | Eindeutige Kennung des Kriteriums (z. B. `P1`, `R3`, `P11-AT`) |
| `Bucket` | Übergeordnete Kategorie: `P` (Pädagogik), `R` (Rigor), `O` (Output/Formatierung), `M` (Modell-Stützung) |
| `Criterion` | Kurzer Name des Kriteriums |
| `What pass requires` | Die spezifische, bewertbare Bedingung, die ein „Bestanden" ausmacht |
| `Notes` | Begründung oder Design-Notizen |
| `Conditional` | Falls nicht leer, gilt das Kriterium nur unter dieser Bedingung. Mehrere Bedingungen werden mit `; ` getrennt und gelten **konjunktiv** (alle müssen erfüllt sein), z. B. `PRIM.SU-Naturwissenschaft; PRIM.SU-SCH3-4-quantitative-daten` |

### Für Unterrichtsplanungen (at-unterrichtsplanung)

Wenden Sie zunächst die `shared.csv` an, dann die relevante fachspezifische Datei:

- Für eine **Mathematik-Unterrichtsplanung**: `shared.csv` + `mathematik.csv`
- Für eine **Deutsch-Unterrichtsplanung**: `shared.csv` + `deutsch.csv`
- Für eine **Sachunterrichts-Unterrichtsplanung** (Naturwissenschaft oder Gesellschaft): `shared.csv` + `sachunterricht.csv`

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
- Korrekter Kompetenz-ID im Schema dieses Projekts (z. B. `AT.LP23.PRIM.M.OPERATIONEN.SCH1.01`)
- RIS-Quellenangabe mit Normdokumentnummer (NOR)
- Abrufdatum der Quelle

**Warum**: Garantiert, dass Unterrichtsmaterialien im amtlichen Lehrplantext verankert sind und nicht auf Paraphrasen oder Vermutungen beruhen.

### 2. **Progression** (P12-AT)
Die Unterrichtsstunde muss das **Spiralprinzip** und **Wiederholen-und-Festigen**-Phasen aus dem Lehrplan respektieren:
- Explizite Verbindungen zu Voraussetzungs-Kompetenzen
- Sichtbare Verknüpfung zu Folge-Kompetenzen
- Belege für zyklische Wiederholung, nicht für eine lineare einmalige Darbietung

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
- Korrekt bestimmt sein (für die Unterrichtsstunde einschlägig)
- Sichtbar integriert sein (nicht nur in Notizen erwähnt)
- Mit dem Fach-Inhalt verflochten sein

**Warum**: Stellt sicher, dass Lehrkräfte erkennen, welche fächerübergreifenden Verbindungen sie nutzen.

### 6. **Dokumentintegrität** (O16-AT)
Alle generierten Dokumente müssen:
- Vollständig ausgegeben werden (nichts abgeschnitten)
- Korrekt formatiert sein (kein Formatierungsverlust)
- Alle Seiten oder Abschnitte beinhalten (kein Verlust von Inhalten)

**Warum**: Gewährleistet, dass generierte Materialien professionelle Qualität haben und im Klassenzimmer nutzbar sind.

### 7. **Fehlvorstellungen** (P16-AT)
Häufige Fehlvorstellungen der Schüler:innen zu jeder Kompetenz müssen:
- Mit einer Quelle zitiert sein
- Mit **`amtlich: false`** gekennzeichnet sein, wenn sie nicht aus amtlichen Quellen stammen
- In eine kuratierte Datenbank eingehen

**Warum**: Verbessert die Qualität der Materialien zu Fehlvorstellungen und gibt Lehrkräften belegte, nachvollziehbare Angaben.

### 8. **Crosswalk** (O17-AT)
Wenn Bildungsstandards-Mapping vorhanden ist:
- Die Zuordnung auf **Kompetenzbereich-Ebene** vornehmen, nicht auf Ebene einzelner Deskriptoren
- **Dokumentierte Begründung** für jede Zuordnung bereitstellen
- Offenlegen, wie Bildungsstandards mit Lehrplan-Kompetenzen verknüpft sind

**Warum**: Unterstützt Lehrkräfte, die Lehrplan und Bildungsstandards parallel heranziehen.

### 9. **Herkunftstrennung** (O18-AT)
Amtliche **RIS-Inhalte** müssen deutlich von **Lehrkraft-bereitgestellten** (`docs/`) Materialien unterschieden sein:
- Klare Quellenangaben in Markup oder Metadaten
- Lehrkräfte wissen sofort: Was ist amtlich? Was habe ich selbst gemacht?
- Keine Vermischung von Quellen ohne Kennzeichnung

**Warum**: Erhöht Transparenz und Vertrauenswürdigkeit; verhindert, dass Lehrkräfte versehentlich inoffizielle Inhalte als amtlich ausgeben.

---

## Hinweise für Bewertende

- **Bedingte Kriterien**: Einige Kriterien gelten nur unter bestimmten Bedingungen (gekennzeichnet in der `Conditional`-Spalte). Überspringen Sie ein Kriterium, wenn seine Bedingung nicht erfüllt ist. Bei mehreren, mit `; ` getrennten Bedingungen muss **jede** erfüllt sein.
- **Geltungsbereich gehört in `Conditional`, nicht in `Notes`**: Wenn ein Kriterium nur für einen Fachbereich, eine Schulstufe oder eine Textsorte gilt, muss das in `Conditional` stehen. `Notes` ist reine Begründung und wird beim Überspringen **nicht** ausgewertet — ein dort formulierter Geltungsbereich bleibt wirkungslos. `tests/test_rubric_conditions.py` prüft das für die bekannten Geltungsbereiche.
- **`fehlvorstellungen-kuratiert`**: Diese Bedingung ist **keine** Fachbereichs-Einschränkung, sondern eine Datenverfügbarkeits-Bedingung. Sie ist erfüllt, sobald der ausgelieferte Datensatz kuratierte `typische_fehlvorstellungen` mit `quelle` enthält. **Heute enthält er keine** — `finde_typische_fehlvorstellungen()` gibt bewusst immer `[]` zurück, weil erfundene Fehlvorstellungen schlechter wären als keine. `P16-AT` wird daher derzeit **übersprungen**, nicht als „nicht bestanden" gewertet: Es wäre sinnlos, jede Planung an Daten zu messen, die das Produkt absichtlich nicht ausliefert. Sobald kuratierte Einträge ausgeliefert werden, gilt das Kriterium automatisch wieder. `tests/test_fehlvorstellungen_guard.py` hält beide Seiten dieser Aussage synchron.
- **Unabhängige Bewertung**: Jedes Kriterium wird isoliert bewertet — ein Versagen bei `R2` sagt etwas Spezifisches über kognitive Anforderungen aus, nicht nur „das Material ist schlecht".
- **Kalibrierung**: Erwägen Sie, mit Kolleg:innen zu kalibrieren, wenn Sie diese Rubrics zum ersten Mal verwenden. Die Grenze zwischen „Bestanden" und „Nicht bestanden" erfordert manchmal Urteilsvermögen.

## Weiterführende Ressourcen

- [RIS (Rechtsinformationssystem des Bundes)](https://www.ris.bka.gv.at/) — **einzige** amtliche Quelle für Lehrplan- und Bildungsstandards-Text in diesem Projekt
- Lehrplan der Volksschule: `NOR40271469` · Lehrpläne der Mittelschulen: `NOR40271471` · Bildungsstandards-Verordnung: `NOR40255561`

---

**Hintergrund**: Diese Rubrics wurden abgeleitet aus den Learning Commons/Anthropic K-12 Evals und adaptiert für die österreichische Primarstufe (1.–4. Schulstufe) und Sekundarstufe I (1.–4. Klasse, entspricht der 5.–8. Schulstufe). Sie spiegeln die Struktur des österreichischen Lehrplans 2023, die Bildungsstandards und bewährte Praxis im österreichischen Unterricht wider.
