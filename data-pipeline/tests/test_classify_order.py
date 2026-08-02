"""V-55 guard: the CHECK ORDER inside ``LehrplanParser._classify``'s
``ueberschrift/@typ="erll"`` branch is load-bearing (E12-15).

Run:  .venv/bin/python -m pytest data-pipeline/tests -q

Context (FINDINGS.md V-55, notes/deviations.md 2026-07-27 row):
``absatz/@typ="erltext"`` is the class-year/school-year marker in Sek I, but
in the primary document the *same* marker (``1. Schulstufe:``) is written as
``ueberschrift/@typ="erll"`` -- the identical element type used for area
headings, section headings and the subject's other in-text headings. Because
one element type now carries several different semantic tokens, ``_classify``
disambiguates them by trying a sequence of regexes in a fixed order and
returning on the first match. The deviations.md row's own words: "in primary
a level marker and an area heading share an element type, so the order of
checks in ``_classify`` is load-bearing."

Today's six frozen regexes happen not to overlap (measured below, with the
committed fixtures, in ``test_todays_regexes_never_overlap_on_real_headings``)
-- STUFE_RE requires the text to *start with a digit*, and every other check
in that branch requires a literal word prefix, so nothing in the current
six-shard scheme actually depends on evaluation order today. That is exactly
what makes the order fragile rather than manifestly broken: nothing forces a
future ``SubjectSpec.bereich_re`` (or ``kompetenz_sektion_re``/
``anwendung_sektion_re``) to stay disjoint from ``STUFE_RE``, and if one ever
overlaps, whichever check runs first silently wins. The tests below pin the
*documented* order (STUFE_RE decided before the area/section checks) as a
regression contract: they construct a deliberately permissive ``bereich_re``
("trap" spec, matches literally anything) and show that with today's
production order the level marker still classifies as ``Token.STUFE``, then
show -- using a hand-reproduced, order-swapped copy of the same branch -- that
swapping the two checks flips the classification to ``Token.BEREICH`` and,
followed through a full parse, silently drops the competence it introduces.

The counterfactual is proven twice, at two levels of the real code:

1. ``_classify``-level (``test_order_decides_the_winner_under_a_permissive_area_regex``)
   -- same trap spec, same input element, real bound method vs. the
   order-swapped reproduction; the returned ``Token`` differs.
2. Full-pipeline level (``test_swapped_order_silently_drops_the_competence_end_to_end``)
   -- ``LehrplanParser._classify`` is monkeypatched (temporarily, restored in
   a ``finally``) on the class itself and a tiny synthetic document is run
   through the real ``parse_root``; the competence count drops from 1 to 0
   and a real ``ParseIssue`` (``liste_ohne_kontext``) explains why.

Either test fails outright if a future edit reorders the two checks in
production without also updating this file's reproduction to match --that
divergence is a feature, not a maintenance cost: it is the moment this test
suite notices the order changed at all.
"""

from __future__ import annotations

import dataclasses
import logging
import re
import sys
import types
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_DATA_PIPELINE = _HERE.parent
sys.path.insert(0, str(_DATA_PIPELINE))
sys.path.insert(0, str(_DATA_PIPELINE / "schema"))

import parse_lehrplan as P  # noqa: E402

logging.getLogger("parse_lehrplan").setLevel(logging.CRITICAL)

FIXTURES = _HERE / "fixtures"
NS = "http://www.bka.gv.at"

#: All six committed fixtures with their real (production) SubjectSpec --
#: used only for the "today's regexes never overlap" grounding test.
ALLE_FIXTUREN = [
    ("SEK1.M", "sek1_mathematik.xml"),
    ("SEK1.D", "sek1_deutsch.xml"),
    ("SEK1.E", "sek1_fremdsprache.xml"),
    ("PRIM.D", "prim_deutsch.xml"),
    ("PRIM.M", "prim_mathematik.xml"),
    ("PRIM.SU", "prim_sachunterricht.xml"),
]


def _erll(text: str) -> ET.Element:
    """A bare ``ueberschrift/@typ="erll"`` element carrying *text*, matching
    the shape ``element_text`` reads (children are irrelevant here -- the
    real primary markup nests the marker in a ``<gs>`` letter-spacing
    child, but ``element_text`` flattens that away; a bare ``.text`` is an
    equivalent input for classification purposes)."""
    el = ET.Element(f"{{{NS}}}ueberschrift", {"typ": "erll"})
    el.text = text
    return el


def _classify_erll_swapped_token(spec: P.SubjectSpec, text: str) -> P.Token:
    """Standalone reproduction of *only* the decision reached inside
    ``_classify``'s ``ueberschrift/@typ="erll"`` branch (parse_lehrplan.py,
    read 2026-08-02, ~lines 980-1002), with **exactly one change**: the
    ``STUFE_RE`` check is moved from *before* the ``bereich_re`` check to
    *after* it. Every other check and its relative order is untouched.

    This function does not import or alter parse_lehrplan.py -- it exists
    purely to compute the counterfactual token for comparison against the
    real, unmodified ``LehrplanParser._classify``.
    """
    if P.LEHRPLANZUSATZ_RE.match(text):
        return P.Token.LEHRPLANZUSATZ
    if spec.kompetenz_sektion_re.search(text):
        return P.Token.SEKTION_KOMPETENZ
    if spec.anwendung_sektion_re and spec.anwendung_sektion_re.search(text):
        return P.Token.SEKTION_ANWENDUNG
    if P.GZ_INTEGRATIV_RE.match(text):
        return P.Token.SEKTION_GZ_INTEGRATIV
    # -- MOVED: bereich_re now decided before STUFE_RE (swapped). --
    if spec.bereich_re.match(text):
        return P.Token.BEREICH
    if P.STUFE_RE.match(text):
        return P.Token.STUFE
    return P.Token.ANDERE_UEBERSCHRIFT


def _classify_stufe_after_bereich(self, index: int, el: ET.Element) -> P.Ereignis:
    """Full drop-in replacement for ``LehrplanParser._classify``, used only
    via a temporary class-level monkeypatch. Verbatim copy of the production
    method (parse_lehrplan.py, read 2026-08-02) for every branch except the
    ``ueberschrift/@typ="erll"`` one, where the ``STUFE_RE`` check is moved
    to after the ``bereich_re`` check -- the identical, single change as
    :func:`_classify_erll_swapped_token` above, just as a full method so a
    real document can be parsed through it end to end.
    """
    name = P.localname(el)
    typ = el.get("typ")
    ex = P.element_text(el)
    text = ex.text

    if name == "ueberschrift":
        if typ in ("g1", "g1min"):
            return P.Ereignis(P.Token.FACH_UEBERSCHRIFT, index, el, ex)
        if typ == "erll":
            if P.LEHRPLANZUSATZ_RE.match(text):
                return P.Ereignis(P.Token.LEHRPLANZUSATZ, index, el, ex)
            if self.spec.kompetenz_sektion_re.search(text):
                return P.Ereignis(P.Token.SEKTION_KOMPETENZ, index, el, ex)
            if self.spec.anwendung_sektion_re and self.spec.anwendung_sektion_re.search(text):
                return P.Ereignis(P.Token.SEKTION_ANWENDUNG, index, el, ex)
            if P.GZ_INTEGRATIV_RE.match(text):
                return P.Ereignis(P.Token.SEKTION_GZ_INTEGRATIV, index, el, ex)
            # -- MOVED: bereich_re now decided before STUFE_RE (swapped). --
            m = self.spec.bereich_re.match(text)
            if m:
                return P.Ereignis(P.Token.BEREICH, index, el, ex, self._bereich_daten(m, text))
            m = P.STUFE_RE.match(text)
            if m:
                return P.Ereignis(
                    P.Token.STUFE, index, el, ex,
                    {"nr": int(m.group("nr")), "einheit": m.group("einheit")},
                )
            return P.Ereignis(P.Token.ANDERE_UEBERSCHRIFT, index, el, ex)
        return P.Ereignis(P.Token.IGNORIEREN, index, el, ex)

    # Every other element type is untouched by the swap -- delegate to the
    # real, original implementation so a full document still parses.
    return self._classify_original(index, el)


#: A deliberately permissive area-heading regex -- matches any text at all.
#: No shipped SubjectSpec uses anything this loose (see
#: test_todays_regexes_never_overlap_on_real_headings), but SubjectSpec.bereich_re
#: is a free-form, per-subject regex (six different shapes already exist --
#: AREA_NUMMERIERT_RE, AREA_UNNUMMERIERT_RE, AREA_SCHLICHT_RE, AREA_ADJEKTIV_RE),
#: so nothing in the type system stops a future one from being this loose.
_TRAP_BEREICH_RE = re.compile(r".*")

#: A minimal synthetic SubjectSpec, shaped like the five combined-heading
#: primary/SEK1.D-style subjects, with its bereich_re replaced by the trap.
_TRAP_SPEC = dataclasses.replace(P.PRIM_DEUTSCH, bereich_re=_TRAP_BEREICH_RE)

_STUFE_MARKER_TEXT = "1. Schulstufe:"


class TestOrderIsLoadBearing:
    """The counterfactual proof: identical input, identical spec, only the
    check order differs -- and the classification differs with it."""

    def test_production_order_prioritises_the_level_marker(self):
        """Control: today's real, unmodified ``_classify`` -- even fed the
        maximally permissive trap ``bereich_re`` -- still classifies a level
        marker as ``Token.STUFE``, because ``STUFE_RE`` is tried first."""
        parser = P.LehrplanParser(_TRAP_SPEC, abbildungen_registry={})
        ev = parser._classify(0, _erll(_STUFE_MARKER_TEXT))
        assert ev.token is P.Token.STUFE

    def test_order_decides_the_winner_under_a_permissive_area_regex(self):
        """The core order-sensitivity proof, at the ``_classify`` level.

        Same trap spec, same input text as the control above. The real,
        unmodified method returns STUFE (checked first); the order-swapped
        reproduction returns BEREICH (now checked first) -- diverging
        *only* because the two checks were reordered. If a maintainer ever
        swaps the two blocks in ``parse_lehrplan.py`` itself, this
        assertion (real classify == STUFE) starts failing, which is
        precisely the "fails for a real reason" bar this test exists to
        clear.
        """
        parser = P.LehrplanParser(_TRAP_SPEC, abbildungen_registry={})
        real_token = parser._classify(0, _erll(_STUFE_MARKER_TEXT)).token
        swapped_token = _classify_erll_swapped_token(_TRAP_SPEC, _STUFE_MARKER_TEXT)

        assert real_token is P.Token.STUFE
        assert swapped_token is P.Token.BEREICH
        assert real_token is not swapped_token, (
            "the two orderings must disagree on this input, or the "
            "counterfactual proves nothing"
        )

    def test_swapped_order_silently_drops_the_competence_end_to_end(self):
        """The same counterfactual, but through a full parse.

        ``LehrplanParser._classify`` is monkeypatched at the class level
        (restored in ``finally``, verified restored at the end) with the
        order-swapped reproduction above. A tiny synthetic document -- one
        subject, one school year, one area, one competence -- parses to
        exactly 1 competence under the real (unpatched) order and to 0 under
        the swapped order, because the school-year marker "1. Schulstufe:"
        is misclassified as an (empty, throwaway) area heading instead of a
        STUFE token, so ``self.stufe`` is never set and the competence list
        that follows is skipped with a logged ``liste_ohne_kontext`` issue
        (parse_lehrplan.py ``_emit_kompetenzen``: "competence list without
        area and/or class year; skipped") instead of being emitted with a
        missing stufe.
        """
        xml = """<risdok xmlns="http://www.bka.gv.at"><nutzdaten><abschnitt>
          <ueberschrift typ="g1">NEUNTER TEIL</ueberschrift>
          <ueberschrift typ="g1">TESTFACH</ueberschrift>
          <ueberschrift typ="erll">Kompetenzbeschreibungen und Anwendungsbereiche,
            Lehrstoff (1. bis 4. Schulstufe):</ueberschrift>
          <ueberschrift typ="erll">1. Schulstufe:</ueberschrift>
          <ueberschrift typ="erll">Kompetenzbereich Lesen</ueberschrift>
          <absatz typ="abs">Die Schülerinnen und Schüler können</absatz>
          <liste><aufzaehlung><listelem>lesen.</listelem></aufzaehlung></liste>
        </abschnitt></nutzdaten></risdok>"""

        spec = dataclasses.replace(
            P.SubjectSpec(
                band="PRIM",
                fach_code="D",
                fach_ueberschrift="TESTFACH",
                teil_ueberschrift="NEUNTER TEIL",
                stufen_praefix="SCH",
                kompetenz_sektion_re=re.compile(r"^Kompetenzbeschreibungen"),
                anwendung_sektion_re=None,
            ),
            bereich_re=_TRAP_BEREICH_RE,
        )

        # Control: real, unpatched order -- the competence survives.
        real = P.LehrplanParser(spec, abbildungen_registry={}).parse_root(ET.fromstring(xml))
        assert [k.stufe for k in real.kompetenzen] == ["SCH1"]

        # Swap _classify at the class level, run the same document through
        # the same code path, and put the original back no matter what.
        original = P.LehrplanParser._classify
        try:
            P.LehrplanParser._classify = _classify_stufe_after_bereich
            # The reproduction needs to reach the *unpatched* logic for
            # every non-ueberschrift element -- bind it under a name the
            # patched method delegates to.
            P.LehrplanParser._classify_original = original
            swapped = P.LehrplanParser(spec, abbildungen_registry={}).parse_root(
                ET.fromstring(xml)
            )
        finally:
            P.LehrplanParser._classify = original
            if hasattr(P.LehrplanParser, "_classify_original"):
                del P.LehrplanParser._classify_original

        assert swapped.kompetenzen == []
        assert [i.art for i in swapped.issues].count("liste_ohne_kontext") == 1
        assert "keine_kompetenzen" in [i.art for i in swapped.issues]

        # Prove the monkeypatch really was undone: parsing again with the
        # restored class gives back the correct, non-empty result.
        restored = P.LehrplanParser(spec, abbildungen_registry={}).parse_root(
            ET.fromstring(xml)
        )
        assert [k.stufe for k in restored.kompetenzen] == ["SCH1"]
        assert P.LehrplanParser._classify is original


class TestTodaysRegexesStaySafe:
    """Grounding in reality: none of the six shipped SubjectSpecs actually
    depends on the order today -- their bereich_re/kompetenz_sektion_re/
    anwendung_sektion_re patterns never overlap STUFE_RE on any real
    heading. This is a measured fact about the committed fixtures, not an
    assumption; it is exactly what makes V-55's fragility latent rather than
    an active bug, and it is what test_order_decides_the_winner_under_a_permissive_area_regex
    fabricates a trap spec to expose despite it."""

    @pytest.mark.parametrize("spec_key,fixture", ALLE_FIXTUREN)
    def test_todays_regexes_never_overlap_on_real_headings(self, spec_key, fixture):
        spec = P.SUBJECT_SPECS[spec_key]
        root = ET.parse(str(FIXTURES / fixture)).getroot()
        abschnitt = P.find_abschnitt(root)
        parser = P.LehrplanParser(spec, abbildungen_registry={})

        geprueft = 0
        for el in abschnitt:
            if P.localname(el) != "ueberschrift" or el.get("typ") != "erll":
                continue
            real_ev = parser._classify(0, el)
            swapped_token = _classify_erll_swapped_token(spec, real_ev.extracted.text)
            assert swapped_token is real_ev.token, (
                spec_key, real_ev.extracted.text, real_ev.token, swapped_token,
            )
            geprueft += 1
        # Sanity: every fixture actually exercises this branch at least once
        # (the section headings and area headings are always erll).
        assert geprueft > 0, f"{fixture} produced no ueberschrift/erll elements at all"
