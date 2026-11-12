"""Argus step 3 starts the run: only the files kept in step 2, minus skipped companies, with the flow's settings."""

import asyncio
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from arp.api.deps import get_run_store, settings_dep
from arp.api.main import app
from arp.api.routers import extraction, financials, tnfd
from arp.config import Settings
from arp.db.fields import SchemaRegistry
from arp.ingestion.registry import KeptDocuments
from arp.schemas.common import CompanyRef, DocType, RunManifest, SourceDocument
from arp.schemas.datapoints import DataPointSchema
from arp.storage.run_store import RunStore
from tests.pdf_fixtures import FILLER, make_pdf


class _Registry:
    def __init__(self, docs):
        self.docs = docs
        self.settings = "kept"

    async def fetch_all(self, company, doc_types=None):
        return list(self.docs)


def _doc(key):
    return SourceDocument(company_id="aapl", doc_type=DocType.ANNUAL_REPORT_10K, title=str(key), full_text="x", content_key=key)


def test_kept_documents_filters_by_content_key():
    inner = _Registry([_doc("a"), _doc("b"), _doc(None)])
    apple = CompanyRef(company_id="aapl", name="Apple")
    kept = asyncio.run(KeptDocuments(inner, {"aapl": {"a"}}).fetch_all(apple))
    assert [d.content_key for d in kept] == ["a"]  # a removed file never reaches extraction
    other = CompanyRef(company_id="msft", name="Microsoft")
    assert len(asyncio.run(KeptDocuments(inner, {"aapl": {"a"}}).fetch_all(other))) == 3  # not in the map: unchanged
    assert KeptDocuments(inner, {}).settings == "kept"  # everything else is the wrapped registry's


@pytest.fixture
def settings(tmp_path, pg):
    return Settings(anthropic_api_key="unused", runs_dir=tmp_path / "runs", cache_dir=tmp_path / "cache",
                    documents_dir=tmp_path / "docs", discovery_state_dir=tmp_path / "state", postgres_dsn=pg)


@pytest.fixture
def run_store(settings, pg):
    return RunStore(pg, settings.runs_dir)


@pytest.fixture
def calls(monkeypatch):
    calls: list = []

    def fake(name):
        async def start(req, **kwargs):
            calls.append((name, req, kwargs))
            return {"run_id": f"extraction_{name}{len(calls)}", "company_count": len(req.companies)}
        return start

    monkeypatch.setattr(extraction, "start_extraction_run", fake("custom"))
    monkeypatch.setattr(financials, "start_financials_extraction_run", fake("financials"))
    monkeypatch.setattr(tnfd, "start_tnfd_extraction_run", fake("tnfd"))
    return calls


@pytest.fixture
def client(settings, run_store):
    app.dependency_overrides[settings_dep] = lambda: settings
    app.dependency_overrides[get_run_store] = lambda: run_store
    yield TestClient(app)
    app.dependency_overrides.pop(settings_dep, None)
    app.dependency_overrides.pop(get_run_store, None)


def _schema(settings, released: bool) -> DataPointSchema:
    reg = SchemaRegistry(settings.postgres_dsn)
    body = {"schema_id": "sch_s", "name": "S", "fields": [
        {"field_id": f"f{i}", "name": f"F{i}", "description": "d", "data_type": "number", "extraction_instructions": "Annual report"} for i in range(4)]}
    saved = reg.save(DataPointSchema.model_validate(body))
    return reg.release(saved.schema_id, saved.version, "approver") if released else saved


@pytest.fixture
def fid(client, tmp_path):
    fid = client.post("/api/argus/flows").json()["flow_id"]
    lst = "name,company_id\nApple Inc,aapl\nMicrosoft Corporation,msft\nSAP SE,sap\n"
    client.post(f"/api/argus/flows/{fid}/companies/upload", files={"file": ("u.csv", lst)})
    client.patch(f"/api/argus/flows/{fid}", json={"reporting_year": 2025, "step": 3})
    for cid, name in (("aapl", "Apple Inc"), ("msft", "Microsoft Corporation")):
        data = make_pdf(tmp_path / f"{cid}.pdf", [f"{name} Annual Report 2025", FILLER], n_pages=2).read_bytes()
        r = client.post(f"/api/argus/flows/{fid}/documents/upload", data={"company_id": cid, "doc_type": "10-K"},
                        files={"file": (f"{cid}.pdf", data, "application/pdf")})
        assert r.status_code == 200, r.text
    client.post(f"/api/argus/flows/{fid}/files", json={"all_that_pass": True})
    return fid


def _choose(client, fid, schema, **settings):
    body = {"schema_choice": {"kind": "schema", "schema_id": schema.schema_id, "version": schema.version}}
    if settings:
        body["settings"] = settings
    assert client.patch(f"/api/argus/flows/{fid}", json=body).status_code == 200


def test_start_released_schema_on_kept_files(client, fid, calls, settings, run_store):
    schema = _schema(settings, released=True)
    _choose(client, fid, schema, evidence_passages=3, decision_framework_id="fw", decision_framework_version=2)
    r = client.post(f"/api/argus/flows/{fid}/start")
    assert r.status_code == 200, r.text
    name, req, kwargs = calls[0]
    assert name == "custom" and req.trial is False and req.datapoint_schema.schema_id == "sch_s"
    assert [c.company_id for c in req.companies] == ["aapl", "msft"]  # SAP has no kept file
    assert (req.decision_framework_id, req.decision_framework_version) == ("fw", 2)  # AC-77
    keys = kwargs["registry"].only
    assert set(keys) == {"aapl", "msft"} and all(len(v) == 1 for v in keys.values())
    flow = r.json()
    assert (flow["run_id"], flow["step"]) == ("extraction_custom1", 4)
    run_dir = run_store.run_dir("extraction_custom1")
    assert json.loads((run_dir / "step_settings.json").read_text())["evidence_max_chunks"] == 3  # AC-28
    assert json.loads((run_dir / "only_documents.json").read_text()) == {k: sorted(v) for k, v in keys.items()}
    names = json.loads((run_dir / "kept_names.json").read_text())  # the run's "No text could be read from <file>"
    assert sorted(names.values()) == ["aapl.pdf", "msft.pdf"] and kwargs["registry"].names == names


def test_draft_schema_is_a_trial_on_one_company(client, fid, calls, settings):
    _choose(client, fid, _schema(settings, released=False))
    assert client.post(f"/api/argus/flows/{fid}/start").status_code == 200
    req = calls[0][1]
    assert req.trial is True and [c.company_id for c in req.companies] == ["aapl"]


def test_tnfd_profile_uses_the_reporting_year(client, fid, calls):
    client.patch(f"/api/argus/flows/{fid}", json={"schema_choice": {"kind": "profile", "profile": "tnfd"}})
    assert client.post(f"/api/argus/flows/{fid}/start").status_code == 200
    assert calls[0][0] == "tnfd" and calls[0][1].as_of == "FY2025"


def test_skipped_company_is_left_out_and_unanswered_repeat_blocks(client, fid, calls, settings, run_store, tmp_path):
    schema = _schema(settings, released=True)
    key = hashlib.sha256((tmp_path / "aapl.pdf").read_bytes()).hexdigest()
    run_store.save_manifest(RunManifest(run_id="extraction_old", run_type="extraction", created_at="2026-10-01T00:00:00Z",
                                        company_count=1, params={"schema_id": "sch_s", "schema_version": f"sch_s:v{schema.version}"}))
    run_store.append_result("extraction_old", {"company_id": "aapl", "name": "Apple Inc", "issuer_key": "k", "fields": [],
                                               "documents": [{"content_key": key}]})
    _choose(client, fid, schema)
    r = client.post(f"/api/argus/flows/{fid}/start")
    assert r.status_code == 400 and "Skip" in r.json()["detail"]  # AC-32: start waits for a choice
    client.patch(f"/api/argus/flows/{fid}", json={"repeat": {"aapl": "skip"}})
    assert client.post(f"/api/argus/flows/{fid}/start").status_code == 200
    assert [c.company_id for c in calls[0][1].companies] == ["msft"]  # AC-36


def test_start_refuses_without_choice_and_while_running(client, fid, calls, settings, run_store):
    assert client.post(f"/api/argus/flows/{fid}/start").status_code == 400
    _choose(client, fid, _schema(settings, released=True))
    assert client.post(f"/api/argus/flows/{fid}/start").status_code == 200
    run_store.save_manifest(RunManifest(run_id="extraction_custom1", run_type="extraction", company_count=2, status="running"))
    assert client.post(f"/api/argus/flows/{fid}/start").status_code == 409
    assert len(calls) == 1


def test_an_older_schema_version_is_refused(client, fid, calls, settings):
    v1 = _schema(settings, released=True)
    reg = SchemaRegistry(settings.postgres_dsn)
    reg.save(v1.model_copy(update={"fields": v1.fields[:3]}))  # v2
    _choose(client, fid, v1)
    r = client.post(f"/api/argus/flows/{fid}/start")
    assert (r.status_code, r.json()["detail"]) == (400, "Pick the newest version of S.")
    assert calls == []


def test_a_skip_for_a_company_not_listed_is_ignored(client, fid, calls, settings):
    _choose(client, fid, _schema(settings, released=True))
    client.patch(f"/api/argus/flows/{fid}", json={"repeat": {"msft": "skip"}})  # stale: msft is not in the warning
    assert client.post(f"/api/argus/flows/{fid}/start").status_code == 200
    assert [c.company_id for c in calls[0][1].companies] == ["aapl", "msft"]


def test_a_start_in_progress_is_a_409(client, fid, calls, settings):
    from arp.argus.flows import FlowStore

    _choose(client, fid, _schema(settings, released=True))
    FlowStore(settings.runs_dir / "_flows").update(fid, lambda f: setattr(f, "starting", True))
    assert client.post(f"/api/argus/flows/{fid}/start").status_code == 409
    assert calls == []


def test_a_failed_start_clears_the_marker(client, fid, monkeypatch, settings):
    async def boom(req, **kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(extraction, "start_extraction_run", boom)
    _choose(client, fid, _schema(settings, released=True))
    assert client.post(f"/api/argus/flows/{fid}/start").status_code >= 400  # the app's RuntimeError handler answers
    assert client.get(f"/api/argus/flows/{fid}").json()["starting"] is False


def test_resume_reads_only_the_kept_documents(run_store, monkeypatch, tmp_path):
    from arp.ingestion.registry import ONLY_DOCUMENTS
    from arp.orchestration import jobs

    run_store.save_manifest(RunManifest(run_id="extraction_r", run_type="extraction", company_count=1, status="failed"))
    run_store.save_companies("extraction_r", [CompanyRef(company_id="aapl", name="Apple")])
    (run_store.run_dir("extraction_r") / ONLY_DOCUMENTS).write_text(json.dumps({"aapl": ["a"]}))
    seen = {}

    async def fake(run_id, manifest, companies, *, registry, **kw):
        seen["docs"] = await registry.fetch_all(companies[0])
        return run_id

    monkeypatch.setitem(jobs._RESUME, "extraction", fake)
    inner = _Registry([_doc("a"), _doc("b")])
    asyncio.run(jobs.resume_run("extraction_r", settings=Settings(), run_store=run_store, registry=inner, llm="x", verifier_llm="y", lease=False))
    assert [d.content_key for d in seen["docs"]] == ["a"]


# --- showcase-argus-fixes item 21: the start flag ---

def _starting(settings, fid, seconds_ago):
    """The flow file as a Start left it: `starting` set, last written `seconds_ago` (every save through the store resets that)."""
    from datetime import UTC, datetime, timedelta

    path = settings.runs_dir / "_flows" / f"{fid}.json"
    stamp = (datetime.now(UTC) - timedelta(seconds=seconds_ago)).isoformat()
    path.write_text(json.dumps({**json.loads(path.read_text()), "starting": True, "updated_at": stamp}))


def test_a_start_flag_left_behind_no_longer_blocks_start(client, fid, calls, settings):  # AC-42
    _choose(client, fid, _schema(settings, released=True))
    _starting(settings, fid, 120)
    r = client.post(f"/api/argus/flows/{fid}/start")
    assert r.status_code == 200, r.text
    assert r.json()["run_id"] == "extraction_custom1" and r.json()["starting"] is False


def test_a_fresh_start_flag_still_blocks_start(client, fid, calls, settings):  # AC-43
    _choose(client, fid, _schema(settings, released=True))
    _starting(settings, fid, 5)
    r = client.post(f"/api/argus/flows/{fid}/start")
    assert (r.status_code, r.json()["detail"]) == (409, "This extraction is already starting.")
    assert calls == []


def test_the_flow_points_at_its_run_even_if_the_kept_file_record_fails(client, fid, monkeypatch, settings, run_store):  # AC-44, AC-154
    async def start(req, **kwargs):
        run_store.save_manifest(RunManifest(run_id="extraction_launched", run_type="extraction", company_count=2, status="running"))
        (run_store.run_dir("extraction_launched") / "only_documents.json").mkdir()  # the record cannot be written
        return {"run_id": "extraction_launched", "company_count": 2}

    monkeypatch.setattr(extraction, "start_extraction_run", start)
    _choose(client, fid, _schema(settings, released=True))
    with pytest.raises(OSError):
        client.post(f"/api/argus/flows/{fid}/start")
    flow = client.get(f"/api/argus/flows/{fid}").json()
    assert (flow["starting"], flow["run_id"]) == (False, "extraction_launched")
    r = client.post(f"/api/argus/flows/{fid}/start")
    assert (r.status_code, r.json()["detail"]) == (409, "This extraction is already running.")
