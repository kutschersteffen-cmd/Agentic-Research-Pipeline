"""GET /api/walkthrough/runs/{run_id}/companies/{company_id}: one row's walkthrough (argus-walkthrough spec)."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from arp.api.auth import authorize, current_user
from arp.api.deps import get_document_content_store, get_run_store, settings_dep
from arp.api.main import app
from arp.config import Settings
from arp.extraction.pipeline import load_run_schema
from arp.extraction.tnfd_extractor_agent import GeneralRequirementsDraft
from arp.extraction.verifier_agent import VerifierOutput
from arp.orchestration.review_queue import append_decision
from arp.review.quality import seed_known_answers
from arp.schemas.common import RunManifest
from arp.schemas.datapoints import DataPointSchema
from arp.schemas.review import ReviewDecision
from arp.storage.document_store import DocumentContentStore
from arp.storage.run_store import RunStore
from arp.walkthrough import trace
from tests import test_extraction_corrections_pipeline as corr
from tests import test_walkthrough_financials_tnfd as fintnfd
from tests.conftest import FakeLLMClient
from tests.postgres_helpers import pg_dsn
from tests.test_review_quality import _real_run, qenv  # noqa: F401 - qenv is a fixture
from tests.test_transition_alignment_plan_extraction import _plan, _record, _script
from tests.test_walkthrough_pipeline import DOC, SCHEMA, TEXT, _ac1_llm, _num_field, _run
from tests.transition_alignment_helpers import ta_dirs  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("pg")

FIELD_ID = SCHEMA.fields[0].field_id
KDOC = DOC.model_copy(update={"content_key": "k-walk", "parser_version": "p-walk"})
SETTINGS = Settings(anthropic_api_key="unused")
DEPS = (get_run_store, get_document_content_store, settings_dep)


def _walk(store, run_id, item, company_id="c1", *, content=None, **params):
    app.dependency_overrides[get_run_store] = lambda: store
    app.dependency_overrides[get_document_content_store] = lambda: content
    app.dependency_overrides[settings_dep] = lambda: SETTINGS
    try:
        return TestClient(app).get(f"/api/walkthrough/runs/{run_id}/companies/{company_id}",
                                   params={"item": item, **params})
    finally:
        for dep in DEPS:
            app.dependency_overrides.pop(dep, None)


def _ok(*a, **kw) -> dict:
    r = _walk(*a, **kw)
    assert r.status_code == 200, r.text
    return r.json()


def _results(store, url) -> dict:
    app.dependency_overrides[get_run_store] = lambda: store
    try:
        r = TestClient(app).get(url)
    finally:
        app.dependency_overrides.pop(get_run_store, None)
    assert r.status_code == 200, r.text
    return r.json()


def _company(store, run_id, kind="extraction", company_id="c1") -> dict:
    (rec,) = [r for r in _results(store, f"/api/{kind}/runs/{run_id}/results")["results"] if r["company_id"] == company_id]
    return rec


def _field_rows(store, run_id, field_id=FIELD_ID, company_id="c1") -> list[dict]:
    return [f for f in _company(store, run_id, company_id=company_id)["fields"] if f["field_id"] == field_id]


def _period(row) -> str:
    return row["period_end"] or "unspecified"


def _trace(store, run_id, company_id="c1") -> dict:
    return json.loads((store.run_dir(run_id) / "traces" / f"{company_id}.json").read_text())


def _content(tmp_path, doc=KDOC) -> DocumentContentStore:
    store = DocumentContentStore(tmp_path / "docstore", dsn=pg_dsn())
    if doc is not None:
        store.store(doc.content_key, key_kind="file", parser_version=doc.parser_version, source_suffix=".txt",
                    byte_size=len(doc.full_text), text=doc.full_text, page_breaks=[])
    return store


def _assert_not_recorded(body, reason):
    assert body["recorded"] is False and body["not_recorded_reason"] == reason
    assert body["passages"] == []
    assert [body[k] for k in ("extractor", "verifier", "adjudicator", "vision")] == [None] * 4


# --- runs written by hand, where a real run is overkill ---

OLD = (datetime.now(UTC) - timedelta(days=SETTINGS.retention_runs_days + 1)).isoformat()
F1 = _num_field("f1")


def _hand_run(store, run_id, *, created_at=None, fields=(), trace_data=None, schema_fields=(F1,)):
    store.save_manifest(RunManifest(run_id=run_id, run_type="extraction",
                                    **({"created_at": created_at} if created_at else {})))
    schema = DataPointSchema(schema_id="sch_hand", name="Hand", fields=list(schema_fields))
    (store.run_dir(run_id) / "schema.json").write_text(schema.model_dump_json())
    store.append_result(run_id, {"company_id": "c1", "name": "Acme Corp", "schema_id": "sch_hand", "run_id": run_id,
                                 "fields": list(fields), "documents": []})
    if trace_data:
        trace.write_trace(store, run_id, "c1", trace_data)


def _row(period_end="2025-12-31", reused_from_run=None, field_id="f1", **kw):
    return {"field_id": field_id, "field_name": field_id, "value": 5, "period_end": period_end,
            "reused_from_run": reused_from_run, **kw}


def _entry(field_id="f1", **kw):
    return trace.field_entry(field_id, extractor={"model": "m", "prompt_version": "v", "answer": {"values": []}}, **kw)


# --- data-point runs ---


async def test_recorded_field(tmp_path, fake_llm):  # AC-3
    content = _content(tmp_path)
    store, run_id = await _run(tmp_path, _ac1_llm(fake_llm), docs=(KDOC,))
    rows = _field_rows(store, run_id)
    body = _ok(store, run_id, FIELD_ID, content=content, period_end=_period(rows[0]))
    assert (body["recorded"], body["not_recorded_reason"], body["trace_run_id"]) == (True, None, run_id)
    assert (body["run_id"], body["run_type"], body["company_id"], body["company_name"], body["item"]) == (
        run_id, "extraction", "c1", "Acme Corp", FIELD_ID)
    assert body["item_name"] == SCHEMA.fields[0].name
    assert body["rows"] == rows
    entry = _trace(store, run_id)["fields"][FIELD_ID]
    assert body["passages"]
    assert [{k: p[k] for k in ("doc_id", "char_start", "char_end", "section")} for p in body["passages"]] == entry["passages"]
    for i, p in enumerate(body["passages"]):
        assert p["rank"] == i + 1
        assert p["text"] == TEXT[p["char_start"]:p["char_end"]]
        assert p["doc_title"] == "ESG"
    assert body["extractor"]["answer"]["values"][0]["value"] == 120
    assert (body["verifier"], body["adjudicator"], body["vision"], body["skipped"]) == (
        entry["verifier"], None, None, None)


async def test_old_run_before_traces(tmp_path, fake_llm):  # AC-4
    store, run_id = await _run(tmp_path, _ac1_llm(fake_llm))
    shutil.rmtree(store.run_dir(run_id) / "traces")
    rows = _field_rows(store, run_id)
    body = _ok(store, run_id, FIELD_ID, period_end=_period(rows[0]))
    _assert_not_recorded(body, "before_traces")
    assert body["trace_run_id"] == run_id
    assert body["rows"] == rows


async def _capex_runs(tmp_path, n):
    answers = {corr._field("Capex denominator"): ("cash-flow capex", "Capex denominator: cash-flow capex", None, None)}
    schema, docs = corr._capex("tc_capex_denominator"), [corr._doc(corr.DENOM_DOC)]
    runs = []
    for _ in range(n):
        run_id, store, _ = await corr._run(tmp_path, schema, docs, answers, trial=False)  # only non-trial runs are reused
        runs.append(run_id)
    return store, runs


async def test_reused_row_reads_origin(tmp_path):  # AC-5
    store, (run1, run2) = await _capex_runs(tmp_path, 2)
    [row] = _field_rows(store, run2, "tc_capex_denominator")
    assert row["reused_from_run"] == run1
    body = _ok(store, run2, "tc_capex_denominator", period_end=_period(row))
    assert (body["trace_run_id"], body["recorded"]) == (run1, True)
    assert body["extractor"] == _trace(store, run1)["fields"]["tc_capex_denominator"]["extractor"]
    assert body["rows"] == [row]


async def test_three_run_chain(tmp_path):  # AC-32
    store, (run1, run2, run3) = await _capex_runs(tmp_path, 3)
    [row] = _field_rows(store, run3, "tc_capex_denominator")
    assert row["reused_from_run"] == run2  # reuse names the latest run, so the chain has two hops
    body = _ok(store, run3, "tc_capex_denominator", period_end=_period(row))
    assert (body["trace_run_id"], body["recorded"]) == (run1, True)


def test_tagged_recorded(tmp_path, pg):  # AC-7
    store = RunStore(pg, tmp_path / "runs")
    _hand_run(store, "extraction_tag", fields=[_row(method="tagged")],
              trace_data={"fields": {"f1": trace.field_entry("f1", skipped="tagged")}})
    body = _ok(store, "extraction_tag", "f1", period_end="2025-12-31")
    assert (body["recorded"], body["skipped"], body["not_recorded_reason"]) == (True, "tagged", None)


async def test_no_evidence_recorded(tmp_path, fake_llm):  # AC-36
    schema = DataPointSchema(name="S", fields=[_num_field("zzzunmatched")])
    store, run_id = await _run(tmp_path, fake_llm({}), schema=schema)
    assert _trace(store, run_id)["fields"]["zzzunmatched"]["skipped"] == "no_evidence"
    [row] = _field_rows(store, run_id, "zzzunmatched")
    body = _ok(store, run_id, "zzzunmatched", period_end=_period(row))
    assert (body["recorded"], body["not_recorded_reason"], body["skipped"]) == (True, None, "no_evidence")


async def test_moved_row_reads_source_field(tmp_path):  # AC-37
    quote = "Capital expenditures for 2026 are estimated to be approximately $2.5 billion"
    answers = {corr._field("Total capex"): (2.5, quote, "USD billions", "2026")}
    schema = corr._capex("tc_capex_total", "tc_capex_total_planned")
    run_id, store, _ = await corr._run(tmp_path, schema, [corr._doc(f"Annual Report 2025. {quote}.")], answers,
                                       trial=False)
    [moved] = [r for r in _field_rows(store, run_id, "tc_capex_total_planned") if r["period_end"] == "2026-12-31"]
    assert [c["original"] for c in moved["corrections"]] == ["tc_capex_total"]
    fields = _trace(store, run_id)["fields"]
    assert fields["tc_capex_total_planned"]["extractor"] != fields["tc_capex_total"]["extractor"]
    body = _ok(store, run_id, "tc_capex_total_planned", period_end="2026-12-31")
    assert body["recorded"] is True
    assert body["extractor"] == fields["tc_capex_total"]["extractor"]


def test_expired(tmp_path, pg):  # AC-38
    store = RunStore(pg, tmp_path / "runs")
    _hand_run(store, "extraction_old", created_at=OLD, fields=[_row()])
    body = _ok(store, "extraction_old", "f1", period_end="2025-12-31")
    _assert_not_recorded(body, "expired")


def test_reused_from_expired_run(tmp_path, pg):  # AC-64
    store = RunStore(pg, tmp_path / "runs")
    _hand_run(store, "extraction_r1", created_at=OLD, fields=[_row()])
    _hand_run(store, "extraction_r2", fields=[_row(reused_from_run="extraction_r1")])
    body = _ok(store, "extraction_r2", "f1", period_end="2025-12-31")
    assert body["trace_run_id"] == "extraction_r1"
    _assert_not_recorded(body, "expired")


def test_chain_stops_on_period_mismatch(tmp_path, pg):  # Review Focus 5
    store = RunStore(pg, tmp_path / "runs")
    _hand_run(store, "extraction_p1", fields=[_row("2024-12-31")], trace_data={"fields": {"f1": _entry()}})
    _hand_run(store, "extraction_p2", fields=[_row("2025-12-31", reused_from_run="extraction_p1")])
    body = _ok(store, "extraction_p2", "f1", period_end="2025-12-31")
    assert body["trace_run_id"] == "extraction_p2"
    _assert_not_recorded(body, "before_traces")


async def test_write_failed(tmp_path, fake_llm):  # AC-15
    store, run_id = await _run(
        tmp_path, _ac1_llm(fake_llm), prepare=lambda run_dir: (run_dir / "traces").write_text("not a folder"),
    )
    [row, *_] = _field_rows(store, run_id)
    body = _ok(store, run_id, FIELD_ID, period_end=_period(row))
    _assert_not_recorded(body, "write_failed")


async def test_text_not_available(tmp_path, fake_llm):  # Review Focus 2
    store, run_id = await _run(tmp_path, _ac1_llm(fake_llm), docs=(KDOC,))
    [row, *_] = _field_rows(store, run_id)
    body = _ok(store, run_id, FIELD_ID, content=_content(tmp_path, doc=None), period_end=_period(row))
    assert body["recorded"] is True and body["passages"]
    assert all(p["text"] is None and p["doc_title"] == "ESG" for p in body["passages"])


# --- Financials and TNFD ---


async def test_financials_capex(tmp_path, fake_llm):  # AC-10
    doc = fintnfd.fin._doc()
    store, run_id = await fintnfd._fin_run(tmp_path, fake_llm(fintnfd._fin_responses(doc)), doc)
    body = _ok(store, run_id, "capex", period_end="2025-12-31")  # ignored for a section
    assert (body["recorded"], body["adjudicator"], body["run_type"], body["trace_run_id"]) == (
        True, None, "financials", run_id)
    assert body["rows"] == [_company(store, run_id, "financials")["capex"]]
    record = _trace(store, run_id)["record"]
    assert (body["extractor"], body["verifier"]) == (record["extractor"], record["verifier"])
    assert [p["rank"] for p in body["passages"]] == list(range(1, len(record["passages"]) + 1))


async def test_financials_old_run(tmp_path, fake_llm):  # AC-68
    doc = fintnfd.fin._doc()
    store, run_id = await fintnfd._fin_run(tmp_path, fake_llm(fintnfd._fin_responses(doc)), doc)
    shutil.rmtree(store.run_dir(run_id) / "traces")
    body = _ok(store, run_id, "capex")
    _assert_not_recorded(body, "before_traces")
    assert body["rows"] == [_company(store, run_id, "financials")["capex"]]


async def _tnfd(tmp_path, fake_llm, general_requirements=None):
    doc = fintnfd.tnfd._doc()
    script = fintnfd._tnfd_responses(doc)
    if general_requirements:
        draft = script["TNFDExtractionDraft"][0]
        script["TNFDExtractionDraft"] = [draft.model_copy(update={"general_requirements": general_requirements})]
    return await fintnfd._tnfd_run(tmp_path, fake_llm(script), doc)


async def test_tnfd_disclosures(tmp_path, fake_llm):  # AC-11
    store, run_id = await _tnfd(tmp_path, fake_llm)
    body = _ok(store, run_id, "disclosures")
    assert body["recorded"] is True
    disclosures = _company(store, run_id, "tnfd")["disclosures"]
    assert disclosures and body["rows"] == disclosures


async def test_tnfd_general_requirements_object(tmp_path, fake_llm):  # AC-12
    gr = GeneralRequirementsDraft(materiality_approach="double", disclosure_scope="direct_operations",
                                  location_specificity="site", iplc_engagement_described=False)
    store, run_id = await _tnfd(tmp_path, fake_llm, gr)
    expected = _company(store, run_id, "tnfd")["general_requirements"]
    assert expected is not None
    assert _ok(store, run_id, "general_requirements")["rows"] == [expected]


async def test_tnfd_general_requirements_none(tmp_path, fake_llm):  # AC-13
    store, run_id = await _tnfd(tmp_path, fake_llm)
    assert _company(store, run_id, "tnfd")["general_requirements"] is None
    assert _ok(store, run_id, "general_requirements")["rows"] == []


# --- transition-plan list fields ---


@pytest.mark.usefixtures("ta_dirs")
async def test_plan_row_by_basis(tmp_path, fake_llm):  # AC-42
    store, run_id, _, _ = await _record(tmp_path, fake_llm, _script(_plan()))
    fields = _company(store, run_id, company_id="c")["fields"]
    row = next(f for f in fields if (f["basis"] or "").startswith("action:"))
    body = _ok(store, run_id, row["field_id"], "c", period_end=_period(row), basis=row["basis"])
    assert body["recorded"] is True
    assert body["rows"] and body["rows"] == [f for f in fields
                                             if f["field_id"] == row["field_id"] and f["basis"] == row["basis"]]
    assert all(r["basis"] == row["basis"] for r in body["rows"])
    doc_id = row["citations"][0]["doc_id"]
    assert body["extractor"] == _trace(store, run_id, "c")["plans"][doc_id]["extractor"]
    assert (body["verifier"], body["adjudicator"]) == (None, None)


# --- status codes ---


@pytest.mark.usefixtures("ta_dirs")
async def test_missing_period_or_basis_is_422(tmp_path, fake_llm):  # AC-17
    store, run_id, _, _ = await _record(tmp_path / "plan", fake_llm, _script(_plan()))
    row = next(f for f in _company(store, run_id, company_id="c")["fields"] if (f["basis"] or "").startswith("action:"))
    assert _walk(store, run_id, row["field_id"], "c", period_end=_period(row)).status_code == 422
    store, run_id = await _run(tmp_path / "ac1", _ac1_llm(fake_llm))
    assert _walk(store, run_id, FIELD_ID).status_code == 422
    assert _walk(store, run_id, FIELD_ID, "c404").status_code == 404  # 404 checks come first


async def test_not_found_cases(tmp_path, fake_llm, pg):  # AC-16, AC-70
    p = {"period_end": "2025-12-31"}
    store, run_id = await _run(tmp_path / "dp", _ac1_llm(fake_llm))
    assert _walk(store, "extraction_nope", FIELD_ID, **p).status_code == 404
    assert not (tmp_path / "dp" / "runs" / "extraction_nope").exists()  # no folder made for an unknown run
    assert _walk(store, run_id, FIELD_ID, "c404", **p).status_code == 404
    assert _walk(store, run_id, "not_a_field", **p).status_code == 404
    assert _walk(store, run_id, "capex", **p).status_code == 404
    assert _walk(store, run_id, FIELD_ID, period_end="1999-12-31").status_code == 404  # AC-70

    hand = RunStore(pg, tmp_path / "hand" / "runs")
    _hand_run(hand, "extraction_two", fields=[_row()], schema_fields=(F1, _num_field("f2")))
    assert _walk(hand, "extraction_two", "f2", **p).status_code == 404

    fin_doc = fintnfd.fin._doc()
    fstore, fin_run = await fintnfd._fin_run(tmp_path / "fin", fake_llm(fintnfd._fin_responses(fin_doc)), fin_doc)
    assert _walk(fstore, fin_run, "disclosures", **p).status_code == 404
    tstore, tnfd_run = await _tnfd(tmp_path / "tnfd", fake_llm)
    assert _walk(tstore, tnfd_run, "capex", **p).status_code == 404


async def test_requires_sign_in(tmp_path, fake_llm):  # AC-18
    store, run_id = await _run(tmp_path, _ac1_llm(fake_llm))
    app.dependency_overrides.pop(authorize, None)
    app.dependency_overrides.pop(current_user, None)
    app.dependency_overrides[get_run_store] = lambda: store
    app.dependency_overrides[settings_dep] = lambda: SETTINGS
    try:
        client = TestClient(app)
        results = client.get(f"/api/extraction/runs/{run_id}/results").status_code
        walk = client.get(f"/api/walkthrough/runs/{run_id}/companies/c1",
                          params={"item": FIELD_ID, "period_end": "2025-12-31"}).status_code
    finally:
        for dep in DEPS:
            app.dependency_overrides.pop(dep, None)
    assert walk == results == 401


def _keys(x):
    """Every key outside `rows` and the model `answer` objects."""
    if isinstance(x, dict):
        for k, v in x.items():
            if k in ("rows", "answer"):
                continue
            yield k
            yield from _keys(v)
    elif isinstance(x, list):
        for v in x:
            yield from _keys(v)


async def test_no_review_data(tmp_path, fake_llm):  # AC-19
    store, run_id = await _run(tmp_path, _ac1_llm(fake_llm))
    [item, *_] = store.read_review_queue(run_id)
    reviewer = str(uuid.uuid4())
    append_decision(store, run_id, ReviewDecision(
        item_key=item["item_key"], decision="approve", reason_code="confirmed", reviewer="Zed Reviewer", user_id=reviewer,
        role="analyst", snapshot_id="s1", comment="zq-note-7f3a", step="first",
    ))
    store.append_cosign(run_id, {"item_key": item["item_key"], "user_id": str(uuid.uuid4()), "name": "Cosigner",
                                 "role": "approver", "decision_decided_at": "x", "cosigned_at": "y"})
    body = _ok(store, run_id, item["field_id"], period_end=item["period_end"] or "unspecified")
    assert not [k for k in _keys(body) if any(w in k.lower() for w in ("decision", "reviewer", "cosign"))]
    text = json.dumps(body)
    assert reviewer not in text and "zq-note-7f3a" not in text


def _paths(x, path="$"):
    if isinstance(x, dict):
        for k, v in x.items():
            yield f"{path}.{k}"
            yield from _paths(v, f"{path}.{k}")
    elif isinstance(x, list):
        for v in x:
            yield from _paths(v, f"{path}[]")


def _values(x, path="$"):
    """(path, string) for every key and string value, skipping passage text, row citations and quotes."""
    if isinstance(x, dict):
        for k, v in x.items():
            p = f"{path}.{k}"
            if p.endswith(("passages[].text", ".citations")) or k == "quote":
                continue
            yield p, k
            yield from _values(v, p)
    elif isinstance(x, list):
        for v in x:
            yield from _values(v, f"{path}[]")
    elif isinstance(x, str):
        yield path, x


def test_seeded_and_real_look_alike(qenv, monkeypatch):  # noqa: F811  # AC-20
    rs, store, settings = qenv
    call = FakeLLMClient.complete_structured

    async def stamped(self, *, system, output_model, **kw):  # usage as the real model client stamps it
        answer, usage = await call(self, system=system, output_model=output_model, **kw)
        model = settings.llm_verifier_model if output_model is VerifierOutput else settings.llm_model
        return answer, usage.model_copy(update={"model": model,
                                                "prompt_version": hashlib.sha256(system.encode()).hexdigest()[:12]})

    monkeypatch.setattr(FakeLLMClient, "complete_structured", stamped)
    seeded = seed_known_answers(rs, settings, count=5, seed=3)
    field = next(f for f in load_run_schema(rs, seeded).fields if f.name == "green_capex_fy2025")
    assert not field.high_risk
    real = _real_run(rs, store, settings, field)

    def body(run_id):
        rec, row = next((r, f) for r in rs.read_results(run_id) for f in r["fields"]
                        if f["field_id"] == field.field_id and f["value"] is not None)
        return _ok(rs, run_id, field.field_id, rec["company_id"], content=store, period_end=_period(row))

    a, b = body(seeded), body(real)
    for x in (a, b):
        assert (x["recorded"], x["adjudicator"]) == (True, None)
        assert x["passages"] and all(p["text"] is not None for p in x["passages"])
        assert not [s for _, s in _values({k: v for k, v in x.items() if k != "rows"})
                    if "seed" in s.lower() or "known" in s.lower()]
        assert not [s for _, s in _values(x["rows"]) if "seed" in s.lower() or "known" in s.lower()]
    strip = lambda x: {k: v for k, v in x.items() if k != "rows"}  # noqa: E731
    assert set(_paths(strip(a))) == set(_paths(strip(b)))
    for step in ("extractor", "verifier"):
        assert (a[step]["model"], a[step]["prompt_version"]) == (b[step]["model"], b[step]["prompt_version"])
