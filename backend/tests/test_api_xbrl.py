from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api import deps
from arp.api.auth import current_user
from arp.api.routers import xbrl as xbrl_router
from arp.config import Settings
from arp.orchestration.job_manager import JobManager
from arp.orchestration.jobs import run_lease
from arp.schemas.common import CompanyRef
from arp.schemas.datapoints import ExtractedField, ExtractionRecord
from arp.storage.run_store import RunStore
from arp.xbrl_pipeline.fetch import create_xbrl_run
from arp.xbrl_pipeline.flatten import build_catalog, flatten_company_facts
from arp.xbrl_pipeline.models import ReportMeta, RequiredRow
from arp.xbrl_pipeline.store import XbrlStore
from tests.conftest import PRINCIPAL

FIXTURE = Path(__file__).parent / "fixtures" / "xbrl" / "companyfacts_small.json"
CIK = "0001234567"
REPORT = b"<html><script>alert(1)</script></html>"
CO = CompanyRef(company_id="ex", name="Example Inc", cik=CIK)


@pytest.fixture
def env(tmp_path):
    settings = Settings(xbrl_dir=tmp_path / "xbrl", runs_dir=tmp_path / "runs")
    app = FastAPI()
    app.include_router(xbrl_router.router)
    app.dependency_overrides[deps.settings_dep] = lambda: settings
    app.dependency_overrides[current_user] = lambda: PRINCIPAL
    store = XbrlStore(settings.xbrl_dir)
    raw = FIXTURE.read_bytes()
    facts = json.loads(raw)
    sha = store.save_original(CIK, raw)
    rows = list(flatten_company_facts(facts, company_id="ex", cik=CIK, source_sha=sha))
    store.write_facts(CIK, rows)
    store.write_catalog(CIK, build_catalog(facts))
    store.set_meta(CIK, source_sha=sha, tags=None, company_id="ex", company_name="Example Inc",
                   fact_count=len(rows))
    store.save_report(CIK, REPORT, ReportMeta(
        accession="0001-24-000001", form="10-K", filing_date="2024-11-01", source_url="http://x",
        primary_document="a.htm", filename="annual-0001-24-000001.htm", sha256="s", size=len(REPORT), inline_xbrl=True))
    return TestClient(app), settings, store, RunStore(settings.runs_dir)


def test_start_run_requires_companies_or_universe(env):
    client, *_ = env
    r = client.post("/api/xbrl/runs", json={})
    assert r.status_code == 400


def test_start_run_returns_run_id(env, monkeypatch):
    client, _, _, runs = env
    calls = []

    async def stub(run_id, companies, **kw):
        calls.append((run_id, [c.company_id for c in companies], kw["tags"], kw["refresh"]))

    monkeypatch.setattr(xbrl_router, "execute_xbrl_run", stub)
    r = client.post("/api/xbrl/runs", json={"companies": [CO.model_dump()], "tags": ["us-gaap:Revenues"], "refresh": True})
    assert r.status_code == 200
    body = r.json()
    assert body["company_count"] == 1
    assert runs.load_manifest(body["run_id"]) is not None
    assert calls == [(body["run_id"], ["ex"], ["us-gaap:Revenues"], True)]
    assert client.get(f"/api/xbrl/runs/{body['run_id']}").json()["run_id"] == body["run_id"]
    assert client.get("/api/xbrl/runs/nope").status_code == 404


def test_retry_resumes_same_run(env, monkeypatch):
    client, _, _, runs = env
    calls = []

    async def stub(run_id, companies, **kw):
        calls.append(run_id)

    monkeypatch.setattr(xbrl_router, "execute_xbrl_run", stub)
    run_id = create_xbrl_run([CO], None, False, runs)
    r = client.post(f"/api/xbrl/runs/{run_id}/retry")
    assert r.status_code == 200 and r.json()["run_id"] == run_id
    assert calls == [run_id]
    assert client.post("/api/xbrl/runs/nope/retry").status_code == 404


def _capture(monkeypatch):
    calls = []

    async def stub(run_id, companies, **kw):
        calls.append(kw)

    monkeypatch.setattr(xbrl_router, "execute_xbrl_run", stub)
    return calls


def test_start_run_market_sec_records_params(env, monkeypatch):
    client, _, _, runs = env
    calls = _capture(monkeypatch)
    run_id = client.post("/api/xbrl/runs", json={"companies": [CO.model_dump()], "market": "sec"}).json()["run_id"]
    assert runs.load_manifest(run_id).params["market"] == "sec"
    assert calls[0]["market"] == "sec"


def test_start_run_esef_records_market_in_params(env, monkeypatch):
    client, _, _, runs = env
    calls = _capture(monkeypatch)
    run_id = client.post("/api/xbrl/runs", json={"companies": [CO.model_dump()], "market": "esef"}).json()["run_id"]
    assert runs.load_manifest(run_id).params["market"] == "esef"
    assert calls[0]["market"] == "esef"


def test_retry_keeps_the_runs_market(env, monkeypatch):
    client, _, _, runs = env
    calls = _capture(monkeypatch)
    run_id = create_xbrl_run([CO], None, False, runs, market="esef")
    assert client.post(f"/api/xbrl/runs/{run_id}/retry").status_code == 200
    assert calls[0]["market"] == "esef"


def test_start_run_rejects_unknown_market(env):
    client, *_ = env
    assert client.post("/api/xbrl/runs", json={"companies": [CO.model_dump()], "market": "jp"}).status_code == 422


def test_companies_list_includes_market(env):
    client, *_ = env
    assert client.get("/api/xbrl/companies").json()["items"][0]["market"] == "sec"


def test_run_results_paged(env):
    client, _, _, runs = env
    run_id = create_xbrl_run([CO], None, False, runs)
    runs.results_path(run_id).write_text("".join(json.dumps({"n": i}) + "\n" for i in range(5)))
    body = client.get(f"/api/xbrl/runs/{run_id}/results", params={"offset": 1, "limit": 2}).json()
    assert body == {"total": 5, "results": [{"n": 1}, {"n": 2}]}
    assert client.get(f"/api/xbrl/runs/{run_id}/results", params={"offset": -1}).status_code == 422
    assert client.get(f"/api/xbrl/runs/{run_id}/results", params={"limit": 501}).status_code == 422
    assert client.get("/api/xbrl/runs/nope/results").status_code == 404


def test_tags_search_and_paging(env):
    client, *_ = env
    all_ = client.get("/api/xbrl/tags", params={"seen_only": True}).json()
    assert all_["total"] == 3
    one = client.get("/api/xbrl/tags", params={"q": "revenues"}).json()
    assert [t["concept"] for t in one["items"]] == ["Revenues"]
    assert one["items"][0]["seen_count"] == 1
    page = client.get("/api/xbrl/tags", params={"seen_only": True, "offset": 2, "limit": 5}).json()
    assert page["total"] == 3 and len(page["items"]) == 1
    assert client.get("/api/xbrl/tags", params={"limit": 0}).status_code == 422


def test_taxonomy_update_maps_errors_to_502(env, monkeypatch):
    client, *_ = env
    seen = {}

    async def ok(store, *, fetch, taxonomies=None):
        seen["fetch"] = fetch
        return {"us-gaap": 3}

    monkeypatch.setattr(xbrl_router, "update_taxonomies", ok)
    r = client.post("/api/xbrl/taxonomy/update")
    assert r.status_code == 200 and r.json() == {"us-gaap": 3}

    async def bad_http(store, *, fetch, taxonomies=None):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(xbrl_router, "update_taxonomies", bad_http)
    r = client.post("/api/xbrl/taxonomy/update")
    assert r.status_code == 502 and "no route" in r.json()["detail"]

    async def bad_value(store, *, fetch, taxonomies=None):
        raise ValueError("no official source url configured")

    monkeypatch.setattr(xbrl_router, "update_taxonomies", bad_value)
    r = client.post("/api/xbrl/taxonomy/update")
    assert r.status_code == 502 and "no official source url" in r.json()["detail"]


def test_selection_roundtrip(env):
    client, *_ = env
    assert client.get("/api/xbrl/selections").json() == []
    r = client.put("/api/xbrl/selections/rev", json={"tags": ["us-gaap:Revenues"]})
    assert r.status_code == 200 and r.json()["row_count"] == 3
    assert [s["name"] for s in client.get("/api/xbrl/selections").json()] == ["rev"]
    body = client.get("/api/xbrl/selections/rev/facts", params={"limit": 2}).json()
    assert body["total"] == 3 and len(body["items"]) == 2
    assert {i["concept"] for i in body["items"]} == {"Revenues"}
    assert client.get("/api/xbrl/selections/rev/facts", params={"offset": -1}).status_code == 422


def test_unknown_selection_is_404(env):
    client, *_ = env
    assert client.get("/api/xbrl/selections/ghost/facts").status_code == 404


def test_unsafe_selection_name_is_400(env):
    client, *_ = env
    assert client.put("/api/xbrl/selections/.x", json={"tags": []}).status_code == 400
    assert client.get("/api/xbrl/selections/.x/facts").status_code == 400


def test_companies_listing(env):
    client, *_ = env
    body = client.get("/api/xbrl/companies").json()
    assert body["total"] == 1
    assert body["items"][0]["cik"] == CIK and body["items"][0]["report"]["size"] == len(REPORT)
    assert client.get("/api/xbrl/companies", params={"offset": 1}).json() == {"items": [], "total": 1}


def test_download_has_attachment_nosniff_and_sandbox_headers(env):
    client, *_ = env
    r = client.get(f"/api/xbrl/companies/{CIK}/files/report")
    assert r.status_code == 200 and r.content == REPORT
    assert r.headers["content-disposition"].startswith("attachment")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-security-policy"] == "sandbox"
    assert client.get(f"/api/xbrl/companies/{CIK}/files/original").status_code == 200


def test_download_unknown_kind_is_404_and_unsafe_cik_is_400(env):
    client, *_ = env
    assert client.get(f"/api/xbrl/companies/{CIK}/files/bogus").status_code == 404
    assert client.get("/api/xbrl/companies/0009999999/files/report").status_code == 404
    assert client.get(f"/api/xbrl/companies/{CIK}/files/required").status_code == 404
    assert client.get("/api/xbrl/companies/.x/files/report").status_code == 400


def test_facts_filter_sort_paging_and_bad_sort_is_400(env):
    client, *_ = env
    url = f"/api/xbrl/companies/{CIK}/facts"
    body = client.get(url, params={"q": "revenues", "sort": "period_end", "order": "asc", "limit": 2}).json()
    assert body["total"] == 3 and len(body["items"]) == 2
    ends = [i["period_end"] for i in body["items"]]
    assert ends == sorted(ends)
    assert body["items"][0]["label"] == "Revenues"
    assert client.get(url, params={"annual_only": True}).json()["total"] == 4
    assert client.get(url, params={"sort": "nope"}).status_code == 400
    assert client.get(url, params={"offset": -1}).status_code == 422
    assert client.get(url, params={"order": "sideways"}).status_code == 422
    assert client.get("/api/xbrl/companies/.x/facts").status_code == 400


def test_pivot_shape(env):
    client, *_ = env
    body = client.get(f"/api/xbrl/companies/{CIK}/pivot").json()
    assert set(body) == {"years", "rows", "total"}
    assert body["total"] == len(body["rows"]) > 0
    assert body["years"] == sorted(body["years"], reverse=True)
    assert set(body["rows"][0]) == {"tag_id", "label", "unit", "values"}
    assert client.get(f"/api/xbrl/companies/{CIK}/pivot", params={"limit": 501}).status_code == 422


def _required(company_id, cik, value):
    return RequiredRow(company_id=company_id, cik=cik, metric="revenue", fiscal_year=2024, status="found",
                       concept="us-gaap:Revenues", value=value, unit="USD", period_start=None,
                       period_end="2024-12-31", form="10-K", filed=None)


def test_required_for_run(env):
    client, _, store, runs = env
    store.write_required(CIK, [_required("ex", CIK, 1000.0)])
    other = "0007654321"
    store.write_required(other, [_required("other", other, 5.0)])
    (store.company_dir(other) / "meta.json").write_text(json.dumps({"company_id": "other"}))
    run_id = create_xbrl_run([CO], None, False, runs)
    rows = client.get("/api/xbrl/required", params={"run_id": run_id}).json()
    assert [(r["company_id"], r["value"]) for r in rows] == [("ex", 1000.0)]
    assert client.get("/api/xbrl/required", params={"run_id": "nope"}).status_code == 404


def test_required_matches_any_company_id_of_the_cik(env):
    client, _, store, runs = env
    store.write_required(CIK, [_required("ex", CIK, 1000.0)])
    store.set_meta(CIK, source_sha="s", tags=None, company_id="ex-inc", company_name=None, fact_count=1)
    run_id = create_xbrl_run([CompanyRef(company_id="ex-inc", name="Ex", cik=CIK)], None, False, runs)
    rows = client.get("/api/xbrl/required", params={"run_id": run_id}).json()
    assert [(r["company_id"], r["value"]) for r in rows] == [("ex", 1000.0)]


def _extraction_run(runs, *, settings_text: str | None):
    run_id = create_xbrl_run([CO], None, False, runs)
    rec = ExtractionRecord(company_id="ex", name="Ex", schema_id="s", run_id=run_id, fields=[
        ExtractedField(field_id="rev_f", field_name="rev", value=1004.0, confidence=0.9,
                       canonical_value=1004.0, canonical_unit="USD", period_end="2024-12-31")])
    runs.results_path(run_id).write_text(rec.model_dump_json() + "\n")
    if settings_text is not None:
        (runs.run_dir(run_id) / "step_settings.json").write_text(settings_text)
    return run_id


def test_verify_circular_is_409(env):
    client, _, store, runs = env
    store.write_required(CIK, [_required("ex", CIK, 1000.0)])
    for text in (json.dumps({"xbrl_facts_enabled": True}), "[]", "{bad", None):
        runs_id = _extraction_run(runs, settings_text=text)
        r = client.post("/api/xbrl/verify", json={"run_id": runs_id, "mapping": {"revenue": "rev_f"}})
        assert r.status_code == 409, text
        assert "XBRL" in r.json()["detail"]


def test_verify_returns_rows(env):
    client, _, store, runs = env
    store.write_required(CIK, [_required("ex", CIK, 1000.0)])
    run_id = _extraction_run(runs, settings_text=json.dumps({"xbrl_facts_enabled": False}))
    r = client.post("/api/xbrl/verify", json={"run_id": run_id, "mapping": {"revenue": "rev_f"}})
    assert r.status_code == 200
    assert [(x["outcome"], x["run_value"], x["xbrl_value"]) for x in r.json()] == [("match", 1004.0, 1000.0)]
    assert client.post("/api/xbrl/verify", json={"run_id": "nope", "mapping": {}}).status_code == 404


@pytest.mark.parametrize("route", ["start", "retry"])
def test_background_failure_is_logged_marks_run_failed_and_releases_task(env, monkeypatch, caplog, route):
    client, _, _, runs = env

    async def boom(run_id, companies, **kw):
        raise RuntimeError("source exploded")

    monkeypatch.setattr(xbrl_router, "execute_xbrl_run", boom)
    with caplog.at_level("ERROR", logger=xbrl_router.logger.name), client:
        if route == "start":
            run_id = client.post("/api/xbrl/runs", json={"companies": [CO.model_dump()]}).json()["run_id"]
        else:
            run_id = create_xbrl_run([CO], None, False, runs)
            assert client.post(f"/api/xbrl/runs/{run_id}/retry").status_code == 200
        client.portal.call(asyncio.sleep, 0.05)  # let the background task run and its callback fire
    assert "source exploded" in caplog.text
    assert xbrl_router._tasks == set()
    manifest = runs.load_manifest(run_id)
    assert manifest.status == "failed" and "source exploded" in manifest.error


def test_universe_path_errors_are_400_without_leaking_path(env, tmp_path):
    client, *_ = env
    missing = tmp_path / "secret-dir" / "nope.json"
    r = client.post("/api/xbrl/runs", json={"universe_path": str(missing)})
    assert r.status_code == 400 and "secret-dir" not in r.text and "nope" not in r.text
    bad = tmp_path / "bad.json"
    bad.write_text("{not json SECRETCONTENT")
    r = client.post("/api/xbrl/runs", json={"universe_path": str(bad)})
    assert r.status_code == 400 and "SECRETCONTENT" not in r.text and "bad.json" not in r.text
    odd = tmp_path / "u.txt"
    odd.write_text("x")
    assert client.post("/api/xbrl/runs", json={"universe_path": str(odd)}).status_code == 400


def test_retry_of_executing_run_is_409(env, monkeypatch):
    client, _, _, runs = env
    calls = []

    async def stub(run_id, companies, **kw):
        calls.append(run_id)

    monkeypatch.setattr(xbrl_router, "execute_xbrl_run", stub)
    run_id = create_xbrl_run([CO], None, False, runs)
    with run_lease(runs, run_id):  # another worker holds the run
        r = client.post(f"/api/xbrl/runs/{run_id}/retry")
    assert r.status_code == 409 and "executing" in r.json()["detail"]
    assert calls == []
    # a finished run (lease free, manifest completed) is accepted
    JobManager(runs).finish_run(run_id)
    assert client.post(f"/api/xbrl/runs/{run_id}/retry").status_code == 200
    assert calls == [run_id]


def _finished_with_failure(runs):
    run_id = create_xbrl_run([CO], None, False, runs)
    JobManager(runs).record_progress(run_id, failed_delta=1)
    JobManager(runs).finish_run(run_id)
    assert runs.load_manifest(run_id).status == "partially_completed"
    return run_id


def test_retry_marks_manifest_running_before_the_task_finishes(env, monkeypatch):
    client, _, _, runs = env
    release = asyncio.Event()

    async def stub(run_id, companies, **kw):
        await release.wait()
        JobManager(runs).record_progress(run_id, failed_delta=-1)  # the retry succeeded
        JobManager(runs).finish_run(run_id)

    monkeypatch.setattr(xbrl_router, "execute_xbrl_run", stub)
    run_id = _finished_with_failure(runs)
    with client:
        assert client.post(f"/api/xbrl/runs/{run_id}/retry").status_code == 200
        assert client.get(f"/api/xbrl/runs/{run_id}").json()["status"] == "running"
        client.portal.call(release.set)
        client.portal.call(asyncio.sleep, 0.05)
    assert runs.load_manifest(run_id).status == "completed"


def test_retry_409_leaves_manifest_untouched(env, monkeypatch):
    client, _, _, runs = env

    async def stub(run_id, companies, **kw):
        raise AssertionError("must not launch")

    monkeypatch.setattr(xbrl_router, "execute_xbrl_run", stub)
    run_id = _finished_with_failure(runs)
    before = runs.load_manifest(run_id)
    with run_lease(runs, run_id):
        assert client.post(f"/api/xbrl/runs/{run_id}/retry").status_code == 409
    assert runs.load_manifest(run_id) == before


def test_start_run_rejects_empty_or_malformed_tags(env):
    client, *_ = env
    r = client.post("/api/xbrl/runs", json={"companies": [{"company_id": "ex", "name": "Ex"}], "tags": []})
    assert (r.status_code, r.json()["detail"]) == (400, "tags must not be empty; omit it to extract everything")
    r = client.post("/api/xbrl/runs", json={"companies": [{"company_id": "ex", "name": "Ex"}], "tags": ["Revenues"]})
    assert r.status_code == 400 and "Revenues" in r.json()["detail"]


@pytest.mark.parametrize("tags", [[], ["Revenues"]])
def test_put_selection_rejects_empty_or_malformed_tags(env, tags):
    client, *_ = env
    assert client.put("/api/xbrl/selections/rev", json={"tags": tags}).status_code == 400
    assert client.get("/api/xbrl/selections").json() == []


def test_verify_non_generic_run_is_400(env):
    client, _, store, runs = env
    run_id = _extraction_run(runs, settings_text=json.dumps({"xbrl_facts_enabled": False}))
    runs.results_path(run_id).write_text(json.dumps({"company_id": "ex", "financials": {}}) + "\n")
    r = client.post("/api/xbrl/verify", json={"run_id": run_id, "mapping": {"revenue": "rev_f"}})
    assert r.status_code == 400 and "generic extraction records" in r.json()["detail"]


@pytest.mark.parametrize("tolerance", [-0.1, 1.5])
def test_verify_tolerance_is_bounded(env, tolerance):
    client, *_ = env
    r = client.post("/api/xbrl/verify", json={"run_id": "x", "mapping": {"revenue": "f"}, "tolerance": tolerance})
    assert r.status_code == 422


def test_cors_exposes_content_disposition_for_downloads():
    from arp.api.main import app

    r = TestClient(app).get("/api/xbrl/tags", headers={"Origin": "http://localhost:5173"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "Content-Disposition" in r.headers["access-control-expose-headers"]


def test_start_run_market_defaults_to_auto(env, monkeypatch):
    client, _, _, runs = env
    calls = _capture(monkeypatch)
    run_id = client.post("/api/xbrl/runs", json={"companies": [CO.model_dump()]}).json()["run_id"]
    assert runs.load_manifest(run_id).params["market"] == "auto"
    assert calls[0]["market"] == "auto"
    assert (runs.run_dir(run_id) / "routing.json").exists()


def test_retry_of_an_auto_run_keeps_routing(env, monkeypatch):
    client, _, _, runs = env
    calls = _capture(monkeypatch)
    run_id = create_xbrl_run([CO], None, False, runs, market="auto")
    before = (runs.run_dir(run_id) / "routing.json").read_bytes()
    assert client.post(f"/api/xbrl/runs/{run_id}/retry").status_code == 200
    assert calls[0]["market"] == "auto"
    assert (runs.run_dir(run_id) / "routing.json").read_bytes() == before
