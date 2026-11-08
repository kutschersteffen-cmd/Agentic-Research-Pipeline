"""A discovery run queues flagged documents and empty companies for review, in one write with the result row
(spec: discovery-review-queue; AC-1..10, AC-34, AC-39)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from arp.api.auth import Principal, current_user
from arp.api.deps import get_run_store
from arp.api.main import app
from arp.cli import discovery as cli_discovery
from arp.discovery import crawler, downloader
from arp.discovery.pipeline import create_discovery_run, execute_discovery_run
from tests.discovery_review_support import (
    C1,
    C2,
    C3,
    C4,
    C5,
    URL_A,
    URL_B,
    URL_C3,
    URL_C4,
    Bodies,
    Edgar,
    NullSearch,
    run_discovery_for,
    settings_for,
    sha,
    site,
)

pytestmark = pytest.mark.usefixtures("pg")
ALICE = Principal(user_id="u_alice", name="Alice", role="analyst")


@pytest.fixture(autouse=True)
def _no_ssrf(monkeypatch):
    async def noop(request):
        return None

    for module in (crawler, downloader):
        monkeypatch.setattr(module, "ssrf_guard_request_hook", noop)
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def bodies(tmp_path):
    return Bodies(tmp_path)


def _transport(bodies):
    return site({
        "c2.example": {URL_A: bodies.b1, URL_B: bodies.b2},
        "c3.example": {URL_C3: bodies.b3},
        "c4.example": {URL_C4: bodies.b4},
    })


def _keys(run_store, run_id) -> list[str]:
    return sorted({q["item_key"] for q in run_store.read_review_queue(run_id)})


def _items(run_store, run_id, kind=None):
    app.dependency_overrides[get_run_store] = lambda: run_store
    app.dependency_overrides[current_user] = lambda: ALICE
    r = TestClient(app).get("/api/review/items", params={"run_id": run_id})
    assert r.status_code == 200, r.text
    return [i for i in r.json()["items"] if kind is None or i["kind"] == kind]


async def test_empty_company_queues_no_documents(tmp_path, pg, bodies):
    rs, run_id, _ = await run_discovery_for(tmp_path, pg, [C1], _transport(bodies))
    assert _keys(rs, run_id) == ["no_documents:C1"]  # AC-1
    [item] = _items(rs, run_id)
    assert item["kind"] == "no_documents"  # AC-2
    assert item["payload"]["reason_codes"] == ["no_documents"]  # AC-3


async def test_scheduled_run_queues_no_empty_company(tmp_path, pg, bodies):
    rs, run_id, _ = await run_discovery_for(tmp_path, pg, [C1], _transport(bodies), triggered_by="schedule")
    assert _keys(rs, run_id) == []  # AC-4


async def test_flagged_documents_queue_one_item_each(tmp_path, pg, bodies):
    rs, run_id, _ = await run_discovery_for(tmp_path, pg, [C2], _transport(bodies))
    assert _keys(rs, run_id) == sorted([f"discovered:C2:{sha(bodies.b1)}", f"discovered:C2:{sha(bodies.b2)}"])  # AC-5
    items = _items(rs, run_id)
    assert {i["kind"] for i in items} == {"discovered_document"}
    assert all(i["payload"]["reason_codes"] == ["match_ambiguous"] for i in items)  # AC-6
    p = next(i["payload"] for i in items if i["item_key"].endswith(sha(bodies.b1)))
    assert (p["company_id"], p["name"], p["url"], p["doc_type"], p["sha256"], p["company_match"], p["page_count"]) == (
        "C2", "Second Co", URL_A, "10-K", sha(bodies.b1), "none", 3)
    assert p["local_path"].endswith(".pdf") and "reporting_year" in p


async def test_no_text_document_is_check_failed(tmp_path, pg, bodies):
    rs, run_id, _ = await run_discovery_for(tmp_path, pg, [C3], _transport(bodies))
    [item] = _items(rs, run_id)
    assert item["item_key"] == f"discovered:C3:{sha(bodies.b3)}"
    assert item["payload"]["reason_codes"] == ["check_failed"]  # AC-7


async def test_passing_document_queues_nothing(tmp_path, pg, bodies):
    rs, run_id, _ = await run_discovery_for(tmp_path, pg, [C4], _transport(bodies))
    assert _keys(rs, run_id) == []  # AC-8


async def test_edgar_only_company_queues_nothing(tmp_path, pg, bodies):
    rs, run_id, _ = await run_discovery_for(tmp_path, pg, [C5], _transport(bodies))
    assert _keys(rs, run_id) == []  # AC-34


async def test_review_count_equals_queued_items(tmp_path, pg, bodies):
    rs, run_id, _ = await run_discovery_for(tmp_path, pg, [C1, C2], _transport(bodies))
    assert rs.load_manifest(run_id).review_count == 3  # AC-9
    assert len(_keys(rs, run_id)) == 3


async def test_result_row_and_items_are_written_together(tmp_path, pg, bodies):
    rs, run_id, _ = await run_discovery_for(tmp_path, pg, [C1], _transport(bodies))
    assert [r["company_id"] for r in rs.read_results(run_id)] == ["C1"]
    assert "no_documents:C1" in _keys(rs, run_id)  # Review Focus 1: no result without its items


async def test_resume_after_stop_keeps_three_items(tmp_path, pg, bodies):
    from arp.orchestration.jobs import restart_run
    from arp.storage.run_store import RunStore

    settings = settings_for(tmp_path)
    rs = RunStore(pg, settings.runs_dir)
    run_id = create_discovery_run([C1, C2], None, "manual", rs)

    async def execute(companies):
        await execute_discovery_run(run_id, companies, settings=settings, run_store=rs, search_client=NullSearch(),
                                    edgar_source=Edgar(), transport=_transport(bodies))

    await execute([C1])  # the run stops after C1's result is stored
    assert _keys(rs, run_id) == ["no_documents:C1"]
    restart_run(rs, run_id)
    await execute([C1, C2])  # C1 is in the results: neither queued nor counted again
    assert rs.load_manifest(run_id).review_count == 3  # AC-39
    assert len(_keys(rs, run_id)) == 3  # AC-39b


def _cli(monkeypatch, tmp_path, pg, bodies, companies):
    from arp.storage.run_store import RunStore

    settings = settings_for(tmp_path)
    rs = RunStore(pg, settings.runs_dir)

    async def wrapped(cs, *, settings, run_store, doc_types, triggered_by):
        run_id = create_discovery_run(cs, doc_types, triggered_by, run_store)
        return await execute_discovery_run(run_id, cs, settings=settings, run_store=run_store, search_client=NullSearch(),
                                           edgar_source=Edgar(), transport=_transport(bodies))

    monkeypatch.setattr(cli_discovery, "run_discovery", wrapped)
    monkeypatch.setattr(cli_discovery, "get_settings", lambda: settings)
    monkeypatch.setattr(cli_discovery, "_run_store", lambda: rs)
    monkeypatch.setattr(cli_discovery, "load_company_universe", lambda path: companies)
    return CliRunner().invoke(cli_discovery.discover_app, ["run", "--universe", str(tmp_path / "u.csv")])


def test_cli_prints_queued_line(monkeypatch, tmp_path, pg, bodies):
    res = _cli(monkeypatch, tmp_path, pg, bodies, [C1, C2])
    assert res.exit_code == 0, res.output
    assert "3 items queued for review (open the Review page)" in res.output  # AC-10


def test_cli_prints_no_line_when_nothing_queued(monkeypatch, tmp_path, pg, bodies):
    res = _cli(monkeypatch, tmp_path, pg, bodies, [C4])
    assert res.exit_code == 0, res.output
    assert "queued for review" not in res.output
