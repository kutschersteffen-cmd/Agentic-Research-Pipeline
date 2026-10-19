"""Phase 3 derivations: fetch the registered sources, extract each fact per stored document, count the checked values."""

from __future__ import annotations

import json
import shutil
from datetime import date

import pytest
from fastapi.testclient import TestClient

from arp.api.auth import current_user
from arp.api.deps import get_document_content_store, get_run_store, settings_dep
from arp.api.main import app
from arp.config import Settings, get_settings
from arp.extraction.extractor_agent import PeriodValue
from arp.schemas.common import Citation, DocType
from arp.storage.document_store import DocumentContentStore
from arp.storage.run_store import RunStore
from arp.transition_barrier import RUN_TYPE, clock, dataset, derivation
from arp.transition_barrier.rule_book import sign_rule_book
from tests.postgres_helpers import pg_dsn
from tests.transition_barrier_helpers import (
    A_ANALYST,
    B_APPROVER,
    CELL,
    D_URLS,
    DOCS,
    FIXTURES,
    PRICE,
    QUOTES,
    FactStub,
    derive,
    enter_fact,
    fetch_stub,
    fixture_pdf,
    pdf_with,
)

pytestmark = pytest.mark.usefixtures("pg")
D1, D2, D3, D4 = (DOCS[d][0] for d in ("D1", "D2", "D3", "D4"))
SETTINGS = Settings(
    second_review_sample_rate=0.0, bulk_accept_sample_rate=0.0, transition_barrier_refresh_enabled=True,
    hybrid_retrieval_enabled=False,
)
AC7 = (
    "H: Effective carbon price >= 50 USD/tCO2 and Border levy in force is Yes. Effective carbon price = 72 USD/tCO2 "
    "(EU ETS Market Report 2026, p. 12): pass. Border levy in force = Yes (CBAM Regulation 2023/956, p. 3): pass."
)


@pytest.fixture
def env(tmp_path, monkeypatch, pg):
    target = tmp_path / "transition_barrier"
    shutil.copytree(FIXTURES, target)
    monkeypatch.setenv("ARP_TRANSITION_BARRIER_DATA_DIR", str(target))
    get_settings.cache_clear()
    dataset.reset_caches()
    monkeypatch.setattr(clock, "today", lambda: date(2026, 10, 20))
    rs = RunStore(pg, tmp_path / "runs")
    app.dependency_overrides[get_run_store] = lambda: rs
    app.dependency_overrides[get_document_content_store] = lambda: DocumentContentStore(tmp_path / "docs", dsn=pg_dsn())
    app.dependency_overrides[settings_dep] = lambda: SETTINGS
    yield target
    for dep in (get_run_store, get_document_content_store, settings_dep, current_user):
        app.dependency_overrides.pop(dep, None)
    get_settings.cache_clear()
    dataset.reset_caches()


@pytest.fixture
def client(env):
    return TestClient(app)


def pv(value, quote: str, unit: str | None = "USD/tCO2", *, period: str | None = None, page=None, location=None):
    cite = Citation(doc_id="", doc_type=DocType.OTHER, quote=quote, page=page, location=location)
    return PeriodValue(value=value, raw_value_text=quote, unit_text=unit, period_text=period, citations=[cite])


def answers(**price) -> dict:
    """The defaults extracted: price 72 (D1, p. 12), applies (D1, p. 4), levy (D2, p. 3); `price=` replaces the D1 price."""
    out = {
        ("price", D1): price.get("price", pv(72, QUOTES["D1"][12])),
        ("applies", D1): pv(True, QUOTES["D1"][4], None),
        ("levy", D2): pv(True, QUOTES["D2"][3], None),
    }
    return {k: v for k, v in out.items() if v is not None}


def extracting(monkeypatch, found: dict, served=None) -> tuple[FactStub, list[str]]:
    stub = FactStub(found)
    monkeypatch.setattr(derivation, "_llms", lambda settings: (stub, stub))
    return stub, fetch_stub(monkeypatch, served)


def as_user(client, who):
    app.dependency_overrides[current_user] = lambda: who
    return client


def latest(client):
    r = as_user(client, A_ANALYST).get(CELL)
    assert r.status_code == 200, r.text
    return r.json()["latest_result"]


def run(client):
    return derive(as_user(client, A_ANALYST))


def clause(result, fact, level="H"):
    return next(c for c in result["levels"][level]["conditions"] if c["fact"] == fact)


def value(result, fact, document=D1):
    return next(v for v in result["values"] if v["fact"] == fact and v["document"] == document)


def test_extracted_defaults_rate_h(client, monkeypatch):
    extracting(monkeypatch, answers())
    run(client)
    result = latest(client)
    assert (result["rating"], result["confidence"], result["notes"]) == ("H", "high", [])
    assert result["levels"]["H"]["detail"] == AC7  # AC-7
    v = value(result, "price")
    assert v["id"].startswith("x") and (v["machine_checked"], v["entered_by"], v["counted"]) == (True, None, True)


def test_ac9_html_has_locator(client, monkeypatch):
    html = f"<html><body><article><p>{QUOTES['D2'][3]}</p></article></body></html>".encode()
    found = answers() | {("levy", D2): pv(True, QUOTES["D2"][3], None, location="Art. 36")}
    extracting(monkeypatch, found, {D_URLS["D2"]: (html, "text/html; charset=utf-8", None)})
    run(client)
    result = latest(client)
    v = value(result, "levy", D2)
    assert (v["page"], v["locator"]) == (None, "Art. 36")
    assert clause(result, "levy")["clause"] == "Border levy in force = Yes (CBAM Regulation 2023/956, Art. 36): pass."


def test_ac26_ac27_quote_not_found(client, monkeypatch):
    extracting(monkeypatch, answers(price=pv(72, "The effective carbon price was USD 72/tCO2 in Narnia.")))
    run(client)
    result = latest(client)
    v = value(result, "price")
    assert (v["counted"], v["reason"]) == (False, "Quote not found in source")
    assert result["rating"] == "not_rated"


def test_ac28_number_not_in_quote(client, monkeypatch):
    extracting(monkeypatch, answers(price=pv(72, QUOTES["D1"][4])))
    run(client)
    v = value(latest(client), "price")
    assert (v["counted"], v["reason"]) == (False, "Number not in quote")


def test_ac29_news_cannot_ground(client, env, monkeypatch):
    path = env / "criteria_schema.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    sources = raw["criteria"][0]["primary_sources"]
    url = "https://example.org/carbon-weekly"
    sources.append({**sources[2], "key": "carbon_weekly", "tier": "news", "source_name": D4, "url": url})
    path.write_text(json.dumps(raw), encoding="utf-8")
    dataset.reset_caches()
    extracting(monkeypatch, answers() | {("price", D4): pv(72, QUOTES["D4"][1])}, {url: (fixture_pdf("D4"), "application/pdf", DOCS["D4"][2])})
    run(client)
    v = value(latest(client), "price", D4)
    assert (v["counted"], v["reason"]) == (False, "News cannot ground a fact")


def test_ac148_page_from_grounding(client, monkeypatch):
    extracting(monkeypatch, answers(price=pv(72, QUOTES["D1"][12], page=5)))
    run(client)
    assert value(latest(client), "price")["page"] == 12


def test_ac30_converted_with_document_year(client, monkeypatch):
    extracting(monkeypatch, answers(price=pv(66.9, QUOTES["D1"][17], "CNY/tCO2")))
    run(client)
    result = latest(client)
    assert "9.37 USD/tCO2 (66.9 CNY/tCO2)" in clause(result, "price")["clause"]
    assert result["rating"] == "L"


def test_ac31_converted_shown_rounded_fails(client, monkeypatch):
    extracting(monkeypatch, answers(price=pv(71.42, QUOTES["D1"][18], "CNY/tCO2")))
    run(client)
    result = latest(client)
    m = clause(result, "price", "M")
    assert "10 USD/tCO2 (71.42 CNY/tCO2)" in m["clause"] and m["outcome"] == "fail"
    assert result["rating"] == "L"


def test_ac32_converted_with_own_as_of(client, monkeypatch):
    extracting(monkeypatch, answers(price=pv(66.9, QUOTES["D1"][17], "CNY/tCO2", period="2024-06-30")))
    run(client)
    assert "9.3 USD/tCO2 (66.9 CNY/tCO2)" in clause(latest(client), "price")["clause"]


def test_ac33_no_rate_for_year(client, monkeypatch):
    extracting(monkeypatch, answers(price=pv(66.9, QUOTES["D1"][17], "CNY/tCO2", period="2023-06-30")))
    run(client)
    v = value(latest(client), "price")
    assert (v["counted"], v["reason"]) == (False, "No CNY to USD rate for 2023 or earlier")


def test_ac34_unit_not_convertible(client, monkeypatch):
    extracting(monkeypatch, answers(price=pv(66.9, QUOTES["D1"][19], "KRW/tCO2")))
    run(client)
    v = value(latest(client), "price")
    assert (v["counted"], v["reason"]) == (False, "Unit not convertible: KRW/tCO2")


def test_second_derivation_makes_no_model_call(client, monkeypatch):
    stub, _ = extracting(monkeypatch, answers())
    run(client)
    calls, ids = len(stub.calls), [v["id"] for v in latest(client)["values"]]
    assert calls > 0
    run(client)
    assert len(stub.calls) == calls and [v["id"] for v in latest(client)["values"]] == ids


def test_changed_fact_definition_is_extracted_again(client, env, monkeypatch):
    stub, _ = extracting(monkeypatch, answers())
    run(client)
    calls, old = len(stub.calls), value(latest(client), "price")["id"]
    path = env / "rule_book.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    next(f for f in raw["criteria"]["STL-R1"]["facts"] if f["id"] == "price")["definition"] += " Net of free allocation."
    path.write_text(json.dumps(raw), encoding="utf-8")
    sign_rule_book(env, "owner", date(2026, 10, 18))
    dataset.reset_caches()
    run(client)
    result = latest(client)
    assert len(stub.calls) > calls and [v["id"] for v in result["values"] if v["fact"] == "price"] != [old]
    assert len([v for v in result["values"] if v["fact"] == "price"]) == 1 and result["rating"] == "H"


def test_refresh_off_reads_stored_documents(client, monkeypatch):
    stub, requested = extracting(monkeypatch, answers())
    run(client)
    calls, ids = len(stub.calls), [v["id"] for v in latest(client)["values"]]
    requested.clear()
    app.dependency_overrides[settings_dep] = lambda: SETTINGS.model_copy(update={"transition_barrier_refresh_enabled": False})
    run(client)
    result = latest(client)
    assert requested == [] and len(stub.calls) == calls and [v["id"] for v in result["values"]] == ids
    assert (result["rating"], result["notes"]) == ("H", ["Sources not fetched: refresh is disabled"])


def test_no_documents_no_model_client(client, monkeypatch):  # AC-11
    def boom(settings):
        raise AssertionError("a model client was built")

    monkeypatch.setattr(derivation, "_llms", boom)
    app.dependency_overrides[settings_dep] = lambda: SETTINGS.model_copy(update={"transition_barrier_refresh_enabled": False})
    b = as_user(client, B_APPROVER)
    for fact, v, doc, page in (("price", 72, "D1", 12), ("applies", True, "D1", 4), ("levy", True, "D2", 3)):
        assert enter_fact(b, fact, v, doc, page).status_code == 201
    run(client)
    assert latest(client)["rating"] == "H"


def test_llm_build_failure_fails_the_run(client, monkeypatch):
    fetch_stub(monkeypatch)

    def boom(settings):
        raise RuntimeError("no API key")

    monkeypatch.setattr(derivation, "_llms", boom)
    r = as_user(client, A_ANALYST).post("/api/transition-barrier/derive", json={"cells": [{"code": "STL-R1", "region": "European Union"}]})
    assert r.status_code >= 500
    [m] = app.dependency_overrides[get_run_store]().list_runs(RUN_TYPE)
    assert (m.status.value, m.error) == ("failed", "no API key")


def test_changed_document_voids_choice(client, monkeypatch):  # Review Focus 2
    stub, _ = extracting(monkeypatch, answers() | {("price", D3): pv(9, QUOTES["D3"][9])})
    run(client)
    assert latest(client)["rating"] == "conflict"
    chosen = value(latest(client), "price")["id"]
    r = as_user(client, A_ANALYST).post(f"{CELL}/choices", json={"fact": "price", "value_id": chosen, "reason": "newer data"})
    assert r.status_code == 201, r.text
    assert latest(client)["rating"] == "H"
    history = as_user(client, A_ANALYST).get(CELL).json()["history"]
    assert [h["value"] for h in history if h["kind"] == "choice"] == [f"72 USD/tCO2, {D1}"]
    pages = QUOTES["D1"] | {12: QUOTES["D1"][14]}
    fetch_stub(monkeypatch, {D_URLS["D1"]: (pdf_with([pages.get(n) for n in range(1, max(pages) + 1)]), "application/pdf", DOCS["D1"][2])})
    stub.answers[("price", D1)] = pv(45, PRICE.format(45))
    run(client)
    result = latest(client)
    assert result["rating"] == "conflict"
    assert value(result, "price")["id"] != chosen and value(result, "price")["value"] == 45


@pytest.mark.parametrize(("analyst", "page", "rating"), [(72, 12, "H"), (30, 13, "conflict")])
def test_extracted_and_analyst_same_source(client, monkeypatch, analyst, page, rating):  # Review Focus 3
    extracting(monkeypatch, answers())
    assert enter_fact(as_user(client, B_APPROVER), "price", analyst, "D1", page).status_code == 201
    run(client)
    result = latest(client)
    assert result["rating"] == rating
    assert sorted(v["machine_checked"] and v["entered_by"] is None for v in result["values"] if v["fact"] == "price") == [False, True]


def test_payload_lists_not_counted(client, monkeypatch):
    extracting(monkeypatch, answers(price=pv(72, QUOTES["D1"][4])))
    run_id = run(client)
    [item] = as_user(client, A_ANALYST).get(f"/api/review/items?run_id={run_id}").json()["items"]
    assert item["payload"]["not_counted"] == [f"Effective carbon price = 72 USD/tCO2 ({D1}): Number not in quote"]


def test_same_text_new_bytes_no_model_call_and_choice_holds(client, monkeypatch):  # HTML and generated PDFs
    stub, _ = extracting(monkeypatch, answers() | {("price", D3): pv(9, QUOTES["D3"][9])})
    run(client)
    chosen = value(latest(client), "price")["id"]
    r = as_user(client, A_ANALYST).post(f"{CELL}/choices", json={"fact": "price", "value_id": chosen, "reason": "newer data"})
    assert r.status_code == 201, r.text
    calls = len(stub.calls)
    fetch_stub(monkeypatch, {D_URLS[d]: (fixture_pdf(d) + b"\n", "application/pdf", DOCS[d][2]) for d in D_URLS})
    run(client)
    result = latest(client)
    assert len(stub.calls) == calls and value(result, "price")["id"] == chosen and result["rating"] == "H"


def test_not_fetched_note_reaches_the_result(client, monkeypatch):
    extracting(monkeypatch, answers(), {D_URLS["D3"]: (b"{}", "application/json", None)})
    run(client)
    assert latest(client)["notes"] == [f"Not fetched: {D3} (unsupported type application/json)"]


def edit_rule_book(env, edit) -> None:
    path = env / "rule_book.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    edit(raw)
    path.write_text(json.dumps(raw), encoding="utf-8")
    sign_rule_book(env, "owner", date(2026, 10, 18))
    dataset.reset_caches()


FX = {"title": "Fixture rate", "url": "https://example.org/fx"}


def test_new_conversion_row_counts_a_stored_value(client, env, monkeypatch):  # checks run when values are read
    stub, _ = extracting(monkeypatch, answers(price=pv(66.9, QUOTES["D1"][19], "KRW/tCO2")))
    run(client)
    assert value(latest(client), "price")["reason"] == "Unit not convertible: KRW/tCO2"
    calls = len(stub.calls)
    edit_rule_book(env, lambda raw: raw["conversions"].append({"from": "KRW", "to": "USD", "rate": 0.001, "year": 2020, "source": FX}))
    run(client)
    v = value(latest(client), "price")
    assert len(stub.calls) == calls and (v["counted"], v["reason"], v["extracted"]) == (True, None, "66.9 KRW/tCO2")


def test_changed_rate_reaches_a_stored_value(client, env, monkeypatch):
    stub, _ = extracting(monkeypatch, answers(price=pv(66.9, QUOTES["D1"][17], "CNY/tCO2")))
    run(client)
    assert latest(client)["rating"] == "L"
    calls = len(stub.calls)
    edit_rule_book(env, lambda raw: raw["conversions"].append({"from": "CNY", "to": "USD", "rate": 1.0, "year": 2026, "source": FX}))
    run(client)
    result = latest(client)
    assert len(stub.calls) == calls and "66.9 USD/tCO2 (66.9 CNY/tCO2)" in clause(result, "price")["clause"]
    assert result["rating"] == "H"


def test_retiered_source_reaches_a_stored_value(client, env, monkeypatch):
    stub, _ = extracting(monkeypatch, answers())
    run(client)
    calls = len(stub.calls)
    path = env / "criteria_schema.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    next(s for s in raw["criteria"][0]["primary_sources"] if s["key"] == "eu_ets_report")["tier"] = "news"
    path.write_text(json.dumps(raw), encoding="utf-8")
    dataset.reset_caches()
    run(client)
    v = value(latest(client), "price")
    assert len(stub.calls) == calls and (v["counted"], v["reason"]) == (False, "News cannot ground a fact")
