from __future__ import annotations

import threading
import uuid

import pytest
from sqlalchemy import select

from arp.config import Settings
from arp.db.models import ReviewItem, RunResult
from arp.db.session import require_dsn, transaction
from arp.orchestration.review_queue import queue_for_review
from arp.schemas.common import CompanyRef, JobStatus, RunManifest

LEI = "5493001KJTIIGC8Y1R13"


def test_manifest_round_trip(run_store):
    m = RunManifest(
        run_id="r1", run_type="extraction", status=JobStatus.RUNNING, params={"trial": True, "n": [1]},
        company_count=3, completed_count=1, input_tokens=7, estimated_cost_usd=0.1 + 0.2, model="m", error="e",
    )
    assert run_store.load_manifest("r1") is None
    run_store.save_manifest(m)
    assert run_store.load_manifest("r1") == m


def test_list_runs_newest_first(run_store):
    for rid, day in (("a", 2), ("b", 3), ("c", 1)):
        run_store.save_manifest(RunManifest(run_id=rid, run_type="theme", created_at=f"2026-01-0{day}T00:00:00+00:00"))
    run_store.save_manifest(RunManifest(run_id="x", run_type="extraction", params={"trial": True}))
    run_store.append_result("orphan", {"_key": "k"})  # rows without a manifest are no run
    assert [m.run_id for m in run_store.list_runs()] == ["x", "b", "a", "c"]
    assert [m.run_id for m in run_store.list_runs("theme")] == ["b", "a", "c"]
    assert run_store.extraction_runs() == []
    assert run_store.load_manifest("orphan") is None


def test_lock_serialises_manifest_updates(run_store):
    run_store.save_manifest(RunManifest(run_id="r", run_type="theme"))

    def bump():
        for _ in range(50):
            with run_store.lock("r"):
                m = run_store.load_manifest("r")
                m.completed_count += 1
                run_store.save_manifest(m)

    threads = [threading.Thread(target=bump) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert run_store.load_manifest("r").completed_count == 100


def test_lock_is_reentrant_and_creates_the_run_row(run_store):
    with run_store.lock("r"), run_store.lock("r"):
        run_store.append_result("r", {"_key": "a"})
    assert run_store.read_results("r") == [{"_key": "a"}]


def test_reappending_same_company_result_is_noop(run_store):
    run_store.save_companies("r", [CompanyRef(company_id="SIE", name="Siemens", lei=LEI)])
    run_store.append_result("r", {"_key": "SIE", "v": 1})
    run_store.append_result("r", {"_key": "SIE", "v": 2})
    run_store.append_result("r", {"_key": "theme:x", "v": 3})  # not a company key: kept, no company
    assert run_store.read_results("r") == [{"_key": "SIE", "v": 1}, {"_key": "theme:x", "v": 3}]
    entity = run_store.load_companies("r")[0].entity_id
    with transaction(run_store.dsn) as s:
        assert dict(s.execute(select(RunResult.result_key, RunResult.company_id)).all()) == {"SIE": entity, "theme:x": None}


def test_save_companies_resolves_and_records_identity_conflicts(run_store):
    run_store.save_companies("r0", [CompanyRef(company_id="A", name="A", lei=LEI), CompanyRef(company_id="B", name="B", isin="US00000000BB")])
    saved = run_store.save_companies(
        "r", [CompanyRef(company_id="C", name="C", lei=LEI, isin="US00000000BB"), CompanyRef(company_id="D", name="D")]
    )
    assert [c.company_id for c in saved] == ["D"] and saved[0].entity_id
    assert run_store.load_companies("r") == saved
    [err] = run_store.read_errors("r")
    assert err["kind"] == "identity_conflict" and err["company_id"] == "C" and len(err["conflict"]) == 2


def test_queue_for_review_sets_the_item_company(run_store):
    acme = CompanyRef(company_id="ACME", name="Acme")
    [acme] = run_store.save_companies("r", [acme])
    queue_for_review(run_store, "r", "ACME:f1", {"x": 1}, company=acme)
    queue_for_review(run_store, "r", "ACME:f1", {"x": 2}, company=acme)  # re-queued: last row wins
    queue_for_review(run_store, "r", "src:1", {"x": 3})
    rows = run_store.read_review_queue("r")
    assert [(r["item_key"], r["x"]) for r in rows] == [("ACME:f1", 2), ("src:1", 3)]
    with transaction(run_store.dsn) as s:
        got = dict(s.execute(select(ReviewItem.item_key, ReviewItem.company_id)).all())
    assert got == {"ACME:f1": acme.entity_id, "src:1": None}
    assert isinstance(acme.entity_id, uuid.UUID)


def test_app_refuses_to_start_without_dsn():
    with pytest.raises(RuntimeError, match="ARP_POSTGRES_DSN"):
        require_dsn(Settings(postgres_dsn=None))


def test_rows_jsonb_cannot_hold_are_cleaned(run_store):
    bad = {"_key": "k", "nan": float("nan"), "inf": [float("-inf")], "s\x00": "a\x00b"}
    run_store.append_result("r", bad)
    run_store.append_error("r", {**bad, "key": "k"})
    run_store.append_review_item("r", {**bad, "item_key": "k"})
    clean = {"_key": "k", "nan": None, "inf": [None], "s": "ab"}
    assert run_store.read_results("r") == [clean]
    assert run_store.read_errors("r") == [{**clean, "key": "k"}]
    assert run_store.read_review_queue("r") == [{**clean, "item_key": "k"}]


async def test_a_nan_result_does_not_stop_the_batch(run_store):
    from arp.orchestration.batch_runner import run_batch, run_sinks

    async def worker(item):
        return float("nan") if item == "a" else 1.0

    await run_batch(["a", "b"], item_key=lambda i: i, worker=worker, sinks=run_sinks(run_store, "r"),
                    concurrency=1, result_to_json=lambda v: {"v": v})
    assert sorted((r["_key"], r["v"]) for r in run_store.read_results("r")) == [("a", None), ("b", 1.0)]


async def test_company_batch_skips_identity_conflicts(run_store):
    from arp.orchestration.batch_runner import run_company_batch
    from arp.orchestration.job_manager import JobManager

    run_store.save_companies("r0", [CompanyRef(company_id="A", name="A", lei=LEI), CompanyRef(company_id="B", name="B", isin="US00000000BB")])
    universe = [CompanyRef(company_id="C", name="C", lei=LEI, isin="US00000000BB"), CompanyRef(company_id="D", name="D")]
    run_id = JobManager(run_store).create_run("theme", {}, 2, companies=universe).run_id
    seen = []

    async def worker(company):
        seen.append((company.company_id, company.entity_id is not None))
        return {}

    await run_company_batch(run_id, universe, run_store=run_store, worker=worker, result_to_json=dict, concurrency=1)
    assert seen == [("D", True)]
    assert [e["kind"] for e in run_store.read_errors(run_id)] == ["identity_conflict"]


def test_decision_rows_must_be_review_decisions(run_store):
    run_store.append_decision_row("r", {"item_key": "k", "decision": "approve"})
    run_store.append_decision_row("r", {"theme_id": "t", "action": "promote", "reason": "real"})
    with pytest.raises(ValueError, match="maybe"):
        run_store.append_decision_row("r", {"item_key": "k", "decision": "maybe"})
    with pytest.raises(ValueError):
        run_store.append_decision_row("r", {"item_key": "k"})
    assert [r.get("decision") for r in run_store.read_decisions("r")] == ["approve", None]


def test_save_companies_returns_only_stored_refs(run_store):
    twins = [CompanyRef(company_id="A", name="A", lei=LEI), CompanyRef(company_id="A2", name="A", lei=LEI)]
    assert [c.company_id for c in run_store.save_companies("r", twins)] == ["A"]
    assert run_store.load_companies("r") == run_store.save_companies("r", twins)


UNREACHABLE = "postgresql+psycopg://arp:s3cret@localhost:1/arp"


def test_startup_fails_when_postgres_is_unreachable(monkeypatch):
    from fastapi.testclient import TestClient
    from typer.testing import CliRunner

    from arp.api.main import app
    from arp.cli import app as cli
    from arp.config import get_settings
    from arp.db.session import require_postgres

    with pytest.raises(RuntimeError, match=r"arp:\*\*\*@localhost:1/arp") as exc:
        require_postgres(Settings(postgres_dsn=UNREACHABLE))
    assert "s3cret" not in str(exc.value)

    monkeypatch.setenv("ARP_POSTGRES_DSN", UNREACHABLE)
    get_settings.cache_clear()
    try:
        result = CliRunner().invoke(cli, ["runs", "list"])
        assert result.exit_code == 1 and "arp:***@localhost:1/arp" in result.stderr and "s3cret" not in result.output
        with pytest.raises(RuntimeError, match="unreachable"), TestClient(app):
            pass
    finally:
        get_settings.cache_clear()


async def test_all_conflict_run_processes_no_companies(run_store):
    from arp.orchestration.batch_runner import run_company_batch
    from arp.orchestration.job_manager import JobManager

    run_store.save_companies("r0", [CompanyRef(company_id="A", name="A", lei=LEI), CompanyRef(company_id="B", name="B", isin="US00000000BB")])
    universe = [CompanyRef(company_id="C", name="C", lei=LEI, isin="US00000000BB")]
    run_id = JobManager(run_store).create_run("theme", {}, 1, companies=universe).run_id
    assert run_store.has_companies(run_id) and run_store.load_companies(run_id) == []
    seen = []

    async def worker(company):
        seen.append(company.company_id)
        return {}

    await run_company_batch(run_id, universe, run_store=run_store, worker=worker, result_to_json=dict, concurrency=1)
    assert seen == []
    assert [e["kind"] for e in run_store.read_errors(run_id)] == ["identity_conflict"]
    assert run_store.load_manifest(run_id).status == JobStatus.COMPLETED


def test_decision_cosign_and_company_ref_are_cleaned(run_store):
    run_store.append_decision_row("r", {"item_key": "k", "decision": "approve", "comment": "a\x00b", "v": float("nan")})
    run_store.append_cosign("r", {"item_key": "k", "name": "A\x00n", "x": float("inf")})
    [ref] = run_store.save_companies("r", [CompanyRef(company_id="c\x001", name="N\x00ame")])
    assert run_store.read_decisions("r") == [{"item_key": "k", "decision": "approve", "comment": "ab", "v": None}]
    assert run_store.read_cosigns("r") == [{"item_key": "k", "name": "An", "x": None}]
    assert (ref.company_id, ref.name) == ("c1", "Name")
    assert run_store.load_companies("r") == [ref]
