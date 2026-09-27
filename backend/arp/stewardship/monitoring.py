"""Stage 1 monitoring rules: which company data raises a trigger.

The rules are a ZEN decision table (`data/house_monitoring_policy.graph.json`,
hit policy `collect`, output path `triggers`), so one issuer can raise several
triggers. Each trigger has a type from the Trigger Event enum, a theme, a
severity, the rule that fired and a reason. Missing data never raises a
trigger: decision-table cells do not match null.

A trigger is matched to an open engagement on the same issuer and theme; an
unmatched trigger makes the issuer a selection candidate, and a person can open
an engagement from it.
"""

from __future__ import annotations

import json
from collections import Counter

import zen

from arp.schemas.engagement import EngagementRecord, IssueStatus
from arp.stewardship.policy_review import DATA
from arp.stewardship.tiers import tier_contexts

TYPES = {
    "vote_outcome",
    "controversy",
    "score_change",
    "holding_change",
    "commitment_missed",
    "engagement_stalled",
    "calendar",
    "manual",
}
SEVERITIES = {"low", "medium", "high"}


def load_graph() -> dict:
    return json.loads((DATA / "house_monitoring_policy.graph.json").read_text())


def evaluate(graph: dict, sample: dict, records: list[EngagementRecord]) -> list[dict]:
    """Every trigger the rules raise on the sample, matched to open engagements."""
    content = json.dumps(graph)
    engine = zen.ZenEngine({"loader": lambda _key: content})
    open_by_theme = {
        (r.company_id, i.theme): i.issue_id
        for r in records
        for i in r.issues
        if i.status in (IssueStatus.OPEN, IssueStatus.STALLED)
    }
    out = []
    for c in tier_contexts(sample, records):
        for t in engine.evaluate("monitoring", c)["result"].get("triggers") or []:
            if t.get("type") not in TYPES or t.get("severity") not in SEVERITIES or not t.get("theme"):
                raise ValueError(f"Monitoring rule {t.get('rule')!r} returned an invalid trigger for {c['issuer_id']}: {t}")
            out.append(
                {
                    "issuer_id": c["issuer_id"],
                    "company": c["name"],
                    "sector": c["issuer"]["sector"],
                    **{k: t.get(k) for k in ("type", "theme", "severity", "rule", "reason")},
                    "engagement_id": open_by_theme.get((c["issuer_id"], t["theme"])),
                }
            )
    return out


def preview(candidate: dict, active: dict, sample: dict, records: list[EngagementRecord]) -> dict:
    """What a candidate rule set would raise against the active one."""
    new, old = evaluate(candidate, sample, records), evaluate(active, sample, records)
    new_ids, old_ids = {t["issuer_id"] for t in new}, {t["issuer_id"] for t in old}
    names = {t["issuer_id"]: t["company"] for t in new + old}
    return {
        "companies": len(sample["issuers"]),
        "triggers_candidate": len(new),
        "triggers_active": len(old),
        "flagged_candidate": len(new_ids),
        "flagged_active": len(old_ids),
        "by_rule_candidate": dict(Counter(t["rule"] for t in new)),
        "by_rule_active": dict(Counter(t["rule"] for t in old)),
        "newly_flagged": [{"issuer_id": i, "company": names[i]} for i in sorted(new_ids - old_ids)],
        "no_longer_flagged": [{"issuer_id": i, "company": names[i]} for i in sorted(old_ids - new_ids)],
        "triggers": new,
    }
