"""The StewardIQ cockpit (spec `stewardship-cockpit`): one read-only aggregate over the engagement and vote
ledger, the confirmed coverage tiers and the proxy-voting runs, for today and the next 30 days.

Every rule (control gap, escalation step, ballot state, vote topic) lives here; the page only draws."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import Row, func, select

from arp.db.session import transaction
from arp.schemas.common import CompanyRef
from arp.schemas.engagement import ESCALATION_ORDER, OLD_STAGES
from arp.stewardship.tiers import TIER_LABELS, TIERS
from arp.storage.postgres_models import (
    StwCompanyModel,
    StwEngagementModel,
    StwObjectiveModel,
    VoteDecisionModel,
    VoteItemModel,
    VoteMeetingModel,
)

WINDOW = 30
OPEN = {"open", "stalled"}
CURRENT_OBJECTIVE = {"initiated", "in_progress"}
DEMO_SOURCES = ("mock_voice_seed", "npx_urth_demo", "cockpit_demo")
DEMO_CONFIRMER = "showcase demo"
THEMES = ["Climate", "Corporate governance", "Nature", "AI and digital", "Norm violations", "Other"]
THEME_OF = {
    **dict.fromkeys(["climate_mitigation", "climate_adaptation"], "Climate"),
    **dict.fromkeys(["governance_board_pay", "business_ethics", "tax_accounting", "shareholder_rights"], "Corporate governance"),
    **dict.fromkeys(["natural_capital", "resources_circular", "pollution"], "Nature"),
    "digital_responsibility": "AI and digital",
    **dict.fromkeys(["human_rights", "human_capital", "consumer_protection", "communities"], "Norm violations"),
}
RULE_THEME = {"high_emitter": "Climate", "nature_impact": "Nature"}
STEP_LABELS = ["Private dialogue", "Letter to the board", "Meeting with the chair", "Vote against management",
               "File a resolution", "Public statement"]  # fmt: skip
STAGES = [s.value for s in ESCALATION_ORDER]
TOPICS = ["Shareholder proposals", "Remuneration", "Director elections", "Auditors", "Capital and other"]
RUN_TOPIC = {"shareholder_resolution": TOPICS[0], "say_on_pay": TOPICS[1], "director_election": TOPICS[2],
             "auditor_ratification": TOPICS[3]}  # fmt: skip
AGAINST = {"against", "withhold"}


def theme_of(fir_theme: str | None) -> str:
    return THEME_OF.get(fir_theme or "", "Other")


def step_of(stage: str | None) -> int:
    """1-based position on the ladder; null and unknown stages count as step 1, a retired stage name maps first (OLD_STAGES)."""
    stage = OLD_STAGES.get(stage, stage) if stage else None
    return STAGES.index(stage) + 1 if stage in STAGES else 1


def ballot_state_of_run(statuses: list[str]) -> str:
    if statuses and all(s == "cast" for s in statuses):
        return "cast"
    return "awaiting" if "awaiting" in statuses or not statuses else "decided"


def ballot_state_of_ledger(items: int, decided: int) -> str:
    if items and decided == items:
        return "cast"
    return "awaiting" if decided else "not_started"


def ledger_topic(proponent: str | None, categories: list[str] | None) -> str:
    cats = [c.upper() for c in categories or []]
    if (proponent or "").lower() == "shareholder":
        return TOPICS[0]
    for topic, needles in ((TOPICS[1], ("SAY-ON-PAY", "COMPENSATION")), (TOPICS[2], ("DIRECTOR",)), (TOPICS[3], ("AUDIT",))):
        if any(n in c for c in cats for n in needles):
            return topic
    return TOPICS[4]


def _vote_bucket(vote: str | None) -> str:
    if vote == "withhold":
        return "against"
    return vote if vote in ("for", "against", "abstain") else "other"


def _utc_day(ts: datetime | None) -> date | None:
    return ts.astimezone(UTC).date() if ts else None


def _iso_day(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None


CONTRIBUTORS = 6


def emissions_of(
    financed: dict[str, float], uncovered: int, companies: dict[str, CompanyRef], engaged: set[str], selected: set[str], escalated: set[str]
) -> dict | None:
    """The `emissions` section from per-company financed tCO2e (`metrics.financed_emissions_by_company` over the
    scope's holdings); None when the total is 0. Sums are taken unrounded, then rounded to 0.01 t."""
    total = sum(financed.values())
    if not total:
        return None

    def status(c: str) -> str:
        if c in escalated:
            return "in_escalation"
        return "engaged" if c in engaged else "selected" if c in selected else "not_selected"

    def name(c: str) -> str:
        return companies[c].name if c in companies else c

    top = sorted(financed, key=lambda c: (-financed[c], name(c), c))[:CONTRIBUTORS]
    return {
        "total_tco2e": round(total, 2),
        "engaged_tco2e": round(sum(v for c, v in financed.items() if c in engaged), 2),
        "selected_not_engaged_tco2e": round(sum(v for c, v in financed.items() if c in selected and c not in engaged), 2),
        "not_selected_tco2e": round(sum(v for c, v in financed.items() if c not in engaged and c not in selected), 2),
        "uncovered_holding_count": uncovered,
        "contributors": [
            {"company_id": c, "company": name(c), "sector": companies[c].sector if c in companies else None,
             "tco2e": round(financed[c], 2), "share": round(financed[c] / total, 4), "status": status(c)}  # fmt: skip
            for c in top
        ],
    }


def build(
    dsn: str,
    as_of: date,
    run_items: list[dict],
    confirmed: dict[str, dict],
    held: set[str] | None,
    financed: tuple[dict[str, float], int, dict[str, CompanyRef]] | None = None,
) -> dict:
    """Every section but `scope` and `portfolios`. `held` is the scope's company keys, None for all portfolios;
    `confirmed` is `TierStore.latest()`; `run_items` is `voting_feed.items()` (runs newest first); `financed` is
    the scope's per-company financed tCO2e, uncovered holding count and the portfolio companies, None for no
    `emissions`."""
    window = [as_of + timedelta(days=i) for i in range(WINDOW)]
    end = window[-1]

    def in_scope(company_id: str | None) -> bool:
        return held is None or company_id in held

    with transaction(dsn) as s:
        names = {c: n for c, n in s.execute(select(StwCompanyModel.company_id, StwCompanyModel.name))}
        engagements = [e for e in s.execute(select(
                StwEngagementModel.engagement_id, StwEngagementModel.company_id, StwEngagementModel.source, StwEngagementModel.status,
                StwEngagementModel.fir_theme, StwEngagementModel.escalation_stage, StwEngagementModel.planned_meeting_date, StwEngagementModel.started_at,
            )) if in_scope(e.company_id)]  # fmt: skip
        open_ids = [e.engagement_id for e in engagements if e.status in OPEN]
        objectives: dict[str, Row] = {}
        for o in s.execute(select(StwObjectiveModel.engagement_id, StwObjectiveModel.objective_id, StwObjectiveModel.description, StwObjectiveModel.started_at).where(StwObjectiveModel.engagement_id.in_(open_ids), StwObjectiveModel.status.in_(CURRENT_OBJECTIVE))):
            key = (o.started_at or datetime.min.replace(tzinfo=UTC), o.objective_id)
            cur = objectives.get(o.engagement_id)
            if cur is None or key > (cur.started_at or datetime.min.replace(tzinfo=UTC), cur.objective_id):
                objectives[o.engagement_id] = o
        day_start = datetime.combine(as_of, datetime.min.time(), tzinfo=UTC)
        meetings = [
            m
            for m in s.execute(
                select(VoteMeetingModel.meeting_id, VoteMeetingModel.company_id, VoteMeetingModel.issuer_name, VoteMeetingModel.meeting_date).where(
                    VoteMeetingModel.company_id.is_not(None),
                    VoteMeetingModel.meeting_date >= day_start,
                    VoteMeetingModel.meeting_date < day_start + timedelta(days=WINDOW),
                )
            )
            if in_scope(m.company_id)
        ]
        item_counts = dict(
            s.execute(
                select(VoteItemModel.meeting_id, func.count()).where(VoteItemModel.meeting_id.in_([m.meeting_id for m in meetings])).group_by(VoteItemModel.meeting_id)
            ).all()
        )
        decided_counts = dict(
            s.execute(
                select(VoteItemModel.meeting_id, func.count(func.distinct(VoteItemModel.item_id)))
                .join(VoteDecisionModel, VoteDecisionModel.item_id == VoteItemModel.item_id)
                .where(VoteItemModel.meeting_id.in_([m.meeting_id for m in meetings]))
                .group_by(VoteItemModel.meeting_id)
            ).all()
        )
        season_start = datetime(as_of.year, 1, 1, tzinfo=UTC)
        season_end = day_start + timedelta(days=1)
        decisions = [
            r
            for r in s.execute(
                select(
                    VoteMeetingModel.company_id, VoteMeetingModel.issuer_name, VoteMeetingModel.meeting_date,
                    VoteItemModel.categories, VoteItemModel.proponent, VoteDecisionModel.vote, VoteDecisionModel.against_management,
                )
                .join(VoteItemModel, VoteItemModel.meeting_id == VoteMeetingModel.meeting_id)
                .join(VoteDecisionModel, VoteDecisionModel.item_id == VoteItemModel.item_id)
                .where(VoteMeetingModel.meeting_date >= season_start, VoteMeetingModel.meeting_date < season_end)
            )  # fmt: skip
            if in_scope(r.company_id)
        ]
        ledger_run_ids = set(s.scalars(select(VoteDecisionModel.run_id).where(VoteDecisionModel.run_id.is_not(None)).distinct()))
        demo_meeting = s.scalar(
            select(func.count()).select_from(VoteMeetingModel).where(VoteMeetingModel.source.in_(DEMO_SOURCES), *([VoteMeetingModel.company_id.in_(held)] if held is not None else []))
        )
        demo_decision = s.scalar(
            select(func.count())
            .select_from(VoteDecisionModel)
            .join(VoteItemModel, VoteItemModel.item_id == VoteDecisionModel.item_id)
            .join(VoteMeetingModel, VoteMeetingModel.meeting_id == VoteItemModel.meeting_id)
            .where(VoteDecisionModel.source.in_(DEMO_SOURCES), *([VoteMeetingModel.company_id.in_(held)] if held is not None else []))
        )

    def name(company_id: str, fallback: str | None = None) -> str:
        return names.get(company_id) or fallback or company_id

    open_engagements = [e for e in engagements if e.status in OPEN]
    groups: dict[str, set[str]] = defaultdict(set)  # company -> theme groups of its open engagements
    step: dict[str, int] = {}
    for e in open_engagements:
        groups[e.company_id].add(theme_of(e.fir_theme))
        step[e.company_id] = max(step.get(e.company_id, 1), step_of(e.escalation_stage))
    engaged = set(step)
    tier_of = {c: r["tier"] for c, r in confirmed.items() if r["tier"] in TIERS and in_scope(c)}
    selected = set(tier_of)

    themes = []
    for theme in THEMES:
        sel = {c for c in selected if (theme in groups[c] if c in engaged else RULE_THEME.get(confirmed[c].get("rule"), "Other") == theme)}
        eng = sel & engaged
        if theme == "Other" and not sel:
            continue
        themes.append({
            "theme": theme, "selected": len(sel), "engaged": len(eng),
            "tiers": [{"tier": t, "selected": sum(tier_of[c] == t for c in sel), "engaged": sum(tier_of[c] == t for c in eng)} for t in TIERS],
        })  # fmt: skip

    engagement_meetings = sorted(
        (
            {
                "date": e.planned_meeting_date, "company_id": e.company_id, "company": name(e.company_id), "engagement_id": e.engagement_id,
                "theme": theme_of(e.fir_theme), "objective": (o.description if (o := objectives.get(e.engagement_id)) else None),
                "step": step_of(e.escalation_stage), "stage": STAGES[step_of(e.escalation_stage) - 1],
            }  # fmt: skip
            for e in open_engagements
            if e.planned_meeting_date and as_of <= e.planned_meeting_date <= end
        ),
        key=lambda r: (r["date"], r["company"], r["engagement_id"]),
    )

    by_ballot: dict[tuple[str, date], list[dict]] = {}
    latest_run: dict[tuple[str, date], str] = {}
    for r in run_items:  # newest run first: the first run seen for a company and date is the latest
        d = _iso_day(r["meeting_date"])
        if d is None or not in_scope(r["company_id"]):
            continue
        key = (r["company_id"], d)
        latest_run.setdefault(key, r["run_id"])
        if latest_run[key] == r["run_id"]:
            by_ballot.setdefault(key, []).append(r)
    shareholder = []
    for (company_id, d), rows in by_ballot.items():
        if as_of <= d <= end:
            shareholder.append({
                "date": d, "company_id": company_id, "company": name(company_id, rows[0]["company"]), "items": len(rows),
                "flagged": sum(r["policy"] in AGAINST and r["management"] == "for" for r in rows),
                "ballot_state": ballot_state_of_run([r["status"] for r in rows]), "run_id": rows[0]["run_id"],
            })  # fmt: skip
    seen = {(r["company_id"], r["date"]) for r in shareholder}
    for m in meetings:
        d = _utc_day(m.meeting_date)
        if (m.company_id, d) in seen:
            continue
        seen.add((m.company_id, d))
        items = item_counts.get(m.meeting_id, 0)
        shareholder.append({
            "date": d, "company_id": m.company_id, "company": name(m.company_id, m.issuer_name), "items": items, "flagged": None,
            "ballot_state": ballot_state_of_ledger(items, decided_counts.get(m.meeting_id, 0)), "run_id": None,
        })  # fmt: skip
    for r in shareholder:
        r["days_to_meeting"] = (r["date"] - as_of).days
        r["action_due"] = r["ballot_state"] in ("awaiting", "not_started") and r["days_to_meeting"] <= 7
    shareholder.sort(key=lambda r: (r["date"], r["company"], r["company_id"]))

    gaps = []
    for e in open_engagements:
        kinds = [k for k, missing in (("no_objective", e.engagement_id not in objectives),
                                     ("no_next_meeting", e.planned_meeting_date is None or e.planned_meeting_date < as_of)) if missing]  # fmt: skip
        if kinds:
            started = _utc_day(e.started_at)
            gaps.append({
                "company_id": e.company_id, "company": name(e.company_id), "engagement_id": e.engagement_id,
                "theme": theme_of(e.fir_theme), "open_days": (as_of - started).days if started else None, "gaps": kinds,
            })  # fmt: skip
    gaps.sort(key=lambda r: (r["open_days"] is None, -(r["open_days"] or 0), r["company"], r["engagement_id"]))

    ladder = [
        {
            "step": i + 1, "stage": stage, "label": STEP_LABELS[i],
            "companies": sorted(({"company_id": c, "company": name(c)} for c, n in step.items() if n == i + 1), key=lambda x: (x["company"], x["company_id"])),
        }  # fmt: skip
        for i, stage in enumerate(STAGES)
    ]

    voting = {"season": as_of.year, "meetings": 0, "votes": 0, "for": 0, "against": 0, "abstain": 0, "other": 0, "against_management": 0}
    topics = {t: [0, 0] for t in TOPICS}
    voted_meetings = set()

    def count(company: str | None, day: date, vote: str | None, against_management: bool, topic: str) -> None:
        voting["votes"] += 1
        voting[_vote_bucket(vote)] += 1
        voting["against_management"] += against_management
        topics[topic][0] += 1
        topics[topic][1] += against_management
        voted_meetings.add((company, day))

    for r in decisions:
        count(r.company_id or r.issuer_name, _utc_day(r.meeting_date), r.vote, bool(r.against_management), ledger_topic(r.proponent, r.categories))
    for r in run_items:
        d = _iso_day(r["meeting_date"])
        if r["status"] != "cast" or r["run_id"] in ledger_run_ids or d is None or not (d.year == as_of.year and d <= as_of) or not in_scope(r["company_id"]):
            continue
        count(r["company_id"], d, r["vote"], bool(r["against_management"]), RUN_TOPIC.get(r["type"], TOPICS[4]))
    voting["meetings"] = len(voted_meetings)
    voting["topics"] = [{"topic": t, "votes": v, "against_management": a} for t, (v, a) in topics.items()]

    demo = bool(
        any(e.source in DEMO_SOURCES for e in engagements)
        or demo_meeting
        or demo_decision
        or any(r.get("confirmed_by") == DEMO_CONFIRMER for c, r in confirmed.items() if c in tier_of)
    )
    return {
        "as_of": as_of,
        "demo": demo,
        "summary": {"selected": len(selected), "engaged_selected": len(selected & engaged), "engaged_outside_selection": len(engaged - selected)},
        "days": [
            {"date": d, "engagement_meetings": sum(r["date"] == d for r in engagement_meetings), "shareholder_meetings": sum(r["date"] == d for r in shareholder)}
            for d in window
        ],
        "tiers": [
            {"tier": t, "label": TIER_LABELS.get(t, t), "selected": sum(v == t for v in tier_of.values()), "engaged": sum(v == t for c, v in tier_of.items() if c in engaged)}
            for t in TIERS
        ],
        "themes": themes,
        "engagement_meetings": engagement_meetings,
        "shareholder_meetings": shareholder,
        "control_gaps": gaps,
        "ladder": ladder,
        "voting": voting,
        "emissions": emissions_of(*financed, engaged, selected, {c for c, n in step.items() if n >= 2}) if financed else None,
    }
