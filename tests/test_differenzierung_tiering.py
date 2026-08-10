"""E7-03 acceptance: the Sek I mathematics tiering fixture (``at-differenzierung``).

Ground truth is exclusively the live public access layer in ``plugin/scripts/kompetenz.py`` --
every claim below is checked against what ``finde_anwendungsbereiche``/``finde_differenzierung``
actually return for ``AT.LP23.SEK1.M.ZAHLEN.K2.03``, never against strings that merely happen to
occur in the fixture. V-10 (``Wiederholen und Festigen`` backlinks), V-42/V-60 (``Standard AHS``
is prose, never a per-item marker) and V-78/V-88 (K1 tier-label rule; ``enrichment_items`` is
gated on the axis, not on ``niveaus``) are the ground truth this file pins.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "differenzierung_flow"
    / "sek1_mathematik_k2_bruchrechnen.differenzierung.json"
)
RENDERER = REPO_ROOT / "plugin" / "skills" / "at-differenzierung" / "scripts" / "render_documents.py"
CHECKER = REPO_ROOT / "plugin" / "scripts" / "pruefe_verankerung.py"
KOMPETENZ_ID = "AT.LP23.SEK1.M.ZAHLEN.K2.03"

sys.path.insert(0, str(REPO_ROOT / "plugin" / "scripts"))
import kompetenz  # noqa: E402  pylint: disable=wrong-import-position
import pruefe_verankerung  # noqa: E402  pylint: disable=wrong-import-position


def _blocks(value: object) -> list[dict]:
    if isinstance(value, dict):
        found = [value] if isinstance(value.get("type"), str) else []
        for child in value.values():
            found.extend(_blocks(child))
        return found
    if isinstance(value, list):
        return [block for child in value for block in _blocks(child)]
    return []


def _source() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _all_text(blocks: list[dict]) -> str:
    """Concatenate every string-valued field that plausibly carries prose, across every
    block -- used for whole-document assertions that must hold regardless of exactly which
    block shape carries a given sentence."""
    parts: list[str] = []
    for block in blocks:
        for key in ("text", "label", "meta", "eyebrow", "title"):
            value = block.get(key)
            if isinstance(value, str):
                parts.append(value)
        items = block.get("items")
        if isinstance(items, list):
            parts.extend(i for i in items if isinstance(i, str))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Mechanical gates: anchoring checker + renderer, per the task's own recipe.
# ---------------------------------------------------------------------------


def test_fixture_passes_pruefe_verankerung() -> None:
    verletzungen = pruefe_verankerung.pruefe_lesson(FIXTURE)
    assert verletzungen == [], verletzungen

    cli = subprocess.run(
        [sys.executable, str(CHECKER), str(FIXTURE)],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert cli.returncode == 0, cli.stdout + cli.stderr


def test_fixture_renders_docx_for_all_four_documents(tmp_path: Path) -> None:
    pytest.importorskip("docx", reason="python-docx is optional; DOCX flow test is skipped")
    result = subprocess.run(
        [sys.executable, str(RENDERER), str(FIXTURE), "--format", "docx", "--outdir", str(tmp_path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout

    for doc_id in ("differenzierungsplan", "arbeitsblatt_unter", "arbeitsblatt_auf", "arbeitsblatt_ueber"):
        docx_path = tmp_path / f"{doc_id}.docx"
        assert docx_path.is_file(), f"{doc_id}.docx was not written"
        assert (tmp_path / f"{doc_id}.html").is_file(), f"{doc_id}.html was not written"
        with zipfile.ZipFile(docx_path) as document:
            assert "word/document.xml" in document.namelist()

    # No unresolved inline-formula tokens may survive into the rendered HTML body -- a
    # literal token would mean an abbildungen sibling array was missing (V-87 trap).
    for doc_id in ("differenzierungsplan", "arbeitsblatt_auf", "arbeitsblatt_ueber"):
        html = (tmp_path / f"{doc_id}.html").read_text(encoding="utf-8")
        body = html.split("</style>", 1)[-1]  # the CSS carries an explanatory "ABB:" comment
        assert "⟦ABB:" not in body, f"{doc_id}.html still contains a literal, unresolved ABB token"


# ---------------------------------------------------------------------------
# Document set shape.
# ---------------------------------------------------------------------------


def test_fixture_has_exactly_one_plan_and_three_tier_documents() -> None:
    source = _source()
    docs = {doc["id"]: doc for doc in source["documents"]}
    assert set(docs) == {
        "differenzierungsplan",
        "arbeitsblatt_unter",
        "arbeitsblatt_auf",
        "arbeitsblatt_ueber",
    }
    assert docs["differenzierungsplan"]["audience"] == "teacher"
    for tier_id in ("arbeitsblatt_unter", "arbeitsblatt_auf", "arbeitsblatt_ueber"):
        assert docs[tier_id]["audience"] == "student"
    for doc in docs.values():
        assert doc["sections"], f"{doc['id']} has no sections"


def test_kompetenzbezug_lives_once_in_shared_and_is_referenced_via_from_shared() -> None:
    source = _source()
    shared_anchor = source["shared"]["kompetenz"]
    assert shared_anchor["type"] == "kompetenzbezug"
    assert shared_anchor["kompetenz_id"] == KOMPETENZ_ID

    record = kompetenz.kompetenz_nach_id(KOMPETENZ_ID)
    assert shared_anchor["text"] == kompetenz.voller_wortlaut(record)
    assert shared_anchor["quelle"] == record["provenienz"]

    # No document may retype a second kompetenzbezug block for this (or any) competence --
    # the only one in the whole file lives in ``shared``.
    all_blocks = _blocks(source)
    kompetenzbezug_blocks = [b for b in all_blocks if b.get("type") == "kompetenzbezug"]
    assert len(kompetenzbezug_blocks) == 1

    for doc in source["documents"]:
        doc_blocks = _blocks(doc)
        refs = [b for b in doc_blocks if b.get("type") == "from_shared" and b.get("key") == "kompetenz"]
        assert refs, f"{doc['id']} does not reference the shared kompetenzbezug via from_shared"


# ---------------------------------------------------------------------------
# Auf-Stufe: binding application items are real, complete, and not smuggled optional.
# ---------------------------------------------------------------------------


def test_auf_stufe_binding_items_are_real_and_complete() -> None:
    real_binding = {
        item["text"] for item in kompetenz.finde_anwendungsbereiche(KOMPETENZ_ID, nur_verbindlich=True)
    }
    real_optional = {
        item["text"] for item in kompetenz.finde_anwendungsbereiche(KOMPETENZ_ID, nur_verbindlich=False)
    }
    assert len(real_binding) == 8
    assert len(real_optional) == 1

    source = _source()
    binding_block = source["shared"]["verbindliche_items"]
    assert binding_block["type"] == "list"
    assert "erbindlich" in binding_block["label"]
    fixture_binding = set(binding_block["items"])

    assert fixture_binding == real_binding, (
        f"missing: {real_binding - fixture_binding!r}, extra: {fixture_binding - real_binding!r}"
    )
    assert fixture_binding.isdisjoint(real_optional)

    doc_ids = [doc["id"] for doc in source["documents"]]
    for doc_id in ("differenzierungsplan", "arbeitsblatt_auf"):
        assert doc_id in doc_ids
        doc = next(doc for doc in source["documents"] if doc["id"] == doc_id)
        refs = [
            b for b in _blocks(doc)
            if b.get("type") == "from_shared" and b.get("key") == "verbindliche_items"
        ]
        assert refs, f"{doc_id} does not show the binding application items"


def test_auf_stufe_binding_items_carry_abbildungen_for_every_embedded_token() -> None:
    """Trap 3 from the brief, measured rather than assumed: more than the two items the task
    text names actually carry ⟦ABB:...⟧ tokens for this competence (K2.13 as well as K2.20),
    so the sibling ``abbildungen`` array must cover all of them, not just two."""
    real_binding = kompetenz.finde_anwendungsbereiche(KOMPETENZ_ID, nur_verbindlich=True)
    tokens_in_texts: set[str] = set()
    for item in real_binding:
        tokens_in_texts.update(re.findall(r"⟦ABB:[^⟧]+⟧", item["text"]))
    assert len(tokens_in_texts) == 7, (
        "ground truth changed: re-measure which binding items for this competence carry "
        "inline formula images before trusting this test"
    )

    source = _source()
    binding_block = source["shared"]["verbindliche_items"]
    declared_tokens = {a["token"] for a in binding_block.get("abbildungen", [])}
    assert tokens_in_texts <= declared_tokens, (
        f"binding block text contains tokens {tokens_in_texts - declared_tokens} with no "
        "matching entry in its sibling abbildungen array"
    )
    for a in binding_block["abbildungen"]:
        assert a["pfad"].startswith("data/abbildungen/NOR40271471/")


# ---------------------------------------------------------------------------
# Über-Stufe: the single allenfalls item, labelled non-compulsory.
# ---------------------------------------------------------------------------


def test_ueber_stufe_allenfalls_item_present_and_labelled_non_compulsory() -> None:
    diff = kompetenz.finde_differenzierung(KOMPETENZ_ID)
    assert diff["achse"].get("enrichment_quelle") == "allenfalls"
    real_enrichment = diff["enrichment_items"]
    assert len(real_enrichment) == 1
    assert real_enrichment[0]["id"] == "AT.LP23.SEK1.M.AB.ZAHLEN.K2.17"
    assert real_enrichment[0]["verbindlich"] is False

    source = _source()
    allenfalls_block = source["shared"]["allenfalls_item"]
    assert allenfalls_block["items"] == [real_enrichment[0]["text"]]
    label = allenfalls_block["label"].lower()
    assert "optional" in label or "allenfalls" in label
    assert "verpflichtend" in label or "nicht verpflichtend" in label

    ueber = next(doc for doc in source["documents"] if doc["id"] == "arbeitsblatt_ueber")
    ueber_blocks = _blocks(ueber)
    refs = [
        b for b in ueber_blocks
        if b.get("type") == "from_shared" and b.get("key") == "allenfalls_item"
    ]
    assert refs, "arbeitsblatt_ueber does not show the allenfalls enrichment item"

    # And it must be visibly marked non-official-binding / non-compulsory somewhere in the
    # tier document, not merely present.
    text = _all_text(ueber_blocks)
    assert "allenfalls" in text.lower()
    assert "nicht verpflichtend" in text or "nicht verbindlich" in text


def test_ueber_stufe_has_skill_authored_depth_anchored_to_stammsatz_and_text() -> None:
    record = kompetenz.kompetenz_nach_id(KOMPETENZ_ID)
    source = _source()
    ueber = next(doc for doc in source["documents"] if doc["id"] == "arbeitsblatt_ueber")
    blocks = _blocks(ueber)

    non_official_herkunft = [
        b for b in blocks if b.get("type") == "herkunftsblock" and b.get("amtlich") is False
    ]
    assert non_official_herkunft, "arbeitsblatt_ueber has no skill-authored (amtlich: false) block"
    for h in non_official_herkunft:
        hinweis = h.get("quelle_hinweis", "")
        assert record["id"] in hinweis
        assert "stammsatz" in hinweis and "text" in hinweis
        assert h.get("blocks"), "skill-authored herkunftsblock carries no actual content"


# ---------------------------------------------------------------------------
# Unter-Stufe: two distinct sources, not conflated (trap 1 from the brief).
# ---------------------------------------------------------------------------


def test_unter_stufe_represents_vorklasse_and_wiederholen_as_distinct_sources() -> None:
    diff = kompetenz.finde_differenzierung(KOMPETENZ_ID)
    vorklasse_ids = {v["id"] for v in diff["vorklasse_stuetzen"]}
    assert vorklasse_ids == {
        "AT.LP23.SEK1.M.ZAHLEN.K1.01",
        "AT.LP23.SEK1.M.ZAHLEN.K1.02",
        "AT.LP23.SEK1.M.ZAHLEN.K1.03",
    }

    real_binding = kompetenz.finde_anwendungsbereiche(KOMPETENZ_ID, nur_verbindlich=True)
    wiederholen_items = [i for i in real_binding if i["text"].startswith("Wiederholen und Festigen:")]
    assert len(wiederholen_items) == 1
    wiederholen_item = wiederholen_items[0]
    assert wiederholen_item["id"] == "AT.LP23.SEK1.M.AB.ZAHLEN.K2.12"
    # The competence-level API result must not silently substitute one for the other (the
    # docstring's explicit prohibition) -- their ID namespaces stay disjoint.
    assert vorklasse_ids.isdisjoint({wiederholen_item["id"]})

    source = _source()
    vorklasse_block = source["shared"]["vorklasse_liste"]
    wiederholen_block = source["shared"]["wiederholen_item"]

    # The two shared blocks are genuinely separate objects with separate labels.
    assert vorklasse_block is not wiederholen_block
    assert vorklasse_block["label"] != wiederholen_block["label"]

    for v in diff["vorklasse_stuetzen"]:
        assert any(v["id"] in item for item in vorklasse_block["items"]), (
            f"vorklasse competence {v['id']} not represented in the Unter-Stufe's "
            "vorklasse_liste block"
        )
        assert v["volltext"] in "\n".join(vorklasse_block["items"])

    assert wiederholen_block["items"] == [wiederholen_item["text"]]

    # The Wiederholen item must not appear inside the vorklasse block, and no vorklasse
    # competence ID may appear inside the Wiederholen block -- the two lists never merge.
    vorklasse_text = "\n".join(vorklasse_block["items"])
    assert wiederholen_item["text"] not in vorklasse_text
    for vid in vorklasse_ids:
        assert vid not in "\n".join(wiederholen_block["items"])

    unter = next(doc for doc in source["documents"] if doc["id"] == "arbeitsblatt_unter")
    unter_blocks = _blocks(unter)
    refs = {
        b["key"] for b in unter_blocks if b.get("type") == "from_shared"
    }
    assert "vorklasse_liste" in refs, "arbeitsblatt_unter does not show the vorklasse competences"
    assert "wiederholen_item" in refs, "arbeitsblatt_unter does not show the Wiederholen item"


def test_wiederholen_item_is_checked_as_a_genuine_binding_item_by_pruefe_verankerung() -> None:
    """The Unter-Stufe's Wiederholen block is labelled 'verbindlich', so the mechanical
    checker validates it against the real binding set for this competence -- this test proves
    that path is actually exercised, not merely that the checker returns zero violations
    overall (which a block it never looks at would also satisfy)."""
    source = _source()
    wiederholen_block = source["shared"]["wiederholen_item"]
    assert pruefe_verankerung._VERBINDLICH_LABEL.search(wiederholen_block["label"])

    broken = _source()
    broken["shared"]["wiederholen_item"]["items"] = ["Erfundener Wiederholen-Text, der nicht existiert;"]
    verletzungen = pruefe_verankerung.pruefe_daten(broken)
    assert any(
        v.regel == pruefe_verankerung.REGEL_ERFUNDENES_VERBINDLICHES_ITEM for v in verletzungen
    )


# ---------------------------------------------------------------------------
# V-42/V-60/V-78: no text anywhere claims a per-item Standard/Standard-AHS split.
# ---------------------------------------------------------------------------


def test_no_document_claims_a_per_item_standard_standard_ahs_distinction() -> None:
    diff = kompetenz.finde_differenzierung(KOMPETENZ_ID)
    assert diff["niveaus"] == ["Standard", "Standard AHS"]  # K2: effective at this stage

    source = _source()
    all_blocks = _blocks(source)

    # No labelled application-item list may attach "Standard"/"Standard AHS" to an
    # individual item string.
    for block in all_blocks:
        if block.get("type") == "list" and isinstance(block.get("items"), list):
            for item in block["items"]:
                assert "Standard AHS" not in item and "Standard" != item.strip("., "), (
                    f"item {item!r} appears to carry a per-item Standard/Standard-AHS marker"
                )

    # Wherever "Standard" or "Standard AHS" occurs in prose, it must sit in a sentence that
    # also disclaims a per-item/dataset-query reading -- not a bare label.
    disclaiming_markers = (
        "kein einzelnes",
        "keine Abfrage",
        "nie eine Markierung",
        "Metadaten-Einstufung",
        "Fließtext",
        "kein 'Standard-AHS'-Item",
    )
    for block in all_blocks:
        text = block.get("text")
        if isinstance(text, str) and "Standard" in text:
            assert any(marker in text for marker in disclaiming_markers), (
                f"prose mentions Standard/Standard AHS without a disclaiming marker: {text!r}"
            )


def test_k2_unit_is_correct_ground_for_showing_non_empty_niveaus() -> None:
    """This fixture deliberately anchors on a K2 competence, where niveaus is non-empty
    (V-78's K1 rule does not apply here) -- documented so a future reader does not mistake
    the absence of a K1 example in this fixture for an oversight; the K1 rule itself is
    pinned against the live API directly, independent of which competence this fixture uses."""
    k1_record = next(c for c in kompetenz.finde_kompetenz("SEK1.M") if c["stufe"] == "K1")
    k1_diff = kompetenz.finde_differenzierung(k1_record["id"])
    assert k1_diff["niveaus"] == []

    k2_diff = kompetenz.finde_differenzierung(KOMPETENZ_ID)
    assert k2_diff["niveaus"] == ["Standard", "Standard AHS"]
