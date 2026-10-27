"""Financials and TNFD runs write one walkthrough trace file per company (argus-walkthrough spec)."""

from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from arp.api.deps import get_run_store
from arp.api.main import app
from arp.extraction import financials_pipeline, tnfd_pipeline
from arp.extraction.financials_pipeline import create_financials_extraction_run, execute_financials_extraction_run
from arp.extraction.tnfd_extractor_agent import DisclosureDraft, TNFDExtractionDraft
from arp.extraction.tnfd_pipeline import create_tnfd_extraction_run, execute_tnfd_extraction_run
from arp.ingestion.registry import DocumentSourceRegistry
from arp.schemas.common import Citation, CompanyRef, DocType, SourceDocument
from arp.storage.run_store import RunStore
from tests import test_financials_extraction_pipeline as fin
from tests import test_tnfd_extraction_pipeline as tnfd

pytestmark = pytest.mark.usefixtures("pg")

COMPANY = CompanyRef(company_id="c1", name="Acme Corp", ticker="ACME")
KEYS = {"doc_id", "char_start", "char_end", "section"}


def _tnfd_responses(doc):
    draft = TNFDExtractionDraft(
        disclosures=[DisclosureDraft(
            recommendation_id="governance.A", disclosed=True, summary="The Board reviews nature-related risks quarterly.",
            summary_citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="The Board reviews nature-related dependencies, impacts, risks and opportunities on a quarterly basis")],
            materiality_basis="double",
        )],
        confidence=0.9,
    )
    return {"TNFDExtractionDraft": [draft], "TNFDVerifierOutput": [tnfd._agreeing_verifier()]}


def _fin_responses(doc):
    draft, verifier = fin._single_pair_responses(doc)
    return {"FinancialsExtractionDraft": [draft], "FinancialsVerifierOutput": [verifier]}


async def _fin_run(tmp_path, llm, doc):
    settings = fin._settings(tmp_path).model_copy(update={"hybrid_retrieval_enabled": False})
    store = RunStore(settings.postgres_dsn, settings.runs_dir)
    run_id = create_financials_extraction_run([COMPANY], settings, store)
    await execute_financials_extraction_run(
        run_id, [COMPANY], llm=llm, registry=DocumentSourceRegistry([fin._FixedDocSource([doc])]),
        settings=settings, run_store=store,
    )
    return store, run_id


async def _tnfd_run(tmp_path, llm, doc):
    settings = tnfd._settings(tmp_path).model_copy(update={"hybrid_retrieval_enabled": False})
    store = RunStore(settings.postgres_dsn, settings.runs_dir)
    run_id = create_tnfd_extraction_run([COMPANY], "FY2025", settings, store)
    await execute_tnfd_extraction_run(
        run_id, [COMPANY], "FY2025", llm=llm, registry=DocumentSourceRegistry([tnfd._FixedDocSource([doc])]),
        settings=settings, run_store=store,
    )
    return store, run_id


def _trace(store, run_id) -> dict:
    return json.loads((store.run_dir(run_id) / "traces" / "c1.json").read_text())


def _check_record(trace: dict) -> None:
    assert set(trace) == {"record"}
    rec = trace["record"]
    assert set(rec) == {"passages", "extractor", "verifier"}
    assert rec["passages"] and all(set(p) == KEYS for p in rec["passages"])
    assert set(rec["extractor"]) == {"model", "prompt_version", "answer"}
    assert set(rec["verifier"]) == {"model", "prompt_version", "answer"}
    assert rec["extractor"]["answer"] and rec["verifier"]["answer"]


async def test_financials_trace_record(tmp_path, fake_llm):  # AC-9
    doc = fin._doc()
    store, run_id = await _fin_run(tmp_path, fake_llm(_fin_responses(doc)), doc)
    trace = _trace(store, run_id)
    _check_record(trace)
    assert trace["record"]["extractor"]["answer"]["capex"]["total"]["value"] == 450


async def test_tnfd_trace_record(tmp_path, fake_llm):
    doc = tnfd._doc()
    store, run_id = await _tnfd_run(tmp_path, fake_llm(_tnfd_responses(doc)), doc)
    trace = _trace(store, run_id)
    _check_record(trace)
    assert trace["record"]["extractor"]["answer"]["disclosures"][0]["recommendation_id"] == "governance.A"


async def test_financials_call_count(tmp_path, fake_llm):  # AC-30
    doc = fin._doc()
    llm = fake_llm(_fin_responses(doc))
    await _fin_run(tmp_path, llm, doc)
    assert llm.calls == ["FinancialsExtractionDraft", "FinancialsVerifierOutput"]


async def test_tnfd_call_count(tmp_path, fake_llm):  # AC-65
    doc = tnfd._doc()
    llm = fake_llm(_tnfd_responses(doc))
    await _tnfd_run(tmp_path, llm, doc)
    assert llm.calls == ["TNFDExtractionDraft", "TNFDVerifierOutput"]


async def test_no_evidence_still_records_empty_trace(tmp_path, fake_llm):
    doc = SourceDocument(company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, title="10-K", full_text="We sell shoes.")
    llm = fake_llm({})
    store, run_id = await _fin_run(tmp_path, llm, doc)
    assert _trace(store, run_id) == {"record": {"passages": [], "extractor": None, "verifier": None}}
    assert llm.calls == []


def _results(store, url: str) -> dict:
    app.dependency_overrides[get_run_store] = lambda: store
    try:
        r = TestClient(app).get(url)
    finally:
        app.dependency_overrides.pop(get_run_store, None)
    assert r.status_code == 200, r.text
    return r.json()


def _normalised(body: dict, run_id: str) -> str:
    return re.sub(r'"\d{4}-\d\d-\d\dT[^"]*"', '"TS"', json.dumps(body, sort_keys=True).replace(run_id, "RUN"))


async def test_financials_results_unchanged(tmp_path, fake_llm, monkeypatch):  # AC-63 stand-in
    doc = fin._doc()
    store, traced = await _fin_run(tmp_path / "a", fake_llm(_fin_responses(doc)), doc)
    assert (store.run_dir(traced) / "traces" / "c1.json").exists()
    real = financials_pipeline._extract_company_financials

    async def _no_sink(*a, trace_sink=None, **kw):  # as on main: no sink, nothing written
        return await real(*a, **kw)

    monkeypatch.setattr(financials_pipeline, "_extract_company_financials", _no_sink)
    store2, plain = await _fin_run(tmp_path / "b", fake_llm(_fin_responses(doc)), doc)
    assert not (store2.run_dir(plain) / "traces").exists()
    a = _results(store, f"/api/financials/runs/{traced}/results")
    b = _results(store2, f"/api/financials/runs/{plain}/results")
    assert _normalised(a, traced) == _normalised(b, plain)


async def test_tnfd_results_unchanged(tmp_path, fake_llm, monkeypatch):
    doc = tnfd._doc()
    store, traced = await _tnfd_run(tmp_path / "a", fake_llm(_tnfd_responses(doc)), doc)
    assert (store.run_dir(traced) / "traces" / "c1.json").exists()
    real = tnfd_pipeline._extract_company_tnfd

    async def _no_sink(*a, trace_sink=None, **kw):
        return await real(*a, **kw)

    monkeypatch.setattr(tnfd_pipeline, "_extract_company_tnfd", _no_sink)
    store2, plain = await _tnfd_run(tmp_path / "b", fake_llm(_tnfd_responses(doc)), doc)
    assert not (store2.run_dir(plain) / "traces").exists()
    a = _results(store, f"/api/tnfd/runs/{traced}/results")
    b = _results(store2, f"/api/tnfd/runs/{plain}/results")
    assert _normalised(a, traced) == _normalised(b, plain)
