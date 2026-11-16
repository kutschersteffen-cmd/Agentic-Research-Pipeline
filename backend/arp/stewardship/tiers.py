"""Coverage tiers (E1): every issuer in scope gets one of three tiers, with the
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
import logging
from collections import Counter
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import zen

from arp.schemas.engagement import EngagementRecord, EscalationStage
from arp.stewardship.backtest import _nest
from arp.stewardship.policy_review import load
from arp.stewardship.tracking import OPEN
from arp.storage.locks import KeyedLock

logger = logging.getLogger(__name__)

TIERS = ["bilateral", "letter", "monitor"]
TIER_LABELS = {"bilateral": "Bilateral", "letter": "Letter", "monitor": "Monitor"}
# Keys written before the three tiers, mapped when read; stored files are never rewritten.
# The only place the old keys appear. A confirmed thematic row is retired instead (TierStore).
RETIRED_TIER = "thematic_collaborative"
OLD_TIERS = {"priority_bilateral": "bilateral", "scaled_baseline": "letter", "systemic": "monitor", RETIRED_TIER: "letter"}
REEVALUATE_AFTER = timedelta(days=91)  # quarterly minimum (E1)
# One lock per log file, held across processes, around every check-then-append.
_LOCKS = KeyedLock(lock_path=lambda p: Path(p + ".lock"))


def map_tier(tier: object) -> object:
    """A tier key as read from a coverage-rule output or an approved programme version; only text is mapped."""
    return OLD_TIERS.get(tier, tier) if isinstance(tier, str) else tier


def _read_log(path: Path, required: Callable[[dict], tuple[str, ...]]) -> Iterator[dict]:
    """The log's rows. A damaged line (not UTF-8, not a JSON object, or missing a required field) is skipped
    with a warning; the file is never rewritten."""
    if not path.exists():
        return
    for n, raw in enumerate(path.read_bytes().splitlines(), 1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw.decode("utf-8"))
        except ValueError:  # UnicodeDecodeError and JSONDecodeError
            row = None
        if isinstance(row, dict) and all(k in row for k in required(row)):
            yield row
        else:
            logger.warning("Skipping damaged line %d in %s", n, path)


def _append(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


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
        result["tier"] = map_tier(result.get("tier"))
        if result["tier"] not in TIERS:
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
        """Every row with its tier mapped to the current keys; a retired thematic row reads as tier None."""
        rows = _read_log(self.path, lambda _r: ("issuer_id", "tier", "assigned_at"))
        return [{**r, "tier": None if r["tier"] == RETIRED_TIER else map_tier(r["tier"])} for r in rows]

    def lock(self):
        """Hold it across reading the open changes and confirming them."""
        return _LOCKS.acquire(str(self.path))

    def latest(self) -> dict[str, dict]:
        """The confirmed tier per issuer. An issuer whose latest row is retired has none."""
        latest: dict[str, dict] = {}
        for row in self.all():
            latest[row["issuer_id"]] = row
        return {i: r for i, r in latest.items() if r["tier"] is not None}

    def confirm(self, proposal: dict, decided_by: str) -> dict:
        if not decided_by.strip():
            raise ValueError("A tier confirmation needs decided_by")
        row = {**proposal, "confirmed_by": decided_by, "assigned_at": datetime.now(UTC).isoformat()}
        with self.lock():
            _append(self.path, row)
        return row


class PickStore:
    """Append-only log of bilateral picks: a pick stands from its `picked` event
    until a later `withdrawn` event for the same issuer."""

    def __init__(self, root: Path) -> None:
        self.path = root / "bilateral_picks.jsonl"

    def standing(self) -> list[dict]:
        """The standing picks, oldest first."""
        picks: dict[str, dict] = {}
        for event in _read_log(self.path, _pick_fields):
            if event["event"] == "picked":
                picks[event["issuer_id"]] = {k: event[k] for k in ("issuer_id", "reason", "by", "at")}
            else:
                picks.pop(event["issuer_id"], None)
        return list(picks.values())

    def _append(self, event: dict) -> None:
        _append(self.path, {**event, "at": datetime.now(UTC).isoformat()})

    def pick(self, issuer_id: str, reason: str, by: str, universe: set[str]) -> None:
        reason = reason.strip()
        if not reason:
            raise ValueError("A bilateral pick needs a reason")
        if len(reason) > 500:
            raise ValueError("A bilateral pick reason has at most 500 characters")
        if issuer_id not in universe:
            raise ValueError(f"Not in the house universe: {issuer_id}")
        with _LOCKS.acquire(str(self.path)):
            if any(p["issuer_id"] == issuer_id for p in self.standing()):
                raise ValueError(f"{issuer_id} is already picked for bilateral")
            self._append({"issuer_id": issuer_id, "event": "picked", "reason": reason, "by": by})

    def withdraw(self, issuer_id: str, by: str) -> None:
        with _LOCKS.acquire(str(self.path)):
            if not any(p["issuer_id"] == issuer_id for p in self.standing()):
                raise ValueError(f"{issuer_id} has no bilateral pick")
            self._append({"issuer_id": issuer_id, "event": "withdrawn", "by": by})


def _pick_fields(event: dict) -> tuple[str, ...]:
    return ("issuer_id", "event", "reason", "by", "at") if event.get("event") == "picked" else ("issuer_id", "event")


def apply_picks(proposals: list[dict], picks: list[dict]) -> list[dict]:
    """A standing pick replaces the rules' proposal for its issuer; a pick outside the proposals makes none."""
    by_issuer = {p["issuer_id"]: p for p in picks}
    return [
        {**p, "tier": "bilateral", "rule": "manual", "reason": f"Picked by {pick['by']}: {pick['reason']}"}
        if (pick := by_issuer.get(p["issuer_id"]))
        else p
        for p in proposals
    ]


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
