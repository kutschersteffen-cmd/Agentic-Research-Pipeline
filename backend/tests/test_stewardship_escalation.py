from __future__ import annotations

import copy
import json

import pytest

pytest.importorskip("zen")

from fastapi import HTTPException  # noqa: E402

from arp.api.routers.stewardship import (  # noqa: E402
    CreateStreamRequest,
    ExceptionDecisionRequest,
    create_stream,
    decide_client_exception,
)
from arp.config import Settings  # noqa: E402
from arp.schemas.engagement import Commitment, CommitmentStatus  # noqa: E402
from arp.stewardship.escalation import (  # noqa: E402
    client_evaluate,
    evaluate,
    load_client_default,
    load_client_example,
    load_graph,
    preview,
)
from arp.stewardship.policies import PolicyStore  # noqa: E402
from arp.stewardship.process import (  # noqa: E402
    HOUSE,
    SAMPLE_PATH,
    StreamStore,
    client_store,
    escalation_contexts,
    flow,
)
from arp.storage.engagement_store import EngagementStore  # noqa: E402
from tests.conftest import PRINCIPAL

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


def _example_without_wait() -> dict:
    """The example client graph, without its 3-month wait, so a just-opened live engagement qualifies."""
    graph = load_client_example()
    rules = next(n for n in graph["nodes"] if n["id"] == "escalation_rules")
    rules["content"]["rules"][0]["mas"] = ""
    return graph


def test_client_graph_inherits_the_house_unless_it_overrides(tmp_path):
    ctxs = escalation_contexts(tmp_path, SAMPLE, [], sla_days=30)
    house = evaluate(load_graph(), ctxs)
    assert not any(r["higher"] for r in client_evaluate(load_client_default(), ctxs, house))
    higher = [r for r in client_evaluate(load_client_example(), ctxs, house) if r["higher"]]
    assert [(r["company_id"], r["recommended"], r["rule"]) for r in higher] == [
        ("SYN10", "vote_against_management", "clti_laggard")
    ]


def test_client_store_only_holds_client_policies_and_keeps_four_eyes(tmp_path):
    store = client_store(tmp_path, "pension-fund")
    assert store.versions("escalation_rules")[0]["note"] == "Same as the house"
    with pytest.raises(KeyError):
        store.versions("coverage_rules")
    version = store.save("escalation_rules", load_client_example(), "CLTI", "Designer", SAMPLE)
    with pytest.raises(ValueError, match="Four-eyes"):
        store.activate("escalation_rules", version, "designer")
    store.activate("escalation_rules", version, "Approver")
    assert PolicyStore(tmp_path).active_version("escalation_rules") == 0  # the house is untouched
    with pytest.raises(ValueError):
        client_store(tmp_path, "../escape")


@pytest.mark.parametrize("decision", ["adopt", "decline"])
def test_a_client_escalation_above_the_house_is_decided_at_the_house_checkpoint(tmp_path, decision):
    streams, engagements = StreamStore(tmp_path / "s"), EngagementStore(tmp_path / "e")
    stream = streams.get(create_stream(CreateStreamRequest(name="Pension Fund", vehicle_type="SMA"), streams)["stream_id"])
    store = client_store(streams.root, stream["stream_id"])
    store.activate(
        "escalation_rules", store.save("escalation_rules", _example_without_wait(), "", "Designer", SAMPLE), "Approver"
    )
    _, issue = engagements.open_issue("SYN10", "Synthetic Company 10", theme="climate_transition")
    settings = Settings(engagement_sla_days=365)

    def checkpoint():
        stages = flow(HOUSE, streams, engagements.list_all(), sla_days=365)["stages"]
        return [d for d in next(s for s in stages if s["id"] == "checkpoint")["decisions"] if d["kind"] == "client_exception"]

    [item] = checkpoint()
    assert (item["client"], item["house"], item["client_step"]) == ("Pension Fund", "private_engagement", "joint_engagement")
    body = ExceptionDecisionRequest(
        issue_id=issue.issue_id, client_step=item["client_step"], decision=decision
    )
    row = decide_client_exception(stream["stream_id"], body, settings, streams, engagements, PRINCIPAL)
    assert row["decision"] == decision
    # the decided step is gone (this test graph has no wait, so after an adopt it already asks for the next step)
    assert all(d["client_step"] != item["client_step"] for d in checkpoint())
    [live] = engagements.get("SYN10").issues
    assert live.escalation_stage.value == ("joint_engagement" if decision == "adopt" else "private_engagement")
    with pytest.raises(HTTPException) as again:
        decide_client_exception(stream["stream_id"], body, settings, streams, engagements, PRINCIPAL)
    assert again.value.status_code == 404
