from __future__ import annotations

import pytest

from arp.api import main  # noqa: F401  (registers the routers)
from arp.api.routers import waiting as waiting_router
from arp.orchestration.review_queue import record_review_decision as record_decision
from arp.review.items import list_open_items
from arp.review.waiting import waiting_counts
from arp.schemas.common import RunManifest
from tests.test_review_decide import (
    ALICE,
    APPROVE,
    CORRECT,
    client,
    decide,
    env,  # noqa: F401  (the fixture)
)

pytestmark = pytest.mark.usefixtures("pg")

NO_FLOW = {"stages": []}


def counts(rs):
    return waiting_counts(rs, ALICE, NO_FLOW)


@pytest.fixture
def stub_flow(monkeypatch):
    monkeypatch.setattr(waiting_router, "flow", lambda *a, **k: NO_FLOW)


def _ballots(rs, queued=5, decided=()):
    rs.save_manifest(RunManifest(run_id="pv1", run_type="proxy_voting"))
    for i in range(queued):
        rs.append_review_item("pv1", {"item_key": f"m1:r{i}"})
    for key in decided:
        record_decision(rs, "pv1", key, "approve", "Alice", None)


def test_ac1_shape(env, stub_flow):  # noqa: F811
    r = client(ALICE).get("/api/waiting")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"review", "decisions", "ballots", "total"}
    assert all(type(v) is int for v in body.values())
    assert body["total"] == body["review"] + body["decisions"] + body["ballots"]


def test_ac2_review_equals_open_items(env, stub_flow):  # noqa: F811
    items = client(ALICE).get("/api/review/items").json()["items"]
    assert len({i["run_id"] for i in items}) >= 2
    assert client(ALICE).get("/api/waiting").json()["review"] == len(items) == len(list_open_items(env[0], ALICE))


def test_ac3_single_review_approve_drops_one(env):  # noqa: F811
    before = counts(env[0]).review
    r = decide(ALICE, APPROVE)
    assert r.status_code == 200 and r.json()["state"] == "final", r.text
    assert counts(env[0]).review == before - 1


def test_ac3b_first_of_two_unchanged(env):  # noqa: F811
    before = counts(env[0]).review
    assert decide(ALICE, CORRECT).json()["state"] == "first_done"
    assert counts(env[0]).review == before


def test_ac4_decisions_checkpoint_and_tracking_only(env):  # noqa: F811
    house = {"stages": [
        {"id": "checkpoint", "decisions": [{"kind": "tier_change"}, {"kind": "tier_change"}, {"kind": "outreach"}]},
        {"id": "tracking", "decisions": [{"kind": "commitment_due"}]},
        {"id": "voting", "decisions": [{}, {}, {}]},
    ]}
    assert waiting_counts(env[0], ALICE, house).decisions == 4


def test_ac4b_ballots(env):  # noqa: F811
    _ballots(env[0], decided=["m1:r0", "m1:r1"])
    assert counts(env[0]).ballots == 3


def test_ballots_zero_without_queue(env):  # noqa: F811
    env[0].save_manifest(RunManifest(run_id="pv2", run_type="proxy_voting"))
    assert counts(env[0]).ballots == 0


def test_ballots_changed_decision_counts_once(env):  # noqa: F811
    _ballots(env[0], decided=["m1:r0"])
    record_decision(env[0], "pv1", "m1:r0", "reject", "Alice", None)
    assert counts(env[0]).ballots == 4


def test_broken_flow_is_503(env, monkeypatch):  # noqa: F811
    def broken(*a, **k):
        raise ValueError("bad policy")

    monkeypatch.setattr(waiting_router, "flow", broken)
    r = client(ALICE).get("/api/waiting")
    assert r.status_code == 503 and "could not be counted" in r.text

