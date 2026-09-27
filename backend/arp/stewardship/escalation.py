"""Escalation rules: how far an open engagement should move up the ladder.

The rules are one ZEN graph (`data/house_escalation_policy.graph.json`) with two
decision tables, both hit policy `first`:

- `tier_caps`: the highest ladder step (0-6) the issuer's coverage tier allows;
- `escalation_rules`: how many steps up (`escalate_by`) this engagement should
  move, with the rule and the reason. Inputs are the engagement (step, months at
  the step, missed commitments, stalled beyond the SLA), the monitoring triggers
  on the same theme, and the issuer's company data.

The recommendation is capped by the tier. Wanting to go beyond the cap sets
`promote_tier`. The rules only recommend: a person decides every move at stage 5.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime

import zen

from arp.engagement.orchestrator import is_stalled
from arp.schemas.engagement import ESCALATION_ORDER, CommitmentStatus, EngagementRecord, IssueStatus
from arp.stewardship.backtest import _nest
from arp.stewardship.policy_review import DATA

STEPS = [s.value for s in ESCALATION_ORDER]
TOP = len(STEPS) - 1


def load_graph() -> dict:
    return json.loads((DATA / "house_escalation_policy.graph.json").read_text())


def _months_since(iso: str, now: datetime) -> int:
    return (now - datetime.fromisoformat(iso)).days // 30


def contexts(
    sample: dict,
    records: list[EngagementRecord],
    tiers: dict[str, str],
    triggers: list[dict],
    sla_days: int,
    now: datetime | None = None,
) -> list[dict]:
    """One context per open engagement: the synthetic sample ones and the live ones."""
    now = now or datetime.now(UTC)
    issuers = {i["issuer_id"]: i for i in sample["issuers"]}

    def ctx(source, company_id, company, issue_id, theme, step, months, missed, stalled):
        on_theme = [t for t in triggers if t["issuer_id"] == company_id and t["theme"] == theme]
        issuer = issuers.get(company_id)
        return {
            "source": source,
            "company_id": company_id,
            "company": company,
            "issue_id": issue_id,
            "engagement": {
                "theme": theme,
                "step": step,
                "step_index": STEPS.index(step),
                "months_at_step": months,
                "commitments_missed": missed,
                "stalled": stalled,
            },
            "tier": {"tier": tiers.get(company_id)},
            "triggers": {
                "same_theme": len(on_theme),
                "high_same_theme": any(t["severity"] == "high" for t in on_theme),
            },
            "issuer": _nest(issuer["fields"]) if issuer else {},
        }

    out = [
        ctx(
            "sample",
            e["issuer_id"],
            issuers[e["issuer_id"]]["name"],
            None,
            e["theme"],
            e["step"],
            e.get("months_at_step"),
            e.get("commitments_missed"),
            None,  # the sample has no activity dates
        )
        for e in sample.get("engagements", [])
        if "step" in e
    ]
    for r in records:
        for i in r.issues:
            if i.status not in (IssueStatus.OPEN, IssueStatus.STALLED):
                continue
            since = i.escalation_history[-1].changed_at if i.escalation_history else i.opened_at
            out.append(
                ctx(
                    "live",
                    r.company_id,
                    r.name,
                    i.issue_id,
                    i.theme,
                    i.escalation_stage.value,
                    _months_since(since, now),
                    sum(c.status == CommitmentStatus.MISSED for c in i.commitments),
                    is_stalled(i, sla_days, now),
                )
            )
    return out


def _step(value, what: str, where: str) -> int:
    if not isinstance(value, int | float) or value != int(value) or not 0 <= value <= TOP:
        raise ValueError(f"The escalation rules returned an invalid {what} for {where}: {value!r} (a whole number 0-{TOP})")
    return int(value)


def evaluate(graph: dict, ctxs: list[dict]) -> list[dict]:
    """The recommendation per engagement, capped by the tier."""
    content = json.dumps(graph)
    engine = zen.ZenEngine({"loader": lambda _key: content})
    out = []
    for c in ctxs:
        result = engine.evaluate("escalation", c)["result"]
        where = f"{c['company_id']} / {c['engagement']['theme']}"
        rec = result.get("recommendation") or {}
        cap = _step((result.get("tier") or {}).get("max_step"), "tier cap", where)
        by = _step(rec["escalate_by"], "number of steps", where) if rec else 0  # no rule matched: hold
        current = c["engagement"]["step_index"]
        wanted = min(current + by, TOP)
        recommended = max(current, min(wanted, cap))  # never recommends a step down
        out.append(
            {
                "source": c["source"],
                "company_id": c["company_id"],
                "company": c["company"],
                "issue_id": c["issue_id"],
                "theme": c["engagement"]["theme"],
                "tier": c["tier"]["tier"],
                "max_step": STEPS[cap],
                "current": STEPS[current],
                "recommended": STEPS[recommended],
                "escalate": recommended > current,
                "promote_tier": by > 0 and wanted > cap,
                "rule": rec.get("rule", "none"),
                "reason": rec.get("reason", "No rule matched"),
            }
        )
    return out


def needs_decision(r: dict) -> bool:
    return r["escalate"] or r["promote_tier"]


def preview(candidate: dict, active: dict, ctxs: list[dict]) -> dict:
    """What a candidate rule set would recommend against the active one."""
    new, old = evaluate(candidate, ctxs), evaluate(active, ctxs)
    changed = [
        {
            "company": n["company"],
            "theme": n["theme"],
            "source": n["source"],
            "current": n["current"],
            "active": o["recommended"] + (" (promote)" if o["promote_tier"] else ""),
            "this draft": n["recommended"] + (" (promote)" if n["promote_tier"] else ""),
            "why": f"{n['reason']} ({n['rule']})",
        }
        for n, o in zip(new, old, strict=True)
        if (n["recommended"], n["promote_tier"]) != (o["recommended"], o["promote_tier"])
    ]
    return {
        "engagements": len(new),
        "escalations_candidate": sum(r["escalate"] for r in new),
        "escalations_active": sum(r["escalate"] for r in old),
        "promotions_candidate": sum(r["promote_tier"] for r in new),
        "promotions_active": sum(r["promote_tier"] for r in old),
        "by_rule_candidate": dict(Counter(r["rule"] for r in new if needs_decision(r))),
        "by_rule_active": dict(Counter(r["rule"] for r in old if needs_decision(r))),
        "changes": changed,
        "recommendations": new,
    }
