"""Stewardship priority worklist (spec `stewardship-priority-worklist`): one row per company in scope with the
indicator columns side by side, and a priority score from 0 to 100 that is one column among them.

Everything is computed on read from what the app already stores: holdings in the house universe, confirmed or
proposed coverage tiers, stored triggers, engagement records, the vote ledger's meetings and the portfolio
observations. Nothing is cached and no score is stored.

The score is plain arithmetic: each component's points = weight x a 0..1 normalised value, rounded to 1 decimal,
and the score is the sum of the rounded points, so the points always add up to it. The weights are the house
policy `priority_weights` (versioned and four-eyes activated like every other house policy).

A scope decides which companies are rows and what Holdings weight, AUM held and Equity held mean: the house
(every issuer of the house universe), one fund, or a saved portfolio group (of funds or of companies). Every other
column is about the company and is the same in every scope.

The engagement selection is an append-only log per cycle and scope (`selection/<cycle>/<scope file>.jsonl`):
`added`, `removed` and `confirmed` events. It stores no score; selecting changes nothing in the rows but the
`selection`, `held_in` and `selected_elsewhere` fields. Programme memberships (`programmes.py`) and notes
(`notes.py`) likewise change nothing but the `programmes` and `notes` fields.
"""

from __future__ import annotations

import json
import re
import threading
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import quote, unquote

from arp.schemas.engagement import FIR_THEME_LABELS, CommitmentStatus, EngagementRecord, EscalationStage
from arp.showcase.schema import FIELD_IDS as SIMULATED_FIELDS
from arp.stewardship.notes import NoteLog
from arp.stewardship.policies import PolicyStore, component_ids, validate_weights
from arp.stewardship.process import current_tiers
from arp.stewardship.programmes import ProgrammeLog
from arp.stewardship.tiers import TIERS, TierStore
from arp.stewardship.tracking import OPEN
from arp.stewardship.trigger_store import TriggerStore
from arp.storage.jsonl_io import read_jsonl

POLICY = "priority_weights"
TIER_VALUE = dict(zip(TIERS, (1.0, 0.5, 0.0), strict=True))
GRADES = {"A": ("Leader", 0.0), "B": ("Credible", 0.2), "C": ("Gaps", 0.4), "D": ("Emerging", 0.6),
          "E": ("Not credible", 0.8), "F": ("Disqualified", 1.0)}  # fmt: skip
# row key -> portfolio observation field id (columns 11 to 14)
OBSERVED = {"transition_grade": "transition_grade", "esg_score": "esg_score", "controversy": "controversy_level",
            "carbon_intensity": "ghg_intensity"}  # fmt: skip
NORMS, EVIC = "norms_violation", "climate_evic_eur_m"
EXTRA = [f for f in SIMULATED_FIELDS if f not in (*OBSERVED.values(), NORMS)]  # `esg_extra`: simulated fields with no column
HOUSE = "All house holdings"
FUND_SCOPE = "Fund scopes need the portfolio universe"
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


def _utc(s: str) -> datetime:
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def engaged(record: EngagementRecord | None) -> tuple[dict, list[str]]:
    """Engaged (any issue, any status; last = the latest activity's UTC date, else the latest `opened_at`) and the
    last engagement topics (issues newest first by their own last activity, FIR label else theme, distinct, at most 3)."""
    issues = record.issues if record else []
    if not issues:
        return {"yes": False, "last": None}, []
    when = [_utc(c.date) for i in issues for c in i.correspondence] or [_utc(i.opened_at) for i in issues]
    newest = sorted(issues, key=lambda i: max((_utc(c.date) for c in i.correspondence), default=_utc(i.opened_at)), reverse=True)
    topics = list(dict.fromkeys(FIR_THEME_LABELS[i.fir_theme] if i.fir_theme else i.theme for i in newest))[:3]
    return {"yes": True, "last": max(when).astimezone(UTC).date().isoformat()}, topics


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
        obs, company_obs = observed[iid], observations.get(iid, {})
        norms = company_obs.get(NORMS)
        engaged_, topics = engaged(record)
        grade = obs["transition_grade"]
        if grade is not None:
            grade = {**grade, "label": GRADES.get(str(grade["value"]), ("", None))[0]}
        rows.append(
            {
                "issuer_id": iid,
                "company": issuer["name"],
                "sector": issuer["sector"],
                "identifier": iid.removeprefix("isin_"),
                "engaged": engaged_,
                "last_topics": topics,
                "norms_violation": _observed(norms, False) if norms is not None and isinstance(norms.value, bool) else None,
                "esg_extra": {f: o for f in EXTRA if (o := _observed(company_obs.get(f), False)) is not None},
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


def score(normalised: dict[str, float | None], weights: dict, ids: list[str] | None = None) -> tuple[float, list[dict]]:
    """The score and its parts, in the bundled file's component order (`ids`: read it once per call, not per row).
    A component a saved version lacks weighs 0. Points are computed from the shown 4-decimal `normalised` on purpose,
    so weight x normalised always equals the points in the why panel."""
    by_id = {c["id"]: c["weight"] for c in weights["components"]}
    parts = []
    for cid in ids or component_ids():
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
    root: Path,
    sample: dict,
    records: list[EngagementRecord],
    meetings: dict[str, date],
    observations: dict[str, dict],
    today: date,
    issuers: list[dict] | None = None,
) -> list[dict]:
    """`indicators()` with the stored triggers and the tiers (the confirmed one, else the coverage rules' proposal).
    Tiers always come from the whole house `sample`; `issuers` (default: the sample's) are the scope's rows."""
    confirmed = TierStore(root).latest()
    tiers = {i: (t, i in confirmed) for i, t in current_tiers(root, sample, records).items()}
    rows = {"issuers": sample["issuers"] if issuers is None else issuers}
    return indicators(rows, records, TriggerStore(root).list_triggers(), tiers, meetings, observations, today)


def fund_holdings(store) -> dict[str, dict]:
    """portfolio_id -> {"name", "companies": {company_id: [market value EUR, of which equity]}} at the global latest
    snapshot (each portfolio's newest snapshot on or before it), counting only holdings that resolve to a company,
    as `from_portfolio` does. Portfolios with no such holding are left out."""
    dates = store.all_snapshot_dates()
    if not dates:
        return {}
    names = {p.portfolio_id: p.name for p in store.list_portfolios()}
    asset_class = {s.security_id: s.asset_class for s in store.list_securities()}
    resolved: dict[str, str | None] = {}
    out: dict[str, dict] = {}
    for h in store.load_holdings_as_of(dates[-1]):
        if h.security_id not in asset_class:  # from_portfolio resolves only the directory's securities
            continue
        if h.security_id not in resolved:
            r = store.get_resolution(h.security_id)
            resolved[h.security_id] = r.company_id if r is not None else None
        if not (cid := resolved[h.security_id]):
            continue
        fund = out.setdefault(h.holder_id, {"name": names.get(h.holder_id, h.holder_id), "companies": {}})
        value, mv = fund["companies"].setdefault(cid, [0.0, 0.0]), h.market_value_eur or 0.0
        value[0] += mv
        if asset_class.get(h.security_id) == "equity":
            value[1] += mv
    return out


def has_funds(sample: dict) -> bool:
    """Fund scopes need the portfolio universe; the sample universe has no funds."""
    return sample.get("source") == "portfolio"


def resolve_scope(key: str, sample: dict, store) -> dict:
    """{"key", "label", "kind", "members": company ids or None, "portfolios": fund ids or None}. LookupError for an
    unknown portfolio or group (404), ValueError for a key that is not a workbench scope here (422)."""
    if key == "house":
        return {"key": key, "label": HOUSE, "kind": "house", "members": None, "portfolios": None}
    kind, _, ref = key.partition(":")
    funds_ok = has_funds(sample)
    if kind == "portfolio":
        if not funds_ok:
            raise ValueError(FUND_SCOPE)
        if (p := store.get_portfolio(ref)) is None:
            raise LookupError(f"unknown portfolio {ref}")
        return {"key": key, "label": p.name, "kind": "portfolio", "members": None, "portfolios": [ref]}
    if kind != "group":
        raise ValueError(f"Unknown scope {key}")
    if (g := store.get_group(ref)) is None:
        raise LookupError(f"unknown group {ref}")
    if g.kind == "securities":
        raise ValueError("Groups of securities are not a workbench scope")
    if g.kind == "portfolios" and not funds_ok:
        raise ValueError(FUND_SCOPE)
    scope = {"key": key, "label": g.name, "kind": "group", "members": None, "portfolios": None}
    return scope | ({"portfolios": g.members} if g.kind == "portfolios" else {"members": set(g.members)})


def _held(funds: dict[str, dict], portfolios: list[str] | None) -> dict[str, list[float]]:
    """company_id -> [market value EUR, of which equity] across the funds (all of them when `portfolios` is None)."""
    out: dict[str, list[float]] = {}
    for pid in funds if portfolios is None else portfolios:
        for cid, (mv, equity) in funds.get(pid, {}).get("companies", {}).items():
            v = out.setdefault(cid, [0.0, 0.0])
            v[0] += mv
            v[1] += equity
    return out


def scope_issuers(sample: dict, scope: dict, funds: dict[str, dict]) -> list[dict]:
    """The scope's rows as sample issuers; in a fund scope `holding` is the company's share of the scope's holdings."""
    issuers = sample["issuers"]
    if scope["members"] is not None:
        return [i for i in issuers if i["issuer_id"] in scope["members"]]
    if scope["portfolios"] is None:
        return issuers
    held = _held(funds, scope["portfolios"])
    total = sum(v[0] for v in held.values())
    return [
        {**i, "holding": {"index_weight_pct": round(v / total * 100, 3) if total else None, "aum_held_eur_m": round(v / 1e6, 1)}}
        for i in issuers
        if (v := held.get(i["issuer_id"], [None])[0]) is not None
    ]


def scope_labels(store) -> dict[str, str]:
    """scope key -> label for every fund and group (for `selected_elsewhere`)."""
    return {f"portfolio:{p.portfolio_id}": p.name for p in store.list_portfolios()} | {f"group:{g.group_id}": g.name for g in store.list_groups()}


def scopes(sample: dict, store, funds: dict[str, dict]) -> list[dict]:
    """`house`, every fund with company holdings at the latest snapshot, then every group of funds or companies."""
    out = [{"key": "house", "label": HOUSE, "kind": "house", "companies": len(sample["issuers"])}]
    out += [{"key": f"portfolio:{pid}", "label": f["name"], "kind": "portfolio", "companies": len(f["companies"])} for pid, f in funds.items()]
    for g in store.list_groups():
        try:
            scope = resolve_scope(f"group:{g.group_id}", sample, store)
        except ValueError:  # securities, or funds with the sample universe
            continue
        out.append({"key": scope["key"], "label": scope["label"], "kind": "group", "companies": len(scope_issuers(sample, scope, funds))})
    return out


def build(
    root: Path,
    sample: dict,
    records: list[EngagementRecord],
    meetings: dict[str, date] | None = None,
    observations: dict[str, dict] | None = None,
    today: date | None = None,
    scope: dict | None = None,
    funds: dict[str, dict] | None = None,
    labels: dict[str, str] | None = None,
) -> dict:
    """The worklist of a scope (default: the house). `root` is the stewardship streams dir; `meetings` maps a company
    to its newest vote-ledger meeting date; `observations` maps a company to {field_id: latest observation}; `funds`
    is `fund_holdings()`; `labels` names the other scopes for `selected_elsewhere`."""
    today = today or datetime.now(UTC).date()
    policies = PolicyStore(root)
    version = policies.active_version(POLICY)
    weights = policies.content(POLICY, version)
    activation = policies.activations(POLICY)[-1] if version else {}
    scope, funds, labels, observations = scope or resolve_scope("house", sample, None), funds or {}, labels or {}, observations or {}
    cycle = cycle_of(today)
    selections = SelectionLog(root).all_rows(cycle)
    programmes, notes = ProgrammeLog(root).memberships(), NoteLog(root).summary()
    rows = house_rows(root, sample, records, meetings or {}, observations, today, scope_issuers(sample, scope, funds))
    held = _held(funds, scope["portfolios"])
    held_in: dict[str, list[dict]] = {}
    for pid, fund in funds.items():
        total = sum(v[0] for v in fund["companies"].values())
        status = selections.get(f"portfolio:{pid}", {})
        for cid, (mv, _) in fund["companies"].items():
            held_in.setdefault(cid, []).append({
                "portfolio_id": pid, "name": fund["name"], "weight_pct": round(mv / total * 100, 3) if total else None,
                "market_value_eur_m": round(mv / 1e6, 1), "selection_status": status[cid]["status"] if cid in status else None,
            })  # fmt: skip
    labels = {"house": HOUSE, **labels}
    ids = component_ids()
    for row in rows:
        iid = row["issuer_id"]
        row["score"], row["parts"] = score(row.pop("normalised"), weights, ids)
        row["programmes"] = programmes.get(iid, [])
        sel = selections.get(scope["key"], {}).get(iid)
        row["selection"] = {k: v for k, v in sel.items() if k not in ("issuer_id", "company")} if sel else None
        row["selected_elsewhere"] = [
            {"scope": key, "label": labels.get(key, key), "status": picked[iid]["status"]}
            for key, picked in selections.items()
            if key != scope["key"] and iid in picked
        ]
        row["held_in"] = held_in.get(iid, [])
        row["equity_held_eur_m"] = round(held.get(iid, [0.0, 0.0])[1] / 1e6, 1)
        evic = observations.get(iid, {}).get(EVIC)
        aum = held[iid][0] / 1e6 if iid in held else row["aum_held_eur_m"]  # unrounded, so the share keeps 4 decimals
        ok = evic is not None and isinstance(evic.value, int | float) and not isinstance(evic.value, bool) and evic.value > 0
        row["ownership_pct"] = {"value": round(aum / evic.value * 100, 4), "simulated": evic.source == "simulated"} if ok and aum is not None else None
        row["notes"] = notes.get(iid, {"count": 0, "latest": None})
    return {
        "as_of": today.isoformat(),
        "universe_note": sample.get("note"),
        "scope": {"key": scope["key"], "label": scope["label"], "kind": scope["kind"], "companies": len(rows)},
        "weights": {"version": version, "activated_by": activation.get("approved_by"), "activated_at": activation.get("approved_at")},
        "cycle": cycle,
        "rows": rows,
    }


def preview(candidate: dict, active: dict, rows: list[dict]) -> dict:
    """What candidate weights change against the active ones, on rows from `indicators()` (house scope). The route
    validates the candidate before it builds the rows too, so a bad candidate costs no store reads."""
    validate_weights(candidate)
    names = {r["issuer_id"]: r["company"] for r in rows}
    ids = component_ids()
    old = {r["issuer_id"]: score(r["normalised"], active, ids)[0] for r in rows}
    new = {r["issuer_id"]: score(r["normalised"], candidate, ids)[0] for r in rows}
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


def _scope_file(scope: str) -> str:
    """`house`, `portfolio__<id>` or `group__<id>`; the id is %-quoted, so it never leaves the cycle's directory."""
    kind, _, ref = scope.partition(":")
    return f"{kind}__{quote(ref, safe='')}" if ref else kind


class SelectionLog:
    """The engagement selection per cycle and scope: an append-only log of added, removed and confirmed events."""

    def __init__(self, root: Path) -> None:
        self.root = root / "selection"

    def _dir(self, cycle: str) -> Path:
        if not CYCLE.fullmatch(cycle):
            raise ValueError(f"A cycle looks like 2026-Q4, not {cycle!r}")
        return self.root / cycle

    def _path(self, cycle: str, scope: str = "house") -> Path:
        return self._dir(cycle) / f"{_scope_file(scope)}.jsonl"

    def all_rows(self, cycle: str) -> dict[str, dict[str, dict]]:
        """scope key -> issuer id -> row, for every scope with a log this cycle."""
        out = {}
        for path in sorted(self._dir(cycle).glob("*.jsonl")):
            kind, _, ref = path.stem.partition("__")
            out[f"{kind}:{unquote(ref)}" if ref else kind] = {r["issuer_id"]: r for r in self._fold(path)}
        return out

    def rows(self, cycle: str, scope: str = "house") -> list[dict]:
        return self._fold(self._path(cycle, scope))

    @staticmethod
    def _fold(path: Path) -> list[dict]:
        folded: dict[str, dict] = {}
        for e in read_jsonl(path):
            iid = e["issuer_id"]
            if e["event"] == "added" and iid not in folded:  # a later `added` never overwrites a row
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

    def change(
        self,
        cycle: str,
        today: date,
        names: dict[str, str],
        add: list[str],
        remove: list[str],
        by: str,
        weights_version: int,
        scope: str = "house",
        in_scope: set[str] | None = None,
    ) -> None:
        """Adds rows as proposed and removes proposed rows. Nothing is written when any id is refused. `names` are the
        house companies; `in_scope` the scope's rows (default: all of `names`)."""
        current = cycle_of(today)
        if cycle != current:
            raise ValueError(f"only {current} can be changed")
        with _LOCK:
            self._change(cycle, scope, names, names.keys() if in_scope is None else in_scope, add, remove, by, weights_version)

    def _change(self, cycle, scope, names, in_scope, add: list[str], remove: list[str], by: str, weights_version: int) -> None:
        state = {r["issuer_id"]: r["status"] for r in self.rows(cycle, scope)}
        # a company that left the universe (or the scope) can still be removed from this cycle's rows
        if unknown := [i for i in dict.fromkeys(add + remove) if i not in names and (i in add or i not in state)]:
            raise ValueError(f"unknown company: {', '.join(unknown)}")
        if outside := [i for i in dict.fromkeys(add) if i not in in_scope]:
            raise ValueError(f"not in scope {scope}: {', '.join(outside)}")
        if any(state.get(i) == "confirmed" for i in remove):
            raise ValueError("confirmed selections cannot be removed")
        events = [{"event": "added", "issuer_id": i, "company": names[i]} for i in dict.fromkeys(add) if i not in state]
        events += [{"event": "removed", "issuer_id": i} for i in dict.fromkeys(remove) if state.get(i) == "proposed" and i not in add]
        self._write(cycle, scope, events, by, weights_version)

    def confirm(self, cycle: str, today: date, by: str, weights_version: int, scope: str = "house") -> int:
        current = cycle_of(today)
        if cycle != current:
            raise ValueError(f"only {current} can be changed")
        with _LOCK:
            proposed = [r["issuer_id"] for r in self.rows(cycle, scope) if r["status"] == "proposed"]
            self._write(cycle, scope, [{"event": "confirmed", "issuer_id": i} for i in proposed], by, weights_version)
        return len(proposed)

    def _write(self, cycle: str, scope: str, events: list[dict], by: str, weights_version: int) -> None:
        if not by.strip():
            raise ValueError("A selection change needs the signed-in user")
        if not events:
            return
        at = datetime.now(UTC).isoformat()
        path = self._path(cycle, scope)
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
    """company_id -> {field_id: its latest observation, any source} for columns 11 to 14, Norm violation, EVIC and
    `esg_extra`, as of the latest holdings snapshot. Only (company, field) pairs that have observations are read."""
    dates = store.all_snapshot_dates()
    if not dates:
        return {}
    wanted, keys = set(issuer_ids), {*OBSERVED.values(), NORMS, EVIC, *EXTRA}
    out: dict[str, dict] = {}
    for cid, fid in store.list_observation_keys():
        if cid in wanted and fid in keys and (obs := store.latest_observation(cid, fid, dates[-1])) is not None:
            out.setdefault(cid, {})[fid] = obs
    return out


MAX_VOTES = 500


def votes(dsn: str, company_id: str) -> dict:
    """Every vote-ledger decision on a meeting of the company, newest meeting first, then item number."""
    from sqlalchemy import select

    from arp.db.session import transaction
    from arp.stewardship import npx_load, seed_demo
    from arp.storage.postgres_models import VoteDecisionModel as D
    from arp.storage.postgres_models import VoteItemModel as I
    from arp.storage.postgres_models import VoteMeetingModel as M

    q = select(M, I, D).join(I, I.meeting_id == M.meeting_id).join(D, D.item_id == I.item_id).where(M.company_id == company_id)

    def key(row) -> tuple:
        m, i, _ = row
        number = i.item_number or ""
        when = -(m.meeting_date.timestamp() if m.meeting_date else float("-inf"))
        return (when, m.meeting_id, [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", number)])  # a meeting's items together

    with transaction(dsn) as s:  # the rows are read inside the session
        found = s.execute(q).all()
        rows = [
        {
            "meeting_date": m.meeting_date.astimezone(UTC).date().isoformat() if m.meeting_date else None,
            "meeting_type": m.meeting_type, "item_number": i.item_number, "description": i.description,
            "proponent": i.proponent, "management_recommendation": i.management_recommendation, "vote": d.vote,
            "vote_label": d.vote_label, "against_management": d.against_management, "rationale": d.rationale,
            "source": d.source, "demo": d.source in (npx_load.SOURCE, seed_demo.SOURCE),
        }  # fmt: skip
        for m, i, d in sorted(found, key=key)
        ]
    return {"votes": rows[:MAX_VOTES], "total": len(rows)}
