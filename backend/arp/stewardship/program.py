"""Client program (operating model Part 5): tilt -> selection -> sanction ->
escalation, checked against the house program, and the proposal deck.

A program is calibration parameters stored on the client stream; the
simulation is recomputed from them on every request, through engines that
already exist:

1. Tilt: the index engine's `MetricTilt` on `score.clti` over the benchmark
   weights (`arp.index.weighting.apply_tilts`).
2. Selection: CLTI laggards on climate plus monitoring triggers on other
   themes, ranked by leverage (portfolio weight x gap).
3. Escalation: the client's escalation graph, chained on the house one, per
   target engagement (a new target starts at private engagement).
4. Sanction: a target whose client step reaches vote against management is
   `at_vote_step`; the client's voting policy then gives the expected votes at
   its next meeting. Expected votes only: the tool never casts a vote.
5. House comparison: overlap, workload against capacity, theme gap, vote and
   escalation conflicts, tilt coherence, each a traffic light.

The benchmark is the synthetic sample's 12 companies standing in for MSCI
World until constituents are connected; every output says so.
"""

from __future__ import annotations

import copy
import json
from math import fsum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from arp.index.weighting import apply_tilts, normalise
from arp.reporting.deck_builder import build_deck
from arp.schemas.engagement import EngagementRecord, IssueStatus
from arp.schemas.index import IndexCandidate, MetricTilt
from arp.schemas.reporting import (
    ChartSpec,
    ChartType,
    ContentItem,
    LayoutInstructions,
    ReportPlan,
    ReportSection,
    SectionLayoutHint,
    TableSpec,
)
from arp.stewardship import escalation, monitoring
from arp.stewardship.backtest import build_contexts, proposed_policy
from arp.stewardship.client_report import _dataset, _w
from arp.stewardship.policies import PolicyStore
from arp.stewardship.policy_graph import evaluate as evaluate_votes
from arp.stewardship.policy_graph import generate
from arp.stewardship.policy_review import review
from arp.stewardship.process import SAMPLE_PATH, client_store, current_tiers
from arp.stewardship.tiers import TIER_LABELS

VOTE_STEP = escalation.STEPS.index("vote_against_management")
SEVERITY_WEIGHT = {"high": 1.0, "medium": 0.6, "low": 0.3}
POOLED = {"CCF", "ETF"}


class ProgramParams(BaseModel):
    objective: str = "Tilt an MSCI World portfolio towards CLTI leaders and engage the laggards it keeps."
    normalisation: Literal["rank_percentile", "zscore", "max"] = "rank_percentile"
    tilt_floor: float = Field(default=0.5, gt=0, description="Weight multiplier for the worst CLTI score")
    tilt_ceiling: float = Field(default=1.5, gt=0, description="Weight multiplier for the best CLTI score")
    leader_clti: float = Field(default=70, ge=0, le=100)
    laggard_clti: float = Field(default=40, ge=0, le=100, description="Engage on climate below this CLTI score")
    include_triggers: bool = Field(default=True, description="Also select on medium and high monitoring triggers")
    max_targets: int = Field(default=6, ge=1, le=50)
    min_weight_ratio: float = Field(
        default=0.5, ge=0, le=1, description="Coherence: a target keeps at least this share of its benchmark weight"
    )
    effort_days: float = Field(default=10, gt=0, description="Analyst days per new engagement per year")
    free_capacity_days: float = Field(default=40, ge=0, description="Free house analyst days per year")

    @model_validator(mode="after")
    def _ordered(self) -> ProgramParams:
        if self.tilt_floor > self.tilt_ceiling:
            raise ValueError("tilt_floor must not exceed tilt_ceiling")
        if self.laggard_clti > self.leader_clti:
            raise ValueError("laggard_clti must not exceed leader_clti")
        return self


def _light(ok: bool, warn: bool) -> str:
    return "green" if ok else "amber" if warn else "red"


def _tilt(sample: dict, p: ProgramParams) -> list[dict]:
    issuers = sample["issuers"]
    bench = normalise({i["issuer_id"]: i["holding"]["index_weight_pct"] for i in issuers})
    candidates = [
        IndexCandidate(
            company_id=i["issuer_id"],
            name=i["name"],
            sector=i["sector"],
            price=1.0,
            shares_outstanding=1.0,
            metrics={"clti": i["fields"]["score.clti"]} if i["fields"].get("score.clti") is not None else {},
        )
        for i in issuers
    ]
    rule = MetricTilt(field="clti", normalisation=p.normalisation, floor=p.tilt_floor, ceiling=p.tilt_ceiling, missing="pass")
    tilted, multipliers, _ = apply_tilts(bench, candidates, [rule])
    return [
        {
            "issuer_id": i["issuer_id"],
            "company": i["name"],
            "sector": i["sector"],
            "clti": i["fields"].get("score.clti"),
            "benchmark_pct": round(bench[i["issuer_id"]] * 100, 3),
            "portfolio_pct": round(tilted[i["issuer_id"]] * 100, 3),
            "active_pct": round((tilted[i["issuer_id"]] - bench[i["issuer_id"]]) * 100, 3),
            "multiplier": round(multipliers[i["issuer_id"]], 3),
            "role": "leader"
            if (i["fields"].get("score.clti") or 0) >= p.leader_clti
            else "laggard"
            if i["fields"].get("score.clti") is not None and i["fields"]["score.clti"] < p.laggard_clti
            else "",
        }
        for i in issuers
    ]


def _weighted_clti(rows: list[dict], key: str) -> float:
    scored = [r for r in rows if r["clti"] is not None]
    total = fsum(r[key] for r in scored)
    return round(fsum(r[key] * r["clti"] for r in scored) / total, 1) if total else 0.0


def simulate(root: Path, stream: dict, records: list[EngagementRecord], sla_days: int, params: dict | None = None) -> dict:
    p = ProgramParams(**(params if params is not None else stream.get("program", {}).get("params", {})))
    sample = json.loads(SAMPLE_PATH.read_text())
    house_store = PolicyStore(root)

    # 1. Tilt
    holdings = _tilt(sample, p)
    by_issuer = {h["issuer_id"]: h for h in holdings}
    bench_clti, port_clti = _weighted_clti(holdings, "benchmark_pct"), _weighted_clti(holdings, "portfolio_pct")
    active_share = round(fsum(abs(h["active_pct"]) for h in holdings) / 2, 2)

    # 2. Selection
    candidates: dict[tuple[str, str], dict] = {}
    for h in holdings:
        if h["clti"] is not None and h["clti"] < p.laggard_clti:
            candidates[(h["issuer_id"], "climate_transition")] = {
                "reason": f"CLTI {h['clti']:g} below {p.laggard_clti:g}",
                "gap": (100 - h["clti"]) / 100,
            }
    if p.include_triggers:
        triggers = monitoring.evaluate(house_store.active("monitoring_rules"), sample, records)
        for t in triggers:
            if t["severity"] in ("high", "medium"):
                candidates.setdefault(
                    (t["issuer_id"], t["theme"]), {"reason": t["reason"], "gap": SEVERITY_WEIGHT[t["severity"]]}
                )
    house_engaged = {(e["issuer_id"], e["theme"]) for e in sample.get("engagements", [])} | {
        (r.company_id, i.theme) for r in records for i in r.issues if i.status in (IssueStatus.OPEN, IssueStatus.STALLED)
    }
    house_themes = {theme for _, theme in house_engaged}
    tiers = current_tiers(root, sample, records)
    ranked = sorted(
        (
            {
                "issuer_id": issuer_id,
                "company": by_issuer[issuer_id]["company"],
                "theme": theme,
                "reason": c["reason"],
                "portfolio_pct": by_issuer[issuer_id]["portfolio_pct"],
                "leverage": round(by_issuer[issuer_id]["portfolio_pct"] * c["gap"], 2),
                "tier": tiers.get(issuer_id),
                "origin": "house" if (issuer_id, theme) in house_engaged else "client_only",
                "weight_ratio": round(by_issuer[issuer_id]["portfolio_pct"] / by_issuer[issuer_id]["benchmark_pct"], 2)
                if by_issuer[issuer_id]["benchmark_pct"]
                else 0,
            }
            for (issuer_id, theme), c in candidates.items()
        ),
        key=lambda t: (-t["leverage"], t["issuer_id"], t["theme"]),
    )
    targets = ranked[: p.max_targets]

    # 3. Escalation: existing engagements keep their state, new targets start at the bottom
    esc_sample = copy.deepcopy(sample)
    known = {(e["issuer_id"], e["theme"]) for e in esc_sample["engagements"] if "step" in e}
    live = {(r.company_id, i.theme) for r in records for i in r.issues if i.status in (IssueStatus.OPEN, IssueStatus.STALLED)}
    for t in targets:
        if (t["issuer_id"], t["theme"]) not in known | live:
            esc_sample["engagements"].append(
                {
                    "issuer_id": t["issuer_id"],
                    "theme": t["theme"],
                    "at_vote_step": False,
                    "step": "private_engagement",
                    "months_at_step": 0,
                    "commitments_missed": 0,
                }
            )
    triggers_all = monitoring.evaluate(house_store.active("monitoring_rules"), sample, records)
    ctxs = escalation.contexts(esc_sample, records, tiers, triggers_all, sla_days)
    house_esc = escalation.evaluate(house_store.active("escalation_rules"), ctxs)
    client_esc = escalation.client_evaluate(client_store(root, stream["stream_id"]).active("escalation_rules"), ctxs, house_esc)
    esc_by_key = {(r["company_id"], r["theme"]): r for r in client_esc}  # live overrides sample for the same key
    for t in targets:
        r = esc_by_key[(t["issuer_id"], t["theme"])]
        t.update(
            step_now=r["current"],
            house_step=r["house_recommended"],
            client_step=r["recommended"],
            above_house=r["higher"],
            max_step=r["max_step"],
            at_vote_step=escalation.STEPS.index(r["recommended"]) >= VOTE_STEP,
        )

    # 4. Sanction: expected votes on the targets' meetings
    built = stream.get("built_policy")
    house_policy = house_store.active("house_voting")
    client_policy = built or proposed_policy(review(stream["client_policy"], house_policy), house_policy)
    vote_sample = copy.deepcopy(sample)
    for t in targets:
        for e in vote_sample["engagements"]:
            if (e["issuer_id"], e["theme"]) == (t["issuer_id"], t["theme"]):
                e["at_vote_step"] = t["at_vote_step"]
                break
        else:
            vote_sample["engagements"].append(
                {"issuer_id": t["issuer_id"], "theme": t["theme"], "at_vote_step": t["at_vote_step"]}
            )
    target_issuers = {t["issuer_id"] for t in targets}
    base_ctx = [(rid, c) for rid, c in build_contexts(sample) if rid.split("-")[0] in target_issuers]
    prog_ctx = [(rid, c) for rid, c in build_contexts(vote_sample) if rid.split("-")[0] in target_issuers]
    house_votes = evaluate_votes(generate(house_policy)["graph"], [c for _, c in base_ctx])
    client_votes = evaluate_votes(generate(client_policy)["graph"], [c for _, c in prog_ctx])
    votes = [
        {
            "company": by_issuer[rid.split("-")[0]]["company"],
            "resolution": f"{rid.split(':')[1]} {_w(c['resolution']['category'])}"
            + (f" ({_w(', '.join(c['resolution'].get('roles', [])))})" if c["resolution"].get("roles") else ""),
            "house": h["expected_vote"],
            "client": v["expected_vote"],
            "sanction": "yes" if "stewardship.engagement_escalation" in v["decided_by"] else "",
        }
        for (rid, c), h, v in zip(prog_ctx, house_votes, client_votes, strict=True)
    ]
    sanctions = [v for v in votes if v["sanction"]]
    conflicts = [v for v in votes if v["house"] != v["client"]]

    # 5. House comparison
    vehicle = stream["client_policy"].get("mandate", {}).get("vehicle_type", "SMA")
    overlap = sum(t["origin"] == "house" for t in targets) / len(targets) if targets else 1.0
    client_only = sum(t["origin"] == "client_only" for t in targets)
    workload = client_only * p.effort_days
    theme_gap = sorted({t["theme"] for t in targets} - house_themes)
    above = [t for t in targets if t["above_house"]]
    incoherent = [t for t in targets if t["weight_ratio"] < p.min_weight_ratio]
    checks = [
        {
            "check": "Engagement overlap",
            "value": f"{overlap:.0%} of targets already engaged by the house",
            "status": _light(overlap >= 0.5, overlap >= 0.25),
            "note": "Joining an existing dialogue costs nothing extra.",
        },
        {
            "check": "Marginal workload",
            "value": f"{workload:g} of {p.free_capacity_days:g} free analyst days",
            "status": _light(workload <= 0.8 * p.free_capacity_days, workload <= p.free_capacity_days),
            "note": f"{client_only} new engagements x {p.effort_days:g} days.",
        },
        {
            "check": "Theme gap",
            "value": ", ".join(_w(t) for t in theme_gap) or "none",
            "status": _light(not theme_gap, True),
            "note": "Themes the house does not engage on yet need new expertise.",
        },
        {
            "check": "Vote conflicts",
            "value": f"{len(conflicts)} resolutions differ from the house",
            "status": "green" if not conflicts else ("red" if vehicle in POOLED else "amber"),
            "note": f"Vehicle {vehicle}: "
            + ("pooled, votes one way; not deliverable." if vehicle in POOLED else "separate votes are possible."),
        },
        {
            "check": "Escalation above the house",
            "value": f"{len(above)} targets",
            "status": _light(not above, True),
            "note": "The house has to adopt the higher step at its checkpoint, or the proposal says it will not.",
        },
        {
            "check": "Tilt vs engagement coherence",
            "value": f"{len(incoherent)} targets below {p.min_weight_ratio:.0%} of benchmark weight",
            "status": _light(not incoherent, True),
            "note": "Leverage falls with the position.",
        },
    ]
    kpis = {
        "weighted_clti_benchmark": bench_clti,
        "weighted_clti_portfolio": port_clti,
        "clti_uplift": round(port_clti - bench_clti, 1),
        "active_share_pct": active_share,
        "targets": len(targets),
        "client_only_targets": client_only,
        "sanctions": len(sanctions),
        "vote_conflicts": len(conflicts),
    }
    return {
        "client": stream["name"],
        "stream_id": stream["stream_id"],
        "benchmark": stream["client_policy"].get("mandate", {}).get("benchmark", "MSCI World"),
        "vehicle": vehicle,
        "voting_policy": "custom policy (built)" if built else "custom policy (as envisioned, not yet built)",
        "escalation_rules": f"version {client_store(root, stream['stream_id']).active_version('escalation_rules')}"
        if client_store(root, stream["stream_id"]).active_version("escalation_rules")
        else "same as the house",
        "params": p.model_dump(),
        "kpis": kpis,
        "holdings": sorted(holdings, key=lambda h: -h["active_pct"]),
        "candidates": len(ranked),
        "targets": targets,
        "votes": votes,
        "checks": checks,
        "data_note": "Benchmark: the synthetic sample's 12 fictional companies standing in for MSCI World; scores are placeholders. "
        "Engagements marked live are the house's records. Tracking error is not computed (no risk model on the sample).",
    }


def build_proposal(sim: dict, out_path: Path) -> Path:
    k, p = sim["kpis"], sim["params"]

    def text(*lines: str) -> list[ContentItem]:
        return [ContentItem(text=t) for t in lines]

    top = sorted(sim["holdings"], key=lambda h: -abs(h["active_pct"]))[:8]
    datasets = [
        _dataset("active", [{"company": h["company"], "active weight %": h["active_pct"]} for h in top], {"active weight %"}),
        _dataset(
            "targets",
            [
                {
                    "company": t["company"],
                    "theme": _w(t["theme"]),
                    "why": t["reason"],
                    "tier": TIER_LABELS.get(t["tier"], "none"),
                    "origin": _w(t["origin"]),
                    "leverage": t["leverage"],
                }
                for t in sim["targets"]
            ],
        ),
        _dataset(
            "escalation",
            [
                {
                    "company": t["company"],
                    "theme": _w(t["theme"]),
                    "now": _w(t["step_now"]),
                    "house": _w(t["house_step"]),
                    "client": _w(t["client_step"]),
                    "above house": "yes" if t["above_house"] else "no",
                }
                for t in sim["targets"]
            ],
        ),
        _dataset("votes", [v for v in sim["votes"] if v["sanction"] or v["house"] != v["client"]]),
        _dataset("checks", [{"check": c["check"], "status": c["status"], "value": c["value"]} for c in sim["checks"]]),
    ]
    reds = [c for c in sim["checks"] if c["status"] != "green"]
    sections = [
        ReportSection(
            heading="Objective and the program on one page",
            layout_hint=SectionLayoutHint.TEXT_ONLY,
            narrative=text(
                p["objective"],
                f"Tilt: weighted CLTI {k['weighted_clti_portfolio']} against {k['weighted_clti_benchmark']} for the benchmark "
                f"({k['clti_uplift']:+}), active share {k['active_share_pct']}%.",
                f"Engagement: {k['targets']} targets, {k['client_only_targets']} not yet engaged by the house.",
                f"Voting: {sim['voting_policy']}; {k['sanctions']} expected sanction votes, {k['vote_conflicts']} differ from the house.",
                f"Escalation rules: {sim['escalation_rules']}. Vehicle: {sim['vehicle']}.",
            ),
        ),
        ReportSection(
            heading="Tilt: CLTI leaders over, laggards under",
            narrative=text(
                f"Multiplier {p['tilt_floor']}x (worst CLTI) to {p['tilt_ceiling']}x (best), {_w(p['normalisation'])}.",
                f"Weighted CLTI uplift {k['clti_uplift']:+} points.",
            ),
            chart=ChartSpec(
                dataset_id="active", chart_type=ChartType.BAR, category_column="company", value_columns=["active weight %"]
            ),
        ),
        ReportSection(
            heading="Engagement targets",
            layout_hint=SectionLayoutHint.CHART_FOCUS,
            narrative=text(f"CLTI below {p['laggard_clti']:g} on climate, plus monitoring triggers; ranked by leverage."),
            table=TableSpec(dataset_id="targets", max_rows=12),
        ),
        ReportSection(
            heading="Voting: expected sanctions and differences from the house",
            layout_hint=SectionLayoutHint.CHART_FOCUS,
            narrative=text("Expected votes only; the votes are cast by whoever votes the mandate."),
            table=TableSpec(dataset_id="votes", max_rows=12),
        )
        if datasets[3].rows
        else ReportSection(heading="Voting: expected sanctions", narrative=text("No sanction and no difference from the house.")),
        ReportSection(
            heading="Escalation: house and client steps",
            layout_hint=SectionLayoutHint.CHART_FOCUS,
            table=TableSpec(dataset_id="escalation", max_rows=12),
        ),
        ReportSection(
            heading="Feasibility against the house program",
            layout_hint=SectionLayoutHint.CHART_FOCUS,
            narrative=text(f"{len(reds)} checks need attention." if reds else "Every check is green."),
            table=TableSpec(dataset_id="checks"),
        ),
        ReportSection(
            heading="Monitoring once live",
            layout_hint=SectionLayoutHint.TEXT_ONLY,
            narrative=text(
                f"Weighted CLTI uplift stays at or above {k['clti_uplift']:+}.",
                "A new name qualifies as a target, or a target no longer does.",
                "Engagement progress per target; stalls raise triggers.",
                "Ingested votes on sanctioned resolutions match the expected vote.",
                "Client escalations waiting on a house decision.",
            ),
        ),
        ReportSection(
            heading="Calibration and data",
            layout_hint=SectionLayoutHint.TEXT_ONLY,
            narrative=text(
                f"Selection: max {p['max_targets']} targets, triggers {'included' if p['include_triggers'] else 'excluded'}; "
                f"capacity {p['free_capacity_days']:g} days at {p['effort_days']:g} per new engagement.",
                sim["data_note"],
            ),
            appendix=True,
        ),
    ]
    plan = ReportPlan(
        title=f"{sim['client']}: stewardship program proposal", subtitle=f"Benchmark {sim['benchmark']}", sections=sections
    )
    return build_deck(plan, datasets, LayoutInstructions(include_appendix=True), None, out_path)
