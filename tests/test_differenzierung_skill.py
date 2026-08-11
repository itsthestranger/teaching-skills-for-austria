"""E7-01/E7-02 acceptance: ``at-differenzierung/SKILL.md`` loads, routes unambiguously against
``at-unterrichtsplanung``, and reads the differentiation axis from ``meta`` rather than
re-deriving or hardcoding it.

These tests compare the skill's stated contract against the *real* public access layer in
``plugin/scripts/kompetenz.py`` (V-61/V-78/V-42/V-60 ground truth), not merely against strings
that happen to occur in the file.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = REPO_ROOT / "plugin" / "skills" / "at-differenzierung" / "SKILL.md"

sys.path.insert(0, str(REPO_ROOT / "plugin" / "scripts"))
import kompetenz  # noqa: E402  pylint: disable=wrong-import-position


def test_skill_file_exists_and_loads() -> None:
    assert SKILL.is_file()
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "name: at-differenzierung" in text


#: The specification is a **local-only, gitignored** working document (CLAUDE.md: it is a
#: reference for the build and nothing ships it), so it is absent on any CI runner and on any
#: fresh clone. A test that reads it can only run where it exists.
PLAN = REPO_ROOT / "teaching-skills-austria-plan.md"


@pytest.mark.skipif(
    not PLAN.is_file(),
    reason=(
        "teaching-skills-austria-plan.md is local-only and gitignored, so byte-identity with "
        "plan §6.5 is only checkable on a machine that has the spec. The frontmatter itself is "
        "still guarded everywhere by tests/test_skill_routing.py, which asserts name, "
        "description and the full routing semantics without needing the plan."
    ),
)
def test_frontmatter_is_plan_section_6_5_verbatim() -> None:
    """The frontmatter block (between the two ``---`` fences) must be byte-identical to the
    plan's §6.5 ``at-differenzierung`` YAML block -- no rewording, per the task's explicit
    instruction.

    Deliberately still enforced where the plan exists: the frontmatter carries the pre-V-61
    simplification *"Sprachen: GERS A1/A2/B1"*, retained on purpose (2026-08-06 deviation row)
    because it is the skill's routing surface. This test is what stops someone "correcting" it.
    """
    plan = PLAN.read_text(encoding="utf-8")
    plan_lines = plan.splitlines()
    start = plan_lines.index("name: at-differenzierung") - 1  # the '---' line before it
    assert plan_lines[start] == "---"
    end = start + 1
    while plan_lines[end] != "---":
        end += 1
    expected_block = "\n".join(plan_lines[start : end + 1]) + "\n"

    skill_lines = SKILL.read_text(encoding="utf-8").splitlines()
    assert skill_lines[0] == "---"
    skill_end = 1
    while skill_lines[skill_end] != "---":
        skill_end += 1
    actual_block = "\n".join(skill_lines[0 : skill_end + 1]) + "\n"

    assert actual_block == expected_block


def test_routing_vs_at_unterrichtsplanung_is_unambiguous() -> None:
    """A new unit is one at-unterrichtsplanung request (even if it wants tiers); this skill
    states the complement without contradicting the sibling's own description."""
    skill = SKILL.read_text(encoding="utf-8")
    for required in (
        "at-unterrichtsplanung",
        "bestehende",
        "NICHT zusätzlich aufrufen",
    ):
        assert required in skill


def test_skill_reads_axis_from_meta_and_disclaims_a_hardcoded_table() -> None:
    """E7-02's acceptance criterion, checked literally: the skill must name the real access
    call and explicitly disclaim deriving the axis from its own subject table."""
    skill = SKILL.read_text(encoding="utf-8")
    for required in (
        "`finde_differenzierung(kompetenz_id)`",
        "meta.differenzierungs_achse",
        "nie aus einer eigenen Fach",
        "keine eigene Fachreferenz-Tabelle",
    ):
        assert required in skill


def test_skill_states_k1_empty_niveaus_and_standard_ahs_is_prose_only() -> None:
    """V-78 (K1 must not be labelled Standard/Standard AHS) and V-42/V-60 (Standard AHS is
    prose, never a per-item marker) must both be stated, not merely implied."""
    skill = SKILL.read_text(encoding="utf-8")
    assert "K1" in skill and "leer" in skill
    assert "Fließtext im Lehrplan" in skill
    assert "nie eine Markierung an" in skill


def test_skill_states_enrichment_items_are_sek1_m_only() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    assert "enrichment_quelle" in skill
    assert "SEK1.M" in skill


def test_skill_states_k1_enrichment_is_real_but_never_standard_ahs_labelled() -> None:
    """V-78: K1 SEK1.M competences can carry real allenfalls enrichment_items even though
    niveaus is empty there; the skill must say that content may inform the Über-Stufe but must
    never be relabelled Standard AHS."""
    skill = SKILL.read_text(encoding="utf-8")
    assert "K1" in skill
    assert "AT.LP23.SEK1.M.FIGUREN.K1.01" in skill
    assert "**nie**" in skill


def test_skill_states_gers_hat_fachweite_und_je_stufe_angaben() -> None:
    """E8-05: the skill must distinguish the two gers facts -- 'niveaus' (the
    fachweite A1/A2/B1 statement) from 'je_stufe' (the real per-class-year
    mapping, je_stufe_ausgewiesen True since E8-05) -- never conflate them."""
    skill = SKILL.read_text(encoding="utf-8")
    assert "je_stufe_ausgewiesen" in skill
    assert "fachweite" in skill
    assert "gers_stufe" in skill


# ---------------------------------------------------------------------------
# Ground truth: verify the claims above against the live access layer, not
# just against the SKILL.md prose.
# ---------------------------------------------------------------------------


def test_measured_sek1_m_k1_vs_k2_niveaus_difference() -> None:
    sek1m = kompetenz.finde_kompetenz("SEK1.M")
    k1 = next(c for c in sek1m if c["stufe"] == "K1")
    k2 = next(c for c in sek1m if c["stufe"] == "K2")

    d_k1 = kompetenz.finde_differenzierung(k1["id"])
    d_k2 = kompetenz.finde_differenzierung(k2["id"])

    assert d_k1["achse"]["typ"] == "standard_standardplus"
    assert d_k1["achse"].get("gilt_ab_stufe") == "K2"
    assert d_k1["niveaus"] == []

    assert d_k2["achse"]["typ"] == "standard_standardplus"
    assert d_k2["niveaus"] == ["Standard", "Standard AHS"]


def test_measured_primary_shard_uses_lehrplan_generisch() -> None:
    prim_m = kompetenz.finde_kompetenz("PRIM.M")[0]
    result = kompetenz.finde_differenzierung(prim_m["id"])
    assert result["achse"]["typ"] == "lehrplan_generisch"
    assert result["niveaus"] == result["achse"]["niveaus"]


def test_measured_sek1_e_gers_hat_fachweite_und_je_stufe_angaben() -> None:
    """E8-05: 'niveaus' stays the fachweite A1/A2/B1 statement; 'je_stufe' is
    now a real, sourced per-class-year mapping (je_stufe_ausgewiesen True),
    and gers_stufe resolves it for the queried competence's own stufe."""
    sek1e = kompetenz.finde_kompetenz("SEK1.E")
    k2 = next(c for c in sek1e if c["stufe"] == "K2")
    result = kompetenz.finde_differenzierung(k2["id"])
    gers = result["achse"]["gers"]
    assert gers["je_stufe_ausgewiesen"] is True
    assert gers["niveaus"] == ["A1", "A2", "B1"]
    assert result["gers_stufe"]["niveau"] == "A2"
    assert result["gers_stufe"] == gers["je_stufe"]["K2"]


def test_measured_enrichment_items_nonempty_only_for_sek1_m() -> None:
    sek1m = kompetenz.finde_kompetenz("SEK1.M")
    k2_m = next(c for c in sek1m if c["stufe"] == "K2")
    result_m = kompetenz.finde_differenzierung(k2_m["id"])
    assert result_m["achse"].get("enrichment_quelle") == "allenfalls"
    assert result_m["enrichment_items"], "SEK1.M must have real allenfalls enrichment items"

    for fach in ("PRIM.M", "PRIM.D", "PRIM.SU", "SEK1.D", "SEK1.E"):
        records = kompetenz.finde_kompetenz(fach)
        sample = records[0]
        result = kompetenz.finde_differenzierung(sample["id"])
        assert result["achse"].get("enrichment_quelle") != "allenfalls"
        assert result["enrichment_items"] == []


def test_measured_k1_sek1_m_can_carry_real_enrichment_despite_empty_niveaus() -> None:
    """V-78 ground truth: enrichment_items is gated only on enrichment_quelle, not on
    gilt_ab_stufe/niveaus, so a K1 SEK1.M competence can legitimately have both an empty
    niveaus list and a non-empty enrichment_items list at the same time."""
    record = kompetenz.kompetenz_nach_id("AT.LP23.SEK1.M.FIGUREN.K1.01")
    assert record["stufe"] == "K1"
    result = kompetenz.finde_differenzierung(record["id"])
    assert result["niveaus"] == []
    assert result["enrichment_items"], "K1 FIGUREN.K1.01 must carry real allenfalls content"


def test_skill_names_the_pruefe_verankerung_gate() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    assert "plugin/scripts/pruefe_verankerung.py" in skill
    assert "in **einer** Antwort" in skill
