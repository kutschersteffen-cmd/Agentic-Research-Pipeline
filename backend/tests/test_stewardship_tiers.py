from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("zen")

from arp.stewardship.process import SAMPLE_PATH, confirm_tiers, tier_review  # noqa: E402
from arp.stewardship.tiers import TIERS, TierStore, evaluate, load_graph, review_tiers, tier_contexts  # noqa: E402
from arp.storage.engagement_store import EngagementStore  # noqa: E402

pytestmark = pytest.mark.usefixtures("sample_house_universe")


def _ctx(issuer_id="X", weight=None, aum=None, emitter=None, open_engagements=0, escalated=False) -> dict:
    return {
        "issuer_id": issuer_id,
        "name": issuer_id,
        "holding": {"index_weight_pct": weight, "aum_held_eur_m": aum},
        "issuer": {"climate": {"high_emitter": emitter}},
        "history": {"open_engagements": open_engagements, "escalated": escalated},
    }


@pytest.mark.parametrize(
    ("ctx", "tier", "rule"),
    [
        (_ctx(weight=2.0, emitter=True), "priority_bilateral", "top_weight"),  # first hit wins over the emitter rule
        (_ctx(weight=0.2, aum=800), "priority_bilateral", "large_exposure"),
        (_ctx(weight=0.2, escalated=True), "priority_bilateral", "escalated"),
        (_ctx(weight=0.02, emitter=True), "thematic_collaborative", "high_emitter"),
        (_ctx(weight=0.02), "systemic", "small_position"),
        (_ctx(weight=0.3), "scaled_baseline", "default"),
        (_ctx(), "scaled_baseline", "default"),  # no data: never fails, falls through to the default
    ],
)
def test_house_rules_assign_a_tier_with_the_rule_that_fired(ctx, tier, rule):
    [result] = evaluate(load_graph(), [ctx])
    assert (result["tier"], result["rule"]) == (tier, rule)


def test_every_sample_issuer_gets_a_valid_tier():
    sample = json.loads(SAMPLE_PATH.read_text())
    results = evaluate(load_graph(), tier_contexts(sample, []))
    assert len(results) == len(sample["issuers"]) and all(r["tier"] in TIERS and r["rule"] for r in results)


def test_confirm_is_append_only_and_only_changes_need_a_person(tmp_path):
    records = EngagementStore(tmp_path / "e").list_all()
    first = tier_review(tmp_path, json.loads(SAMPLE_PATH.read_text()), records)
    assert len(first["changes"]) == first["in_scope"] and first["confirmed"] == 0
    assert confirm_tiers(tmp_path, records, "tester") == first["in_scope"]
    after = tier_review(tmp_path, json.loads(SAMPLE_PATH.read_text()), records)
    assert after["changes"] == [] and after["confirmed"] == after["in_scope"]
    assert sum(after["distribution"].values()) == after["in_scope"]
    rows_before = len(TierStore(tmp_path).all())
    assert confirm_tiers(tmp_path, records, "tester") == 0  # nothing to confirm, nothing written
    assert len(TierStore(tmp_path).all()) == rows_before


def test_reevaluation_is_due_after_a_quarter():
    proposal = {"issuer_id": "X", "name": "X", "tier": "systemic", "rule": "r", "reason": "", "inputs": {}}
    old = {**proposal, "assigned_at": (datetime.now(UTC) - timedelta(days=100)).isoformat()}
    assert review_tiers([proposal], {"X": old})["reevaluation_due"]
    fresh = {**old, "assigned_at": datetime.now(UTC).isoformat()}
    assert not review_tiers([proposal], {"X": fresh})["reevaluation_due"]


def test_confirmation_needs_a_name(tmp_path):
    with pytest.raises(ValueError):
        TierStore(tmp_path).confirm({"issuer_id": "X", "tier": "systemic"}, " ")


def test_tier_report_endpoint(tmp_path):
    from arp.api.routers.stewardship import get_tiers
    from arp.stewardship.process import StreamStore

    engagements = EngagementStore(tmp_path / "e")
    confirm_tiers(tmp_path / "s", engagements.list_all(), "tester")
    report = get_tiers(StreamStore(tmp_path / "s"), engagements)
    assert report["confirmed"] == report["in_scope"] == len(report["assignments"])
    assert all(a["rule"] and a["confirmed_by"] == "tester" for a in report["assignments"])
