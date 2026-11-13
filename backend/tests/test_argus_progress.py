"""Argus step 4: the run's progress per company, in the spec's fixed statuses."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from arp.api.deps import get_run_store, settings_dep
from arp.api.main import app
from arp.argus.flows import FlowStore
from arp.argus.progress import company_status, minutes_left
from arp.config import Settings
from arp.orchestration import step_tally
from arp.schemas.common import JobStatus, RunManifest
from arp.storage.run_store import RunStore


@pytest.mark.parametrize("raw, run, steps, expected", [
    ("done", "running", {}, ("Done", 100)),
    ("review", "completed", {}, ("Done", 100)),
    ("failed", "partially_completed", {}, ("Failed", 0)),
    ("waiting", "cancelled", {}, ("Stopped", 0)),
    ("waiting", "partially_completed", {}, ("Stopped", 0)),  # never started and the run is over
    ("waiting", "pending", {}, ("Waiting", 0)),
    ("waiting", "running", {}, ("Waiting", 0)),
    ("waiting", "running", {"parse_index": 1}, ("Reading documents", 25)),
    ("waiting", "running", {"gather_evidence": 4, "extract": 2}, ("Extracting", 50)),
    ("waiting", "running", {"gather_evidence": 4, "extract": 4, "verify": 1}, ("Checking the answers", 75)),
    ("waiting", "running", {"aggregate": 1}, ("Checking the answers", 75)),
])
def test_company_status(raw, run, steps, expected):
    assert company_status(raw, run, steps) == expected


def test_minutes_left():
    start = datetime(2026, 11, 10, 14, 0, tzinfo=UTC)
    assert minutes_left(start, start + timedelta(minutes=6), done=3, total=10) == 14  # 2 min each, 7 to go
    assert minutes_left(start, start + timedelta(minutes=5), done=3, total=10) == 12  # rounded up
    assert minutes_left(start, start + timedelta(minutes=5), done=0, total=10) is None  # nothing finished yet
    assert minutes_left(start, start + timedelta(minutes=5), done=10, total=10) == 0
    assert minutes_left(start, start - timedelta(minutes=5), done=3, total=10) == 0  # a start time ahead of the clock
    assert minutes_left(start.replace(tzinfo=None), start + timedelta(minutes=6), done=3, total=10) == 14  # stored without a zone


@pytest.fixture
def settings(tmp_path, pg):
    return Settings(anthropic_api_key="unused", runs_dir=tmp_path / "runs", cache_dir=tmp_path / "cache",
                    documents_dir=tmp_path / "docs", discovery_state_dir=tmp_path / "state", postgres_dsn=pg)


@pytest.fixture
def run_store(settings, pg):
    return RunStore(pg, settings.runs_dir)


@pytest.fixture
def client(settings, run_store):
    app.dependency_overrides[settings_dep] = lambda: settings
    app.dependency_overrides[get_run_store] = lambda: run_store
    yield TestClient(app)
    app.dependency_overrides.pop(settings_dep, None)
    app.dependency_overrides.pop(get_run_store, None)


def _run(run_store, status, created_at="2026-11-10T14:02:00+00:00", **counts):
    run_store.save_manifest(RunManifest(run_id="extraction_p", run_type="extraction", created_at=created_at, status=status,
                                        company_count=4, estimated_cost_usd=1.234, **counts))
    companies = [{"company_id": c, "name": c.upper()} for c in ("a", "b", "c", "d")]
    (run_store.run_dir("extraction_p") / "start_request.json").write_text(json.dumps({"profile": "custom", "companies": companies}))


def _flow(client, settings, run_id="extraction_p"):
    fid = client.post("/api/argus/flows").json()["flow_id"]
    FlowStore(settings.runs_dir / "_flows").update(fid, lambda f: (setattr(f, "run_id", run_id), setattr(f, "step", 4)))
    return fid


def test_progress_mixes_statuses(client, settings, run_store):
    _run(run_store, "running", completed_count=1, failed_count=1)
    run_store.append_result("extraction_p", {"_key": "a", "company_id": "a", "name": "A", "issuer_key": "a", "fields": [
        {"field_id": "f1", "route": "review"}, {"field_id": "f2", "route": "review"}, {"field_id": "f3", "route": "auto_accept"}]})
    run_store.append_review_item("extraction_p", {"item_key": "a:f1:unspecified", "company_id": "a", "field": {"field_id": "f1"}})
    run_store.append_error("extraction_p", {"key": "b", "error": "No text could be read from b.pdf", "document_problem": True})
    # a pre-step stopped d for review: an error row with review=True and a company-level review item
    report = {"failed_step": "parse_index", "error": "Parse & index failed for D: no document text could be parsed"}
    run_store.append_error("extraction_p", {"key": "d", "error": report["error"], "review": True, "report": report})
    run_store.append_review_item("extraction_p", {"item_key": "d", "company_id": "d", **report})
    step_tally._live["extraction_p"] = step_tally._Tally()
    step_tally._live["extraction_p"].add("c", "extract", 1.0)
    try:
        p = client.get(f"/api/argus/flows/{_flow(client, settings)}/progress").json()
    finally:
        step_tally._live.pop("extraction_p", None)
    assert (p["started_at"], p["done"], p["total"], p["cost_usd"], p["status"]) == ("2026-11-10T14:02:00+00:00", 2, 4, 1.234, "running")
    rows = {r["company_id"]: r for r in p["companies"]}
    assert (rows["a"]["status"], rows["a"]["needs_you"]) == ("Done", 1)  # open items, not the stored review routes
    assert (rows["d"]["status"], rows["d"]["needs_you"], rows["d"]["reason"]) == ("Done", 1, report["error"])
    assert (rows["b"]["status"], rows["b"]["reason"], rows["b"]["document_problem"]) == (
        "Failed", "No text could be read from b.pdf", True)
    assert rows["c"]["status"] == "Extracting"


def test_progress_after_stop_and_without_a_live_tally(client, settings, run_store):
    _run(run_store, "cancelled", completed_count=1)  # the API restarted: no live counts, nothing on disk
    run_store.append_result("extraction_p", {"_key": "a", "company_id": "a", "name": "A", "issuer_key": "a", "fields": []})
    p = client.get(f"/api/argus/flows/{_flow(client, settings)}/progress").json()
    assert [r["status"] for r in p["companies"]] == ["Done", "Stopped", "Stopped", "Stopped"]  # AC-72


def test_progress_needs_a_run(client, settings):
    fid = client.post("/api/argus/flows").json()["flow_id"]
    assert client.get(f"/api/argus/flows/{fid}/progress").status_code == 404
    assert client.get("/api/argus/flows/nope/progress").status_code == 404


def test_a_finished_run_moves_the_flow_to_results(client, settings, run_store):
    _run(run_store, "running")
    fid = _flow(client, settings)
    assert client.get(f"/api/argus/flows/{fid}").json()["step"] == 4
    m = run_store.load_manifest("extraction_p")
    m.status = JobStatus.COMPLETED
    run_store.save_manifest(m)
    assert client.get(f"/api/argus/flows/{fid}").json()["step"] == 5


def test_time_left_counts_from_the_latest_restart(client, settings, run_store):
    restarted = (datetime.now(UTC) - timedelta(minutes=9.5)).isoformat()
    _run(run_store, "running", created_at="2026-01-01T00:00:00+00:00", completed_count=3)
    m = run_store.load_manifest("extraction_p")
    m.params = {"restarted_at": restarted, "done_at_restart": 2}  # a Retry hours after the run finished
    run_store.save_manifest(m)
    p = client.get(f"/api/argus/flows/{_flow(client, settings)}/progress").json()
    assert p["minutes_left"] == 10  # 1 company in 9.5 minutes since the restart, 1 to go -- not months of idle time


# --- showcase-argus-fixes items 22 to 26 ---

def _companies(run_store, names, run_id="extraction_p"):
    rows = [{"company_id": c, "name": c.upper()} for c in names]
    (run_store.run_dir(run_id) / "start_request.json").write_text(json.dumps({"profile": "custom", "companies": rows}))


def _result(run_store, cid):
    run_store.append_result("extraction_p", {"_key": cid, "company_id": cid, "name": cid.upper(), "issuer_key": cid, "fields": []})


def _progress(client, settings):
    r = client.get(f"/api/argus/flows/{_flow(client, settings)}/progress")
    assert r.status_code == 200, r.text
    return r.json(), {c["company_id"]: c for c in r.json()["companies"]}


def test_a_company_dropped_for_conflicting_identifiers_reads_failed(client, settings, run_store, pg):  # AC-45, AC-46, AC-47
    from sqlalchemy import insert

    from arp.db.models import RunError
    from arp.db.session import transaction

    run_store.save_manifest(RunManifest(run_id="extraction_p", run_type="extraction", status="completed", company_count=3,
                                        completed_count=2))
    _companies(run_store, ("apple", "microsoft", "mixed"))
    _result(run_store, "apple")
    _result(run_store, "microsoft")
    with transaction(pg) as s:  # as RunStore.save_companies records a company it leaves out
        s.execute(insert(RunError).values(run_id="extraction_p", error={
            "kind": "identity_conflict", "company_id": "mixed", "conflict": ["u1", "u2"]}))
    p, rows = _progress(client, settings)
    assert (rows["mixed"]["status"], rows["mixed"]["reason"], rows["mixed"]["retryable"]) == (
        "Failed", "Identifiers match more than one company. Correct them in a new extraction.", False)
    assert (p["finished"], p["total"], p["done"]) == (3, 3, 2)


def test_finished_counts_every_row_that_reads_done_or_failed(client, settings, run_store):  # AC-48, AC-49, AC-141, AC-142
    _run(run_store, "running", completed_count=1, failed_count=1)
    _result(run_store, "a")
    run_store.append_error("extraction_p", {"key": "b", "error": "No text could be read from b.pdf", "document_problem": True})
    report = {"failed_step": "parse_index", "error": "Parse & index failed for D: no document text could be parsed"}
    run_store.append_error("extraction_p", {"key": "d", "error": report["error"], "review": True, "report": report})
    p, rows = _progress(client, settings)
    assert [rows[c]["status"] for c in "abcd"] == ["Done", "Failed", "Waiting", "Done"]
    assert (p["finished"], p["done"], p["stopping"]) == (3, 2, False)
    assert [rows[c]["retryable"] for c in "abcd"] == [False, True, False, False]


def test_never_started_rows_stay_stopped_during_a_retry(client, settings, run_store):  # AC-50
    _run(run_store, "running", failed_count=1)
    run_store.append_error("extraction_p", {"key": "b", "error": "boom"})
    m = run_store.load_manifest("extraction_p")
    m.params = {"retrying": ["b"]}
    run_store.save_manifest(m)
    _, rows = _progress(client, settings)
    assert [rows[c]["status"] for c in "abcd"] == ["Stopped", "Waiting", "Stopped", "Stopped"]


def test_a_requested_stop_is_reported(client, settings, run_store):  # AC-51
    _run(run_store, "running")
    m = run_store.load_manifest("extraction_p")
    m.cancel_requested = True
    run_store.save_manifest(m)
    assert _progress(client, settings)[0]["stopping"] is True


def test_minutes_left_from_the_stages_reached():
    start = datetime(2026, 11, 10, 14, 0, tzinfo=UTC)
    assert minutes_left(start, start + timedelta(minutes=4), done=0, total=2, reached=0.5) == 12  # 4 / 0.5 * 1.5
    assert minutes_left(start, start + timedelta(minutes=5), done=0, total=2, reached=0.75) == 9  # 5 / 0.75 * 1.25, rounded up
    assert minutes_left(start, start + timedelta(minutes=4), done=0, total=2, reached=0.0) is None
    assert minutes_left(start, start + timedelta(minutes=4), done=0, total=4, reached=0.2) is None  # too little to go by
    assert minutes_left(start, start + timedelta(minutes=6), done=3, total=10, reached=3.5) == 14  # a finished company decides


@pytest.mark.parametrize("ago, steps, expected", [
    (3.9, {"c1": "extract"}, 12),  # AC-52: one company at Extracting, one Waiting
    (4.9, {"c1": "verify"}, 9),  # AC-146: one at Checking the answers
    (3.9, {}, None),  # AC-53: both Waiting
])
def test_time_left_before_any_company_has_finished(client, settings, run_store, ago, steps, expected):
    started = (datetime.now(UTC) - timedelta(minutes=ago)).isoformat()
    run_store.save_manifest(RunManifest(run_id="extraction_p", run_type="extraction", created_at=started, status="running",
                                        company_count=2))
    _companies(run_store, ("c1", "c2"))
    step_tally._live["extraction_p"] = step_tally._Tally()
    for cid, node in steps.items():
        step_tally._live["extraction_p"].add(cid, node, 1.0)
    try:
        assert _progress(client, settings)[0]["minutes_left"] == expected
    finally:
        step_tally._live.pop("extraction_p", None)


async def test_cost_includes_the_finished_calls_of_a_company_in_progress(client, settings, run_store):  # AC-54, AC-55
    import asyncio
    from typing import TypedDict

    from langgraph.graph import END, START, StateGraph

    from arp.llm.base import LLMUsage
    from arp.orchestration.batch_runner import run_company_batch
    from arp.orchestration.cost_tracker import estimate_cost_usd
    from arp.orchestration.job_manager import JobManager
    from arp.schemas.common import CompanyRef

    calls = [LLMUsage(input_tokens=400_000, output_tokens=10_000, model="stand-in"),
             LLMUsage(input_tokens=90_000, output_tokens=70_000, model="stand-in")]
    cost = [estimate_cost_usd("stand-in", u) for u in calls]
    first_call_done, release = asyncio.Event(), asyncio.Event()

    class State(TypedDict):
        usages: list

    async def extract(state):
        return {"usages": state["usages"] + [calls[0]]}

    async def verify(state):
        first_call_done.set()
        await release.wait()
        return {"usages": state["usages"] + [calls[1]]}

    graph = StateGraph(State)
    graph.add_node("extract", extract)
    graph.add_node("verify", verify)
    graph.add_edge(START, "extract")
    graph.add_edge("extract", "verify")
    graph.add_edge("verify", END)
    compiled = graph.compile()

    async def worker(company):
        final = await step_tally.run_graph(compiled, {"usages": []})
        return {"company_id": company.company_id, "cost": sum(estimate_cost_usd(u.model, u) for u in final["usages"])}

    companies = [CompanyRef(company_id="c1", name="C1")]
    run_id = JobManager(run_store).create_run("stand_in", {}, 1, companies=companies).run_id
    _companies(run_store, ("c1",), run_id)
    url = f"/api/argus/flows/{_flow(client, settings, run_id)}/progress"
    batch = asyncio.create_task(run_company_batch(run_id, companies, run_store=run_store, worker=worker, result_to_json=dict,
                                                  cost_usd=lambda r: r["cost"], concurrency=1))
    await asyncio.wait_for(first_call_done.wait(), 10)
    running = await asyncio.to_thread(client.get, url)
    assert running.json()["cost_usd"] == pytest.approx(cost[0]) and running.json()["companies"][0]["status"] != "Done"
    release.set()
    await asyncio.wait_for(batch, 10)
    assert client.get(url).json()["cost_usd"] == pytest.approx(cost[0] + cost[1])  # each call once


async def test_a_failed_companys_finished_calls_stay_in_the_cost(client, settings, run_store):
    from arp.orchestration.batch_runner import run_company_batch
    from arp.orchestration.job_manager import JobManager
    from arp.schemas.common import CompanyRef

    async def worker(company):
        step_tally.record_call_cost(0.25)
        raise RuntimeError("model down")

    companies = [CompanyRef(company_id="c1", name="C1")]
    run_id = JobManager(run_store).create_run("stand_in", {}, 1, companies=companies).run_id
    await run_company_batch(run_id, companies, run_store=run_store, worker=worker, result_to_json=dict, concurrency=1)
    assert run_store.load_manifest(run_id).estimated_cost_usd == pytest.approx(0.25)  # the header never counts down


def test_time_left_during_a_retry_counts_only_the_retried_company(client, settings, run_store):
    """Code review of PR #425: the three never-started rows read Stopped and will not run, yet they were counted as left."""
    _run(run_store, "running", failed_count=1)
    run_store.append_error("extraction_p", {"key": "b", "error": "boom"})
    m = run_store.load_manifest("extraction_p")
    m.params = {"retrying": ["b"], "done_at_restart": 1,
                "restarted_at": (datetime.now(UTC) - timedelta(minutes=1.9)).isoformat()}
    run_store.save_manifest(m)
    step_tally._live["extraction_p"] = step_tally._Tally()
    step_tally._live["extraction_p"].add("b", "extract", 1.0)
    try:
        p, rows = _progress(client, settings)
    finally:
        step_tally._live.pop("extraction_p", None)
    assert [rows[c]["status"] for c in "abcd"] == ["Stopped", "Extracting", "Stopped", "Stopped"]
    assert p["minutes_left"] == 2  # 1.9 min for half of the one company, half to go; not 14 for four
