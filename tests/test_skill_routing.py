"""E7-06: routing test between ``at-unterrichtsplanung`` and ``at-differenzierung``.

Scope, per the task: assert **only** against the YAML frontmatter (``name`` and ``description``)
of the two ``SKILL.md`` files. The frontmatter is plan Section 6.5, verbatim and frozen
(``tests/test_differenzierung_skill.py::test_frontmatter_is_plan_section_6_5_verbatim`` guards
the byte-identity); it is also what a router reads before ever opening either skill body. The
body prose of both files is being rewritten concurrently by other agents while this test is
being written, so nothing here may key on body wording.

Three routing cases must each resolve to exactly one skill:

1. A brand-new unit -> ``at-unterrichtsplanung`` only.
2. An existing unit split into tiers -> ``at-differenzierung`` only.
3. A brand-new unit that wants tiers from the start -> still ONE ``at-unterrichtsplanung``
   request, never an additional ``at-differenzierung`` call. This is the case the task exists
   for: it is easy to double-call both skills.

Rather than grepping for one literal clause copied out of the file (which would pass by
construction and prove nothing about the file's actual claims), the checks below parse each
description into sentences and classify each sentence as a positive capability claim or a
disclaim, using the one structural marker both files actually use for disclaiming: a sentence
that opens with the bare word ``NICHT``. Routing signals (does a sentence claim "new unit",
"existing unit", "one request", ...) are then matched only within the correct class of sentence.
This keeps the tests tied to what the frontmatter actually asserts, and makes them sensitive to
the kinds of edits that would silently break routing (see the mutation-testing notes in the
E7-06 report: removing a disclaim clause, or having both descriptions claim new-unit creation,
breaks the corresponding test below).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
UNTER_SKILL = REPO_ROOT / "plugin" / "skills" / "at-unterrichtsplanung" / "SKILL.md"
DIFF_SKILL = REPO_ROOT / "plugin" / "skills" / "at-differenzierung" / "SKILL.md"


# ---------------------------------------------------------------------------
# stdlib-only frontmatter parsing (no PyYAML: requirements-dev.txt is pinned to
# jsonschema/pytest/python-docx and adding a dependency is not this task's call).
# Handles exactly the two forms these two files use: a plain "key: value" scalar and a
# "key: >" folded block scalar. Not a general YAML parser.
# ---------------------------------------------------------------------------


def parse_frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    assert lines and lines[0] == "---", "frontmatter must open with a bare '---' line"
    end = 1
    while lines[end] != "---":
        end += 1
    block = lines[1:end]

    result: dict[str, str] = {}
    key_re = re.compile(r"^([A-Za-z_][\w-]*):\s*(.*)$")
    i = 0
    while i < len(block):
        m = key_re.match(block[i])
        if not m:
            i += 1
            continue
        key, rest = m.group(1), m.group(2).strip()
        if rest in (">", "|", ">-", "|-"):
            i += 1
            collected: list[str] = []
            while i < len(block) and (block[i].startswith(" ") or not block[i].strip()):
                collected.append(block[i].strip())
                i += 1
            result[key] = re.sub(r"\s+", " ", " ".join(collected)).strip()
        else:
            result[key] = rest
            i += 1
    return result


def frontmatter_of(path: Path) -> dict[str, str]:
    return parse_frontmatter(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def unter_fm() -> dict[str, str]:
    return frontmatter_of(UNTER_SKILL)


@pytest.fixture(scope="module")
def diff_fm() -> dict[str, str]:
    return frontmatter_of(DIFF_SKILL)


# ---------------------------------------------------------------------------
# Sentence-structural helpers. Both descriptions are written as '.'-terminated sentences, and
# both open their exclusion list with a bare "NICHT ..." sentence -- that is the one structural
# signal used here to separate "what this skill does" from "what it explicitly refuses".
# ---------------------------------------------------------------------------

_SENTENCE_SPLIT = re.compile(r"(?<=[.])\s+")
_NEGATIVE_START = re.compile(r"(?i)^nicht\b")


def sentences(desc: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(desc.strip()) if s.strip()]


def positive_sentences(desc: str) -> list[str]:
    """Sentences stating a capability (do not open with the disclaim marker 'NICHT')."""
    return [s for s in sentences(desc) if not _NEGATIVE_START.match(s)]


def negative_sentences(desc: str) -> list[str]:
    """Sentences opening with the disclaim marker 'NICHT ...'."""
    return [s for s in sentences(desc) if _NEGATIVE_START.match(s)]


def any_sentence(sents: list[str], *patterns: str) -> bool:
    """True if some single sentence in `sents` matches every one of `patterns` (each a
    case-insensitive regex) -- i.e. one sentence carries all of the given signals together."""
    return any(all(re.search(p, s, re.IGNORECASE) for p in patterns) for s in sents)


# ---------------------------------------------------------------------------
# Basic frontmatter sanity
# ---------------------------------------------------------------------------


def test_frontmatter_parses_name_and_description(unter_fm, diff_fm) -> None:
    assert unter_fm["name"] == "at-unterrichtsplanung"
    assert diff_fm["name"] == "at-differenzierung"
    assert unter_fm["description"], "at-unterrichtsplanung description must be non-empty"
    assert diff_fm["description"], "at-differenzierung description must be non-empty"


# ---------------------------------------------------------------------------
# Case 1: brand-new unit -> at-unterrichtsplanung only
# ---------------------------------------------------------------------------


def test_case1_new_unit_routes_to_unterrichtsplanung_only(unter_fm, diff_fm) -> None:
    unter_claims_new = any_sentence(positive_sentences(unter_fm["description"]), r"neu erstellen")
    # ".{0,25}" (not "\s+"), and no leading \b on "einheit", so this also catches a compound
    # like "neue Unterrichtseinheit" -- "einheit" has no word boundary before it mid-compound.
    # Not only the bare "neue Einheit". A mutation-testing finding, see the E7-06 report.
    diff_claims_new = any_sentence(
        positive_sentences(diff_fm["description"]), r"neue?n?\b.{0,25}einheit"
    )

    assert unter_claims_new, (
        "at-unterrichtsplanung's description must positively claim it creates new units"
    )
    assert not diff_claims_new, (
        "at-differenzierung's description must not positively claim new-unit creation "
        "(only its NICHT-clause may mention a new unit, to disclaim it)"
    )
    resolved = set()
    if unter_claims_new:
        resolved.add("at-unterrichtsplanung")
    if diff_claims_new:
        resolved.add("at-differenzierung")
    assert resolved == {"at-unterrichtsplanung"}


def test_case1_differenzierung_explicitly_disclaims_new_unit(diff_fm) -> None:
    assert any_sentence(
        negative_sentences(diff_fm["description"]), r"erstellen einer neuen einheit"
    ), "at-differenzierung must explicitly disclaim creating a new unit"


# ---------------------------------------------------------------------------
# Case 2: existing unit split into tiers -> at-differenzierung only
# ---------------------------------------------------------------------------


def test_case2_existing_unit_tiering_routes_to_differenzierung_only(unter_fm, diff_fm) -> None:
    diff_claims_tiering = any_sentence(
        positive_sentences(diff_fm["description"]), r"bestehende", r"niveaustufen"
    )
    unter_claims_existing = any_sentence(positive_sentences(unter_fm["description"]), r"bestehende")

    assert diff_claims_tiering, (
        "at-differenzierung's description must positively claim tiering an existing unit "
        "in one sentence (both 'bestehende' and 'Niveaustufen')"
    )
    assert not unter_claims_existing, (
        "at-unterrichtsplanung must not positively claim handling an existing unit"
    )
    resolved = set()
    if diff_claims_tiering:
        resolved.add("at-differenzierung")
    if unter_claims_existing:
        resolved.add("at-unterrichtsplanung")
    assert resolved == {"at-differenzierung"}


def test_case2_unterrichtsplanung_explicitly_disclaims_differentiating_existing_unit(unter_fm) -> None:
    assert any_sentence(
        negative_sentences(unter_fm["description"]), r"differenzieren einer bestehenden einheit"
    ), "at-unterrichtsplanung must explicitly disclaim differentiating an existing unit"


# ---------------------------------------------------------------------------
# Case 3: brand-new unit that wants tiers from the start -> ONE at-unterrichtsplanung request
# ---------------------------------------------------------------------------


def test_case3_new_tiered_unit_is_one_unterrichtsplanung_request(unter_fm) -> None:
    positives = positive_sentences(unter_fm["description"])
    assert any_sentence(
        positives, r"neue\s+einheit", r"differenziert|mehrstufig", r"eine\s+planungsanfrage"
    ), (
        "at-unterrichtsplanung must state, in one sentence, that a new unit wanting "
        "differentiated/tiered material is ONE planning request"
    )
    assert any_sentence(
        positives, r"nicht\s+zus.tzlich\s+at-differenzierung\s+aufrufen"
    ), "at-unterrichtsplanung must say not to additionally call at-differenzierung for this case"


def test_case3_differenzierung_description_cannot_capture_a_new_tiered_unit(diff_fm) -> None:
    """The differentiation skill's positive capability claim is scoped to an existing unit and
    never offers 'neue' as an alternate subject -- so a request for a brand-new (even if
    tiered) unit structurally falls outside what this description claims."""
    positives = positive_sentences(diff_fm["description"])
    assert any_sentence(positives, r"bestehende"), (
        "at-differenzierung's positive claim must require an existing unit"
    )
    assert not any_sentence(positives, r"\bneue\b"), (
        "at-differenzierung's positive claim must not also mention a 'neue' unit as an "
        "alternate subject -- that would let it wrongly capture case 3"
    )


# ---------------------------------------------------------------------------
# Explicit mutual-exclusivity check on the new-vs-existing distinction
# ---------------------------------------------------------------------------


def test_new_vs_existing_is_mutually_exclusive_between_the_two_descriptions(unter_fm, diff_fm) -> None:
    unter = unter_fm["description"]
    diff = diff_fm["description"]

    # at-unterrichtsplanung claims new-unit creation ...
    assert any_sentence(positive_sentences(unter), r"neu erstellen")
    # ... and at-differenzierung explicitly disclaims it.
    assert any_sentence(negative_sentences(diff), r"erstellen einer neuen einheit")

    # at-differenzierung requires an existing unit ...
    assert any_sentence(positive_sentences(diff), r"bestehende")
    # ... and at-unterrichtsplanung explicitly disclaims handling one.
    assert any_sentence(negative_sentences(unter), r"bestehenden einheit")


# ---------------------------------------------------------------------------
# Load-before-asking instruction: both skills must be loaded before any clarifying question,
# not after -- otherwise the routing decision above never happens before the model starts
# asking the teacher questions that only one of the two skills would need.
# ---------------------------------------------------------------------------


def test_both_descriptions_require_loading_before_a_clarifying_question(unter_fm, diff_fm) -> None:
    pattern = re.compile(r"(?i)vor jeder r.ckfrage.{0,80}laden")
    assert pattern.search(unter_fm["description"]), (
        "at-unterrichtsplanung must instruct loading itself before any clarifying question"
    )
    assert pattern.search(diff_fm["description"]), (
        "at-differenzierung must instruct loading itself before any clarifying question"
    )
