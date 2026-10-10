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
    run_store.save_companies("r0", [CompanyRef(company_id="A", name="A", lei=LEI), CompanyRef(company_id="B", name="B", ticker="BB")])
    saved = run_store.save_companies(
        "r", [CompanyRef(company_id="C", name="C", lei=LEI, ticker="BB"), CompanyRef(company_id="D", name="D")]
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
