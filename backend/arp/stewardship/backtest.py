"""Builds per-resolution contexts for the policy graphs and back-tests two
policies against the same meetings: which resolutions would be voted
differently, and which issues cause it.

Input shape (see data/examples/sample_meetings.json, which is synthetic):
issuers with flat company fields keyed by field id, engagements per issuer
and theme, and meetings with their resolutions. The context contract is in
`policy_graph`'s docstring.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from arp.stewardship.policy_graph import evaluate, generate


def _nest(fields: dict[str, Any]) -> dict:
    """{"governance.board_independence_pct": 55} -> {"governance": {"board_independence_pct": 55}}"""
    out: dict = {}
    for field_id, value in fields.items():
        *parents, leaf = field_id.split(".")
        node = out
        for part in parents:
            node = node.setdefault(part, {})
        node[leaf] = value
    return out


def build_contexts(sample: dict) -> list[tuple[str, dict]]:
    """(resolution_id, context) for every resolution in the sample."""
    issuers = {i["issuer_id"]: i for i in sample["issuers"]}
    engagements: dict[str, dict] = defaultdict(dict)
    for e in sample.get("engagements", []):
        engagements[e["issuer_id"]][e["theme"]] = {k: v for k, v in e.items() if k not in ("issuer_id", "theme")}
    contexts = []
    for meeting in sample["meetings"]:
        issuer = issuers[meeting["issuer_id"]]
        issuer_context = {**_nest(issuer["fields"]), "region": issuer["region"], "sector": issuer["sector"]}
        for resolution in meeting["resolutions"]:
            contexts.append(
                (
                    f"{meeting['meeting_id']}:{resolution['item']}",
                    {"issuer": issuer_context, "resolution": resolution, "engagement": engagements[meeting["issuer_id"]]},
                )
            )
    return contexts


def backtest(base_policy: dict, other_policy: dict, sample: dict) -> dict:
    """Evaluates both policies on every resolution in the sample and
    attributes each changed vote to the issues whose rules fired differently."""
    contexts = build_contexts(sample)
    ids = [rid for rid, _ in contexts]
    base = evaluate(generate(base_policy)["graph"], [c for _, c in contexts])
    other = evaluate(generate(other_policy)["graph"], [c for _, c in contexts])

    rows, affected, masked = [], Counter(), Counter()
    for rid, (_, context), b, o in zip(ids, contexts, base, other, strict=True):
        b_hits = {(h["issue_id"], h["vote"]) for h in b["all_hits"]}
        o_hits = {(h["issue_id"], h["vote"]) for h in o["all_hits"]}
        issues = sorted({issue for issue, _ in b_hits ^ o_hits})
        changed = b["expected_vote"] != o["expected_vote"]
        for issue in issues:
            (affected if changed else masked)[issue] += 1
        rows.append(
            {
                "resolution_id": rid,
                "category": context["resolution"]["category"],
                "base_vote": b["expected_vote"],
                "other_vote": o["expected_vote"],
                "changed": changed,
                "issues": issues,
            }
        )
    return {
        "resolutions": len(rows),
        "changed": sum(r["changed"] for r in rows),
        "base_votes": dict(Counter(r["base_vote"] for r in rows)),
        "other_votes": dict(Counter(r["other_vote"] for r in rows)),
        # resolutions whose final vote changes because of the issue
        "affected_by_issue": dict(affected),
        # rule fired differently, but another rule already decided the vote
        "masked_by_issue": dict(masked),
        "rows": rows,
    }


def proposed_policy(review_result: dict, house_policy: dict) -> dict:
    """The client policy as envisioned: the house policy with every client
    position applied, as if all differences were adopted. What the review
    back-tests before anything is decided."""
    client = {r["issue_id"]: r["client_position"] for r in review_result["register"] if r.get("client_position")}
    positions = [
        {**p, **client[p["issue_id"]], "issue_id": p["issue_id"]} if p["issue_id"] in client else p
        for p in house_policy["positions"]
    ]
    return {**house_policy, "policy_id": f"{review_result['client_policy_id']}_proposed", "positions": positions}


def attach_impact(review_result: dict, house_policy: dict, sample: dict, sample_label: str) -> dict:
    """Fills `assessment.impact` on every register row from a back-test of
    the envisioned client policy against the house policy."""
    bt = backtest(house_policy, proposed_policy(review_result, house_policy), sample)
    for row in review_result["register"]:
        if "assessment" in row and "changes" in row:
            row["assessment"]["impact"] = {
                "sample": sample_label,
                "resolutions": bt["resolutions"],
                "votes_changed": bt["affected_by_issue"].get(row["issue_id"], 0),
                "rule_differences_masked": bt["masked_by_issue"].get(row["issue_id"], 0),
            }
    review_result["summary"]["backtest"] = {k: bt[k] for k in ("resolutions", "changed", "base_votes", "other_votes")} | {
        "sample": sample_label
    }
    return review_result
