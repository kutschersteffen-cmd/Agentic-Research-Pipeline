"""Data-point extraction runs write one walkthrough trace file per company (argus-walkthrough spec)."""

from __future__ import annotations

import json
import os
import re
from collections import Counter

import pytest
from fastapi.testclient import TestClient

from arp.api.deps import get_run_store
from arp.api.main import app
from arp.extraction import pipeline
from arp.extraction.adjudicator import AdjudicatorOutput
from arp.extraction.extractor_agent import ExtractionDraft, FieldDraft, GroupDraft, PeriodValue
from arp.extraction.pipeline import _extract_company, create_extraction_run, execute_extraction_run
from arp.extraction.verifier_agent import VerifierOutput
from arp.golden_set.runner import run_golden_set
from arp.golden_set.schema import GoldenSetCase
from arp.ingestion.registry import DocumentSourceRegistry
from arp.research.revenue_exposure.resolver import extract_schema_fields
from arp.research.taxonomy_sources.empirical import gather_corpus_from_extraction
from arp.retention import cleanup
from arp.schemas.common import Citation, CompanyRef, DocType, SourceDocument
from arp.schemas.datapoints import DataPointSchema, DerivedRule, ExtractedField, FieldDataType, FieldDefinition
from arp.storage.run_store import RunStore
from tests.test_extraction_pipeline import _FixedDocSource, _schema, _settings
from tests.test_transition_alignment_plan_extraction import _plan, _record, _script
from tests.transition_alignment_helpers import ta_dirs  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("pg")

COMPANY = CompanyRef(company_id="c1", name="Acme Corp", ticker="ACME")
TEXT = "Acme Corp report. In fiscal 2025, we invested $120 million in green capex across our facilities."
DOC = SourceDocument(company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="ESG", full_text=TEXT)
KEYS = {"doc_id", "char_start", "char_end", "section"}
AGREE = VerifierOutput(agrees=True, confidence=0.95, notes="ok")
SCHEMA = _schema()  # one shared copy: _schema() mints a new field id per call


def _draft(value, quote, doc=DOC) -> ExtractionDraft:
    return ExtractionDraft(values=[PeriodValue(
        value=value, raw_value_text=str(value), unit_text="USD million", period_text="fiscal 2025",
        citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote=quote)],
    )], confidence=0.95)


def _ac1_llm(fake_llm):
    return fake_llm({"ExtractionDraft": [_draft(120.0, "invested $120 million in green capex")], "VerifierOutput": [AGREE]})


async def _run(tmp_path, llm, *, schema=None, docs=(DOC,), settings=None, prepare=None):
    settings = settings or _settings(tmp_path).model_copy(update={"hybrid_retrieval_enabled": False})
    store = RunStore(settings.postgres_dsn, settings.runs_dir)
    schema = schema or SCHEMA
    run_id = create_extraction_run(schema, [COMPANY], settings, store, trial=True)
    if prepare:
        prepare(store.run_dir(run_id))
    await execute_extraction_run(
        run_id, schema, [COMPANY], llm=llm, registry=DocumentSourceRegistry([_FixedDocSource(list(docs))]),
        settings=settings, run_store=store,
    )
    return store, run_id


def _trace_file(store, run_id, company_id="c1"):
    return store.run_dir(run_id) / "traces" / f"{company_id}.json"


def _results(store, run_id) -> dict:
    app.dependency_overrides[get_run_store] = lambda: store
    try:
        r = TestClient(app).get(f"/api/extraction/runs/{run_id}/results")
    finally:
        app.dependency_overrides.pop(get_run_store, None)
    assert r.status_code == 200, r.text
    return r.json()


async def test_run_writes_one_trace_file_per_company(tmp_path, fake_llm):  # AC-1
    llm = _ac1_llm(fake_llm)
    store, run_id = await _run(tmp_path, llm)
    trace = json.loads(_trace_file(store, run_id).read_text())
    assert set(trace) == {"fields"}
    field_id = SCHEMA.fields[0].field_id
    assert set(trace["fields"]) == {field_id}
    e = trace["fields"][field_id]
    assert (e["grouped"], e["skipped"], e["vision"], e["adjudicator"]) == (False, None, None, None)
    assert (e["verifier"]["blind"], e["verifier"]["verdict"]) == (False, None)
    assert e["extractor"]["answer"]["values"][0]["value"] == 120
    assert e["passages"] and all(set(p) == KEYS for p in e["passages"])
    positions = [llm.prompts[0].index(TEXT[p["char_start"]:p["char_end"]]) for p in e["passages"]]
    assert positions == sorted(positions)


async def test_trace_file_is_small(tmp_path, fake_llm):  # AC-31
    store, run_id = await _run(tmp_path, _ac1_llm(fake_llm))
    assert _trace_file(store, run_id).stat().st_size <= 8192


GROUP_DOC = SourceDocument(company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="ESG",
                           full_text="Spills: 10 incidents in FY2024.\n\nFines: 20 penalties in FY2024.")


def _num_field(name: str, **kw) -> FieldDefinition:
    return FieldDefinition(field_id=name, name=name, description=name, data_type=FieldDataType.NUMBER,
                           extraction_instructions=name, seed_keywords=[name], **kw)


def _group_script():
    return {"GroupDraft": [GroupDraft(fields=[
        FieldDraft(field_id="spills", draft=_draft(10, "Spills: 10 incidents", GROUP_DOC)),
        FieldDraft(field_id="fines", draft=_draft(20, "Fines: 20 penalties", GROUP_DOC)),
    ])], "VerifierOutput": [AGREE] * 2}


async def _grouped(tmp_path, llm, traces=None):
    settings = _settings(tmp_path).model_copy(update={"extraction_group_size": 2, "hybrid_retrieval_enabled": False})
    schema = DataPointSchema(name="S", fields=[_num_field("spills"), _num_field("fines")])
    kw = {} if traces is None else {"traces": traces}
    return await _extract_company(
        COMPANY, schema, registry=DocumentSourceRegistry([_FixedDocSource([GROUP_DOC])]), llm=llm, settings=settings, **kw,
    )


async def test_grouped_fields_share_passages(tmp_path, fake_llm):  # AC-8
    traces = {}
    await _grouped(tmp_path, fake_llm(_group_script()), traces)
    a, b = traces["fields"]["spills"], traces["fields"]["fines"]
    assert a["grouped"] is True and b["grouped"] is True
    assert a["passages"] and a["passages"] == b["passages"]
    assert [v["value"] for v in a["extractor"]["answer"]["values"]] == [10]
    assert [v["value"] for v in b["extractor"]["answer"]["values"]] == [20]


async def test_derived_and_held_entries(tmp_path, fake_llm, monkeypatch):  # AC-34, AC-35
    async def _stub(company_name, field, **_):
        return [ExtractedField(field_id=field.field_id, field_name=field.name, value=True, confidence=0.95)], False, []

    with monkeypatch.context() as m:
        m.setattr(pipeline, "extract_one_field", _stub)
        base = FieldDefinition(name="x", description="", data_type=FieldDataType.BOOLEAN, extraction_instructions="",
                               seed_keywords=["x"])
        schema = DataPointSchema(name="Derived", fields=[
            base.model_copy(update={"field_id": "a", "name": "a"}),
            base.model_copy(update={"field_id": "b", "name": "b"}),
            base.model_copy(update={"field_id": "d", "name": "d", "derived_rule": DerivedRule(all_of=["a", "b"])}),
        ])
        traces = {}
        await _extract_company(COMPANY, schema, registry=DocumentSourceRegistry([_FixedDocSource([DOC])]), llm=None,
                               settings=_settings(tmp_path), traces=traces)
    assert traces["fields"]["d"]["skipped"] == "derived"
    assert traces["fields"]["d"]["passages"] == [] and traces["fields"]["d"]["extractor"] is None

    held = SourceDocument(company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT,
                          title="Acme Energy GmbH Sustainability Report 2025", full_text=TEXT)
    llm = fake_llm({})
    store, run_id = await _run(tmp_path, llm, docs=(held,))
    trace = json.loads(_trace_file(store, run_id).read_text())
    assert llm.calls == []
    assert {k: e["skipped"] for k, e in trace["fields"].items()} == {
        f.field_id: "documents_held" for f in SCHEMA.fields}


@pytest.mark.usefixtures("ta_dirs")
async def test_plan_documents_recorded(tmp_path, fake_llm):  # AC-41, AC-66
    plan = _plan()
    store, run_id, _, llm = await _record(tmp_path, fake_llm, _script(plan))
    rows = [f for r in store.read_results(run_id) for f in r["fields"] if f["basis"] and f["basis"].startswith("action:")]
    assert len({r["basis"] for r in rows}) == 2
    trace = json.loads(_trace_file(store, run_id, "c").read_text())
    entry = trace["plans"]["P1"]
    assert entry["passages"] and all(set(p) == KEYS for p in entry["passages"])
    assert entry["extractor"]["answer"] == plan.model_dump(mode="json")
    assert set(entry["extractor"]) == {"model", "prompt_version", "answer"}
    assert llm.calls.count("PlanDraft") == 1


async def test_trace_write_failure_does_not_fail_the_run(tmp_path, fake_llm):  # AC-14
    store, run_id = await _run(
        tmp_path, _ac1_llm(fake_llm), prepare=lambda run_dir: (run_dir / "traces").write_text("not a folder"),
    )
    manifest = store.load_manifest(run_id)
    assert manifest.status.value == "completed" and manifest.completed_count == 1
    assert [r["company_id"] for r in _results(store, run_id)["results"]] == ["c1"]
    assert [e["company_id"] for e in store.read_events(run_id) if e["type"] == "trace_write_failed"] == ["c1"]


def _trace_files(root):
    return list(root.glob("**/traces/*.json"))


async def test_research_callers_write_no_trace(tmp_path, fake_llm):  # AC-24
    settings = _settings(tmp_path).model_copy(update={"hybrid_retrieval_enabled": False})
    registry = DocumentSourceRegistry([_FixedDocSource([DOC])])
    llm = _ac1_llm(fake_llm)
    await extract_schema_fields(COMPANY, SCHEMA, [SCHEMA.fields[0].field_id], documents=[DOC], registry=registry,
                                llm=llm, settings=settings)
    assert llm.calls  # the extraction really ran
    theme = SourceDocument(company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="ESG",
                           full_text="Acme Corp builds green capex projects: wind farms and solar parks.")
    llm2 = fake_llm({"ExtractionDraft": [ExtractionDraft(values=[], confidence=0.9)], "VerifierOutput": [AGREE]})
    await gather_corpus_from_extraction("green capex", "d", [COMPANY], DocumentSourceRegistry([_FixedDocSource([theme])]),
                                        llm2, settings)
    assert _trace_files(tmp_path) == []


async def test_golden_set_writes_no_trace(tmp_path, fake_llm, monkeypatch):  # AC-23
    monkeypatch.chdir(tmp_path)
    case = GoldenSetCase(case_id="g1", description="d", company_name="Acme Corp", field=SCHEMA.fields[0],
                         document_text=TEXT, expected_value=120.0)
    report = await run_golden_set([case], llm=_ac1_llm(fake_llm), fuzzy_threshold=0.9, confidence_review_threshold=0.6)
    assert report.total == 1
    assert _trace_files(tmp_path) == []


async def test_model_call_counts_unchanged(tmp_path, fake_llm):  # AC-28, AC-29, AC-66, AC-73
    llm = _ac1_llm(fake_llm)
    await _run(tmp_path / "ac1", llm)
    assert Counter(llm.calls) == {"ExtractionDraft": 1, "VerifierOutput": 1}

    llm = fake_llm({"ExtractionDraft": [_draft(2.8, "invested $120 million in green capex"),
                                        _draft(2.794, "invested $120 million in green capex")],
                    "AdjudicatorOutput": [AdjudicatorOutput(settled=False, notes="unclear")]})
    schema = SCHEMA.model_copy(update={"fields": [SCHEMA.fields[0].model_copy(update={"high_risk": True})]})
    store, run_id = await _run(tmp_path / "ac2", llm, schema=schema)
    assert Counter(llm.calls) == {"ExtractionDraft": 2, "AdjudicatorOutput": 1}  # extractor, blind verifier, adjudicator
    e = json.loads(_trace_file(store, run_id).read_text())["fields"][schema.fields[0].field_id]
    assert (e["verifier"]["blind"], e["verifier"]["answer"]["values"][0]["value"]) == (True, 2.794)
    assert (e["verifier"]["verdict"]["agrees"], e["adjudicator"]["answer"]["settled"]) == (False, False)

    with_sink, without = fake_llm(_group_script()), fake_llm(_group_script())
    await _grouped(tmp_path, with_sink, {})
    await _grouped(tmp_path, without)
    assert Counter(with_sink.calls) == Counter(without.calls) == {"GroupDraft": 1, "VerifierOutput": 2}


def _normalised(body: dict, run_id: str) -> str:
    """Two runs differ only in run id and timestamps."""
    return re.sub(r'"\d{4}-\d\d-\d\dT[^"]*"', '"TS"', json.dumps(body, sort_keys=True).replace(run_id, "RUN"))


async def test_results_unchanged_by_traces(tmp_path, fake_llm, monkeypatch):  # AC-25 stand-in
    store, traced = await _run(tmp_path / "a", _ac1_llm(fake_llm))
    assert _trace_file(store, traced).exists()
    real = pipeline._extract_company

    async def _no_traces(*a, traces=None, **kw):  # as on main: no sink, nothing written
        return await real(*a, **kw)

    monkeypatch.setattr(pipeline, "_extract_company", _no_traces)
    store2, plain = await _run(tmp_path / "b", _ac1_llm(fake_llm))
    assert not (store2.run_dir(plain) / "traces").exists()
    assert _normalised(_results(store, traced), traced) == _normalised(_results(store2, plain), plain)


async def test_retention_removes_traces(tmp_path, fake_llm):  # AC-71
    settings = _settings(tmp_path).model_copy(update={"hybrid_retrieval_enabled": False,
                                                      "blob_store_dir": tmp_path / "blobs"})
    store, run_id = await _run(tmp_path, _ac1_llm(fake_llm), settings=settings)
    assert _trace_file(store, run_id).exists()
    before = _results(store, run_id)
    old = (settings.retention_runs_days + 1) * 86400
    for f in store.run_dir(run_id).rglob("*"):
        if f.is_file():
            t = f.stat().st_mtime - old
            os.utime(f, (t, t))
    cleanup(settings, apply=True)
    assert _trace_files(store.run_dir(run_id).parent) == []
    after = _results(store, run_id)
    # `field_names` comes from the run's schema.json, which retention removes with every other run file (as on main)
    before["results"][0].pop("field_names")
    assert after == before
