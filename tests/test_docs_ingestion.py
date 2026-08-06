"""Tests for the `docs/` ingestion contract (plan §6.6, backlog E6-05).

Closes E4-07 too: `kompetenz.finde_lernaufgaben` must satisfy the full
ingestion contract, not the interim native-`.md`/`.txt`-only reader.

Two data sources, deliberately never the real (gitignored) `docs/`:

- ``tests/fixtures/docs_ingestion/`` -- a small, committed, text-only tree
  exercising the folder convention, the alias table, the unknown-folder
  "unassigned, not discarded" path, and both competence-binding mechanisms
  (filename suffix, YAML frontmatter).
- ``tmp_path`` -- for anything that needs binary content generated on the
  fly (a real `.docx` via `python-docx`, a `.pdf`-suffixed stub) or would
  otherwise bloat the repository (size-limit / count-limit / token-budget
  scenarios), mirroring the same pattern the sibling interim test
  (``data-pipeline/tests/test_kompetenz_access.py::test_finde_lernaufgaben_folder_convention_and_filters``)
  already uses.

``docs_ingest.STANDARD_DOCS_ROOT`` is the injectable module-level default
root (mirrors ``kompetenz.KOMPETENZEN_ROOT`` in
``data-pipeline/tests/test_kompetenz_contract.py``) -- monkeypatched here so
a call to ``kompetenz.finde_lernaufgaben(...)`` *without* an explicit
``docs_root`` argument still never touches the real `docs/`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent
_FIXTURE_ROOT = _HERE / "fixtures" / "docs_ingestion"
sys.path.insert(0, str(_REPO_ROOT / "plugin" / "scripts"))

import docs_ingest as DI  # noqa: E402
import kompetenz as K  # noqa: E402


@pytest.fixture(autouse=True)
def _standard_root_zeigt_nie_auf_echtes_docs(monkeypatch):
    """``docs/`` is gitignored -- no test in this module may depend on its
    real contents. Redirecting the injectable default root is the concrete
    guarantee, exercised by every test that calls ``finde_lernaufgaben``
    without an explicit ``docs_root``."""
    monkeypatch.setattr(DI, "STANDARD_DOCS_ROOT", _FIXTURE_ROOT)


# ---------------------------------------------------------------------------
# Missing / empty docs/ -- E4-07's explicit acceptance criterion
# ---------------------------------------------------------------------------


def test_missing_docs_root_returns_empty_report_not_error(tmp_path):
    bericht = DI.sammle(tmp_path / "nicht-vorhanden")
    assert bericht.treffer == []
    assert bericht.uebersprungen == []
    assert bericht.verworfen == []


def test_empty_docs_dir_returns_empty_report(tmp_path):
    bericht = DI.sammle(tmp_path)
    assert bericht.treffer == []


def test_finde_lernaufgaben_missing_docs_root_returns_empty_list():
    assert K.finde_lernaufgaben(fach="SEK1.M", docs_root="/pfad/der/nicht/existiert") == []


def test_finde_lernaufgaben_default_root_ist_umgeleitet_und_leer_oder_gefuellt():
    """No explicit docs_root -- must resolve through the monkeypatched
    STANDARD_DOCS_ROOT (the fixture tree), never the real docs/."""
    ergebnis = K.finde_lernaufgaben(fach="M")
    assert isinstance(ergebnis, list)
    assert any(e["pfad"].endswith("bruchrechnen.md") for e in ergebnis)


# ---------------------------------------------------------------------------
# Folder convention + alias table (against the committed fixture tree)
# ---------------------------------------------------------------------------


def test_alias_table_deckt_die_vier_faecher_und_kurzformen_ab():
    assert DI.FACH_ALIAS["mathematik"] == "M"
    assert DI.FACH_ALIAS["deutsch"] == "D"
    assert DI.FACH_ALIAS["englisch"] == "E"
    assert DI.FACH_ALIAS["sachunterricht"] == "SU"
    for kurz, code in (("m", "M"), ("d", "D"), ("e", "E"), ("su", "SU")):
        assert DI.FACH_ALIAS[kurz] == code


def test_fach_aus_ordner_unbekannt_gibt_none_nicht_fehler():
    assert DI.fach_aus_ordner("unbekanntesfach") is None
    assert DI.fach_aus_ordner("Mathematik") == "M"  # case-insensitive


def test_stufe_normalisieren_akzeptiert_nur_die_acht_gueltigen_token():
    assert DI.stufe_normalisieren("K2") == "K2"
    assert DI.stufe_normalisieren("sch3") == "SCH3"
    assert DI.stufe_normalisieren("S1") is None  # not a real level token (plan §4.8)
    assert DI.stufe_normalisieren("K5") is None


def test_unbekannter_ordner_ist_unassigned_nicht_verworfen():
    """The core E6-05 trap: an unrecognised folder must still surface with
    fach = stufe = None -- never silently dropped."""
    bericht = DI.sammle(_FIXTURE_ROOT)
    treffer = {e.pfad: e for e in bericht.treffer}
    unbekannt = treffer[str(Path("unbekanntesfach") / "sonstiges.md")]
    assert unbekannt.fach is None
    assert unbekannt.stufe is None
    assert unbekannt.herkunft == "docs"
    assert unbekannt.amtlich is False

    ohne_fachordner = treffer["lernnotizen.md"]
    assert ohne_fachordner.fach is None
    assert ohne_fachordner.stufe is None


def test_readme_wird_nie_als_lernaufgabe_gelistet():
    bericht = DI.sammle(_FIXTURE_ROOT)
    assert all(e.pfad != "README.md" for e in bericht.treffer)
    assert all(e.pfad != "README.md" for e in bericht.uebersprungen)


def test_fach_und_stufe_filter_ueber_die_ordnerkonvention():
    bericht = DI.sammle(_FIXTURE_ROOT, fach="M", stufe="K2")
    pfade = {e.pfad for e in bericht.treffer}
    assert str(Path("mathematik") / "K2" / "bruchrechnen.md") in pfade
    # geometrie__...md has no stufe folder (2 path parts) -- subject-wide,
    # so it is *not* excluded by an explicit stufe filter either.
    assert any(p.endswith("geometrie__AT.LP23.SEK1.M.EBENERAUM.K2.01.md") for p in pfade)


def test_fach_akzeptiert_vollen_shard_schluessel():
    """``fach="SEK1.M"`` (the shard key finde_differenzierung passes) must
    resolve to the bare subject code "M" against the folder convention,
    since docs/ folders never encode a band."""
    ueber_shard = {e.pfad for e in DI.sammle(_FIXTURE_ROOT, fach="SEK1.M").treffer}
    ueber_code = {e.pfad for e in DI.sammle(_FIXTURE_ROOT, fach="M").treffer}
    assert ueber_shard == ueber_code
    assert ueber_shard  # non-empty -- proves the resolution actually matched something


def test_native_txt_wird_gelesen_und_nicht_als_konvertiert_markiert():
    bericht = DI.sammle(_FIXTURE_ROOT, fach="D")
    (treffer,) = bericht.treffer
    assert treffer.format == "txt"
    assert treffer.konvertiert is False
    assert "Deutschunterricht" in treffer.text


# ---------------------------------------------------------------------------
# Competence binding -- filename suffix (precedence) and frontmatter
# ---------------------------------------------------------------------------


def test_kompetenz_id_aus_dateinamen_suffix():
    bericht = DI.sammle(_FIXTURE_ROOT, fach="M", stufe="K2")
    treffer = next(e for e in bericht.treffer if e.pfad.endswith("geometrie__AT.LP23.SEK1.M.EBENERAUM.K2.01.md"))
    assert treffer.kompetenz_id == "AT.LP23.SEK1.M.EBENERAUM.K2.01"
    assert treffer.titel == "Geometrie-Zusatzblatt"


def test_kompetenz_id_aus_frontmatter_und_titel_aus_frontmatter():
    bericht = DI.sammle(_FIXTURE_ROOT, fach="M")
    treffer = next(e for e in bericht.treffer if e.pfad.endswith("frontmatter_bindung.md"))
    assert treffer.kompetenz_id == "AT.LP23.SEK1.M.ZAHLEN.K3.01"
    assert treffer.titel == "Frontmatter Bindung"
    # The frontmatter block itself must not leak into the displayed text.
    assert "kompetenz_id:" not in treffer.text
    assert "Freier Text" in treffer.text


def test_kompetenz_id_bindung_hat_vorrang_vor_ordnerfilter():
    """A file bound to a specific competence ID must surface for a query
    naming that ID even when the query's fach/stufe would otherwise exclude
    it by folder location -- the plan's stated precedence."""
    bericht = DI.sammle(
        _FIXTURE_ROOT, fach="D", stufe="K4", kompetenz_id="AT.LP23.SEK1.M.EBENERAUM.K2.01"
    )
    pfade = {e.pfad for e in bericht.treffer}
    assert str(Path("mathematik") / "K2" / "geometrie__AT.LP23.SEK1.M.EBENERAUM.K2.01.md") in pfade


def test_ohne_bindung_bleibt_kompetenz_id_none_nie_erfunden():
    bericht = DI.sammle(_FIXTURE_ROOT, fach="M", stufe="K2")
    treffer = next(e for e in bericht.treffer if e.pfad.endswith("bruchrechnen.md"))
    assert treffer.kompetenz_id is None


# ---------------------------------------------------------------------------
# Origin marking -- "Teacher material appears marked as teacher-supplied"
# ---------------------------------------------------------------------------


def test_jeder_treffer_ist_als_lehrkraft_material_markiert():
    bericht = DI.sammle(_FIXTURE_ROOT)
    assert bericht.treffer  # sanity: the fixture tree is non-empty
    for e in bericht.treffer:
        assert e.herkunft == "docs"
        assert e.amtlich is False


def test_finde_lernaufgaben_gibt_dieselbe_markierung_ueber_kompetenz_py():
    ergebnisse = K.finde_lernaufgaben(fach="SEK1.M", docs_root=_FIXTURE_ROOT)
    assert ergebnisse
    for e in ergebnisse:
        assert e["herkunft"] == "docs"
        assert e["amtlich"] is False
        assert set(e) >= {
            "titel", "pfad", "fach", "stufe", "kompetenz_id", "format",
            "konvertiert", "text", "bytes", "tokens_approx", "herkunft", "amtlich",
        }


# ---------------------------------------------------------------------------
# .cache/ exclusion
# ---------------------------------------------------------------------------


def test_cache_ordner_wird_nie_als_quelle_gelesen(tmp_path):
    (tmp_path / ".cache").mkdir()
    (tmp_path / ".cache" / "sollte_nie_erscheinen.md").write_text("x", encoding="utf-8")
    (tmp_path / "mathematik").mkdir()
    (tmp_path / "mathematik" / "echt.md").write_text("# Echt\ntext", encoding="utf-8")

    bericht = DI.sammle(tmp_path)
    pfade = {e.pfad for e in bericht.treffer}
    assert pfade == {str(Path("mathematik") / "echt.md")}


# ---------------------------------------------------------------------------
# .docx conversion (python-docx, an already-accepted runtime dependency)
# ---------------------------------------------------------------------------


docx = pytest.importorskip("docx")


def _schreibe_docx(pfad: Path) -> None:
    dokument = docx.Document()
    dokument.add_heading("Konvertiertes Kapitel", level=1)
    dokument.add_paragraph("Ein Absatz mit richtigem Fließtext.")
    tabelle = dokument.add_table(rows=1, cols=2)
    tabelle.rows[0].cells[0].text = "Spalte A"
    tabelle.rows[0].cells[1].text = "Spalte B"
    dokument.save(str(pfad))


def test_docx_wird_konvertiert_und_gecacht(tmp_path):
    ordner = tmp_path / "mathematik"
    ordner.mkdir()
    quelle = ordner / "altehandreichung.docx"
    _schreibe_docx(quelle)

    bericht = DI.sammle(tmp_path, fach="M")
    (treffer,) = bericht.treffer
    assert treffer.format == "docx"
    assert treffer.konvertiert is True
    assert "# Konvertiertes Kapitel" in treffer.text
    assert "Ein Absatz mit richtigem Fließtext." in treffer.text
    assert "Spalte A | Spalte B" in treffer.text

    cache_datei = tmp_path / ".cache" / "mathematik" / "altehandreichung.docx.md"
    assert cache_datei.is_file()
    assert cache_datei.read_text(encoding="utf-8") == treffer.text

    # Source stays untouched.
    assert quelle.read_bytes()  # still a valid, unmodified docx (would raise if truncated)
    docx.Document(str(quelle))  # re-openable -- proves it was never rewritten


def test_docx_konvertierung_wird_bei_gueltigem_cache_nicht_erneut_aufgerufen(tmp_path, monkeypatch):
    ordner = tmp_path / "mathematik"
    ordner.mkdir()
    quelle = ordner / "cachetest.docx"
    _schreibe_docx(quelle)

    DI.sammle(tmp_path, fach="M")  # first call -- populates the cache

    aufrufe = []
    original = DI._konvertiere_docx

    def zaehlend(pfad):
        aufrufe.append(pfad)
        return original(pfad)

    monkeypatch.setattr(DI, "_konvertiere_docx", zaehlend)
    DI.sammle(tmp_path, fach="M")  # second call -- must hit the cache
    assert aufrufe == []


def test_docx_ungueltige_datei_wird_als_unusable_geloggt_nicht_fatal(tmp_path):
    ordner = tmp_path / "mathematik"
    ordner.mkdir()
    (ordner / "kaputt.docx").write_bytes(b"das ist kein echtes docx")

    bericht = DI.sammle(tmp_path, fach="M")
    assert bericht.treffer == []
    (eintrag,) = bericht.uebersprungen
    assert eintrag["pfad"] == str(Path("mathematik") / "kaputt.docx")
    assert "konvertierbar" in eintrag["grund"] or "DOCX" in eintrag["grund"]


# ---------------------------------------------------------------------------
# PDF extraction seam -- no library shipped; logged unusable, never fatal
# ---------------------------------------------------------------------------


def test_pdf_ohne_installierten_extraktor_wird_geloggt_nicht_fatal(tmp_path):
    ordner = tmp_path / "mathematik"
    ordner.mkdir()
    (ordner / "gescannt.pdf").write_bytes(b"%PDF-1.4\n...keine echten Textobjekte...")

    bericht = DI.sammle(tmp_path, fach="M")
    assert bericht.treffer == []
    (eintrag,) = bericht.uebersprungen
    assert eintrag["pfad"] == str(Path("mathematik") / "gescannt.pdf")
    assert "PDF" in eintrag["grund"]

    # The measured, current-environment fact this decision rests on: no PDF
    # library is installed, so every registered extractor returns None.
    assert DI.extrahiere_pdf_text(ordner / "gescannt.pdf") is None


def test_pdf_extraktions_naht_ist_pluggbar_ohne_neue_abhaengigkeit(tmp_path, monkeypatch):
    """Proves the seam contract (`_PDF_EXTRAKTOREN`) without adding a real
    PDF dependency: a fake extractor dropped into the tuple is picked up
    exactly the way a future real one would be."""
    ordner = tmp_path / "mathematik"
    ordner.mkdir()
    quelle = ordner / "kuenftig-extrahierbar.pdf"
    quelle.write_bytes(b"%PDF-1.4\nirrelevant fuer den Fake-Extraktor")

    def fake_extraktor(pfad: Path) -> str | None:
        return "Text aus einem zukuenftigen PDF-Extraktor."

    monkeypatch.setattr(DI, "_PDF_EXTRAKTOREN", (fake_extraktor,))
    bericht = DI.sammle(tmp_path, fach="M")
    (treffer,) = bericht.treffer
    assert treffer.text == "Text aus einem zukuenftigen PDF-Extraktor."
    assert treffer.format == "pdf"
    assert treffer.konvertiert is True


def test_pdf_extraktor_der_wirft_wird_wie_scheitern_behandelt(tmp_path, monkeypatch):
    ordner = tmp_path / "mathematik"
    ordner.mkdir()
    (ordner / "fehlerhaft.pdf").write_bytes(b"%PDF-1.4\n")

    def kaputter_extraktor(pfad: Path) -> str | None:
        raise RuntimeError("simulierter Absturz eines Drittanbieter-Extraktors")

    monkeypatch.setattr(DI, "_PDF_EXTRAKTOREN", (kaputter_extraktor,))
    bericht = DI.sammle(tmp_path, fach="M")
    assert bericht.treffer == []
    assert bericht.uebersprungen  # logged, not raised


# ---------------------------------------------------------------------------
# Limits: size, file count, token budget -- all enforced *and* observable
# ---------------------------------------------------------------------------


def test_datei_ueber_groessenlimit_wird_uebersprungen_und_geloggt(tmp_path):
    ordner = tmp_path / "mathematik"
    ordner.mkdir()
    (ordner / "riesig.md").write_text("x" * 100, encoding="utf-8")
    (ordner / "klein.md").write_text("# Klein\ny", encoding="utf-8")

    bericht = DI.sammle(tmp_path, fach="M", max_dateigroesse_bytes=10)
    pfade_treffer = {e.pfad for e in bericht.treffer}
    assert str(Path("mathematik") / "klein.md") in pfade_treffer
    assert str(Path("mathematik") / "riesig.md") not in pfade_treffer
    grund = next(u["grund"] for u in bericht.uebersprungen if u["pfad"].endswith("riesig.md"))
    assert "Limit" in grund or "Byte" in grund


def test_dateilimit_greift_und_verwirft_nach_relevanz_mit_log(tmp_path):
    ordner = tmp_path / "mathematik"
    ordner.mkdir()
    for i in range(5):
        (ordner / f"blatt{i}.md").write_text(f"# Blatt {i}\ntext", encoding="utf-8")

    bericht = DI.sammle(tmp_path, fach="M", max_dateien=2)
    assert len(bericht.treffer) == 2
    assert len(bericht.verworfen) == 3
    for eintrag in bericht.verworfen:
        assert "Dateilimit" in eintrag["grund"]
    # Nothing is unaccounted for: every candidate is either a hit or logged
    # as dropped -- never silently missing.
    alle_pfade = {e.pfad for e in bericht.treffer} | {e["pfad"] for e in bericht.verworfen}
    assert len(alle_pfade) == 5


def test_relevanz_rangiert_kompetenz_id_treffer_vor_dem_dateilimit(tmp_path):
    """When more candidates exist than the file cap allows, an explicit
    competence-ID binding must survive the cut ahead of unbound files."""
    ordner = tmp_path / "mathematik"
    ordner.mkdir()
    for i in range(3):
        (ordner / f"unbound{i}.md").write_text(f"# U{i}\ntext", encoding="utf-8")
    (ordner / "gebunden__AT.LP23.SEK1.M.ZAHLEN.K2.01.md").write_text("# Ziel\ntext", encoding="utf-8")

    bericht = DI.sammle(tmp_path, fach="M", kompetenz_id="AT.LP23.SEK1.M.ZAHLEN.K2.01", max_dateien=1)
    assert len(bericht.treffer) == 1
    assert bericht.treffer[0].kompetenz_id == "AT.LP23.SEK1.M.ZAHLEN.K2.01"


def test_token_budget_greift_und_verwirft_mit_log(tmp_path):
    ordner = tmp_path / "mathematik"
    ordner.mkdir()
    # ~40 tokens each (160 bytes / 4) -- three of them exceed a 50-token budget.
    for i in range(3):
        (ordner / f"blatt{i}.md").write_text("# T\n" + ("wort " * 40), encoding="utf-8")

    bericht = DI.sammle(tmp_path, fach="M", token_budget=50)
    assert len(bericht.treffer) == 1
    assert len(bericht.verworfen) == 2
    for eintrag in bericht.verworfen:
        assert "Token" in eintrag["grund"]


def test_einzelner_treffer_ueber_budget_wird_trotzdem_geliefert(tmp_path):
    """A lone, highest-ranked candidate that alone exceeds the budget is
    still returned -- an empty result would be strictly worse -- but it is
    the only one, and the fact is logged, not hidden."""
    ordner = tmp_path / "mathematik"
    ordner.mkdir()
    (ordner / "riesig.md").write_text("# T\n" + ("wort " * 400), encoding="utf-8")

    bericht = DI.sammle(tmp_path, fach="M", token_budget=10)
    assert len(bericht.treffer) == 1
    assert bericht.treffer[0].tokens_approx > 10


# ---------------------------------------------------------------------------
# approx_tokens -- the same bytes/4 heuristic as data-pipeline/build_dataset.py
# ---------------------------------------------------------------------------


def test_approx_tokens_ist_bytes_durch_vier_und_mindestens_eins():
    assert DI.approx_tokens("") == 1
    assert DI.approx_tokens("x" * 8) == 2
    assert DI.approx_tokens("x") == 1
