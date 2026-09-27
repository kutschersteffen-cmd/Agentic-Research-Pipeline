from __future__ import annotations

import copy
import json

import pytest

pytest.importorskip("zen")

from arp.schemas.engagement import Commitment, CommitmentStatus  # noqa: E402
from arp.stewardship.escalation import evaluate, load_graph, preview  # noqa: E402
from arp.stewardship.policies import PolicyStore  # noqa: E402
from arp.stewardship.process import HOUSE, SAMPLE_PATH, StreamStore, escalation_contexts, flow  # noqa: E402
from arp.storage.engagement_store import EngagementStore  # noqa: E402

SAMPLE = json.loads(SAMPLE_PATH.read_text())


def _ctx(step=0, tier=None, high=False, missed=0, months=0, stalled=False) -> dict:
    return {
        "source": "sample",
        "company_id": "X",
        "company": "X",
        "issue_id": None,
        "engagement": {
            "theme": "t",
            "step_index": step,
            "months_at_step": months,
            "commitments_missed": missed,
            "stalled": stalled,
        },
        "tier": {"tier": tier},
        "triggers": {"same_theme": int(high), "high_same_theme": high},
        "issuer": {},
    }


@pytest.mark.parametrize(
    ("ctx", "recommended", "promote", "rule"),
    [
        (
            _ctx(high=True, missed=1, months=3),
            "written_escalation_to_board",
            False,
            "high_severity_trigger",
        ),  # first hit, two steps
        (_ctx(step=1, missed=1, months=3), "written_escalation_to_board", False, "commitment_missed"),
        (_ctx(step=2, high=True, missed=1), "written_escalation_to_board", False, "hold"),  # just escalated: no repeat
        (_ctx(months=12), "joint_engagement", False, "no_progress_12m"),
        (_ctx(stalled=True), "joint_engagement", False, "stalled"),
        (_ctx(months=3), "private_engagement", False, "hold"),
        (
            _ctx(step=2, tier="thematic_collaborative", high=True, months=4),
            "escalation_to_chair",
            True,
            "high_severity_trigger",
        ),  # capped
        (_ctx(step=3, tier="thematic_collaborative", stalled=True), "escalation_to_chair", True, "stalled"),  # at the cap
        (_ctx(step=6, stalled=True), "public_statement", False, "stalled"),  # top of the ladder, no tier: not capped
        (_ctx(tier="systemic", stalled=True), "private_engagement", True, "stalled"),
        (_ctx(step=5, tier="scaled_baseline", months=3), "file_or_cofile_resolution", False, "hold"),  # never a step down
    ],
)
def test_house_rules_recommend_a_capped_step(ctx, recommended, promote, rule):
    [r] = evaluate(load_graph(), [ctx])
    assert (r["recommended"], r["promote_tier"], r["rule"]) == (recommended, promote, rule)


def test_live_engagements_use_their_own_step_commitments_and_sla(tmp_path):
    store = EngagementStore(tmp_path / "e")
    record, issue = store.open_issue("ACME", "Acme", theme="board_governance")
    store.add_commitment("ACME", issue.issue_id, Commitment(text="x", status=CommitmentStatus.MISSED))
    [live] = [c for c in escalation_contexts(tmp_path / "s", SAMPLE, store.list_all(), sla_days=-1) if c["source"] == "live"]
    assert live["issue_id"] == issue.issue_id and live["tier"] == {"tier": None}
    assert live["engagement"] | {"theme": None} == {
        "theme": None,
        "step": "private_engagement",
        "step_index": 0,
        "months_at_step": 0,
        "commitments_missed": 1,
        "stalled": True,
    }
    [r] = evaluate(load_graph(), [live])
    assert (r["recommended"], r["rule"]) == ("joint_engagement", "stalled")  # the missed commitment waits 3 months


def test_stage_5_decides_live_recommendations_only(tmp_path):
    store = EngagementStore(tmp_path / "e")
    store.open_issue("ACME", "Acme", theme="board_governance")
    stage = next(
        s for s in flow(HOUSE, StreamStore(tmp_path / "s"), store.list_all(), sla_days=-1)["stages"] if s["id"] == "checkpoint"
    )
    decisions = [d for d in stage["decisions"] if d["kind"] == "escalation"]
    assert [(d["company_id"], d["next"]) for d in decisions] == [("ACME", "joint_engagement")]
    metrics = {m["label"]: m["value"] for m in stage["metrics"]}
    assert metrics["Escalations to decide"] == 1 and metrics["Sample recommendations"] > 0


def test_preview_shows_what_a_lower_cap_changes(tmp_path):
    ctxs = escalation_contexts(tmp_path, SAMPLE, [], sla_days=30)
    candidate = copy.deepcopy(load_graph())
    caps = next(n for n in candidate["nodes"] if n["id"] == "tier_caps")
    next(r for r in caps["content"]["rules"] if r["_id"] == "priority_bilateral")["m"] = "2"
    result = preview(candidate, load_graph(), ctxs)
    assert result["promotions_candidate"] > result["promotions_active"]
    assert any(c["this draft"].endswith("(promote)") for c in result["changes"])


def test_a_cap_outside_the_ladder_is_rejected_on_save(tmp_path):
    graph = copy.deepcopy(load_graph())
    caps = next(n for n in graph["nodes"] if n["id"] == "tier_caps")
    caps["content"]["rules"][-1]["m"] = "9"  # the no-tier fallback
    with pytest.raises(ValueError, match="invalid tier cap"):
        PolicyStore(tmp_path).save("escalation_rules", graph, "", "Designer", SAMPLE)
