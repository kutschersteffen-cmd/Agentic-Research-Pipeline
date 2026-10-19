"""Phase 3 extraction: one fact from one stored source document through extract_one_field, then the code checks."""

from __future__ import annotations

import asyncio
import math
from datetime import date

from arp.config import Settings
from arp.extraction import field_graph
from arp.extraction.extractor_agent import PeriodValue
from arp.schemas.common import Citation, DocType, DocumentChunk
from arp.transition_barrier import extraction
from arp.transition_barrier.facts import pdf_pages
from arp.transition_barrier.rule_book import load_rule_book
from tests.transition_barrier_helpers import DOCS, FIXTURES, QUOTES, FactStub, fixture_pdf

CELL = "Steel, European Union, STL-R1"
BOOK, _ = load_rule_book(FIXTURES)
FACTS = {f.id: f for f in BOOK.criteria["STL-R1"].facts}
SETTINGS = Settings(hybrid_retrieval_enabled=False)
DOC_IDS = {"D1": 1, "D2": 2, "D3": 3, "D4": 4}


def doc(name: str, *, html: bool = False) -> dict:
    """The stored-document dict Task 2 returns, built from the fixture without a database."""
    title, tier, as_of = DOCS[name]
    pages = [QUOTES[name][min(QUOTES[name])]] if html else pdf_pages(fixture_pdf(name))
    return {
        "id": DOC_IDS[name], "source_key": name.lower(), "url": f"https://example.org/{name}", "title": title,
        "publisher": "Fixture", "tier": tier, "as_of": date.fromisoformat(as_of), "content_key": f"key-{name}",
        "content_type": "text/html" if html else "application/pdf", "page_texts": pages, "html": html,
        "fetched_at": None,
    }


def pv(value, quote: str, unit: str | None = "USD/tCO2", *, period: str | None = None, page=None, location=None):
    cite = Citation(doc_id="", doc_type=DocType.OTHER, quote=quote, page=page, location=location)
    return PeriodValue(value=value, raw_value_text=quote, unit_text=unit, period_text=period, citations=[cite])


def run(fact: str, d: dict, answer: PeriodValue | None):
    stub = FactStub({(fact, d["title"]): answer} if answer else {}, {f"tbsrc_{d['id']}": d["title"]}.__getitem__)
    out = asyncio.run(extraction.extract(
        FACTS[fact], CELL, d, BOOK.conversions, llm=stub, verifier_llm=stub, settings=SETTINGS,
    ))
    return out, stub


def test_counted_value():
    out, _ = run("price", doc("D1"), pv(72, QUOTES["D1"][12]))
    assert (out.value, out.unit, out.page, out.counted, out.reason) == (72, "USD/tCO2", 12, True, None)
    assert out.extracted is None and out.quote == QUOTES["D1"][12] and out.as_of is None


def test_quote_not_in_any_passage():  # AC-26
    out, _ = run("price", doc("D1"), pv(99, "The effective carbon price was USD 99/tCO2."))
    assert (out.counted, out.reason, out.page) == (False, "Quote not found in source", None)


def test_number_not_in_quote():  # AC-28
    out, _ = run("price", doc("D1"), pv(72, QUOTES["D1"][4]))
    assert (out.counted, out.reason, out.page) == (False, "Number not in quote", 4)


def test_news_cannot_ground():  # AC-29
    out, _ = run("price", doc("D4"), pv(72, QUOTES["D4"][1]))
    assert (out.counted, out.reason, out.value) == (False, "News cannot ground a fact", 72)


def test_page_comes_from_grounding():  # AC-148
    out, _ = run("price", doc("D1"), pv(72, QUOTES["D1"][12], page=5))
    assert out.page == 12 and out.counted


def test_converted_with_document_year():  # AC-30
    out, _ = run("price", doc("D1"), pv(66.9, QUOTES["D1"][17], "CNY/tCO2"))
    assert out.counted and out.reason is None and out.unit == "USD/tCO2"
    assert math.isclose(out.value, 66.9 * 0.14) and out.extracted == "66.9 CNY/tCO2"


def test_converted_with_own_as_of():  # AC-32
    out, _ = run("price", doc("D1"), pv(66.9, QUOTES["D1"][17], "CNY/tCO2", period="2024-06-30"))
    assert out.counted and math.isclose(out.value, 66.9 * 0.139) and out.extracted == "66.9 CNY/tCO2"
    assert out.as_of == date(2024, 6, 30)


def test_no_rate_for_own_year():  # AC-33
    out, _ = run("price", doc("D1"), pv(66.9, QUOTES["D1"][17], "CNY/tCO2", period="2023-06-30"))
    assert (out.counted, out.reason) == (False, "No CNY to USD rate for 2023 or earlier")
    assert (out.value, out.unit, out.extracted) == (66.9, "CNY/tCO2", None)


def test_unit_not_convertible():  # AC-34
    out, _ = run("price", doc("D1"), pv(66.9, QUOTES["D1"][19], "KRW/tCO2"))
    assert (out.counted, out.reason) == (False, "Unit not convertible: KRW/tCO2")


def test_html_has_locator_not_page():  # AC-9
    out, _ = run("levy", doc("D2", html=True), pv(True, QUOTES["D2"][3], None, location="Art. 36"))
    assert (out.value, out.page, out.locator, out.counted, out.reason) == (True, None, "Art. 36", True, None)


def test_passage_not_shown(monkeypatch):  # Review Focus 4: the quote is in the document, not in a shown passage
    d = doc("D1")
    sd = extraction.source_document(d)
    p4_start, p5_start = sd.page_breaks[3], sd.page_breaks[4]
    shown = DocumentChunk(
        chunk_id=f"chk_{sd.doc_id}_{p4_start}_{p5_start}", doc_id=sd.doc_id, company_id=sd.company_id,
        doc_type=sd.doc_type, text=sd.full_text[p4_start:p5_start], char_start=p4_start, char_end=p5_start,
    )
    assert QUOTES["D1"][12] in sd.full_text and QUOTES["D1"][12] not in shown.text
    monkeypatch.setattr(field_graph, "field_evidence", lambda *a, **k: [shown])
    out, _ = run("price", d, pv(72, QUOTES["D1"][12]))
    assert (out.counted, out.reason) == (False, "Quote not found in source")


def test_not_found():
    out, stub = run("price", doc("D1"), None)
    assert out is None and stub.calls.count("ExtractionDraft") == 1


def test_source_document_pages():
    sd = extraction.source_document(doc("D1"))
    pages = doc("D1")["page_texts"]
    assert sd.doc_id == "tbsrc_1" and sd.full_text == "\n".join(pages)
    assert sd.page_breaks[:2] == [0, len(pages[0]) + 1] and len(sd.page_breaks) == len(pages)
    assert extraction.source_document(doc("D2", html=True)).page_breaks == []


def test_field_for_and_fingerprint():
    f = extraction.field_for(FACTS["price"], CELL, BOOK.conversions)
    assert (f.name, f.data_type.value, f.unit, f.seed_keywords) == ("price", "number", None, ["effective", "carbon", "price"])
    assert f.extraction_instructions.startswith(FACTS["price"].definition)
    assert f.extraction_instructions.endswith("Give the as-of date of the value in period_text when the source states one.")
    assert "(for example CNY/tCO2)" in f.extraction_instructions
    changed = FACTS["price"].model_copy(update={"definition": "Something else."})
    assert extraction.fingerprint(FACTS["price"]) != extraction.fingerprint(changed)
    assert extraction.fingerprint(FACTS["price"]) == extraction.fingerprint(FACTS["price"].model_copy())


def test_unit_without_currency_gets_plain_sentence():
    gw = FACTS["price"].model_copy(update={"id": "capacity", "unit": "GW"})
    text = extraction.field_for(gw, CELL, BOOK.conversions).extraction_instructions
    assert "Give unit_text as GW when the source uses that unit." in text and "currency" not in text


def test_sides_match_exactly():  # "USD million" is not the conversion target "USD"
    spend = FACTS["price"].model_copy(update={"unit": "USD million/yr"})
    text = extraction.field_for(spend, CELL, BOOK.conversions).extraction_instructions
    assert "Give unit_text as USD million/yr when the source uses that unit." in text


def test_both_sides_named_in_the_unit_sentence():
    gallon = {"from": "gallon", "to": "litre", "rate": 3.785411784, "year": 1959}
    fuel = FACTS["price"].model_copy(update={"unit": "USD/litre"})
    text = extraction.field_for(fuel, CELL, [*BOOK.conversions, gallon]).extraction_instructions
    assert (
        "Give unit_text in the source's own unit, written like USD/litre; code converts CNY, gallon "
        "(for example CNY/litre, USD/gallon)."
    ) in text
