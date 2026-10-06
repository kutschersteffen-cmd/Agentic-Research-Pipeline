"""Process gap #2: ballots decided in Proxy Voting reach the stewardship flow
-- stage 4's live counts, the checkpoint's review of votes against the
policy, and a vote_outcome monitoring trigger."""

from __future__ import annotations

import asyncio

import pytest

from arp.api.review_endpoints import submit_review
from arp.schemas.common import RunManifest
from arp.schemas.voting import CompanyBallot, PolicyRecommendation, Proposal, ProposalType, VotePosition, VoteRecord
from arp.stewardship import monitoring
from arp.stewardship.process import HOUSE, StreamStore, flow, load_sample
from arp.stewardship.voting_feed import issuer_fields, items
from arp.storage.run_store import RunStore
from arp.voting.ballot_casting import ManualInstructionBallotPlatform
from arp.voting.pipeline import cast_approved_votes

pytestmark = pytest.mark.usefixtures("sample_house_universe")


def _vote(n: str, policy: VotePosition) -> VoteRecord:
    proposal = Proposal(
        company_id="SYN01",
        meeting_id="SYN01-2026-AGM",
        meeting_date="2026-05-15",
        proposal_number=n,
        type=ProposalType.SAY_ON_PAY,
        sponsor="Management",
        resolution_text=f"Item {n}",
        management_recommendation=VotePosition.FOR,
    )
    return VoteRecord(proposal=proposal, policy_recommendation=PolicyRecommendation(vote=policy, rationale="house policy"))


def test_decided_ballots_reach_stage_4_the_checkpoint_and_monitoring(tmp_path):
    runs = RunStore(tmp_path / "runs")
    runs.save_manifest(RunManifest(run_id="vote_run", run_type="proxy_voting"))
    ballot = CompanyBallot(
        company_id="SYN01",
        name="Synthetic Company 01",
        meeting_id="SYN01-2026-AGM",
        meeting_date="2026-05-15",
        votes=[_vote("1", VotePosition.FOR), _vote("2", VotePosition.FOR), _vote("3", VotePosition.FOR)],
    )
    runs.append_jsonl(runs.results_path("vote_run"), ballot.model_dump(mode="json"))
    # 1: approved as recommended and cast; 2: overridden to against, with a reason; 3: awaiting.
    submit_review(runs, "vote_run", item_key="SYN01:1", decision="approve", reviewer="A. Reviewer", edited_value=None)
    submit_review(
        runs, "vote_run", item_key="SYN01:2", decision="edit", reviewer="A. Reviewer",
        edited_value={"vote": "against", "co_signed_by": None}, comment="Pay not linked to targets",
    )
    asyncio.run(cast_approved_votes("vote_run", runs, ManualInstructionBallotPlatform(tmp_path / "ballots")))

    rows = items(runs)
    assert [r["status"] for r in rows] == ["cast", "cast", "awaiting"]
    assert [r["overrode_policy"] for r in rows] == [False, True, False]
    assert issuer_fields(rows)["SYN01"] == {
        "vote.decided": 2,
        "vote.against_management": 1,
        "vote.overrode_policy": 1,
        "vote.last_meeting_date": "2026-05-15",
    }

    # Monitoring: the vote against management raises a trigger on SYN01 only.
    sample = load_sample(tmp_path / "frameworks", votes=rows)
    triggers = [t for t in monitoring.evaluate(monitoring.load_graph(), sample, []) if t["type"] == "vote_outcome"]
    assert [t["issuer_id"] for t in triggers] == ["SYN01"]

    stages = {s["id"]: s for s in flow(HOUSE, StreamStore(tmp_path / "s"), [], sla_days=45, votes=rows)["stages"]}
    metrics = {m["label"]: m["value"] for m in stages["voting"]["metrics"]}
    assert metrics["Ballot items decided"] == "2 of 3"
    assert metrics["Against management"] == 1
    checkpoint = {m["label"]: m["value"] for m in stages["checkpoint"]["metrics"]}
    assert checkpoint["Votes against the policy"] == 1
    [row] = stages["checkpoint"]["details"][0]["rows"]
    assert (row["item"], row["vote"], row["reason"]) == ("2", "against", "Pay not linked to targets")
