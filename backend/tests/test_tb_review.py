"""Barrier rating items in the review system: two people for a rating change, own-fact refusal, bulk accept."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from arp.api.auth import current_user
from arp.api.deps import get_document_content_store, get_run_store, settings_dep
from arp.api.main import app
from arp.config import Settings
from arp.orchestration.job_manager import JobManager
from arp.orchestration.review_queue import queue_for_review
from arp.review.context import _state
from arp.schemas.common import RunManifest
from arp.storage.document_store import DocumentContentStore
from arp.storage.run_store import RunStore
from arp.transition_barrier import RUN_TYPE
from tests.postgres_helpers import pg_dsn
from tests.transition_barrier_helpers import A_ANALYST, A_APPROVER, B_ANALYST, B_APPROVER

pytestmark = pytest.mark.usefixtures("pg")

APPROVE = {"decision": "approve", "reason_code": "confirmed"}
REJECT = {"decision": "reject", "reason_code": "wrong_value"}
CHANGED = "STL-R1:European Union"
REGIONS = ("European Union", "United States", "China")
USED = "you entered a fact this result uses"


def cell(i: int) -> str:
    return f"STL-R1:{REGIONS[i]}"


@pytest.fixture
def env(tmp_path, pg):
    rs = RunStore(pg, tmp_path / "runs")
    settings = Settings(schema_registry_dir=tmp_path / "reg", second_review_sample_rate=0.0, bulk_accept_sample_rate=0.0)
    run_id = JobManager(rs).create_run(RUN_TYPE, {"cells": []}, company_count=3).run_id
    app.dependency_overrides[get_run_store] = lambda: rs
    app.dependency_overrides[get_document_content_store] = lambda: DocumentContentStore(tmp_path / "docs", dsn=pg_dsn())
    app.dependency_overrides[settings_dep] = lambda: settings
    yield rs, settings, run_id
    for dep in (get_run_store, get_document_content_store, settings_dep, current_user):
        app.dependency_overrides.pop(dep, None)


def queue(env, i: int, kind: str, *, entered_by=()):
    rs, _, run_id = env
    current = "H" if i == 0 else "L"  # the shipped hand ratings: an approve needs the item's `current` to be the cell's
    proposed = {"changed": "M", "unchanged": current}.get(kind)
    queue_for_review(rs, run_id, cell(i), {
        "kind": kind, "code": "STL-R1", "region": REGIONS[i], "current": current, "proposed": proposed,
        "values": [], "result_key": f"{cell(i)}:r1", "entered_by": list(entered_by), "rule_book_version": 7,
    })


def client(who):
    app.dependency_overrides[current_user] = lambda: who
    return TestClient(app)


def decide(env, who, body, key=CHANGED, run_id=None):
    run_id = run_id or env[2]
    c = client(who)
    r = c.get(f"/api/review/runs/{run_id}/items/{key}/context")
    assert r.status_code == 200, r.text
    return c.post(f"/api/review/runs/{run_id}/items/{key}/decision", json={**body, "context_etag": r.json()["etag"]})


def bulk(env, who, keys, run_id=None):
    run_id = run_id or env[2]
    c = client(who)
    items = [{"item_key": k, "context_etag": c.get(f"/api/review/runs/{run_id}/items/{k}/context").json()["etag"]} for k in keys]
    return c.post("/api/extraction/items/bulk-accept", json={"run_id": run_id, "items": items})


def state(env, key=CHANGED):
    return _state(env[0], env[2], key).state


def test_ac60(env):
    queue(env, 0, "changed")
    r = decide(env, A_ANALYST, APPROVE)
    assert (r.json()["state"], r.json()["second_reasons"]) == ("first_done", ["published_change"])
    r = decide(env, A_ANALYST, APPROVE)
    assert r.status_code == 409 and r.json()["detail"] == "second review must be a different person"


def test_ac61(env):
    queue(env, 0, "changed")
    decide(env, A_ANALYST, APPROVE)
    r = decide(env, B_ANALYST, APPROVE)
    assert r.status_code == 403 and r.json()["detail"] == "a rating change is confirmed by an approver"
    assert state(env) == "first_done"


def test_ac62(env):
    queue(env, 0, "changed")
    decide(env, A_ANALYST, APPROVE)
    r = decide(env, B_ANALYST, REJECT)
    assert r.status_code == 403 and r.json()["detail"] == "a rating change is confirmed by an approver"


def test_changed_second_review_by_approver_is_final(env):
    queue(env, 0, "changed")
    decide(env, A_ANALYST, APPROVE)
    r = decide(env, A_APPROVER, APPROVE)
    assert r.status_code == 200 and r.json()["state"] == "second_done"


def test_changed_reject_is_final(env):
    queue(env, 0, "changed")
    r = decide(env, A_ANALYST, REJECT)
    assert (r.json()["state"], r.json()["second_reasons"]) == ("final", [])


def test_ac64(env):
    queue(env, 0, "changed", entered_by=["a.approver"])
    for body in (APPROVE, REJECT, {"decision": "escalate", "reason_code": "needs_expert"}):
        r = decide(env, A_APPROVER, body)
        assert r.status_code == 409 and r.json()["detail"] == USED
    assert state(env) == "pending"
    assert decide(env, B_APPROVER, APPROVE).status_code == 200


@pytest.mark.parametrize(("rate", "want"), [(1.0, ("first_done", ["sample"])), (0.0, ("final", []))])
def test_unchanged_uses_normal_sampling(env, rate, want):
    env[1].second_review_sample_rate = rate
    queue(env, 1, "unchanged")
    r = decide(env, A_ANALYST, APPROVE, key=cell(1))
    assert (r.json()["state"], r.json()["second_reasons"]) == want


def test_ac66_refusals(env):
    queue(env, 0, "changed")
    queue(env, 1, "unchanged")
    r = bulk(env, A_ANALYST, [cell(0), cell(1)])
    assert r.status_code == 200, r.text
    assert r.json() == {
        "accepted": 1, "second_review": [],
        "refused": [{"item_key": cell(0), "reason": "a rating change is not bulk-accepted"}],
    }
    assert state(env, cell(0)) == "pending" and state(env, cell(1)) == "final"


def test_ac65_bulk_accept_of_unchanged_items_is_final(env):
    for i in range(3):
        queue(env, i, "unchanged", entered_by=["b.analyst"])
    r = bulk(env, A_ANALYST, [cell(i) for i in range(3)])
    assert r.json() == {"accepted": 3, "second_review": [], "refused": []}
    assert {state(env, cell(i)) for i in range(3)} == {"final"}


def test_ac67_refusals(env):
    for i in range(3):
        queue(env, i, "unchanged", entered_by=["b.analyst"])
    r = bulk(env, B_ANALYST, [cell(i) for i in range(3)])
    assert r.status_code == 200, r.text
    assert r.json() == {
        "accepted": 0, "second_review": [], "refused": [{"item_key": cell(i), "reason": USED} for i in range(3)],
    }
    assert {state(env, cell(i)) for i in range(3)} == {"pending"}


def test_bulk_refuses_items_without_a_proposed_rating(env):
    queue(env, 1, "not_rated")
    queue(env, 2, "conflict")
    r = bulk(env, A_ANALYST, [cell(1), cell(2)])
    assert r.status_code == 200, r.text
    assert r.json() == {
        "accepted": 0, "second_review": [],
        "refused": [{"item_key": cell(i), "reason": "no rating proposed"} for i in (1, 2)],
    }
    assert {state(env, cell(i)) for i in (1, 2)} == {"pending"}


def test_bulk_stale_etag_refuses_only_that_item(env):
    queue(env, 1, "unchanged")
    queue(env, 2, "unchanged")
    c = client(A_ANALYST)
    items = [{"item_key": cell(1), "context_etag": "stale"},
             {"item_key": cell(2), "context_etag": c.get(f"/api/review/runs/{env[2]}/items/{cell(2)}/context").json()["etag"]}]
    r = c.post("/api/extraction/items/bulk-accept", json={"run_id": env[2], "items": items})
    assert r.json() == {
        "accepted": 1, "second_review": [],
        "refused": [{"item_key": cell(1), "reason": "changed since you loaded it; reload"}],
    }


def test_bulk_samples_barrier_items_by_rate_alone(env):
    env[1].bulk_accept_sample_rate = 1.0
    queue(env, 1, "unchanged")
    r = bulk(env, A_ANALYST, [cell(1)])
    assert r.json()["second_review"] == [cell(1)]
    assert state(env, cell(1)) == "first_done"


def test_legacy_review_route_cannot_decide_a_barrier_item(env):
    queue(env, 0, "changed")
    c = client(A_APPROVER)
    # Every legacy review route shares submit_review's guard; financials stands in for the removed refresh route.
    r = c.post(f"/api/financials/runs/{env[2]}/review", json={"item_key": CHANGED, "decision": "approve"})
    assert r.status_code == 400 and "review workbench" in r.text
    assert state(env) == "pending"


# --- other run types stay as they were (AC-134) ---

def _extraction(rs):
    rs.save_manifest(RunManifest(run_id="ext1", run_type="extraction"))
    for k in ("ISS1:f1:2024-12-31", "ISS2:f1:2024-12-31"):
        issuer = k.split(":")[0]
        rs.append_review_item("ext1", {
            "item_key": k, "issuer_key": issuer, "company_id": issuer, "field_id": "f1", "period_end": "2024-12-31",
            "field": {"field_id": "f1", "field_name": "f1", "value": 100, "period_end": "2024-12-31", "checks": [],
                      "route_reasons": ["low_confidence"]},
        })


def test_ac134_extraction_second_review_unchanged(env):
    _extraction(env[0])
    key = "ISS1:f1:2024-12-31"
    assert decide(env, A_ANALYST, REJECT, key=key, run_id="ext1").json()["state"] == "final"
    r = decide(env, A_ANALYST, APPROVE, key=key, run_id="ext1")  # overturns its own final outcome: a published change
    assert (r.json()["state"], r.json()["second_reasons"]) == ("first_done", ["published_change"])
    r = decide(env, B_ANALYST, APPROVE, key=key, run_id="ext1")
    assert r.status_code == 200 and r.json()["state"] == "second_done"


def test_extraction_bulk_accept_still_all_or_nothing(env):
    _extraction(env[0])
    c = client(A_ANALYST)
    keys = ["ISS1:f1:2024-12-31", "ISS2:f1:2024-12-31"]
    items = [{"item_key": k, "context_etag": c.get(f"/api/review/runs/ext1/items/{k}/context").json()["etag"]} for k in keys]
    items[1]["context_etag"] = "stale"
    r = c.post("/api/extraction/items/bulk-accept", json={"run_id": "ext1", "items": items})
    assert r.status_code == 409 and "nothing was accepted" in r.json()["detail"]
    assert env[0].read_decisions("ext1") == []
