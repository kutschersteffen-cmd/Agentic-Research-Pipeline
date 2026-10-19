"""Golden set runner: precision and coverage of phase-3 extraction against labelled cases (AC-122)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pypdf import PdfReader
from typer.testing import CliRunner

from arp.checks.numeric import candidates
from arp.cli.transition_barrier import transition_barrier_app
from arp.config import Settings, get_settings
from arp.extraction.extractor_agent import PeriodValue
from arp.schemas.common import Citation, DocType
from arp.transition_barrier import dataset, golden
from arp.transition_barrier.rule_book import load_rule_book
from tests.transition_barrier_helpers import FIXTURES, QUOTES, FactStub, fixture_pdf

# D1-floor.pdf is D1 again: the stub answers one value per (fact, document), and price is asked twice
FILES = {"D1.pdf": "D1", "D1-floor.pdf": "D1", "D2.pdf": "D2"}


def case(fact, document, value, page, unit=None):
    return {"code": "STL-R1", "region": "European Union", "fact": fact, "document": document, "value": value, "unit": unit, "page": page}


def answer(value, quote, unit=None):
    cite = Citation(doc_id="", doc_type=DocType.OTHER, quote=quote)
    return PeriodValue(value=value, raw_value_text=quote, unit_text=unit, citations=[cite])


CASES = [
    case("applies", "D1.pdf", True, 4),
    case("price", "D1.pdf", 72, 12, "USD/tCO2"),
    case("price", "D1-floor.pdf", 30, 13, "USD/tCO2"),
    case("levy", "D2.pdf", True, 3),
]
ANSWERS = {
    ("applies", "D1.pdf"): answer(True, QUOTES["D1"][4]),
    ("price", "D1.pdf"): answer(72, QUOTES["D1"][12], "USD/tCO2"),
    ("price", "D1-floor.pdf"): answer(30, QUOTES["D1"][13], "USD/tCO2"),
    ("levy", "D2.pdf"): answer(True, QUOTES["D2"][3]),
}


@pytest.fixture
def run_golden(tmp_path, monkeypatch):
    monkeypatch.setenv("ARP_TRANSITION_BARRIER_DATA_DIR", str(FIXTURES))
    get_settings.cache_clear()
    dataset.reset_caches()
    docs = tmp_path / "documents"
    docs.mkdir()
    for name, doc in FILES.items():
        (docs / name).write_bytes(fixture_pdf(doc))

    def run(cases, answers=ANSWERS, *args):
        path = tmp_path / "cases.json"
        path.write_text(json.dumps(cases))
        titles = {f"tbsrc_{i}": name for i, name in enumerate(dict.fromkeys(c["document"] for c in cases), 1)}
        stub = FactStub(answers, titles.__getitem__)
        monkeypatch.setattr(golden, "_llms", lambda settings: (stub, stub))
        monkeypatch.setattr("arp.cli.transition_barrier.get_settings", lambda: Settings(hybrid_retrieval_enabled=False))
        return CliRunner().invoke(
            transition_barrier_app, ["golden", "--cases", str(path), "--documents-dir", str(docs), *args]
        )

    yield run
    get_settings.cache_clear()
    dataset.reset_caches()


def test_golden_fails_below_precision(run_golden):  # AC-122
    cases = [*CASES[:2], case("price", "D1-floor.pdf", 31, 13, "USD/tCO2"), CASES[3]]
    out = run_golden(cases, ANSWERS, "--min-precision", "0.95", "--min-coverage", "0.5")
    assert out.stdout.strip() == "precision 0.75, coverage 1" and out.exit_code == 1


def test_golden_passes(run_golden):
    out = run_golden(CASES, ANSWERS, "--min-precision", "0.95", "--min-coverage", "0.5")
    assert out.stdout.strip() == "precision 1, coverage 1" and out.exit_code == 0


def test_wrong_page_is_incorrect(run_golden):
    cases = [case("price", "D1.pdf", 72, 5, "USD/tCO2")]
    out = run_golden(cases, ANSWERS, "--min-precision", "0.5", "--min-coverage", "0.5")
    assert out.stdout.strip() == "precision 0, coverage 1" and out.exit_code == 1


def test_not_found_lowers_coverage_only(run_golden):
    answers = {k: v for k, v in ANSWERS.items() if k[0] != "levy"}
    out = run_golden(CASES, answers, "--min-precision", "0.95", "--min-coverage", "0.9")
    assert out.stdout.strip() == "precision 1, coverage 0.75" and out.exit_code == 1


def test_numbers_compare_at_two_decimals_half_up(run_golden):
    cases = [case("price", "D1.pdf", 72.01, 12, "USD/tCO2")]
    answers = {("price", "D1.pdf"): answer(72.005, QUOTES["D1"][15], "USD/tCO2")}  # D1 p. 15 holds 72.005
    cases[0]["page"] = 15
    out = run_golden(cases, answers, "--min-precision", "1", "--min-coverage", "1")
    assert out.stdout.strip() == "precision 1, coverage 1" and out.exit_code == 0


def test_counted_value_against_absent_label_is_incorrect(run_golden):  # any fact type, never a crash
    cases = [case("price", "D1.pdf", None, None, "USD/tCO2"), case("applies", "D1.pdf", None, None)]
    out = run_golden(cases, ANSWERS, "--min-precision", "0.5", "--min-coverage", "0.5")
    assert out.stdout.strip() == "precision 0, coverage 1" and out.exit_code == 1


G = Path(__file__).parent / "golden" / "transition_barrier"


def _squash(text: str) -> str:
    return "".join(text.split())


def test_golden_set_shape():  # G for AC-123: the drafted labels hold before the owner's check
    cases = golden.load_cases(G / "cases.json")
    book = load_rule_book(Path(golden.__file__).parent / "data")[0]
    rates = [1.0] + [r["rate"] for r in book.conversions]
    rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in (G / "LABELS.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("| ") and line.split("|")[1].strip().isdigit()
    ]  # LABELS.md case table: #, cell, fact, value, unit, document, page, quote
    assert len(cases) >= 40 and len({c.document for c in cases}) >= 12
    for case, (_, _, _, _, _, document, page, quote) in zip(cases, rows, strict=True):
        facts = {f.id: f for f in book.criteria[case.code].facts}
        assert case.fact in facts and facts[case.fact].type, case  # a measured fact, not a computed one
        path = G / "documents" / case.document
        assert path.is_file() and path.stat().st_size < 5 * 1024 * 1024, case
        assert (document, page) == (case.document, str(case.page or "—")), case
        if case.value is None:  # absent from the document: a counted value for it is wrong
            assert case.page is None, case
            continue
        # the text facts.pdf_pages (and so the scorer) gets for that page, without parsing the whole file
        text = PdfReader(path).pages[case.page - 1].extract_text() or ""
        assert _squash(quote) in _squash(text), case
        if facts[case.fact].type == "number":  # the label is a figure in the quote, converted at most once
            assert any(round(n * r, 2) == case.value for n in candidates(quote) for r in rates), case
