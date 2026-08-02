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
import re
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "schema"))

import abbildungen as ABB  # noqa: E402
import id_schema as ID  # noqa: E402
import parse_lehrplan as P  # noqa: E402

# The parser mirrors every tolerated deviation to logging.WARNING; that is the
# point in production and pure noise here.
logging.getLogger("parse_lehrplan").setLevel(logging.CRITICAL)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ECHT = FIXTURES / "sek1_mathematik.xml"
MINI = FIXTURES / "sek1_mathematik_mini.xml"
BINDUNG_MINI = FIXTURES / "containment_bindung_mini.xml"

#: P4 fixtures: the real span of each subject not yet covered by a shipped
#: SubjectSpec, copied byte-for-byte from resources/ (gitignored) so the
#: TestLiveContainmentSmoke counts above are reproducible without it. See
#: notes/ris-xml-structure.md §12 for the exact child-index ranges and the
#: extraction procedure.
SEK1_DEUTSCH = FIXTURES / "sek1_deutsch.xml"
SEK1_FREMDSPRACHE = FIXTURES / "sek1_fremdsprache.xml"
PRIM_DEUTSCH = FIXTURES / "prim_deutsch.xml"
PRIM_MATHEMATIK = FIXTURES / "prim_mathematik.xml"
PRIM_SACHUNTERRICHT = FIXTURES / "prim_sachunterricht.xml"

RESOURCES = Path(__file__).resolve().parents[1] / "resources"
MS_LIVE = RESOURCES / "mittelschule/NOR40271471.xml"
VS_LIVE = RESOURCES / "volksschule/NOR40271469.xml"

#: Tolerant pattern for the combined single-heading form used by SEK1.D/E and
#: all three primary subjects (V-24): "Kompetenzbeschreibungen [und
#: Anwendungsbereiche], Lehrstoff (...):" -- unlike SEK1.M, which has two
#: separate top-level sections (see SEK1_MATHEMATIK.kompetenz_sektion_re).
KOMBINIERTE_SEKTION_RE = re.compile(
    r"^Kompetenzbeschreibungen(?:\s+und\s+Anwendungsbereiche)?,\s*Lehrstoff\s*\("
)


def parse(path: Path) -> P.ParseResult:
    return P.parse_lehrplan(path, P.SEK1_MATHEMATIK)


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------


class TestTextExtraction(unittest.TestCase):
    def test_bullet_symbol_is_dropped(self):
        for stellen, glyph in (("1", "–"), ("2", "– "), ("1", "-")):
            with self.subTest(stellen=stellen, glyph=glyph):
                el = ET.fromstring(
                    '<listelem xmlns="http://www.bka.gv.at">'
                    f'<symbol stellen="{stellen}">{glyph}</symbol>Text der Kompetenz.</listelem>'
                )
                self.assertEqual(P.element_text(el).text, "Text der Kompetenz.")

    def test_real_symbol_text_and_its_tail_are_retained_in_order(self):
        # Unlike the presentation-only list bullet, ``stellen=3`` carries a
        # source word. RIS omits literal XML whitespace at this run boundary;
        # extraction restores the lexical boundary without reflowing prose.
        el = ET.fromstring(
            '<listelem xmlns="http://www.bka.gv.at">'
            '<symbol stellen="3">Die</symbol>Schülerinnen und Schüler können</listelem>'
        )
        ex = P.element_text(el)
        self.assertEqual(ex.text, "Die Schülerinnen und Schüler können")
        self.assertEqual(ex.roh, "Die Schülerinnen und Schüler können")
        label = ET.fromstring(
            '<listelem xmlns="http://www.bka.gv.at">'
            '<symbol stellen="3">1)</symbol>Eintrag</listelem>'
        )
        self.assertEqual(P.element_text(label).text, "1)Eintrag")
        mislabeled_word = ET.fromstring(
            '<listelem xmlns="http://www.bka.gv.at">'
            '<symbol stellen="1">Die</symbol>Schülerinnen und Schüler können</listelem>'
        )
        self.assertEqual(
            P.element_text(mislabeled_word).text,
            "Die Schülerinnen und Schüler können",
        )

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

    def test_slugify_bereich_never_mints_the_reserved_art_literals(self):
        """Guard against inventing an area code that collides with the
        reserved Art literals 'AB' or 'DT'. These are reserved to keep the
        7-segment competence ID and the 7-segment area-free application-item
        ID grammars unambiguous by construction (see id_schema.py). A
        pathological area name that folds to exactly 'AB' or 'DT' must be
        disambiguated."""
        # Test the exact pathological names that would fold to AB/DT.
        self.assertEqual(P.slugify_bereich("AB"), "ABX")
        self.assertEqual(P.slugify_bereich("DT"), "DTX")
        # Test synthetic names that include only ASCII letters that would
        # produce these exact outputs.
        self.assertEqual(P.slugify_bereich("A B"), "ABX")
        self.assertEqual(P.slugify_bereich("D T"), "DTX")
        # Non-pathological cases stay unchanged.
        self.assertEqual(P.slugify_bereich("ABC"), "ABC")
        self.assertEqual(P.slugify_bereich("DTX"), "DTX")
        self.assertEqual(P.slugify_bereich("Arbeitsblätter"), "ARBEITSBLATT")  # Ends at 12-char limit


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

    def test_application_items_resolve_markers_after_the_legend_is_read(self):
        xml = """<risdok xmlns="http://www.bka.gv.at"><nutzdaten><abschnitt>
          <ueberschrift typ="g1">ACHTER TEIL</ueberschrift>
          <ueberschrift typ="g1">MATHEMATIK</ueberschrift>
          <ueberschrift typ="erll">Kompetenzbereiche (1. bis 4. Klasse):</ueberschrift>
          <absatz typ="erltext">1. Klasse:</absatz>
          <ueberschrift typ="erll">Kompetenzbereich 1: Zahlen und Maße</ueberschrift>
          <absatz typ="abs">Die Schülerinnen und Schüler können</absatz>
          <liste><aufzaehlung><listelem>eine Kompetenz.</listelem></aufzaehlung></liste>
          <ueberschrift typ="erll">Anwendungsbereiche (1. bis 4. Klasse):</ueberschrift>
          <absatz typ="erltext">1. Klasse:</absatz>
          <absatz typ="abs">Kompetenzbereich 1: Zahlen und Maße</absatz>
          <absatz typ="abs">Die Schülerinnen und Schüler können eine Kompetenz.</absatz>
          <liste><aufzaehlung><listelem>Anwendungsinhalt;<super>4, 99</super></listelem></aufzaehlung></liste>
          <table><tr><td><absatz typ="tabtext"><super>4</super>Informatische Bildung</absatz></td></tr></table>
        </abschnitt></nutzdaten></risdok>"""
        result = P.LehrplanParser(P.SEK1_MATHEMATIK).parse_root(ET.fromstring(xml))
        item = result.anwendungsitems[0]
        self.assertEqual(item.text, "Anwendungsinhalt;")
        self.assertEqual(item.text_roh, "Anwendungsinhalt;4, 99")
        self.assertEqual(item.themen_marker_roh, ["4, 99"])
        self.assertEqual(item.uebergreifende_themen, ["Informatische Bildung"])
        self.assertEqual(item.fussnoten_unaufgeloest, ["99"])
        serialised = P.result_to_dict(result)["anwendungsitems"][0]
        self.assertEqual(
            {
                name: serialised[name]
                for name in (
                    "uebergreifende_themen",
                    "themen_marker_roh",
                    "fussnoten_unaufgeloest",
                )
            },
            {
                "uebergreifende_themen": ["Informatische Bildung"],
                "themen_marker_roh": ["4, 99"],
                "fussnoten_unaufgeloest": ["99"],
            },
        )


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
# Containment attachment (bindung 'bereich' | 'stufe' | 'prosa' | 'keine')
# ---------------------------------------------------------------------------
#
# Measured 2026-07-29 (notes/deviations.md): outside SEK1.M there is no
# text-repetition join -- application items attach to their container
# instead. containment_bindung_mini.xml carries one small synthetic subject
# per bindung value, each parsed here with its own throwaway SubjectSpec.
# These stay throwaway on purpose: they exercise the bindung axes against
# synthetic headings (BEREICHFACH, STUFEFACH, ...) that no real document
# contains. The five *real* subjects are registered in SUBJECT_SPECS as of
# E12-08, and TestNewSubjectFixtures below uses those shipped specs directly.


def _bindung_spec(fach_ueberschrift: str, bindung: str, **overrides) -> P.SubjectSpec:
    kwargs = dict(
        band="TEST",
        fach_code="X",
        fach_ueberschrift=fach_ueberschrift,
        teil_ueberschrift="ACHTER TEIL",
        stufen_praefix="K",
        kompetenz_sektion_re=KOMBINIERTE_SEKTION_RE,
        anwendung_sektion_re=None,
        bereich_re=re.compile(r"^(?:Integrativer\s+)?Kompetenzbereich\s+(?P<name>.+)$"),
        anwendungsbereiche_bindung=bindung,
    )
    kwargs.update(overrides)
    return P.SubjectSpec(**kwargs)


BEREICHFACH = _bindung_spec("BEREICHFACH", "bereich")
STUFEFACH = _bindung_spec("STUFEFACH", "stufe", stufen_praefix="SCH")
PROSAFACH = _bindung_spec("PROSAFACH", "prosa")
KEINEFACH = _bindung_spec("KEINEFACH", "keine")
LPZFACH = _bindung_spec("LPZFACH", "bereich")


def parse_bindung(spec: P.SubjectSpec) -> P.ParseResult:
    return P.parse_lehrplan(BINDUNG_MINI, spec)


class TestBindungBereich(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = parse_bindung(BEREICHFACH)

    def test_two_areas_one_competence(self):
        # Zweitbereich has no competence list of its own -- the structural
        # mirror of SEK1.D's 'Integrativer Kompetenzbereich Sprachbewusstsein
        # und Sprachreflexion'.
        self.assertEqual(len(self.r.bereiche), 2)
        self.assertEqual(len(self.r.kompetenzen), 1)

    def test_one_ab_block_per_area_including_the_one_without_competences(self):
        self.assertEqual(len(self.r.bloecke), 2)
        self.assertEqual(len(self.r.anwendungsitems), 2)
        namen = sorted(b.bereich_name for b in self.r.bloecke)
        self.assertEqual(namen, ["Erstbereich", "Zweitbereich"])

    def test_zweitbereich_block_is_not_misbound_to_erstbereich(self):
        block = next(b for b in self.r.bloecke if b.bereich_name == "Zweitbereich")
        self.assertEqual(
            [i.text for i in block.items],
            ["Anwendungsitem zu Zweitbereich ohne eigene Kompetenzen."],
        )
        self.assertEqual(self.r.issues.by_art("ab_block_ohne_bereich"), [])

    def test_no_kompetenz_id_is_synthesised(self):
        # Non-negotiable per notes/deviations.md (2026-07-29): the regulation
        # makes no per-competence link for bindung='bereich'.
        for item in self.r.anwendungsitems:
            self.assertIsNone(item.kompetenz_id)
            self.assertIsNone(item.join_methode)

    def test_ids_carry_the_ab_segment_and_are_unique(self):
        ids = [i.id for i in self.r.anwendungsitems] + [k.id for k in self.r.kompetenzen]
        self.assertEqual(len(ids), len(set(ids)))
        for i in self.r.anwendungsitems:
            self.assertIn(".AB.", i.id)

    def test_join_stats_are_not_run(self):
        # join_anwendungen is a no-op for non-'kompetenz' bindung.
        s = self.r.join_stats
        self.assertEqual(s["exact"], 0)
        self.assertEqual(s["fuzzy"], 0)
        self.assertEqual(s["positional"], 0)
        self.assertEqual(s["unmatched"], 0)

    def test_legend_table_terminates_the_subject(self):
        self.assertEqual(self.r.themen_map, {"1": "Thema Eins"})


class TestBindungStufe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = parse_bindung(STUFEFACH)

    def test_areas_and_competences(self):
        self.assertEqual(len(self.r.bereiche), 2)
        self.assertEqual(len(self.r.kompetenzen), 4)

    def test_one_block_per_school_year_not_per_area(self):
        # Beta is the last area of each year -- the block must attach to the
        # stufe, never to Beta.
        self.assertEqual(len(self.r.bloecke), 2)
        self.assertEqual(sorted(b.stufe for b in self.r.bloecke), ["SCH1", "SCH2"])
        for b in self.r.bloecke:
            self.assertIsNone(b.bereich_nummer)
            self.assertEqual(b.bereich_name, "")

    def test_items_are_not_attached_to_the_last_area(self):
        for item in self.r.anwendungsitems:
            self.assertIsNone(item.bereich_nummer)
            self.assertEqual(item.bereich_name, "")
            self.assertIsNone(item.kompetenz_id)

    def test_item_counts_per_year(self):
        self.assertEqual(
            sorted(i.text for i in self.r.anwendungsitems if i.stufe == "SCH1"),
            ["Jahresthema eins.", "Jahresthema zwei."],
        )
        self.assertEqual(
            [i.text for i in self.r.anwendungsitems if i.stufe == "SCH2"],
            ["Jahresthema Jahr 2."],
        )

    def test_block_count_consistency_check_does_not_fire(self):
        # Exactly one block per stufe here -- the discriminator assertion
        # must stay silent.
        self.assertEqual(self.r.issues.by_art("ab_block_anzahl_unerwartet"), [])


class TestProgressionBucketsOnAreaSlug(unittest.TestCase):
    """V-59 / E12-04: link_wiederholungen must bucket on bereich_slug, not
    bereich_nummer. STUFEFACH's Alpha and Beta are both unnumbered
    (bereich_nummer is None for every competence, exactly the shape of five
    of the six real subjects) -- before the fix, both areas fell into the
    same (stufe, None) bucket and progression fanned out across them."""

    @classmethod
    def setUpClass(cls):
        cls.r = parse_bindung(STUFEFACH)

    def test_both_areas_are_unnumbered(self):
        # The bug precondition: bucketing on bereich_nummer alone cannot
        # distinguish Alpha from Beta here.
        self.assertTrue(all(k.bereich_nummer is None for k in self.r.kompetenzen))

    def test_bucketing_key_is_the_slug_not_the_number(self):
        alpha = next(k for k in self.r.kompetenzen if k.bereich_name == "Alpha")
        beta = next(k for k in self.r.kompetenzen if k.bereich_name == "Beta")
        self.assertIsNone(alpha.bereich_nummer)
        self.assertIsNone(beta.bereich_nummer)
        self.assertNotEqual(alpha.bereich_slug, beta.bereich_slug)

    def test_progression_never_crosses_an_area_boundary(self):
        alpha1 = next(k for k in self.r.kompetenzen if k.stufe == "SCH1" and k.bereich_name == "Alpha")
        alpha2 = next(k for k in self.r.kompetenzen if k.stufe == "SCH2" and k.bereich_name == "Alpha")
        beta1 = next(k for k in self.r.kompetenzen if k.stufe == "SCH1" and k.bereich_name == "Beta")
        beta2 = next(k for k in self.r.kompetenzen if k.stufe == "SCH2" and k.bereich_name == "Beta")

        self.assertEqual(alpha2.vorlaeufer, [alpha1.id])
        self.assertEqual(alpha1.folge, [alpha2.id])
        self.assertEqual(beta2.vorlaeufer, [beta1.id])
        self.assertEqual(beta1.folge, [beta2.id])

        # Neither area's progression ever names a competence from the other.
        self.assertNotIn(beta1.id, alpha2.vorlaeufer)
        self.assertNotIn(alpha1.id, beta2.vorlaeufer)


class TestBindungStufeInconsistency(unittest.TestCase):
    def test_more_than_one_block_per_stufe_is_logged_not_silent(self):
        # Deliberately malformed: two AB-BLOCKs land under the same stufe.
        # Not a live shape -- exercises the discriminator assertion itself.
        xml = """<risdok xmlns="http://www.bka.gv.at"><nutzdaten><abschnitt>
          <ueberschrift typ="g1">ACHTER TEIL</ueberschrift>
          <ueberschrift typ="g1">DOPPELTFACH</ueberschrift>
          <ueberschrift typ="erll">Kompetenzbeschreibungen und Anwendungsbereiche, Lehrstoff (1. Schulstufe):</ueberschrift>
          <ueberschrift typ="erll">1. Schulstufe:</ueberschrift>
          <ueberschrift typ="erll">Kompetenzbereich Alpha</ueberschrift>
          <absatz typ="abs">Die Schülerinnen und Schüler können</absatz>
          <liste><aufzaehlung><listelem><symbol stellen="1">-</symbol>Alpha.</listelem></aufzaehlung></liste>
          <absatz typ="abs">Anwendungsbereiche</absatz>
          <liste><aufzaehlung><listelem><symbol stellen="1">-</symbol>erstes Jahresthema.</listelem></aufzaehlung></liste>
          <ueberschrift typ="erll">Kompetenzbereich Beta</ueberschrift>
          <absatz typ="abs">Die Schülerinnen und Schüler können</absatz>
          <liste><aufzaehlung><listelem><symbol stellen="1">-</symbol>Beta.</listelem></aufzaehlung></liste>
          <absatz typ="abs">Anwendungsbereiche</absatz>
          <liste><aufzaehlung><listelem><symbol stellen="1">-</symbol>zweites Jahresthema.</listelem></aufzaehlung></liste>
        </abschnitt></nutzdaten></risdok>"""
        spec = _bindung_spec("DOPPELTFACH", "stufe", stufen_praefix="SCH")
        r = P.LehrplanParser(spec).parse_root(ET.fromstring(xml))
        self.assertEqual(len(r.bloecke), 2)
        self.assertEqual(len(r.issues.by_art("ab_block_anzahl_unerwartet")), 1)


class TestE1205AreaFreeItemIds(unittest.TestCase):
    """E12-05 / D3: 'ALLGEMEIN' must never appear in a minted ID again --
    bindung='stufe' items get the area-free 7-segment form instead. These
    two cases reuse the containment_bindung_mini.xml sections (STUFEFACH,
    BEREICHFACH) but override band/fach_code to a real six-shard pair
    (PRIM.D is genuinely 'stufe'-bound, SEK1.D genuinely 'bereich'-bound),
    so _make_id takes the id_schema-delegating path and every ID is checked
    against the real frozen grammar, not just hand-built and eyeballed."""

    def test_stufe_bindung_mints_the_area_free_seven_segment_form(self):
        spec = _bindung_spec(
            "STUFEFACH", "stufe",
            band="PRIM", fach_code="D", stufen_praefix="SCH",
        )
        r = P.parse_lehrplan(BINDUNG_MINI, spec)
        self.assertEqual(len(r.anwendungsitems), 3)  # 2 (SCH1) + 1 (SCH2)
        for item in r.anwendungsitems:
            self.assertNotIn("ALLGEMEIN", item.id)
            self.assertEqual(len(item.id.split(".")), 7)
            parsed = ID.parse_id(item.id)
            self.assertIsInstance(parsed, ID.AnwendungsitemId)
            self.assertIsNone(parsed.bereich)
            self.assertEqual(parsed.art, "AB")
        # The record's own bereich_slug (E12-04 progression-bucketing field)
        # keeps carrying the "ALLGEMEIN" sentinel -- E12-05 only touches the
        # minted ID, never this field.
        self.assertTrue(all(i.bereich_slug == "ALLGEMEIN" for i in r.anwendungsitems))
        # Competences are unaffected: still the area-bearing 7-segment form.
        for k in r.kompetenzen:
            self.assertNotIn("ALLGEMEIN", k.id)
            parsed = ID.parse_id(k.id)
            self.assertIsInstance(parsed, ID.KompetenzId)

    def test_bereich_bindung_still_mints_the_area_bearing_eight_segment_form(self):
        spec = _bindung_spec(
            "BEREICHFACH", "bereich",
            band="SEK1", fach_code="D", stufen_praefix="K",
        )
        r = P.parse_lehrplan(BINDUNG_MINI, spec)
        self.assertEqual(len(r.anwendungsitems), 2)
        for item in r.anwendungsitems:
            self.assertNotIn("ALLGEMEIN", item.id)
            self.assertEqual(len(item.id.split(".")), 8)
            parsed = ID.parse_id(item.id)
            self.assertIsInstance(parsed, ID.AnwendungsitemId)
            self.assertIsNotNone(parsed.bereich)
            self.assertEqual(parsed.art, "AB")
        # Zweitbereich has no competence list of its own but still carries
        # its own area code in the item ID (the case the fixture exists for).
        zweit = next(i for i in r.anwendungsitems if i.bereich_name == "Zweitbereich")
        self.assertIn(".ZWEITBEREICH.", zweit.id)


class TestE1205SiteAUnreachableBecomesParseError(unittest.TestCase):
    """E12-05 / D3: the second, kompetenz-path 'ALLGEMEIN' fallback
    (_emit_anwendungsitems, reachable only via bindung='kompetenz''s own
    SEKTION_ANWENDUNG heading -- see SubjectSpec.anwendung_sektion_re) is
    unreachable in every live document (confirmed by --verify and the full
    suite staying green), but is a genuine structural anomaly if it ever
    did fire: an application item with no preceding area heading. It must
    raise ParseError, not synthesise "ALLGEMEIN"."""

    def test_item_with_no_preceding_area_heading_raises(self):
        xml = """<risdok xmlns="http://www.bka.gv.at"><nutzdaten><abschnitt>
          <ueberschrift typ="g1">ACHTER TEIL</ueberschrift>
          <ueberschrift typ="g1">KOMPETENZFACH</ueberschrift>
          <ueberschrift typ="erll">Kompetenzbereiche (1. Klasse):</ueberschrift>
          <ueberschrift typ="erll">1. Klasse:</ueberschrift>
          <ueberschrift typ="erll">Kompetenzbereich Alpha</ueberschrift>
          <absatz typ="abs">Die Schülerinnen und Schüler können</absatz>
          <liste><aufzaehlung><listelem><symbol stellen="1">-</symbol>Alpha.</listelem></aufzaehlung></liste>
          <ueberschrift typ="erll">Anwendungsbereiche (1. Klasse):</ueberschrift>
          <ueberschrift typ="erll">1. Klasse:</ueberschrift>
          <absatz typ="abs">Die Schülerinnen und Schüler können rechnen.</absatz>
          <liste><aufzaehlung><listelem><symbol stellen="1">-</symbol>Item ohne Bereich.</listelem></aufzaehlung></liste>
        </abschnitt></nutzdaten></risdok>"""
        spec = _bindung_spec(
            "KOMPETENZFACH", "kompetenz",
            kompetenz_sektion_re=re.compile(r"^Kompetenzbereiche\s*\("),
            anwendung_sektion_re=re.compile(r"^Anwendungsbereiche\s*\("),
        )
        with self.assertRaises(P.ParseError):
            P.LehrplanParser(spec).parse_root(ET.fromstring(xml))


class TestBindungProsa(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = parse_bindung(PROSAFACH)

    def test_zero_items_is_correct_not_a_failure(self):
        self.assertEqual(len(self.r.anwendungsitems), 0)
        self.assertEqual(len(self.r.kompetenzen), 1)

    def test_no_phantom_block_is_created(self):
        # Measured shape (SEK1.E): 0 blocks, not a zero-item block.
        self.assertEqual(len(self.r.bloecke), 0)

    def test_section_existence_is_recorded_in_the_issue_log(self):
        issues = self.r.issues.by_art("anwendungsbereiche_prosa")
        self.assertEqual(len(issues), 1)


class TestBindungKeine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = parse_bindung(KEINEFACH)

    def test_no_anwendungsbereiche_at_all(self):
        self.assertEqual(len(self.r.kompetenzen), 1)
        self.assertEqual(len(self.r.anwendungsitems), 0)
        self.assertEqual(len(self.r.bloecke), 0)

    def test_legend_table_still_terminates_the_subject(self):
        # The terminator does not depend on an AB block having existed.
        self.assertEqual(self.r.themen_map, {"1": "Thema Eins"})


class TestLehrplanzusatzTerminator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = parse_bindung(LPZFACH)

    def test_subject_ends_at_the_lehrplanzusatz_heading(self):
        # No legend table in this subject -- only the belt-and-braces
        # LEHRPLANZUSATZ terminator can end it.
        self.assertEqual(len(self.r.kompetenzen), 1)
        self.assertEqual(len(self.r.anwendungsitems), 1)
        self.assertEqual(len(self.r.bloecke), 1)

    def test_content_after_the_terminator_is_never_reached(self):
        # The re-used 'Kompetenzbereich Epsilon' heading inside the
        # Lehrplanzusatz would collide if it were parsed under the same
        # subject -- proving it never is.
        texte = [k.text for k in self.r.kompetenzen] + [
            i.text for i in self.r.anwendungsitems
        ]
        self.assertNotIn("sollte nie gezählt werden, gehört zum Lehrplanzusatz.", texte)


class TestBereichAusAbsatzFlag(unittest.TestCase):
    """P1: bereich_aus_absatz defaults to False; only SEK1.M sets it True.

    With it off, an absatz/@typ="abs" can never be classified as an area
    heading, so the 11 known prose false positives (e.g. "In allen vier
    Kompetenzbereichen wird das Zielniveau A1/A2 angestrebt") are impossible
    by construction rather than suppressed by a state guard.
    """

    def test_absatz_form_area_heading_is_not_recognised_without_the_flag(self):
        spec = P.SubjectSpec(
            band="TEST",
            fach_code="X",
            fach_ueberschrift="PROSATEST",
            stufen_praefix="K",
            kompetenz_sektion_re=P.SEK1_MATHEMATIK.kompetenz_sektion_re,
            anwendung_sektion_re=P.SEK1_MATHEMATIK.anwendung_sektion_re,
            # bereich_aus_absatz left at its default (False).
        )
        parser = P.LehrplanParser(spec)
        parser.state = P.State.ANWENDUNGSBEREICHE
        el = ET.fromstring(
            '<absatz typ="abs" xmlns="http://www.bka.gv.at">'
            "Kompetenzbereich 1: Zahlen und Maße</absatz>"
        )
        ev = parser._classify(0, el)
        self.assertIsNot(ev.token, P.Token.BEREICH)

    def test_sek1_mathematik_sets_the_flag(self):
        self.assertTrue(P.SEK1_MATHEMATIK.bereich_aus_absatz)

    def test_default_is_false(self):
        self.assertFalse(BEREICHFACH.bereich_aus_absatz)


class TestAllenfallsPruefenFlag(unittest.TestCase):
    """P1: allenfalls_pruefen defaults to False; only SEK1.M sets it True."""

    def test_allenfalls_text_stays_verbindlich_without_the_flag(self):
        # The fixture itself has no 'allenfalls' occurrence at all (measured:
        # zero outside SEK1.M) -- check the exact helper the parser uses to
        # decide 'verbindlich' for every non-kompetenz-bindung item.
        parser = P.LehrplanParser(BEREICHFACH)
        self.assertTrue(parser._verbindlich("allenfalls etwas nicht verbindliches."))

    def test_sek1_mathematik_sets_the_flag(self):
        self.assertTrue(P.SEK1_MATHEMATIK.allenfalls_pruefen)

    def test_default_is_false(self):
        self.assertFalse(BEREICHFACH.allenfalls_pruefen)


# ---------------------------------------------------------------------------
# E12-06 / V-58: Kompetenz.stammsatz -- the stem paragraph, verbatim
# ---------------------------------------------------------------------------


class TestStammsatz(unittest.TestCase):
    """The competence stem paragraph is captured verbatim on every Kompetenz,
    for every subject -- not a SEK1.E-only patch (notes/deviations.md,
    2026-07-30 row). 'text'/'text_roh' never gain the stem; a faithful
    quotation is 'stammsatz' + 'text'."""

    def test_bare_stem_is_captured_verbatim(self):
        # BEREICHFACH (containment_bindung_mini.xml) uses the plain,
        # five-subject form.
        r = parse_bindung(BEREICHFACH)
        erste = next(k for k in r.kompetenzen if k.text == "erste Kompetenz.")
        self.assertEqual(erste.stammsatz, "Die Schülerinnen und Schüler können")

    def test_qualified_sek1e_style_stem_is_captured_verbatim(self):
        # The real trailing-comma form measured in NOR40271471 (FINDINGS.md
        # V-58, child 655) -- quoted here, not paraphrased.
        xml = """<risdok xmlns="http://www.bka.gv.at"><nutzdaten><abschnitt>
          <ueberschrift typ="g1">ACHTER TEIL</ueberschrift>
          <ueberschrift typ="g1">FREMDSPRACHENFACH</ueberschrift>
          <ueberschrift typ="erll">Kompetenzbeschreibungen und Anwendungsbereiche, Lehrstoff (1. Klasse):</ueberschrift>
          <absatz typ="erltext">1. Klasse:</absatz>
          <ueberschrift typ="erll">Kompetenzbereich Hoeren</ueberschrift>
          <absatz typ="abs">Die Schülerinnen und Schüler können, wenn sehr langsam, klar und deutlich in Standardsprache gesprochen wird,</absatz>
          <liste><aufzaehlung><listelem><symbol stellen="1">-</symbol>einzelne vertraute Wörter und ganz einfache Sätze verstehen.</listelem></aufzaehlung></liste>
        </abschnitt></nutzdaten></risdok>"""
        spec = _bindung_spec("FREMDSPRACHENFACH", "prosa")
        r = P.LehrplanParser(spec).parse_root(ET.fromstring(xml))
        self.assertEqual(len(r.kompetenzen), 1)
        self.assertEqual(
            r.kompetenzen[0].stammsatz,
            "Die Schülerinnen und Schüler können, wenn sehr langsam, klar und "
            "deutlich in Standardsprache gesprochen wird,",
        )
        # The stem is never folded into 'text'/'text_roh' (rejected
        # alternative in the 2026-07-30 deviations.md decision row).
        self.assertEqual(
            r.kompetenzen[0].text,
            "einzelne vertraute Wörter und ganz einfache Sätze verstehen.",
        )

    def test_stem_does_not_leak_across_a_stufe_boundary(self):
        # Same area name recurs in the second Klasse, this time with no stem
        # paragraph of its own -- a stale stem from the first Klasse must
        # not silently attach to it.
        xml = """<risdok xmlns="http://www.bka.gv.at"><nutzdaten><abschnitt>
          <ueberschrift typ="g1">ACHTER TEIL</ueberschrift>
          <ueberschrift typ="g1">GRENZFACH</ueberschrift>
          <ueberschrift typ="erll">Kompetenzbeschreibungen und Anwendungsbereiche, Lehrstoff (1. bis 2. Klasse):</ueberschrift>
          <absatz typ="erltext">1. Klasse:</absatz>
          <ueberschrift typ="erll">Kompetenzbereich Hoeren</ueberschrift>
          <absatz typ="abs">Die Schülerinnen und Schüler können, wenn sehr langsam, klar und deutlich in Standardsprache gesprochen wird,</absatz>
          <liste><aufzaehlung><listelem><symbol stellen="1">-</symbol>Woerter Jahr 1 verstehen.</listelem></aufzaehlung></liste>
          <absatz typ="erltext">2. Klasse:</absatz>
          <ueberschrift typ="erll">Kompetenzbereich Hoeren</ueberschrift>
          <liste><aufzaehlung><listelem><symbol stellen="1">-</symbol>Woerter Jahr 2 verstehen.</listelem></aufzaehlung></liste>
        </abschnitt></nutzdaten></risdok>"""
        spec = _bindung_spec("GRENZFACH", "prosa")
        r = P.LehrplanParser(spec).parse_root(ET.fromstring(xml))
        self.assertEqual(len(r.kompetenzen), 2)
        jahr1 = next(k for k in r.kompetenzen if k.text == "Woerter Jahr 1 verstehen.")
        jahr2 = next(k for k in r.kompetenzen if k.text == "Woerter Jahr 2 verstehen.")
        self.assertTrue(jahr1.stammsatz.startswith("Die Schülerinnen und Schüler können, wenn"))
        # Not the leaked Jahr-1 stem, and not silently invented -- empty,
        # with the gap logged.
        self.assertEqual(jahr2.stammsatz, "")
        self.assertEqual(len(r.issues.by_art("kompetenz_ohne_stammsatz")), 1)

    def test_stem_does_not_leak_across_a_bereich_boundary(self):
        # Second area, same Klasse, no stem of its own -- the first area's
        # stem must not attach to it either.
        xml = """<risdok xmlns="http://www.bka.gv.at"><nutzdaten><abschnitt>
          <ueberschrift typ="g1">ACHTER TEIL</ueberschrift>
          <ueberschrift typ="g1">GRENZFACH2</ueberschrift>
          <ueberschrift typ="erll">Kompetenzbeschreibungen und Anwendungsbereiche, Lehrstoff (1. Klasse):</ueberschrift>
          <absatz typ="erltext">1. Klasse:</absatz>
          <ueberschrift typ="erll">Kompetenzbereich Hoeren</ueberschrift>
          <absatz typ="abs">Die Schülerinnen und Schüler können, wenn sehr langsam, klar und deutlich in Standardsprache gesprochen wird,</absatz>
          <liste><aufzaehlung><listelem><symbol stellen="1">-</symbol>Hoeren-Kompetenz.</listelem></aufzaehlung></liste>
          <ueberschrift typ="erll">Kompetenzbereich Sehen</ueberschrift>
          <liste><aufzaehlung><listelem><symbol stellen="1">-</symbol>Sehen-Kompetenz.</listelem></aufzaehlung></liste>
        </abschnitt></nutzdaten></risdok>"""
        spec = _bindung_spec("GRENZFACH2", "prosa")
        r = P.LehrplanParser(spec).parse_root(ET.fromstring(xml))
        self.assertEqual(len(r.kompetenzen), 2)
        hoeren = next(k for k in r.kompetenzen if k.text == "Hoeren-Kompetenz.")
        sehen = next(k for k in r.kompetenzen if k.text == "Sehen-Kompetenz.")
        self.assertTrue(hoeren.stammsatz.startswith("Die Schülerinnen und Schüler können, wenn"))
        self.assertEqual(sehen.stammsatz, "")
        self.assertEqual(len(r.issues.by_art("kompetenz_ohne_stammsatz")), 1)

    def test_bare_stem_in_a_nonfirst_list_item_governs_later_items(self):
        # The known V-69 occurrence is first, but list-item stem recognition
        # is semantic: it must not depend on a child index or list position.
        # The preceding item correctly remains stemless; the restored stem
        # governs only source-order entries that follow it.
        xml = """<risdok xmlns="http://www.bka.gv.at"><nutzdaten><abschnitt>
          <ueberschrift typ="g1">ACHTER TEIL</ueberschrift>
          <ueberschrift typ="g1">LISTENFACH</ueberschrift>
          <ueberschrift typ="erll">Kompetenzbeschreibungen und Anwendungsbereiche, Lehrstoff (1. Klasse):</ueberschrift>
          <absatz typ="erltext">1. Klasse:</absatz>
          <ueberschrift typ="erll">Kompetenzbereich Hoeren</ueberschrift>
          <liste><aufzaehlung>
            <listelem>Kompetenz vor dem Stamm.</listelem>
            <listelem><symbol stellen="3">Die</symbol>Schülerinnen und Schüler können</listelem>
            <listelem>Kompetenz nach dem Stamm.</listelem>
          </aufzaehlung></liste>
        </abschnitt></nutzdaten></risdok>"""
        r = P.LehrplanParser(_bindung_spec("LISTENFACH", "prosa")).parse_root(ET.fromstring(xml))
        self.assertEqual([k.text for k in r.kompetenzen], [
            "Kompetenz vor dem Stamm.",
            "Kompetenz nach dem Stamm.",
        ])
        self.assertEqual(r.kompetenzen[0].stammsatz, "")
        self.assertEqual(r.kompetenzen[1].stammsatz, "Die Schülerinnen und Schüler können")
        self.assertEqual(len(r.issues.by_art("kompetenz_ohne_stammsatz")), 1)

    def test_gz_integrativ_stem_is_also_captured(self):
        # _kompetenz_gz_integrativ used to drop the stem too (its own
        # docstring called it "ignored, same as in KOMPETENZBEREICHE") --
        # SEK1.M's 2 promoted GZ competences must carry a stammsatz like
        # every other competence, not be the only ones without one.
        r = P.parse_lehrplan(ECHT, P.SEK1_MATHEMATIK)
        gz = [k for k in r.kompetenzen if k.bereich_slug == P.GZ_INTEGRATIV_BEREICH_SLUG]
        self.assertEqual(len(gz), 2)
        for k in gz:
            self.assertEqual(k.stammsatz, "Die Schülerinnen und Schüler können")


# ---------------------------------------------------------------------------
# E12-06 / V-68: an unmatched token must be logged, never silently dropped
# ---------------------------------------------------------------------------


class TestUnbehandelterToken(unittest.TestCase):
    """_kompetenzbereiche and _anwendungsbereiche now fall back to a logged
    ParseIssue for any token their explicit branches and ignore-set do not
    cover, instead of silently discarding it (the exact mechanism that made
    V-58 invisible). The events are constructed directly so the test does
    not depend on whether today's _classify happens to produce this
    token/state combination from real markup -- it tests the dispatch
    methods' own fallback contract."""

    @staticmethod
    def _ereignis(token):
        el = ET.fromstring('<absatz xmlns="http://www.bka.gv.at" typ="abs">Text</absatz>')
        return P.Ereignis(token, 0, el, P.element_text(el))

    def test_kompetenzbereiche_logs_an_unexpected_token(self):
        parser = P.LehrplanParser(BEREICHFACH)
        parser._reset()
        parser.state = P.State.KOMPETENZBEREICHE
        # DIGITALE_TECHNOLOGIEN has a branch only in _anwendungsbereiche;
        # it is not in _kompetenzbereiche's ignore set either.
        parser._kompetenzbereiche(self._ereignis(P.Token.DIGITALE_TECHNOLOGIEN))
        issues = parser.issues.by_art("unbehandeltes_token_kompetenzbereiche")
        self.assertEqual(len(issues), 1)
        self.assertIn("digitale_technologien", issues[0].nachricht)

    def test_anwendungsbereiche_logs_an_unexpected_token(self):
        parser = P.LehrplanParser(BEREICHFACH)
        parser._reset()
        parser.state = P.State.ANWENDUNGSBEREICHE
        # AB_BLOCK is only ever classified while in KOMPETENZBEREICHE (see
        # AB_BLOCK_RE's state guard in _classify) and has no branch in
        # _anwendungsbereiche.
        parser._anwendungsbereiche(self._ereignis(P.Token.AB_BLOCK))
        issues = parser.issues.by_art("unbehandeltes_token_anwendungsbereiche")
        self.assertEqual(len(issues), 1)
        self.assertIn("ab_block", issues[0].nachricht)

    def test_ignorable_tokens_are_not_logged(self):
        # TEXT/IGNORIEREN are the explicit, justified allow-list (ordinary
        # prose and non-interpreted element types) -- logging these would
        # be exactly the noise the design note warns against.
        parser = P.LehrplanParser(BEREICHFACH)
        parser._reset()
        parser.state = P.State.KOMPETENZBEREICHE
        parser._kompetenzbereiche(self._ereignis(P.Token.TEXT))
        parser._kompetenzbereiche(self._ereignis(P.Token.IGNORIEREN))
        parser.state = P.State.ANWENDUNGSBEREICHE
        parser._anwendungsbereiche(self._ereignis(P.Token.TEXT))
        parser._anwendungsbereiche(self._ereignis(P.Token.IGNORIEREN))
        self.assertEqual(len(parser.issues), 0)


# ---------------------------------------------------------------------------
# Live smoke test: PRIM.SU / SEK1.D reproduce the measured containment counts
# ---------------------------------------------------------------------------
#
# Proves P1+P2 actually work against the real source, not just the synthetic
# fixture above. These throwaway SubjectSpecs live in this test file only --
# adding the shipped SEK1.D/PRIM.SU specs is task P5.


@unittest.skipUnless(
    MS_LIVE.exists() and VS_LIVE.exists(),
    "data-pipeline/resources/ is gitignored and not available in this checkout",
)
class TestLiveContainmentSmoke(unittest.TestCase):
    def test_sek1_deutsch_matches_the_measured_counts(self):
        # SEK1.D has 4 areas / 40 competences / 16 AB blocks / 54 items,
        # bindung='bereich'.
        spec = _bindung_spec(
            "DEUTSCH",
            "bereich",
            band="SEK1",
            fach_code="D",
            teil_ueberschrift="ACHTER TEIL",
            stufen_praefix="K",
        )
        r = P.parse_lehrplan(MS_LIVE, spec)
        self.assertEqual(len(r.bereiche), 4)
        self.assertEqual(len(r.kompetenzen), 40)
        self.assertEqual(len(r.bloecke), 16)
        self.assertEqual(len(r.anwendungsitems), 54)
        self.assertTrue(all(i.kompetenz_id is None for i in r.anwendungsitems))
        alle_ids = [k.id for k in r.kompetenzen] + [i.id for i in r.anwendungsitems]
        self.assertEqual(len(alle_ids), len(set(alle_ids)))
        # The 'Integrativer Kompetenzbereich Sprachbewusstsein und
        # Sprachreflexion' area has an AB block but no competence list.
        namen = {b.bereich_name for b in r.bloecke}
        self.assertIn("Sprachbewusstsein und Sprachreflexion", namen)

    def test_prim_sachunterricht_matches_the_measured_counts(self):
        # notes/deviations.md, 2026-07-29: PRIM.SU 6 areas / 48 competences /
        # 4 AB blocks / 40 items, bindung='stufe'.
        spec = _bindung_spec(
            "SACHUNTERRICHT",
            "stufe",
            band="PRIM",
            fach_code="SU",
            teil_ueberschrift="NEUNTER TEIL",
            stufen_praefix="SCH",
            bereich_re=re.compile(r"^(?P<name>.+\bKompetenzbereich)$"),
        )
        r = P.parse_lehrplan(VS_LIVE, spec)
        self.assertEqual(len(r.bereiche), 6)
        self.assertEqual(len(r.kompetenzen), 48)
        self.assertEqual(len(r.bloecke), 4)
        self.assertEqual(len(r.anwendungsitems), 40)
        self.assertTrue(all(i.kompetenz_id is None for i in r.anwendungsitems))
        self.assertEqual(r.issues.by_art("ab_block_anzahl_unerwartet"), [])
        alle_ids = [k.id for k in r.kompetenzen] + [i.id for i in r.anwendungsitems]
        self.assertEqual(len(alle_ids), len(set(alle_ids)))


# ---------------------------------------------------------------------------
# P4: committed fixtures for the five subjects TestLiveContainmentSmoke above
# can only exercise when resources/ happens to be present. These run the same
# assertions -- and freeze the same measured counts (ERWARTET_SEK1_D etc. in
# parse_lehrplan.py) -- against tests/fixtures/sek1_deutsch.xml and friends,
# so the evidence survives a fresh clone / CI, where resources/ is gitignored
# and TestLiveContainmentSmoke skips. See notes/ris-xml-structure.md §12 for
# how each fixture was extracted (byte-exact span, expat CurrentByteIndex).
# ---------------------------------------------------------------------------


class TestNewSubjectFixtures(unittest.TestCase):
    """One method per subject: area/competence/AB-block/AB-item counts match
    ERWARTET_* exactly, kompetenz_id stays None throughout (none of these five
    subjects use bindung='kompetenz'), and no two IDs collide."""

    def _assert_no_kompetenz_id_and_no_collisions(self, r: P.ParseResult) -> None:
        self.assertTrue(all(i.kompetenz_id is None for i in r.anwendungsitems))
        self.assertTrue(all(i.join_methode is None for i in r.anwendungsitems))
        alle_ids = [k.id for k in r.kompetenzen] + [i.id for i in r.anwendungsitems]
        self.assertEqual(len(alle_ids), len(set(alle_ids)))

    def _assert_item_theme_counts(self, r: P.ParseResult, erwartet_markiert: int) -> None:
        """Freeze E12-07's item-theme counts on each containment fixture.

        These subjects emit through _emit_ab_items rather than SEK1.M's
        _emit_anwendungsitems path, so they need their own regression guard.
        """
        markiert = [i for i in r.anwendungsitems if i.themen_marker_roh]
        self.assertEqual(len(markiert), erwartet_markiert)
        self.assertEqual(sum(bool(i.uebergreifende_themen) for i in r.anwendungsitems), erwartet_markiert)
        self.assertEqual(sum(bool(i.fussnoten_unaufgeloest) for i in r.anwendungsitems), 0)
        self.assertTrue(all(i.themen_marker_roh for i in markiert))

    def test_sek1_deutsch(self):
        spec = P.SUBJECT_SPECS["SEK1.D"]
        r = P.parse_lehrplan(SEK1_DEUTSCH, spec)
        self.assertEqual(spec.anwendungsbereiche_bindung, "bereich")
        self.assertEqual(len(r.bereiche), 4)
        self.assertEqual(len(r.kompetenzen), 40)
        self.assertEqual(len(r.bloecke), 16)
        self.assertEqual(len(r.anwendungsitems), 54)
        self.assertEqual(P.actual_counts(r), P.ERWARTET_SEK1_D)
        self._assert_no_kompetenz_id_and_no_collisions(r)
        self._assert_item_theme_counts(r, 15)
        # The first Lesen list element is a fused stem carried by
        # ``<symbol stellen="3">Die</symbol>``. It must classify as a stem,
        # never as a spurious competence, so the real K2 entries start at .01.
        lesen_k2 = [
            k for k in r.kompetenzen
            if k.bereich_slug == "LESEN" and k.stufe == "K2"
        ]
        self.assertEqual([k.id.rsplit(".", 1)[-1] for k in lesen_k2], ["01", "02", "03"])
        self.assertTrue(all(k.stammsatz == "Die Schülerinnen und Schüler können" for k in lesen_k2))
        self.assertEqual(r.issues.by_art("kompetenz_ohne_stammsatz"), [])
        # This is the regression check for the LEHRPLANZUSATZ DEUTSCH ALS
        # ZWEITSPRACHE hazard (notes/deviations.md, 2026-07-28/29): the
        # fixture carries that appendix's *own* 'Kompetenzbereich Lesen' /
        # 'Kompetenzbereich Schreiben' headings (a second, distinct
        # curriculum reusing the same area names). If the legend-table /
        # LEHRPLANZUSATZ terminator ever regressed, the parser would keep
        # scanning into that appendix -- see the extensive verification in
        # the P4 task report (child-by-child trace + two isolated-module
        # monkeypatch experiments): with *only* the terminator removed the
        # 4 real areas silently balloon to 6 (spurious 'Hören'/'Sprechen'
        # entries minted from the appendix); with the terminator *and* the
        # SEKTION_KOMPETENZ stufe-reset both removed, parsing raises
        # ParseError on an actual 'AT.LP23.SEK1.D.LESEN.K4.01' ID collision.
        # Both regressions are caught by the plain assertions above (bereiche
        # == 4, not 6; no raised exception) without needing to reproduce the
        # monkeypatch here.
        namen = sorted(b.name for b in r.bereiche)
        self.assertEqual(
            namen,
            ["Lesen", "Schreiben", "Sprachbewusstsein und Sprachreflexion", "Zuhören und Sprechen"],
        )
        self.assertNotIn("Hören", namen)
        self.assertNotIn("Sprechen", namen)
        # The integrative area has an AB block but no competence list of its
        # own (mirrors GZINTEGRATIV; notes/deviations.md, 2026-07-28).
        block_namen = {b.bereich_name for b in r.bloecke}
        self.assertIn("Sprachbewusstsein und Sprachreflexion", block_namen)

    def test_sek1_fremdsprache(self):
        spec = P.SUBJECT_SPECS["SEK1.E"]
        r = P.parse_lehrplan(SEK1_FREMDSPRACHE, spec)
        self.assertEqual(spec.anwendungsbereiche_bindung, "prosa")
        self.assertEqual(len(r.bereiche), 4)
        self.assertEqual(len(r.kompetenzen), 37)
        self.assertEqual(len(r.bloecke), 0)
        self.assertEqual(len(r.anwendungsitems), 0)
        self.assertEqual(P.actual_counts(r), P.ERWARTET_SEK1_E)
        self._assert_no_kompetenz_id_and_no_collisions(r)
        # 'prosa' bindung: the heading is seen and logged, not silently
        # dropped -- zero blocks is correct, not a phantom empty one.
        self.assertEqual(len(r.issues.by_art("anwendungsbereiche_prosa")), 4)

    def test_prim_deutsch(self):
        spec = P.SUBJECT_SPECS["PRIM.D"]
        r = P.parse_lehrplan(PRIM_DEUTSCH, spec)
        self.assertEqual(spec.anwendungsbereiche_bindung, "stufe")
        self.assertEqual(len(r.bereiche), 4)
        self.assertEqual(len(r.kompetenzen), 40)
        self.assertEqual(len(r.bloecke), 4)
        self.assertEqual(len(r.anwendungsitems), 37)
        self.assertEqual(P.actual_counts(r), P.ERWARTET_PRIM_D)
        self._assert_no_kompetenz_id_and_no_collisions(r)
        self._assert_item_theme_counts(r, 11)
        # 'stufe' bindung: blocks attach to the school year only, never to
        # whichever area happened to precede them.
        for b in r.bloecke:
            self.assertIsNone(b.bereich_nummer)
            self.assertEqual(b.bereich_name, "")
        for item in r.anwendungsitems:
            self.assertIsNone(item.bereich_nummer)
            self.assertEqual(item.bereich_name, "")
        self.assertEqual(r.issues.by_art("ab_block_anzahl_unerwartet"), [])

    def test_prim_mathematik(self):
        spec = P.SUBJECT_SPECS["PRIM.M"]
        r = P.parse_lehrplan(PRIM_MATHEMATIK, spec)
        self.assertEqual(spec.anwendungsbereiche_bindung, "keine")
        self.assertEqual(len(r.bereiche), 4)
        self.assertEqual(len(r.kompetenzen), 40)
        self.assertEqual(len(r.bloecke), 0)
        self.assertEqual(len(r.anwendungsitems), 0)
        self.assertEqual(P.actual_counts(r), P.ERWARTET_PRIM_M)
        self._assert_no_kompetenz_id_and_no_collisions(r)

    def test_prim_sachunterricht(self):
        spec = P.SUBJECT_SPECS["PRIM.SU"]
        r = P.parse_lehrplan(PRIM_SACHUNTERRICHT, spec)
        self.assertEqual(spec.anwendungsbereiche_bindung, "stufe")
        self.assertEqual(len(r.bereiche), 6)
        self.assertEqual(len(r.kompetenzen), 48)
        self.assertEqual(len(r.bloecke), 4)
        self.assertEqual(len(r.anwendungsitems), 40)
        self.assertEqual(P.actual_counts(r), P.ERWARTET_PRIM_SU)
        self._assert_no_kompetenz_id_and_no_collisions(r)
        self._assert_item_theme_counts(r, 1)
        for b in r.bloecke:
            self.assertIsNone(b.bereich_nummer)
            self.assertEqual(b.bereich_name, "")
        self.assertEqual(r.issues.by_art("ab_block_anzahl_unerwartet"), [])

    def test_fixtures_do_not_require_resources(self):
        # The whole point of P4: these five paths resolve under tests/fixtures/
        # (committed), never under resources/ (gitignored).
        for path in (SEK1_DEUTSCH, SEK1_FREMDSPRACHE, PRIM_DEUTSCH, PRIM_MATHEMATIK, PRIM_SACHUNTERRICHT):
            with self.subTest(path=path.name):
                self.assertTrue(path.is_file())
                self.assertIn("fixtures", path.parts)
                self.assertNotIn("resources", path.parts)


# ---------------------------------------------------------------------------
# End-to-end counts
# ---------------------------------------------------------------------------


class TestShippedSpecRegistry(unittest.TestCase):
    """E12-08: all six specs registered, --verify wired, source band-aware."""

    def test_all_six_registered(self):
        self.assertEqual(
            sorted(P.SUBJECT_SPECS),
            ["PRIM.D", "PRIM.M", "PRIM.SU", "SEK1.D", "SEK1.E", "SEK1.M"],
        )

    def test_every_spec_has_expected_counts(self):
        # --verify must fail loudly rather than silently pass on an empty
        # table, so every registered spec needs an ERWARTET_BY_SPEC entry.
        self.assertEqual(set(P.ERWARTET_BY_SPEC), set(P.SUBJECT_SPECS))
        for schluessel, soll in P.ERWARTET_BY_SPEC.items():
            with self.subTest(spec=schluessel):
                self.assertTrue(soll, "empty expected-count table")

    def test_default_source_follows_the_band(self):
        # The CLI default must not stay pinned to the Mittelschule document:
        # three of the six subjects live in the Volksschule one.
        for schluessel, spec in P.SUBJECT_SPECS.items():
            with self.subTest(spec=schluessel):
                quelle = P.default_source(schluessel)
                erwartet = "mittelschule" if spec.band == "SEK1" else "volksschule"
                self.assertIn(erwartet, quelle.parts)

    def test_primary_and_lower_secondary_use_different_documents(self):
        self.assertNotEqual(P.default_source("SEK1.M"), P.default_source("PRIM.M"))


class TestResultToDictBreadth(unittest.TestCase):
    """E12-08: the serialisation carries blocks and the binding axis."""

    def test_binding_axis_in_meta(self):
        spec = P.SUBJECT_SPECS["PRIM.D"]
        d = P.result_to_dict(P.parse_lehrplan(PRIM_DEUTSCH, spec))
        self.assertEqual(d["meta"]["anwendungsbereiche_bindung"], "stufe")
        self.assertEqual(d["meta"]["anwendungsbereiche_status"], "optional_sektion")

    def test_blocks_are_emitted_with_item_ids_not_nested_bodies(self):
        spec = P.SUBJECT_SPECS["PRIM.D"]
        r = P.parse_lehrplan(PRIM_DEUTSCH, spec)
        d = P.result_to_dict(r)
        bloecke = d["anwendungsbereiche_bloecke"]
        self.assertEqual(len(bloecke), len(r.bloecke))
        self.assertEqual(len(bloecke), 4)
        # Membership is preserved as ids; the bodies live once, under
        # 'anwendungsitems'. Nesting them here would duplicate the whole
        # application payload in the parser's serialisation.
        flach = [i for b in bloecke for i in b["items"]]
        self.assertTrue(all(isinstance(i, str) for i in flach))
        self.assertEqual(sorted(flach), sorted(i["id"] for i in d["anwendungsitems"]))

    def test_serialisation_is_json_round_trippable_for_all_six(self):
        for schluessel, pfad in (
            ("SEK1.D", SEK1_DEUTSCH),
            ("SEK1.E", SEK1_FREMDSPRACHE),
            ("PRIM.D", PRIM_DEUTSCH),
            ("PRIM.M", PRIM_MATHEMATIK),
            ("PRIM.SU", PRIM_SACHUNTERRICHT),
        ):
            with self.subTest(spec=schluessel):
                spec = P.SUBJECT_SPECS[schluessel]
                d = P.result_to_dict(P.parse_lehrplan(pfad, spec))
                wieder = json.loads(json.dumps(d, ensure_ascii=False))
                self.assertEqual(
                    wieder["meta"]["anwendungsbereiche_bindung"],
                    spec.anwendungsbereiche_bindung,
                )


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
