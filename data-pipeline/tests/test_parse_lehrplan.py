"""Unit tests for parse_lehrplan.py (stdlib unittest, no third-party deps).

Run:  python3 -m unittest discover -s data-pipeline/tests -t data-pipeline/tests
  or: python3 -m pytest data-pipeline/tests

Two fixtures are used:

``sek1_mathematik.xml``
    The real MATHEMATIK span of NOR40271471 (children 854..1071), wrapped in a
    stub of its surrounding TEIL and flanked by trimmed neighbour subjects.
    Byte-for-byte identical to the source inside that span, so the six measured
    counts must reproduce exactly.

``sek1_mathematik_mini.xml``
    Synthetic. Same shape, one fiftieth the size, and carries the cases the
    live document lacks -- notably a join that only the positional fallback can
    resolve.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import abbildungen as ABB  # noqa: E402
import parse_lehrplan as P  # noqa: E402

# The parser mirrors every tolerated deviation to logging.WARNING; that is the
# point in production and pure noise here.
logging.getLogger("parse_lehrplan").setLevel(logging.CRITICAL)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ECHT = FIXTURES / "sek1_mathematik.xml"
MINI = FIXTURES / "sek1_mathematik_mini.xml"


def parse(path: Path) -> P.ParseResult:
    return P.parse_lehrplan(path, P.SEK1_MATHEMATIK)


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------


class TestTextExtraction(unittest.TestCase):
    def test_bullet_symbol_is_dropped(self):
        el = ET.fromstring(
            '<listelem xmlns="http://www.bka.gv.at">'
            '<symbol stellen="1">–</symbol>Text der Kompetenz.</listelem>'
        )
        self.assertEqual(P.element_text(el).text, "Text der Kompetenz.")

    def test_super_removed_from_text_but_kept_separately(self):
        el = ET.fromstring(
            '<listelem xmlns="http://www.bka.gv.at">'
            '<symbol stellen="1">–</symbol>Daten erheben;<super>6, 7</super></listelem>'
        )
        ex = P.element_text(el)
        self.assertEqual(ex.text, "Daten erheben;")
        self.assertEqual(ex.super_marker, ("6, 7",))
        self.assertEqual(ex.roh, "Daten erheben;6, 7")

    def test_binary_src_never_leaks_into_the_sentence(self):
        el = ET.fromstring(
            '<listelem xmlns="http://www.bka.gv.at">Wert 0,6'
            '<binary nr="1"><src>/Dokumente/x.png</src></binary>.</listelem>'
        )
        ex = P.element_text(el)
        self.assertNotIn("/Dokumente", ex.text)
        self.assertEqual(ex.text, "Wert 0,6⟦ABB:x.png⟧.")
        self.assertEqual(ex.abbildungen, ("/Dokumente/x.png",))
        self.assertTrue(ex.hat_abbildung)

    def test_binary_token_uses_the_mathematical_white_square_brackets(self):
        # U+27E6 / U+27E7 -- chosen because this pair cannot occur in the
        # source text, so token vs. prose is never ambiguous.
        self.assertEqual(P.abbildung_token("x.png"), "⟦ABB:x.png⟧")

    def test_binary_token_position_matches_the_image_position(self):
        # A listelem with prose both before and after the image: the token
        # must land exactly where the <binary> sat, not at the start/end.
        el = ET.fromstring(
            '<listelem xmlns="http://www.bka.gv.at">vor'
            '<binary nr="1"><src>/Dokumente/a.png</src></binary>nach</listelem>'
        )
        ex = P.element_text(el)
        self.assertEqual(ex.text, "vor⟦ABB:a.png⟧nach")

    def test_multiple_binaries_keep_document_order_between_text_and_abbildungen(self):
        el = ET.fromstring(
            '<listelem xmlns="http://www.bka.gv.at">a'
            '<binary nr="1"><src>/Dokumente/one.png</src></binary>b'
            '<binary nr="2"><src>/Dokumente/two.png</src></binary>c</listelem>'
        )
        ex = P.element_text(el)
        self.assertEqual(ex.text, "a⟦ABB:one.png⟧b⟦ABB:two.png⟧c")
        self.assertEqual(ex.abbildungen, ("/Dokumente/one.png", "/Dokumente/two.png"))

    def test_no_internal_whitespace_collapsing(self):
        el = ET.fromstring(
            '<absatz xmlns="http://www.bka.gv.at">a b  c</absatz>'
        )
        self.assertEqual(P.element_text(el).text, "a b  c")


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


class TestNormalisation(unittest.TestCase):
    def test_stem_is_stripped(self):
        self.assertEqual(
            P.strip_stem("Die Schülerinnen und Schüler können rechnen."),
            "rechnen.",
        )

    def test_stem_absent_is_a_no_op(self):
        self.assertEqual(P.strip_stem("rechnen."), "rechnen.")

    def test_match_normalisation_folds_stem_dashes_quotes_and_tail(self):
        a = "Die Schülerinnen und Schüler können Größen – groß – messen."
        b = "Größen - groß - messen;"
        self.assertEqual(P.normalise_for_match(a), P.normalise_for_match(b))

    def test_normalisation_does_not_touch_stored_text(self):
        result = parse(MINI)
        k = result.kompetenzen[0]
        self.assertEqual(k.text, "erste Kompetenz mit Marker;")


# ---------------------------------------------------------------------------
# Subject boundary detection
# ---------------------------------------------------------------------------


class TestSubjectBoundary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mini = parse(MINI)
        cls.echt = parse(ECHT)

    def test_preceding_subject_is_not_captured(self):
        texte = [k.text for k in self.mini.kompetenzen]
        self.assertNotIn("diese Kompetenz gehört nicht zu MATHEMATIK.", texte)

    def test_following_subject_is_not_captured(self):
        texte = [k.text for k in self.mini.kompetenzen]
        self.assertNotIn(
            "diese Kompetenz gehört ebenfalls nicht zu MATHEMATIK.", texte
        )

    def test_teil_and_section_g1_headings_do_not_open_a_subject(self):
        # ACHTER TEIL / A. PFLICHTGEGENSTAENDE are g1 too; only the exact
        # subject heading may start the machine.
        self.assertTrue(all(k.fach == "M" for k in self.echt.kompetenzen))

    def test_subject_heading_in_the_wrong_teil_is_skipped(self):
        # The primary document repeats subject names across TEILs; only the
        # occurrence under the configured TEIL may open the subject.
        xml = """<risdok xmlns="http://www.bka.gv.at"><nutzdaten><abschnitt>
          <ueberschrift typ="g1">SIEBENTER TEIL</ueberschrift>
          <ueberschrift typ="g1">MATHEMATIK</ueberschrift>
          <ueberschrift typ="erll">Kompetenzbereiche (1. bis 4. Klasse):</ueberschrift>
          <absatz typ="erltext">1. Klasse:</absatz>
          <ueberschrift typ="erll">Kompetenzbereich 1: Falscher Teil</ueberschrift>
          <liste><aufzaehlung><listelem>falsch.</listelem></aufzaehlung></liste>
          <ueberschrift typ="g1">ACHTER TEIL</ueberschrift>
          <ueberschrift typ="g1">MATHEMATIK</ueberschrift>
          <ueberschrift typ="erll">Kompetenzbereiche (1. bis 4. Klasse):</ueberschrift>
          <absatz typ="erltext">1. Klasse:</absatz>
          <ueberschrift typ="erll">Kompetenzbereich 1: Richtiger Teil</ueberschrift>
          <liste><aufzaehlung><listelem>richtig.</listelem></aufzaehlung></liste>
        </abschnitt></nutzdaten></risdok>"""
        r = P.LehrplanParser(P.SEK1_MATHEMATIK).parse_root(ET.fromstring(xml))
        self.assertEqual([k.text for k in r.kompetenzen], ["richtig."])
        self.assertEqual(len(r.issues.by_art("fachueberschrift_im_falschen_teil")), 1)

    def test_missing_subject_is_a_hard_failure(self):
        spec = P.SubjectSpec(
            band="SEK1",
            fach_code="X",
            fach_ueberschrift="GIBT ES NICHT",
            stufen_praefix="K",
            kompetenz_sektion_re=P.SEK1_MATHEMATIK.kompetenz_sektion_re,
            anwendung_sektion_re=P.SEK1_MATHEMATIK.anwendung_sektion_re,
        )
        with self.assertRaises(P.ParseError):
            P.LehrplanParser(spec).parse_file(MINI)


# ---------------------------------------------------------------------------
# Competence area detection -- both element forms
# ---------------------------------------------------------------------------


class TestAreaDetection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.echt = parse(ECHT)
        cls.mini = parse(MINI)

    def test_areas_from_ueberschrift_form(self):
        namen = [b.name for b in self.echt.bereiche]
        self.assertEqual(
            namen,
            ["Zahlen und Maße", "Variablen und Funktionen",
             "Figuren und Körper", "Daten und Zufall"],
        )

    def test_areas_from_absatz_form_reach_the_application_items(self):
        # The Anwendungsbereiche section repeats the same headings as
        # absatz/@typ="abs".  If that form were not recognised, every item
        # would land in the same bucket.
        buckets = {(a.stufe, a.bereich_nummer) for a in self.echt.anwendungsitems}
        self.assertEqual(len(buckets), 16)
        self.assertTrue(all(n is not None for _, n in buckets))

    def test_same_area_object_is_reused_across_both_forms(self):
        # Four areas total, not eight -- the absatz form must resolve to the
        # areas already registered from the ueberschrift form.
        self.assertEqual(len(self.echt.bereiche), 4)

    def test_area_numbers_and_id_slugs(self):
        slugs = {b.nummer: b.slug for b in self.echt.bereiche}
        self.assertEqual(slugs, {1: "ZAHLEN", 2: "VARIABLEN", 3: "FIGUREN", 4: "DATEN"})

    def test_unmapped_area_name_gets_a_derived_slug_and_an_issue(self):
        self.assertEqual(P.slugify_bereich("Sozialwissenschaftlicher"), "SOZIALWISSEN")
        self.assertEqual(P.slugify_bereich("Zahlen und Maße"), "ZAHLENUNDMAS")


# ---------------------------------------------------------------------------
# Class-year detection
# ---------------------------------------------------------------------------


class TestStufe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.echt = parse(ECHT)

    def test_all_four_class_years_present(self):
        self.assertEqual(
            sorted({k.stufe for k in self.echt.kompetenzen}), ["K1", "K2", "K3", "K4"]
        )

    def test_ten_competences_per_class_year(self):
        # K3 and K4 carry 11: the usual 10 from the four numbered
        # Kompetenzbereiche plus one promoted "integrative Führung von
        # Geometrisches Zeichnen" competence each (K1/K2 have none -- that
        # appendix only covers 3./4. Klasse). See TestGzIntegrativPromotion.
        erwartet = {"K1": 10, "K2": 10, "K3": 11, "K4": 11}
        for jahr, soll in erwartet.items():
            with self.subTest(jahr=jahr):
                self.assertEqual(
                    sum(1 for k in self.echt.kompetenzen if k.stufe == jahr), soll
                )

    def test_class_year_resets_the_area(self):
        # First competence after each year marker must be area 1.
        for jahr in ("K1", "K2", "K3", "K4"):
            erste = next(k for k in self.echt.kompetenzen if k.stufe == jahr)
            self.assertEqual(erste.bereich_nummer, 1)

    def test_schulstufe_unit_is_tolerated_and_logged(self):
        issues = P.IssueLog()
        parser = P.LehrplanParser(P.SEK1_MATHEMATIK, issues)
        ev = P.Ereignis(
            P.Token.STUFE, 5, ET.Element("x"), P.ExtractedText("2. Schulstufe:", "2. Schulstufe:"),
            {"nr": 2, "einheit": "Schulstufe"},
        )
        self.assertEqual(parser._stufe_code(ev), "K2")
        self.assertEqual(len(issues.by_art("unerwartete_stufeneinheit")), 1)

    def test_level_marker_is_accepted_as_ueberschrift_too(self):
        # Primary writes the marker as ueberschrift/@typ="erll", Sek I as
        # absatz/@typ="erltext".  Both must classify as a level marker.
        xml = """<risdok xmlns="http://www.bka.gv.at"><nutzdaten><abschnitt>
          <ueberschrift typ="g1">ACHTER TEIL</ueberschrift>
          <ueberschrift typ="g1">MATHEMATIK</ueberschrift>
          <ueberschrift typ="erll">Kompetenzbereiche (1. bis 4. Klasse):</ueberschrift>
          <ueberschrift typ="erll">3. Klasse:</ueberschrift>
          <ueberschrift typ="erll">Kompetenzbereich 1: Zahlen und Ma&#223;e</ueberschrift>
          <liste><aufzaehlung><listelem>eine Kompetenz.</listelem></aufzaehlung></liste>
        </abschnitt></nutzdaten></risdok>"""
        r = P.LehrplanParser(P.SEK1_MATHEMATIK).parse_root(ET.fromstring(xml))
        self.assertEqual([k.stufe for k in r.kompetenzen], ["K3"])

    def test_regex_accepts_both_units(self):
        self.assertTrue(P.STUFE_RE.match("1. Klasse:"))
        self.assertTrue(P.STUFE_RE.match("3. Schulstufe:"))
        self.assertIsNone(P.STUFE_RE.match("Kompetenzbereich 1: Zahlen"))


# ---------------------------------------------------------------------------
# allenfalls flag
# ---------------------------------------------------------------------------


class TestAllenfalls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.echt = parse(ECHT)
        cls.mini = parse(MINI)

    def test_measured_count(self):
        self.assertEqual(
            sum(1 for a in self.echt.anwendungsitems if not a.verbindlich), 32
        )

    def test_flag_matches_the_word(self):
        for a in self.echt.anwendungsitems:
            with self.subTest(a.id):
                self.assertEqual(a.verbindlich, "allenfalls" not in a.text.lower())

    def test_mini_fixture(self):
        nicht = [a for a in self.mini.anwendungsitems if not a.verbindlich]
        self.assertEqual(len(nicht), 1)
        self.assertTrue(nicht[0].text.startswith("allenfalls"))

    def test_competences_never_carry_the_flag(self):
        # `verbindlich` is an application-item concept only (plan section 4.4,
        # anwendungsbereiche_status == "item_flags").
        self.assertFalse(hasattr(self.echt.kompetenzen[0], "verbindlich"))


# ---------------------------------------------------------------------------
# The join
# ---------------------------------------------------------------------------


class TestJoin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.echt = parse(ECHT)
        cls.mini = parse(MINI)

    def test_live_rates(self):
        s = self.echt.join_stats
        self.assertEqual(s["bloecke"], 40)
        self.assertEqual(s["exact"], 38)
        self.assertEqual(s["fuzzy"], 2)
        self.assertEqual(s["positional"], 0)
        self.assertEqual(s["unmatched"], 0)

    def test_every_competence_receives_exactly_one_block(self):
        # Every competence from the four numbered Kompetenzbereiche joins
        # exactly one Anwendungsblock. The 2 promoted GZ-integrative
        # competences are the sole, expected exception: that appendix has no
        # Anwendungsbereiche counterpart in the source at all, so they can
        # never be joined -- see TestGzIntegrativPromotion.
        ohne = self.echt.join_stats["kompetenzen_ohne_block"]
        self.assertEqual(ohne, 2)
        unjoined = [
            k.id for k in self.echt.kompetenzen
            if not any(b.kompetenz_id == k.id for b in self.echt.bloecke)
        ]
        self.assertEqual(
            sorted(unjoined),
            ["AT.LP23.SEK1.M.GZINTEGRATIV.K3.01", "AT.LP23.SEK1.M.GZINTEGRATIV.K4.01"],
        )
        ids = [b.kompetenz_id for b in self.echt.bloecke]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_praezisierung_item_carries_a_competence_id(self):
        praez = [a for a in self.echt.anwendungsitems if a.art == "praezisierung"]
        self.assertEqual(len(praez), 198)
        self.assertTrue(all(a.kompetenz_id for a in praez))

    def test_digital_technology_items_are_not_joined(self):
        dt = [a for a in self.echt.anwendungsitems if a.art == "digitale_technologien"]
        self.assertEqual(len(dt), 39)
        self.assertTrue(all(a.kompetenz_id is None for a in dt))

    def test_the_two_fuzzy_pairs_are_the_known_ones(self):
        fuzzy = [b for b in self.echt.bloecke if b.join_methode == "fuzzy"]
        self.assertEqual(len(fuzzy), 2)
        for b in fuzzy:
            self.assertGreaterEqual(b.join_score, P.FUZZY_SCHWELLE)
        self.assertIn(
            "achsensymmetrische Figuren und zueinander kongruente",
            " ".join(b.satz for b in fuzzy),
        )

    def test_every_non_exact_join_is_logged(self):
        nicht_exakt = [b for b in self.echt.bloecke if b.join_methode != "exact"]
        protokolliert = self.echt.issues.by_art("join_fuzzy") + self.echt.issues.by_art("join_positional")
        self.assertEqual(len(nicht_exakt), len(protokolliert))

    def test_mini_exercises_all_three_strategies(self):
        methoden = sorted(b.join_methode for b in self.mini.bloecke)
        self.assertEqual(methoden, ["exact", "exact", "fuzzy", "positional"])
        self.assertEqual(self.mini.join_stats["unmatched"], 0)

    def test_positional_fallback_picks_the_matching_ordinal(self):
        block = next(b for b in self.mini.bloecke if b.join_methode == "positional")
        ziel = next(k for k in self.mini.kompetenzen if k.id == block.kompetenz_id)
        self.assertEqual(ziel.stufe, "K2")
        self.assertEqual(ziel.ordinal, block.ordinal)
        self.assertEqual(len(self.mini.issues.by_art("join_positional")), 1)

    def test_join_is_bucketed_by_year_and_area(self):
        # A block must never join a competence from another year or area.
        nach_id = {k.id: k for k in self.echt.kompetenzen}
        for b in self.echt.bloecke:
            k = nach_id[b.kompetenz_id]
            self.assertEqual((k.stufe, k.bereich_nummer), (b.stufe, b.bereich_nummer))


# ---------------------------------------------------------------------------
# Wiederholen und Festigen
# ---------------------------------------------------------------------------


class TestWiederholung(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.echt = parse(ECHT)
        cls.mini = parse(MINI)

    def test_measured_count(self):
        self.assertEqual(
            sum(1 for a in self.echt.anwendungsitems if a.ist_wiederholung), 16
        )

    def test_never_in_the_first_class_year(self):
        self.assertFalse(
            [a for a in self.echt.anwendungsitems if a.ist_wiederholung and a.stufe == "K1"]
        )
        self.assertFalse(self.echt.issues.by_art("wiederholung_in_erster_stufe"))

    def test_backlinks_point_one_year_back_in_the_same_area(self):
        nach_id = {k.id: k for k in self.echt.kompetenzen}
        treffer = 0
        for a in self.echt.anwendungsitems:
            if not a.ist_wiederholung:
                continue
            self.assertTrue(a.wiederholung_von, a.id)
            for kid in a.wiederholung_von:
                k = nach_id[kid]
                self.assertEqual(k.bereich_nummer, a.bereich_nummer)
                self.assertEqual(int(k.stufe[1:]), int(a.stufe[1:]) - 1)
                treffer += 1
        # 16 items x the competences in the preceding year of their area.
        self.assertEqual(treffer, 38)

    def test_no_dangling_backlink(self):
        self.assertFalse(self.echt.issues.by_art("wiederholung_ohne_ziel"))

    def test_mini_backlink(self):
        item = next(a for a in self.mini.anwendungsitems if a.ist_wiederholung)
        self.assertEqual(item.stufe, "K2")
        ziel = next(k for k in self.mini.kompetenzen if k.id == item.wiederholung_von[0])
        self.assertEqual(ziel.stufe, "K1")
        self.assertEqual(ziel.bereich_nummer, 1)

    def test_positional_progression_on_the_competences(self):
        k1 = [k for k in self.echt.kompetenzen if k.stufe == "K1" and k.bereich_nummer == 1]
        k2 = [k for k in self.echt.kompetenzen if k.stufe == "K2" and k.bereich_nummer == 1]
        self.assertEqual(k1[0].folge, [k.id for k in k2])
        self.assertEqual(k2[0].vorlaeufer, [k.id for k in k1])
        self.assertEqual(k1[0].vorlaeufer, [])


# ---------------------------------------------------------------------------
# Cross-cutting themes (<super>)
# ---------------------------------------------------------------------------


class TestThemen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.echt = parse(ECHT)
        cls.mini = parse(MINI)

    def test_ten_competences_carry_a_marker(self):
        self.assertEqual(sum(1 for k in self.echt.kompetenzen if k.themen_marker_roh), 10)

    def test_legend_table_yields_all_thirteen_themes(self):
        self.assertEqual(len(self.echt.themen_map), 13)
        self.assertEqual(self.echt.themen_map["4"], "Informatische Bildung")

    def test_subject_theme_sentence_parsed_without_splitting_names(self):
        self.assertIn(
            "Wirtschafts-, Finanz- und Verbraucher/innenbildung",
            self.echt.uebergreifende_themen_fach,
        )
        self.assertEqual(len(self.echt.uebergreifende_themen_fach), 10)

    def test_multi_number_super_is_split(self):
        k = next(k for k in self.echt.kompetenzen if k.themen_marker_roh == ["6, 7"])
        self.assertEqual(k.uebergreifende_themen, ["Medienbildung", "Politische Bildung"])

    def test_no_unresolved_footnotes_in_this_subject(self):
        offen = [k.id for k in self.echt.kompetenzen if k.fussnoten_unaufgeloest]
        self.assertEqual(offen, [])

    def test_mini_resolution(self):
        k = next(k for k in self.mini.kompetenzen if k.themen_marker_roh)
        self.assertEqual(k.uebergreifende_themen, ["Informatische Bildung"])


# ---------------------------------------------------------------------------
# Tolerance and hard failures
# ---------------------------------------------------------------------------


class TestTolerance(unittest.TestCase):
    def test_gz_integrativ_heading_no_longer_an_unknown_heading(self):
        # The "... bei integrativer Führung von Geometrisches Zeichnen ..."
        # heading used to fall through to the generic ANDERE_UEBERSCHRIFT /
        # unbekannte_ueberschrift path (see git history / notes/deviations.md).
        # It is now specifically recognised and promoted -- see
        # TestGzIntegrativPromotion -- so it must no longer be logged as an
        # unknown heading, and the mini fixture's genuinely-unrelated unknown
        # trailing heading ("Kompetenzen bei integrativer Führung (Anhang):")
        # must still exercise the untouched fallback path.
        r = parse(ECHT)
        self.assertEqual(r.issues.by_art("unbekannte_ueberschrift"), [])

        m = parse(MINI)
        issues = m.issues.by_art("unbekannte_ueberschrift")
        self.assertEqual(len(issues), 1)
        self.assertIn("integrativer Führung", issues[0].kontext)

    def test_content_after_the_sections_is_carried_not_dropped(self):
        # The mini fixture's unrelated trailing heading still lands in
        # zusatzbloecke (nothing generic was removed); the live document's
        # GZ appendix no longer does, because it is now promoted into
        # r.kompetenzen -- see TestGzIntegrativPromotion.
        r = parse(ECHT)
        self.assertEqual(r.zusatzbloecke, [])
        self.assertEqual(len(r.kompetenzen), 42)

        m = parse(MINI)
        self.assertEqual(len(m.zusatzbloecke), 1)
        self.assertEqual(m.zusatzbloecke[0]["stufe"], "K2")
        self.assertEqual(
            m.zusatzbloecke[0]["text"], "Anhangkompetenz, die nicht zu den vier Kernkompetenzen zählt."
        )

    def test_empty_required_text_is_fatal(self):
        xml = """<risdok xmlns="http://www.bka.gv.at"><nutzdaten><abschnitt>
          <ueberschrift typ="g1">ACHTER TEIL</ueberschrift>
          <ueberschrift typ="g1">MATHEMATIK</ueberschrift>
          <ueberschrift typ="erll">Kompetenzbereiche (1. bis 4. Klasse):</ueberschrift>
          <absatz typ="erltext">1. Klasse:</absatz>
          <ueberschrift typ="erll">Kompetenzbereich 1: Zahlen und Ma&#223;e</ueberschrift>
          <liste><aufzaehlung><listelem><symbol stellen="1">-</symbol></listelem></aufzaehlung></liste>
        </abschnitt></nutzdaten></risdok>"""
        with self.assertRaises(P.ParseError):
            P.LehrplanParser(P.SEK1_MATHEMATIK).parse_root(ET.fromstring(xml))

    def test_id_collision_is_fatal(self):
        # Two identically-keyed competence lists under the same area and year.
        xml = """<risdok xmlns="http://www.bka.gv.at"><nutzdaten><abschnitt>
          <ueberschrift typ="g1">ACHTER TEIL</ueberschrift>
          <ueberschrift typ="g1">MATHEMATIK</ueberschrift>
          <ueberschrift typ="erll">Kompetenzbereiche (1. bis 4. Klasse):</ueberschrift>
          <absatz typ="erltext">1. Klasse:</absatz>
          <ueberschrift typ="erll">Kompetenzbereich 1: Zahlen und Ma&#223;e</ueberschrift>
          <liste><aufzaehlung><listelem>erste.</listelem></aufzaehlung></liste>
          <ueberschrift typ="erll">Kompetenzbereich 1: Zahlen und Ma&#223;e</ueberschrift>
          <liste><aufzaehlung><listelem>zweite.</listelem></aufzaehlung></liste>
        </abschnitt></nutzdaten></risdok>"""
        with self.assertRaises(P.ParseError) as ctx:
            P.LehrplanParser(P.SEK1_MATHEMATIK).parse_root(ET.fromstring(xml))
        self.assertIn("ID collision", str(ctx.exception))

    def test_document_without_nutzdaten_is_fatal(self):
        with self.assertRaises(P.ParseError):
            P.LehrplanParser(P.SEK1_MATHEMATIK).parse_root(ET.fromstring("<risdok/>"))

    def test_list_without_context_is_skipped_and_logged(self):
        xml = """<risdok xmlns="http://www.bka.gv.at"><nutzdaten><abschnitt>
          <ueberschrift typ="g1">ACHTER TEIL</ueberschrift>
          <ueberschrift typ="g1">MATHEMATIK</ueberschrift>
          <ueberschrift typ="erll">Kompetenzbereiche (1. bis 4. Klasse):</ueberschrift>
          <liste><aufzaehlung><listelem>ohne Stufe und Bereich.</listelem></aufzaehlung></liste>
        </abschnitt></nutzdaten></risdok>"""
        r = P.LehrplanParser(P.SEK1_MATHEMATIK).parse_root(ET.fromstring(xml))
        self.assertEqual(r.kompetenzen, [])
        self.assertEqual(len(r.issues.by_art("liste_ohne_kontext")), 1)
        self.assertEqual(len(r.issues.by_art("keine_kompetenzen")), 1)

    def test_ids_are_unique_and_well_formed(self):
        r = parse(ECHT)
        alle = [k.id for k in r.kompetenzen] + [a.id for a in r.anwendungsitems]
        self.assertEqual(len(alle), len(set(alle)))
        self.assertTrue(all(i.startswith("AT.LP23.SEK1.M.") for i in alle))


# ---------------------------------------------------------------------------
# The 2 promoted "integrative Führung von Geometrisches Zeichnen" competences
# ---------------------------------------------------------------------------


class TestGzIntegrativPromotion(unittest.TestCase):
    """Decision taken (notes/deviations.md): the 2 competences under
    'Kompetenzen für den Mathematik-Lehrplan bei integrativer Führung von
    Geometrisches Zeichnen (1. bis 4. Klasse):' ship as part of the main
    dataset instead of being carried in zusatzbloecke. 40 -> 42."""

    @classmethod
    def setUpClass(cls):
        cls.echt = parse(ECHT)

    def test_exactly_two_promoted_competences_with_the_expected_ids(self):
        promoted = [
            k for k in self.echt.kompetenzen
            if k.id.startswith("AT.LP23.SEK1.M.GZINTEGRATIV.")
        ]
        self.assertEqual(
            sorted(k.id for k in promoted),
            ["AT.LP23.SEK1.M.GZINTEGRATIV.K3.01", "AT.LP23.SEK1.M.GZINTEGRATIV.K4.01"],
        )

    def test_promoted_competences_carry_the_verbatim_text(self):
        by_id = {k.id: k for k in self.echt.kompetenzen}
        k3 = by_id["AT.LP23.SEK1.M.GZINTEGRATIV.K3.01"]
        k4 = by_id["AT.LP23.SEK1.M.GZINTEGRATIV.K4.01"]
        self.assertEqual(
            k3.text,
            "Grund-, Auf- und Kreuzriss, Schrägrisse und Zentralrisse von "
            "geometrischen Objekten lesen, mit unterschiedlichen Methoden "
            "herstellen sowie die Raumvorstellung mittels Raumtransformation "
            "von geometrischen Objekten weiterentwickeln.",
        )
        self.assertEqual(
            k4.text,
            "Geometrische Objekte in unterschiedlichen Rissen mithilfe von "
            "Raumtransformationen und Booleschen Operationen unter Verwendung "
            "von Konstruktionszeichnungen und 3D-Software erzeugen und "
            "bearbeiten sowie die Raumvorstellung stärken.",
        )

    def test_promoted_competences_get_a_synthetic_unnumbered_area(self):
        by_id = {k.id: k for k in self.echt.kompetenzen}
        for kid in ("AT.LP23.SEK1.M.GZINTEGRATIV.K3.01", "AT.LP23.SEK1.M.GZINTEGRATIV.K4.01"):
            k = by_id[kid]
            self.assertIsNone(k.bereich_nummer)
            self.assertEqual(k.bereich_name, P.GZ_INTEGRATIV_BEREICH_NAME)

    def test_synthetic_area_is_not_added_to_kompetenzbereiche(self):
        # There are still exactly 4 official Kompetenzbereiche; the promoted
        # pair is labelled but not folded into that list as a 5th area.
        self.assertEqual(len(self.echt.bereiche), 4)
        self.assertNotIn(P.GZ_INTEGRATIV_BEREICH_NAME, [b.name for b in self.echt.bereiche])

    def test_total_competence_count_is_42(self):
        self.assertEqual(len(self.echt.kompetenzen), 42)

    def test_promoted_competences_have_no_super_or_abbildung(self):
        by_id = {k.id: k for k in self.echt.kompetenzen}
        for kid in ("AT.LP23.SEK1.M.GZINTEGRATIV.K3.01", "AT.LP23.SEK1.M.GZINTEGRATIV.K4.01"):
            k = by_id[kid]
            self.assertEqual(k.themen_marker_roh, [])
            self.assertEqual(k.abbildungen, [])

    def test_year_over_year_progression_links_the_two(self):
        by_id = {k.id: k for k in self.echt.kompetenzen}
        k3 = by_id["AT.LP23.SEK1.M.GZINTEGRATIV.K3.01"]
        k4 = by_id["AT.LP23.SEK1.M.GZINTEGRATIV.K4.01"]
        self.assertEqual(k3.folge, [k4.id])
        self.assertEqual(k4.vorlaeufer, [k3.id])
        self.assertEqual(k3.vorlaeufer, [])
        self.assertEqual(k4.folge, [])


# ---------------------------------------------------------------------------
# Inline images (⟦ABB:...⟧ tokens and the abbildungen metadata array)
# ---------------------------------------------------------------------------


class TestAbbildungen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.echt = parse(ECHT)

    def test_no_placeholder_survives_anywhere(self):
        d = P.result_to_dict(self.echt)
        payload = json.dumps(d, ensure_ascii=False)
        self.assertNotIn("[Abbildung]", payload)

    def test_raw_src_path_never_leaks_into_quotable_text(self):
        # The raw <binary>/<src> path must never appear in `text`/`text_roh`
        # (that was the original bug this whole feature fixes). It legitimately
        # *does* appear inside abbildungen[].quelle_url, which is the point.
        for k in self.echt.kompetenzen:
            self.assertNotIn("/Dokumente/Bundesnormen", k.text)
            self.assertNotIn("/Dokumente/Bundesnormen", k.text_roh)
        for a in self.echt.anwendungsitems:
            self.assertNotIn("/Dokumente/Bundesnormen", a.text)
            self.assertNotIn("/Dokumente/Bundesnormen", a.text_roh)

    def test_every_token_in_text_has_a_matching_abbildungen_entry(self):
        # Order of tokens found in `text` must match `abbildungen`, 1:1.
        alle = list(self.echt.kompetenzen) + list(self.echt.anwendungsitems)
        checked_any = False
        for rec in alle:
            tokens_in_text = P.ABBILDUNG_TOKEN_RE.findall(rec.text)
            if not tokens_in_text:
                self.assertEqual(rec.abbildungen, [])
                continue
            checked_any = True
            self.assertEqual(len(tokens_in_text), len(rec.abbildungen))
            for dateiname, eintrag in zip(tokens_in_text, rec.abbildungen):
                self.assertEqual(dateiname, eintrag["datei"])
                self.assertEqual(eintrag["token"], P.abbildung_token(dateiname))
        self.assertTrue(checked_any, "fixture should exercise at least one image-bearing record")

    def test_25_application_items_carry_images_none_of_the_kompetenzen_do(self):
        mit_bild = [a for a in self.echt.anwendungsitems if a.abbildungen]
        self.assertEqual(len(mit_bild), 25)
        self.assertEqual([k for k in self.echt.kompetenzen if k.abbildungen], [])

    def test_abbildung_metadata_matches_the_shipped_file(self):
        item = next(a for a in self.echt.anwendungsitems if a.abbildungen)
        eintrag = item.abbildungen[0]
        shipped = ABB.PLUGIN_ABBILDUNGEN_DIR / eintrag["nor"] / eintrag["datei"]
        self.assertTrue(shipped.is_file(), f"{shipped} must be shipped under plugin/data/abbildungen/")
        data = shipped.read_bytes()
        self.assertEqual(eintrag["sha256"], hashlib.sha256(data).hexdigest())
        breite, hoehe = ABB.read_png_dimensions(data)
        self.assertEqual((eintrag["breite_px"], eintrag["hoehe_px"]), (breite, hoehe))
        self.assertEqual(eintrag["hoehe_px"], 17)  # measured fact: every glyph is 17px tall
        self.assertEqual(eintrag["pfad"], f"data/abbildungen/{eintrag['nor']}/{eintrag['datei']}")
        self.assertEqual(
            eintrag["quelle_url"],
            f"https://www.ris.bka.gv.at/Dokumente/Bundesnormen/{eintrag['nor']}/{eintrag['datei']}",
        )

    def test_all_63_in_scope_images_resolve_against_the_shipped_registry(self):
        # 64 images exist in the Mittelschule document; 63 fall inside the
        # Sek I Mathematik span this parser covers (the 64th sits in the
        # following GEOMETRISCHES ZEICHNEN subject, out of scope). None of
        # them should be logged as missing/unresolvable.
        total = sum(len(a.abbildungen) for a in self.echt.anwendungsitems)
        self.assertEqual(total, 63)
        self.assertEqual(self.echt.issues.by_art("abbildung_nicht_installiert"), [])
        self.assertEqual(self.echt.issues.by_art("abbildung_pfad_unerwartet"), [])

    def test_unresolvable_image_is_tolerated_and_logged_not_fatal(self):
        # The mini fixture's image references a synthetic NOR
        # ("NOR00000000") that is never shipped -- this must not crash the
        # parser; it is logged and the token still appears in the text.
        m = parse(MINI)
        item = next(a for a in m.anwendungsitems if "⟦ABB:" in a.text)
        self.assertEqual(item.abbildungen, [])
        self.assertEqual(len(m.issues.by_art("abbildung_nicht_installiert")), 1)


# ---------------------------------------------------------------------------
# End-to-end counts
# ---------------------------------------------------------------------------


class TestMeasuredCounts(unittest.TestCase):
    def test_all_six_expected_counts(self):
        ist = P.actual_counts(parse(ECHT))
        self.assertEqual(ist, P.ERWARTET_SEK1_M)

    def test_serialisation_round_trips(self):
        d = P.result_to_dict(parse(ECHT))
        wieder = json.loads(json.dumps(d, ensure_ascii=False))
        self.assertEqual(len(wieder["kompetenzen"]), 42)
        self.assertEqual(len(wieder["anwendungsitems"]), 237)
        self.assertEqual(wieder["meta"]["anwendungsbereiche_status"], "item_flags")

    def test_cli_verify_passes_on_the_live_source(self):
        quelle = Path(__file__).resolve().parents[1] / "resources/mittelschule/NOR40271471.xml"
        if not quelle.exists():  # pragma: no cover - resources are checked in
            self.skipTest("live source not available")
        alt = sys.stdout
        sys.stdout = io.StringIO()
        try:
            code = P._cli(["--source", str(quelle), "--verify"])
        finally:
            sys.stdout = alt
        self.assertEqual(code, 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
