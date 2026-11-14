"""Stewardship priority worklist (spec `stewardship-priority-worklist`): one row per company in scope with the
indicator columns side by side, and a priority score from 0 to 100 that is one column among them.

Everything is computed on read from what the app already stores: holdings in the house universe, confirmed or
proposed coverage tiers, stored triggers, engagement records, the vote ledger's meetings and the portfolio
observations. Nothing is cached and no score is stored.

The score is plain arithmetic: each component's points = weight x a 0..1 normalised value, rounded to 1 decimal,
and the score is the sum of the rounded points, so the points always add up to it. The weights are the house
policy `priority_weights` (versioned and four-eyes activated like every other house policy).

The engagement selection is an append-only log per cycle (`selection/<cycle>/house.jsonl`): `added`, `removed`
and `confirmed` events. It stores no score; selecting changes nothing in the rows but the `selection` field.
"""

from __future__ import annotations

import json
import re
import threading
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path

from arp.schemas.engagement import CommitmentStatus, EngagementRecord, EscalationStage
from arp.stewardship.policies import PolicyStore, component_ids, validate_weights
from arp.stewardship.process import current_tiers
from arp.stewardship.tiers import TIERS, TierStore
from arp.stewardship.tracking import OPEN
from arp.stewardship.trigger_store import TriggerStore
from arp.storage.jsonl_io import read_jsonl

POLICY = "priority_weights"
TIER_VALUE = dict(zip(TIERS, (1.0, 0.67, 0.33, 0.0), strict=True))
GRADES = {"A": ("Leader", 0.0), "B": ("Credible", 0.2), "C": ("Gaps", 0.4), "D": ("Emerging", 0.6),
          "E": ("Not credible", 0.8), "F": ("Disqualified", 1.0)}  # fmt: skip
# row key -> portfolio observation field id (columns 11 to 14)
OBSERVED = {"transition_grade": "transition_grade", "esg_score": "esg_score", "controversy": "controversy_level",
            "carbon_intensity": "ghg_intensity"}  # fmt: skip
TOP = 25
CYCLE = re.compile(r"\d{4}-Q[1-4]")
_LOCK = threading.Lock()  # a selection change reads the log, then appends: one at a time


def cycle_of(today: date) -> str:
    return f"{today.year}-Q{(today.month - 1) // 3 + 1}"


def _percentile(values: dict[str, float]) -> dict[str, float]:
    """(rows with a smaller value) / (n - 1) among the rows that have a value; n = 1 gives 1, ties share."""
    ordered, n = sorted(values.values()), len(values)
    if n == 1:
        return dict.fromkeys(values, 1.0)
    rank, below = {}, 0
    for i, v in enumerate(ordered):
        if i and v != ordered[i - 1]:
            below = i
        rank.setdefault(v, below / (n - 1))
    return {k: rank[v] for k, v in values.items()}


def _add_years(d: date, k: int) -> date:
    try:
        return d.replace(year=d.year + k)
    except ValueError:  # 29 Feb in a non-leap year
        return d.replace(year=d.year + k, day=28)


def next_meeting(last: date, today: date) -> dict:
    """Q1: the last ledger meeting rolled forward by whole years to today or later."""
    k = max(0, today.year - last.year - 1)
    while _add_years(last, k) < today:
        k += 1
    return {"days": (_add_years(last, k) - today).days, "estimated": True, "last_meeting": last.isoformat()}


def _observed(obs, numeric: bool) -> dict | None:
    if obs is None or obs.value is None or (numeric and (isinstance(obs.value, bool) or not isinstance(obs.value, int | float))):
        return None
    return {"value": obs.value, "simulated": obs.source == "simulated"}


def _clamp(x: float) -> float:
    return min(1.0, max(0.0, x))


def indicators(
    sample: dict,
    records: list[EngagementRecord],
    triggers: list,
    tiers: dict[str, tuple[str, bool]],
    meetings: dict[str, date],
    observations: dict[str, dict],
    today: date,
) -> list[dict]:
    """One row per issuer with every indicator column and `normalised`: component id -> 0..1, or None when empty."""
    by_company = {r.company_id: r for r in records}
    counts: dict[str, Counter] = {}
    for t in triggers:
        if t.status in ("open", "acknowledged"):
            counts.setdefault(t.issuer_id, Counter())[t.severity] += 1
    issuers = sample["issuers"]
    weight = _percentile({i["issuer_id"]: v for i in issuers if (v := i.get("holding", {}).get("index_weight_pct")) is not None})
    aum = _percentile({i["issuer_id"]: v for i in issuers if (v := i.get("holding", {}).get("aum_held_eur_m")) is not None})
    observed = {i["issuer_id"]: {k: _observed(observations.get(i["issuer_id"], {}).get(f), k != "transition_grade") for k, f in OBSERVED.items()} for i in issuers}
    carbon = _percentile({k: float(o["carbon_intensity"]["value"]) for k, o in observed.items() if o["carbon_intensity"]})
    rows = []
    for issuer in issuers:
        iid, holding = issuer["issuer_id"], issuer.get("holding", {})
        record = by_company.get(iid)
        open_issues = [i for i in record.issues if i.status in OPEN] if record else []
        escalated = sum(i.escalation_stage != EscalationStage.PRIVATE_ENGAGEMENT for i in open_issues)
        overdue = sum(
            c.status == CommitmentStatus.OPEN and bool(c.target_date) and date.fromisoformat(c.target_date[:10]) < today
            for i in open_issues
            for c in i.commitments
        )
        c = counts.get(iid, Counter())
        trig = {"high": c["high"], "medium": c["medium"], "low": c["low"]}
        tier, confirmed = tiers[iid]
        meeting = next_meeting(meetings[iid], today) if iid in meetings else None
        obs = observed[iid]
        grade = obs["transition_grade"]
        if grade is not None:
            grade = {**grade, "label": GRADES.get(str(grade["value"]), ("", None))[0]}
        rows.append(
            {
                "issuer_id": iid,
                "company": issuer["name"],
                "sector": issuer["sector"],
                "holdings_weight_pct": holding.get("index_weight_pct"),
                "aum_held_eur_m": holding.get("aum_held_eur_m"),
                "coverage_tier": tier,
                "coverage_tier_confirmed": confirmed,
                "triggers": trig,
                "open_engagements": len(open_issues),
                "escalated": escalated,
                "overdue_commitments": overdue,
                "next_meeting": meeting,
                "transition_grade": grade,
                "esg_score": obs["esg_score"],
                "controversy": obs["controversy"],
                "carbon_intensity": obs["carbon_intensity"],
                "normalised": {
                    "open_triggers": min(1.0, (trig["high"] * 1.0 + trig["medium"] * 0.6 + trig["low"] * 0.3) / 2),
                    "holdings_weight": weight.get(iid),
                    "aum_held": aum.get(iid),
                    "coverage_tier": TIER_VALUE[tier],
                    "open_engagements": min(1.0, len(open_issues) / 3),
                    "escalated": 1.0 if escalated else 0.0,
                    "overdue_commitments": min(1.0, overdue / 2),
                    "next_meeting": max(0.0, 1 - meeting["days"] / 90) if meeting else None,
                    "transition_grade": GRADES.get(str(grade["value"]), ("", None))[1] if grade else None,
                    "esg_score": _clamp((10 - obs["esg_score"]["value"]) / 10) if obs["esg_score"] else None,
                    "controversy": _clamp(obs["controversy"]["value"] / 5) if obs["controversy"] else None,
                    "carbon_intensity": carbon.get(iid),
                },
            }
        )
    return rows


def score(normalised: dict[str, float | None], weights: dict) -> tuple[float, list[dict]]:
    """The score and its parts, in the bundled file's component order. A component a saved version lacks weighs 0."""
    by_id = {c["id"]: c["weight"] for c in weights["components"]}
    parts = []
    for cid in component_ids():
        value = normalised.get(cid)
        n = round(value, 4) if value is not None else 0.0
        w = by_id.get(cid, 0)
        parts.append({"id": cid, "weight": w, "normalised": n, "points": round(w * n, 1), "empty": value is None})
    return round(sum(p["points"] for p in parts), 1), parts


def ranks(scores: dict[str, float]) -> dict[str, int]:
    """1 + the number of rows with a strictly higher score (ties share a rank)."""
    ordered = sorted(scores.values(), reverse=True)
    first = {}
    for i, s in enumerate(ordered):
        first.setdefault(s, i + 1)
    return {k: first[s] for k, s in scores.items()}


def house_rows(
    root: Path, sample: dict, records: list[EngagementRecord], meetings: dict[str, date], observations: dict[str, dict], today: date
) -> list[dict]:
    """`indicators()` with the stored triggers and the tiers (the confirmed one, else the coverage rules' proposal)."""
    confirmed = TierStore(root).latest()
    tiers = {i: (t, i in confirmed) for i, t in current_tiers(root, sample, records).items()}
    return indicators(sample, records, TriggerStore(root).list_triggers(), tiers, meetings, observations, today)


def build(
    root: Path,
    sample: dict,
    records: list[EngagementRecord],
    meetings: dict[str, date] | None = None,
    observations: dict[str, dict] | None = None,
    today: date | None = None,
) -> dict:
    """The worklist of the house scope. `root` is the stewardship streams dir; `meetings` maps a company to its
    newest vote-ledger meeting date; `observations` maps a company to {field_id: latest observation}."""
    today = today or datetime.now(UTC).date()
    policies = PolicyStore(root)
    version = policies.active_version(POLICY)
    weights = policies.content(POLICY, version)
    activation = policies.activations(POLICY)[-1] if version else {}
    cycle = cycle_of(today)
    selection = {r["issuer_id"]: r for r in SelectionLog(root).rows(cycle)}
    rows = house_rows(root, sample, records, meetings or {}, observations or {}, today)
    for row in rows:
        row["score"], row["parts"] = score(row.pop("normalised"), weights)
        sel = selection.get(row["issuer_id"])
        row["selection"] = {k: v for k, v in sel.items() if k not in ("issuer_id", "company")} if sel else None
    return {
        "as_of": today.isoformat(),
        "universe_note": sample.get("note"),
        "scope": {"key": "house", "label": "All house holdings", "kind": "house", "companies": len(rows)},
        "weights": {"version": version, "activated_by": activation.get("approved_by"), "activated_at": activation.get("approved_at")},
        "cycle": cycle,
        "rows": rows,
    }


def preview(candidate: dict, active: dict, rows: list[dict]) -> dict:
    """What candidate weights change against the active ones, on rows from `indicators()` (house scope)."""
    validate_weights(candidate)
    names = {r["issuer_id"]: r["company"] for r in rows}
    old = {r["issuer_id"]: score(r["normalised"], active)[0] for r in rows}
    new = {r["issuer_id"]: score(r["normalised"], candidate)[0] for r in rows}
    rank_old, rank_new = ranks(old), ranks(new)

    def top(scores: dict, rank: dict) -> list[dict]:
        ids = sorted((i for i in scores if rank[i] <= TOP), key=lambda i: (-scores[i], names[i]))
        return [{"issuer_id": i, "company": names[i], "score": scores[i], "rank": rank[i]} for i in ids]

    def moved(ids: set) -> list[dict]:
        return [
            {"issuer_id": i, "company": names[i], "rank_active": rank_old[i], "rank_candidate": rank_new[i]}
            for i in sorted(ids, key=lambda i: (rank_new[i], names[i]))
        ]

    in_old = {i for i, r in rank_old.items() if r <= TOP}
    in_new = {i for i, r in rank_new.items() if r <= TOP}
    change = sorted(names, key=lambda i: (-abs(new[i] - old[i]), names[i]))
    return {
        "companies": len(rows),
        "top_active": top(old, rank_old),
        "top_candidate": top(new, rank_new),
        "entering_top": moved(in_new - in_old),
        "leaving_top": moved(in_old - in_new),
        "score_change": [
            {"issuer_id": i, "company": names[i], "active": old[i], "candidate": new[i], "change": round(new[i] - old[i], 1)}
            for i in change
        ],
    }


class SelectionLog:
    """The house engagement selection per cycle: an append-only log of added, removed and confirmed events."""

    def __init__(self, root: Path) -> None:
        self.root = root / "selection"

    def _path(self, cycle: str) -> Path:
        if not CYCLE.fullmatch(cycle):
            raise ValueError(f"A cycle looks like 2026-Q4, not {cycle!r}")
        return self.root / cycle / "house.jsonl"

    def rows(self, cycle: str) -> list[dict]:
        folded: dict[str, dict] = {}
        for e in read_jsonl(self._path(cycle)):
            iid = e["issuer_id"]
            if e["event"] == "added":
                folded[iid] = {
                    "issuer_id": iid, "company": e.get("company", iid), "status": "proposed",
                    "proposed_by": e["by"], "proposed_at": e["at"], "confirmed_by": None, "confirmed_at": None,
                    "weights_version": e["weights_version"],
                }  # fmt: skip
            elif e["event"] == "removed":
                folded.pop(iid, None)
            elif e["event"] == "confirmed" and iid in folded:
                folded[iid].update(status="confirmed", confirmed_by=e["by"], confirmed_at=e["at"])
        return list(folded.values())

    def change(self, cycle: str, today: date, names: dict[str, str], add: list[str], remove: list[str], by: str, weights_version: int) -> None:
        """Adds rows as proposed and removes proposed rows. Nothing is written when any id is refused."""
        current = cycle_of(today)
        if cycle != current:
            raise ValueError(f"only {current} can be changed")
        with _LOCK:
            self._change(cycle, names, add, remove, by, weights_version)

    def _change(self, cycle: str, names: dict[str, str], add: list[str], remove: list[str], by: str, weights_version: int) -> None:
        if unknown := [i for i in dict.fromkeys(add + remove) if i not in names]:
            raise ValueError(f"unknown company: {', '.join(unknown)}")
        state = {r["issuer_id"]: r["status"] for r in self.rows(cycle)}
        if any(state.get(i) == "confirmed" for i in remove):
            raise ValueError("confirmed selections cannot be removed")
        events = [{"event": "added", "issuer_id": i, "company": names[i]} for i in dict.fromkeys(add) if i not in state]
        events += [{"event": "removed", "issuer_id": i} for i in dict.fromkeys(remove) if state.get(i) == "proposed" and i not in add]
        self._write(cycle, events, by, weights_version)

    def confirm(self, cycle: str, today: date, by: str, weights_version: int) -> int:
        current = cycle_of(today)
        if cycle != current:
            raise ValueError(f"only {current} can be changed")
        with _LOCK:
            proposed = [r["issuer_id"] for r in self.rows(cycle) if r["status"] == "proposed"]
            self._write(cycle, [{"event": "confirmed", "issuer_id": i} for i in proposed], by, weights_version)
        return len(proposed)

    def _write(self, cycle: str, events: list[dict], by: str, weights_version: int) -> None:
        if not by.strip():
            raise ValueError("A selection change needs the signed-in user")
        if not events:
            return
        at = datetime.now(UTC).isoformat()
        path = self._path(cycle)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:  # one write, so a change lands whole or not at all
            f.write("".join(json.dumps({**e, "by": by, "at": at, "weights_version": weights_version}, ensure_ascii=False) + "\n" for e in events))


def last_meetings(dsn: str) -> dict[str, date]:
    """company_id -> its newest vote-ledger meeting date (the only source of Next meeting, Q1)."""
    from sqlalchemy import func, select

    from arp.db.session import transaction
    from arp.storage.postgres_models import VoteMeetingModel as M

    with transaction(dsn) as s:
        found = s.execute(select(M.company_id, func.max(M.meeting_date)).where(M.company_id.is_not(None), M.meeting_date.is_not(None)).group_by(M.company_id))
        return {cid: when.astimezone(UTC).date() for cid, when in found}


def latest_observations(store, issuer_ids: list[str]) -> dict[str, dict]:
    """company_id -> {field_id: its latest observation, any source} for columns 11 to 14, as of the latest
    holdings snapshot. Only (company, field) pairs that have observations are read."""
    dates = store.all_snapshot_dates()
    if not dates:
        return {}
    wanted, keys = set(issuer_ids), set(OBSERVED.values())
    out: dict[str, dict] = {}
    for cid, fid in store.list_observation_keys():
        if cid in wanted and fid in keys and (obs := store.latest_observation(cid, fid, dates[-1])) is not None:
            out.setdefault(cid, {})[fid] = obs
    return out
