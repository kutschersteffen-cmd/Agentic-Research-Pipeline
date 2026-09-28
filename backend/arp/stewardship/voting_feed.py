"""The Proxy Voting -> stewardship handoff (process gap #2).

Reads every proxy_voting run: the policy's recommendation, the person's
decision and whether it was cast, per ballot item. Stewardship sees these
two ways:

- `items()`: one row per ballot item, for stage 4 (voting) and stage 5
  (the checkpoint's review of votes cast against the policy).
- `issuer_fields()`: counts per issuer as company fields (`vote.*`), so the
  monitoring, coverage and escalation rules can use them. The house
  monitoring rules turn a vote against management into a `vote_outcome`
  trigger, which opens an engagement like any other trigger.
"""

from __future__ import annotations

from collections import defaultdict

from arp.orchestration.review_queue import latest_decisions
from arp.schemas.voting import CompanyBallot
from arp.storage.run_store import RunStore
from arp.voting.pipeline import _cast_confirmations_path, _human_decision_from_review_row, _item_key

AGAINST = {"against", "withhold"}


def items(run_store: RunStore) -> list[dict]:
    out = []
    for run in run_store.list_runs("proxy_voting"):
        decisions = latest_decisions(run_store, run.run_id)
        cast = {row.get("_key") for row in run_store.read_jsonl(_cast_confirmations_path(run_store, run.run_id))}
        for row in run_store.read_jsonl(run_store.results_path(run.run_id)):
            ballot = CompanyBallot.model_validate(row)
            for v in ballot.votes:
                key = _item_key(ballot.company_id, v.proposal.proposal_number)
                policy = v.policy_recommendation.vote.value if v.policy_recommendation else None
                management = v.proposal.management_recommendation.value if v.proposal.management_recommendation else None
                decision_row = decisions.get(key)
                human = (
                    _human_decision_from_review_row(v.policy_recommendation, decision_row)
                    if decision_row and decision_row["decision"] != "reject"
                    else None
                )
                vote = human.vote.value if human else None
                out.append(
                    {
                        "run_id": run.run_id,
                        "company_id": ballot.company_id,
                        "company": ballot.name,
                        "meeting_date": ballot.meeting_date,
                        "item": v.proposal.proposal_number,
                        "type": v.proposal.type.value,
                        "management": management,
                        "policy": policy,
                        "vote": vote,
                        "status": "cast" if key in cast else "decided" if human else "declined" if decision_row else "awaiting",
                        "decided_by": human.decided_by if human else None,
                        "co_signed_by": human.co_signed_by if human else None,
                        "note": human.override_note if human else None,
                        "overrode_policy": vote is not None and policy is not None and vote != policy,
                        "against_management": vote in AGAINST and management == "for",
                    }
                )
    return out


def issuer_fields(rows: list[dict]) -> dict[str, dict]:
    """issuer id -> `vote.*` company fields, over decided and cast items only."""
    fields: dict[str, dict] = defaultdict(
        lambda: {"vote.decided": 0, "vote.against_management": 0, "vote.overrode_policy": 0, "vote.last_meeting_date": None}
    )
    for r in rows:
        if r["vote"] is None:
            continue
        f = fields[r["company_id"]]
        f["vote.decided"] += 1
        f["vote.against_management"] += r["against_management"]
        f["vote.overrode_policy"] += r["overrode_policy"]
        f["vote.last_meeting_date"] = max(filter(None, [f["vote.last_meeting_date"], r["meeting_date"]]), default=None)
    return dict(fields)
