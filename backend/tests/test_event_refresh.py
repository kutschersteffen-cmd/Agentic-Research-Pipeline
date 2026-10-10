"""E20: a new or updated filing starts one extraction run per issuer and configured released schema;
plus E16 ESEF feed polling, which raises those document events from discovery."""

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from arp.cli._shared import _and_drain
from arp.config import Settings
from arp.db.fields import SchemaRegistry
from arp.discovery import refresh
from arp.discovery.change_detector import ChangeDetector, poll_esef_filings
from arp.discovery.pipeline import create_discovery_run, execute_discovery_run
from arp.discovery.refresh import refresh_hook, refresh_on_events
from arp.discovery.site_finder import WebSearchClient
from arp.ingestion import esef
from arp.ingestion.esef import EsefDocumentSource
from arp.ingestion.registry import DocumentSourceRegistry
from arp.orchestration import jobs
from arp.schemas.common import CompanyRef, DocType
from arp.schemas.datapoints import DataPointSchema, FieldDataType, FieldDefinition, FieldStatus
from arp.schemas.discovery import DiscoveredDocument, DocumentEvent, DocumentEventType
from arp.storage.run_store import RunStore

pytestmark = pytest.mark.usefixtures("pg")

PACKAGE = (Path(__file__).parent / "fixtures" / "esef" / "beispiel-2024.zip").read_bytes()
LEI = "529900T8BM49AURSDO55"


class _Launcher:
    def __init__(self):
        self.calls = []

    def launch(self, run_id, job, *, run_store=None):
        self.calls.append((run_id, job, run_store))


def _settings(tmp_path, **kw) -> Settings:
    base = dict(
        anthropic_api_key="unused", runs_dir=tmp_path / "runs", schema_registry_dir=tmp_path / "schemas",
        documents_dir=tmp_path / "docs", cache_dir=tmp_path / "cache", discovery_state_dir=tmp_path / "disc",
        document_store_dir=tmp_path / "store", event_refresh_state_dir=tmp_path / "refresh", event_refresh_enabled=True, event_refresh_schema_ids=["sch1"],
    )
    return Settings(**{**base, **kw})


def _schema(settings, schema_id="sch1", *, release=True):
    field = FieldDefinition(
        name="revenue", description="Total revenue.", data_type=FieldDataType.CURRENCY_AMOUNT, unit="EUR millions",
        extraction_instructions="Total revenue.", seed_keywords=["revenue"], status=FieldStatus.RELEASED,
    )
    reg = SchemaRegistry()
    saved = reg.save(DataPointSchema(schema_id=schema_id, name=schema_id, fields=[field]))
    return reg.release(saved.schema_id, saved.version) if release else saved


def _event(company_id="c1", sha="a" * 64, kind=DocumentEventType.NEW_DOCUMENT):
    doc = DiscoveredDocument(company_id=company_id, doc_type=DocType.ANNUAL_REPORT_10K, url=f"https://x.example/{sha}.pdf", sha256=sha)
    return DocumentEvent(event_type=kind, company_id=company_id, company_name="Beispiel AG", document=doc)


async def _refresh(settings, events, launcher, **kw):
    store = RunStore(settings.runs_dir)
    ids = await refresh_on_events(
        events, settings=settings, run_store=store, registry=DocumentSourceRegistry([]), launcher=launcher, **kw
    )
    return ids, store


async def test_new_filing_triggers_one_run(tmp_path):
    universe = tmp_path / "universe.json"
    universe.write_text(json.dumps([{"company_id": "c1", "name": "Beispiel AG", "lei": LEI}]))
    settings = _settings(tmp_path, discovery_schedule_universe_path=universe)
    _schema(settings)
    launcher = _Launcher()

    ids, store = await _refresh(settings, [_event()], launcher)

    assert len(ids) == 1 and [c[0] for c in launcher.calls] == ids
    assert launcher.calls[0][2] is store and callable(launcher.calls[0][1])
    manifest = store.load_manifest(ids[0])
    assert manifest.run_type == "extraction" and manifest.params["schema_id"] == "sch1"
    [company] = store.load_companies(ids[0])
    assert (company.company_id, company.lei) == ("c1", LEI)  # the universe's richer CompanyRef


async def test_refresh_without_universe_keeps_company_identifiers(tmp_path):
    settings = _settings(tmp_path)
    _schema(settings)
    company = CompanyRef(company_id="c1", name="Beispiel AG", lei=LEI, cik="0000320193")

    ids, store = await _refresh(settings, [_event()], _Launcher(), company_hint=company)

    [got] = store.load_companies(ids[0])
    assert (got.lei, got.cik) == (LEI, "0000320193")


async def test_same_filing_twice_one_run(tmp_path):
    settings = _settings(tmp_path)
    _schema(settings)
    launcher = _Launcher()

    first, _ = await _refresh(settings, [_event(), _event(kind=DocumentEventType.UPDATED_DOCUMENT)], launcher)
    second, _ = await _refresh(settings, [_event()], launcher)

    assert len(first) == 1 and second == [] and len(launcher.calls) == 1
    changed, _ = await _refresh(settings, [_event(sha="b" * 64)], launcher)  # a changed filing does fire
    assert len(changed) == 1


@pytest.mark.parametrize("kw", [{"event_refresh_enabled": False}, {"event_refresh_schema_ids": []}])
async def test_disabled_or_empty_schema_list_no_runs(tmp_path, kw):
    settings = _settings(tmp_path, **kw)
    _schema(settings)
    launcher = _Launcher()

    ids, store = await _refresh(settings, [_event()], launcher)

    assert ids == [] and launcher.calls == [] and store.list_runs() == []


async def test_unreleased_schema_skipped(tmp_path, caplog):
    settings = _settings(tmp_path, event_refresh_schema_ids=["draft", "sch1", "missing"])
    _schema(settings)
    _schema(settings, "draft", release=False)
    launcher = _Launcher()

    with caplog.at_level(logging.WARNING):
        ids, store = await _refresh(settings, [_event()], launcher)

    assert len(ids) == 1 and store.load_manifest(ids[0]).params["schema_id"] == "sch1"
    assert "draft" in caplog.text and "missing" in caplog.text


async def test_daily_cap(tmp_path):
    settings = _settings(tmp_path, event_refresh_max_runs_per_day=2)
    _schema(settings)
    settings.event_refresh_state_dir.mkdir(parents=True)
    yesterday = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    (settings.event_refresh_state_dir / "fired.jsonl").write_text(
        json.dumps({"company_id": "old", "schema_id": "sch1", "sha256": "0", "run_id": "r0", "fired_at": yesterday}) + "\n"
    )
    launcher = _Launcher()

    ids, _ = await _refresh(settings, [_event(sha=c * 64) for c in "abc"], launcher)
    later, _ = await _refresh(settings, [_event(sha="d" * 64)], launcher)

    assert len(ids) == 2 and later == []  # yesterday's run does not count against today


async def test_change_detector_calls_on_events_and_survives_errors(tmp_path):
    events_path = tmp_path / "docs" / "_events.jsonl"
    seen = []

    async def hook(events, company):
        seen.append((list(events), events_path.exists()))
        assert company.company_id == "c1"
        raise RuntimeError("refresh broke")

    detector = ChangeDetector(tmp_path / "state", events_path, on_events=hook)
    company = CompanyRef(company_id="c1", name="Beispiel AG")
    doc = _event().document

    events = await detector.diff_and_record(company, [doc])
    again = await detector.diff_and_record(company, [doc])

    assert len(events) == 1 and again == []
    assert seen == [(events, True)]  # after recording; not called when nothing changed


class _NullSearch(WebSearchClient):
    async def search(self, query, max_results=5):
        return []


def _esef_source(tmp_path, calls):
    def handler(request):
        calls.append(request.url.path)
        if request.url.path == f"/api/entities/{LEI}/filings":
            return httpx.Response(200, json={"data": [{"attributes": {"period_end": "2024-12-31", "package_url": "/p.zip"}}]})
        if request.url.path == "/p.zip":
            return httpx.Response(200, content=PACKAGE)
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return EsefDocumentSource("https://filings.example", tmp_path / "cache", client=client)


async def _discover(settings, source):
    store = RunStore(settings.runs_dir)
    company = CompanyRef(company_id="c1", name="Beispiel AG", lei=LEI)  # no website: the crawl finds nothing
    run_id = create_discovery_run([company], None, "test", store)
    await execute_discovery_run(run_id, [company], settings=settings, run_store=store, search_client=_NullSearch(), esef_source=source)
    [row] = store.read_jsonl(store._results_path(run_id))
    return row


async def test_esef_poll_raises_document_events_that_reach_refresh(tmp_path, monkeypatch):
    async def noop(request):
        return None

    monkeypatch.setattr(esef, "ssrf_guard_request_hook", noop)
    fired = []

    async def fake_refresh(events, **kw):
        fired.append(events)
        return []

    monkeypatch.setattr(refresh, "refresh_on_events", fake_refresh)
    settings = _settings(tmp_path, esef_enabled=True)
    calls = []

    row = await _discover(settings, _esef_source(tmp_path, calls))
    again = await _discover(settings, _esef_source(tmp_path, calls))

    [event] = row["new_events"]
    assert event["event_type"] == "new_document" and event["document"]["url"] == "https://filings.example/p.zip"
    assert again["new_events"] == []  # the same filing is not new twice
    assert [[e.document.url for e in batch] for batch in fired] == [["https://filings.example/p.zip"]]
    assert (settings.documents_dir / "_events.jsonl").exists()


async def test_esef_poll_off_by_default(tmp_path):
    settings = _settings(tmp_path)
    calls = []

    row = await _discover(settings, _esef_source(tmp_path, calls))

    assert calls == [] and row["new_events"] == []


async def test_parent_run_pair_skipped(tmp_path):
    settings = _settings(tmp_path, event_refresh_schema_ids=["sch1", "sch2"], event_refresh_max_runs_per_day=1)
    _schema(settings)
    _schema(settings, "sch2")
    launcher = _Launcher()

    ids, store = await _refresh(settings, [_event()], launcher, parent=("c1", "sch1", "r-parent"))
    again, _ = await _refresh(settings, [_event()], launcher)

    # the parent's own pair is recorded, not run, and does not use up the daily cap
    assert len(ids) == 1 and store.load_manifest(ids[0]).params["schema_id"] == "sch2" and again == []


async def test_refresh_hook_passes_parent(tmp_path, monkeypatch):
    seen = []

    async def fake_refresh(events, **kw):
        seen.append(kw["parent"])
        return []

    monkeypatch.setattr(refresh, "refresh_on_events", fake_refresh)
    settings = _settings(tmp_path)
    assert refresh_hook(_settings(tmp_path, event_refresh_enabled=False)) is None

    await refresh_hook(settings, parent=("c1", "sch1", "r1"))([_event()])

    assert seen == [("c1", "sch1", "r1")]


async def test_esef_poll_error_never_raises(tmp_path):
    class Broken:
        async def fetch(self, company, doc_types=None):
            raise RuntimeError("unexpected")

    detector = ChangeDetector(tmp_path / "state", tmp_path / "events.jsonl")
    assert await poll_esef_filings(CompanyRef(company_id="c1", name="B", lei=LEI), Broken(), detector) == []


def test_cli_drain_finishes_launched_job(tmp_path, monkeypatch, capsys):
    store = RunStore(tmp_path / "runs")
    monkeypatch.setattr(jobs, "_launcher", jobs.LocalJobLauncher(lambda: store))
    done = []

    async def job():
        await asyncio.sleep(0.01)
        done.append(True)

    async def command():
        jobs.get_job_launcher().launch("r-refresh", job)
        return "r-discovery"

    assert asyncio.run(_and_drain(command())) == "r-discovery"
    assert done == [True] and "r-refresh" in capsys.readouterr().out
