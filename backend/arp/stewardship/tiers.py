"""Coverage tiers (E1): every issuer in scope gets one of four tiers, with the
rule that decided it stored as its justification.

The rules are a ZEN decision table (`data/house_coverage_policy.graph.json`,
hit policy `first`), editable in the rule editor like every other policy. Its
inputs per issuer:

    holding.index_weight_pct, holding.aum_held_eur_m   position size
    issuer.climate.high_emitter, issuer.nature.high_impact_sector   thematic flags
    history.open_engagements, history.escalated         prior engagement

Assignments are append-only (`tier_assignments.jsonl`): re-evaluation never
edits a past row. The rules *propose*; a tier only counts once a person has
confirmed it (stage 5), and tiers are due for re-evaluation every quarter.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

import zen

from arp.schemas.engagement import EngagementRecord, EscalationStage
from arp.stewardship.backtest import _nest
from arp.stewardship.policy_review import load
from arp.stewardship.tracking import OPEN

TIERS = ["priority_bilateral", "thematic_collaborative", "scaled_baseline", "systemic"]
TIER_LABELS = {
    "priority_bilateral": "Priority Bilateral",
    "thematic_collaborative": "Thematic & Collaborative",
    "scaled_baseline": "Scaled Baseline",
    "systemic": "Systemic / Market-Level",
}
REEVALUATE_AFTER = timedelta(days=91)  # quarterly minimum (E1)


def load_graph() -> dict:
    return load("house_coverage_policy.graph.json")


def tier_contexts(sample: dict, records: list[EngagementRecord]) -> list[dict]:
    """One context per issuer: holdings, company flags and engagement history."""
    history: dict[str, dict] = {}
    for r in records:
        open_issues = [i for i in r.issues if i.status in OPEN]
        history[r.company_id] = {
            "open_engagements": len(open_issues),
            "escalated": any(i.escalation_stage != EscalationStage.PRIVATE_ENGAGEMENT for i in open_issues),
        }
    return [
        {
            "issuer_id": i["issuer_id"],
            "name": i["name"],
            "holding": i.get("holding", {}),
            "issuer": {**_nest(i["fields"]), "region": i["region"], "sector": i["sector"]},
            "history": history.get(i["issuer_id"], {"open_engagements": 0, "escalated": False}),
        }
        for i in sample["issuers"]
    ]


def evaluate(graph: dict, contexts: list[dict]) -> list[dict]:
    """The proposed tier per issuer, with the rule that fired and why."""
    content = json.dumps(graph)
    engine = zen.ZenEngine({"loader": lambda _key: content})
    out = []
    for c in contexts:
        result = engine.evaluate("coverage", c)["result"]
        if result.get("tier") not in TIERS:
            raise ValueError(f"Coverage rules returned no valid tier for {c['issuer_id']}: {result}")
        out.append(
            {
                "issuer_id": c["issuer_id"],
                "name": c["name"],
                "tier": result["tier"],
                "rule": result.get("rule"),
                "reason": result.get("reason", ""),
                "inputs": {"holding": c["holding"], "history": c["history"]},
            }
        )
    return out


class TierStore:
    """Append-only log of confirmed tier assignments."""

    def __init__(self, root: Path) -> None:
        self.path = root / "tier_assignments.jsonl"

    def all(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]

    def latest(self) -> dict[str, dict]:
        latest: dict[str, dict] = {}
        for row in self.all():
            latest[row["issuer_id"]] = row
        return latest

    def confirm(self, proposal: dict, decided_by: str) -> dict:
        if not decided_by.strip():
            raise ValueError("A tier confirmation needs decided_by")
        row = {**proposal, "confirmed_by": decided_by, "assigned_at": datetime.now(UTC).isoformat()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row


def review_tiers(proposals: list[dict], latest: dict[str, dict], now: datetime | None = None) -> dict:
    """Compares proposed tiers with the confirmed ones. A proposal needs a
    person when the issuer has no confirmed tier or its tier would change."""
    now = now or datetime.now(UTC)
    changes = []
    for p in proposals:
        current = latest.get(p["issuer_id"])
        if current is None or current["tier"] != p["tier"]:
            changes.append({**p, "current_tier": current["tier"] if current else None})
    confirmed = [latest[p["issuer_id"]] for p in proposals if p["issuer_id"] in latest]
    oldest = min((datetime.fromisoformat(r["assigned_at"]) for r in confirmed), default=None)
    return {
        "changes": changes,
        "distribution": dict(Counter(r["tier"] for r in confirmed)),
        "confirmed": len(confirmed),
        "in_scope": len(proposals),
        "reevaluation_due": oldest is not None and now - oldest > REEVALUATE_AFTER,
    }
