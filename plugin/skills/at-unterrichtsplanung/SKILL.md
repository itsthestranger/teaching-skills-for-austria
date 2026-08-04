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
- **`schueler_material`** (Schüler:innen) — nur wenn die Stunde tatsächlich ein Arbeitsblatt
  braucht; nicht jede Stunde hat eines.
- **`beobachtungsbogen`** (Lehrkraft) — Look-fors aus Anwendungsbereichen/Lehrstoff, inklusive der
  Standard/Standard-AHS-Unterscheidung, wo diese Achse für das Fach und die Schulstufe gilt.

Herkunft ist in jedem Dokument sichtbar getrennt: amtlicher Lehrplantext vs. optionales
Lehrkraft-Material aus `docs/` (nie als amtlich ausgewiesen, siehe `references/kompetenzdaten.md`).

---

## Stand dieser Datei

Dieses Dokument deckt **Routing und Gerüst** ab (Schritt 0 oben plus die fünf Referenzdateien).
Die volle Ablauflogik — Klären (0–2 Fragen) + Entwurfsangebot, Verankerung in Kompetenzen,
Aufbau nach dem Spiralprinzip, Ausgabe von `lesson.json` in einem Turn, sowie die
`docs/`-Ingestion und das docx-Rendering — ist Gegenstand eigener, nachgelagerter Aufgaben und
noch nicht in dieser Datei spezifiziert. Bis dahin: diese Skill routet korrekt zur Fachreferenz
und zum Datenzugriff; sie schreibt noch keinen vollständigen Planungs-Turn vor.
