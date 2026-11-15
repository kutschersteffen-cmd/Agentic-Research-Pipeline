"""`arp stewardship seed-cockpit-demo` (spec `stewardship-cockpit`, "Demo data"): on top of the foundation's demo
data, planned meeting dates, some escalations, confirmed tiers and 14 upcoming shareholder meetings, so every
cockpit section has something to show. Everything derives from sha256 of fixed strings and `as_of`: a re-run with
the same `as_of` writes nothing. Only rows with source `mock_voice_seed` or `cockpit_demo` are changed."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import select

from arp.config import Settings
from arp.db.session import transaction
from arp.schemas.common import new_id, now_iso
from arp.schemas.engagement import ESCALATION_ORDER, OLD_STAGES
from arp.storage.postgres_engagement_store import _ts
from arp.storage.postgres_models import (
    StwCompanyModel,
    StwEngagementModel,
    StwTransitionModel,
    VoteItemModel,
    VoteMeetingModel,
)

SOURCE = "cockpit_demo"
SEED_SOURCE = "mock_voice_seed"
DECIDED_BY = "showcase demo"
OFFSETS = [1, 2, 4, 6, 9, 11, 13, 15, 18, 20, 22, 24, 27, 29]
_ESCALATE = {0: 2, 1: 2, 2: 3, 3: 4, 4: 5}  # h("esc:" + id) mod 100 -> ladder step
# (categories, description) of the issuer items, N-PX style; item i takes entry i mod len
_ITEMS = [
    (["DIRECTOR ELECTIONS"], "Elect director"),
    (["SECTION 14A SAY-ON-PAY VOTES"], "Advisory vote to approve executive compensation"),
    (["AUDIT-RELATED"], "Ratify the appointment of the independent auditor"),
    (["CAPITAL STRUCTURE"], "Authorise the board to repurchase shares"),
    (["DIRECTOR ELECTIONS"], "Re-elect director"),
    (["COMPENSATION"], "Approve the long-term incentive plan"),
]
_SHAREHOLDER = (["OTHER SOCIAL MATTERS"], "Shareholder proposal: report on climate lobbying")


def h(x: str) -> int:
    return int(hashlib.sha256(x.encode("utf-8")).hexdigest(), 16)


def planned_date(engagement_id: str, as_of: date) -> date | None:
    v = h(engagement_id)
    b, k = v % 20, v // 20
    if b <= 5:
        return as_of + timedelta(days=k % 30)
    if b <= 16:
        return as_of + timedelta(days=30 + k % 90)
    return None


def _open_seed(s) -> list[StwEngagementModel]:
    q = select(StwEngagementModel).where(StwEngagementModel.source == SEED_SOURCE, StwEngagementModel.status.in_(["open", "stalled"]))
    return list(s.scalars(q.order_by(StwEngagementModel.engagement_id)))


def step_planned(dsn: str, as_of: date) -> str:
    with transaction(dsn) as s:
        rows = _open_seed(s)
        for e in rows:
            target = planned_date(e.engagement_id, as_of)
            if e.planned_meeting_date != target:
                e.planned_meeting_date = target
    return f"{len(rows)} engagements"


def step_escalation(dsn: str) -> str:
    moved = 0
    with transaction(dsn) as s:
        for e in _open_seed(s):
            if e.escalation_stage != ESCALATION_ORDER[0].value:
                continue
            step = _ESCALATE.get(h("esc:" + e.engagement_id) % 100)
            if step is None:
                continue
            stage = ESCALATION_ORDER[step - 1].value
            e.escalation_stage = stage
            s.add(StwTransitionModel(
                transition_id=new_id("trn"), source=SOURCE, external_id=f"{SOURCE}:escalation:{e.engagement_id}",
                engagement_id=e.engagement_id, kind="escalation", stage=stage, changed_at=_ts(now_iso()),
                decided_by=DECIDED_BY, reason="Showcase demo escalation",
            ))  # fmt: skip
            moved += 1
    return f"{moved} engagements"


def ledger_history(dsn: str) -> list[SimpleNamespace]:
    """Each company's engagements as `tier_contexts` reads records (status, escalation stage), straight from the
    ledger like the cockpit, so a ledger row the record model would reject (no theme) cannot stop the step."""
    issues: dict[str, list[SimpleNamespace]] = defaultdict(list)
    with transaction(dsn) as s:
        for r in s.execute(select(StwEngagementModel.company_id, StwEngagementModel.status, StwEngagementModel.escalation_stage)):
            stage = OLD_STAGES.get(r.escalation_stage, r.escalation_stage) or ESCALATION_ORDER[0].value
            issues[r.company_id].append(SimpleNamespace(status=r.status, escalation_stage=stage))
    return [SimpleNamespace(company_id=c, issues=i) for c, i in issues.items()]


def step_tiers(settings: Settings, dsn: str) -> str:
    from arp.stewardship.process import load_sample, tier_proposals
    from arp.stewardship.tiers import TierStore

    root = settings.stewardship_streams_dir
    store = TierStore(root)
    latest = store.latest()
    proposals = tier_proposals(root, load_sample(), ledger_history(dsn))
    fresh = [p for p in proposals if p["issuer_id"] not in latest]
    for p in fresh:
        store.confirm(p, DECIDED_BY)
    return f"{len(fresh)} confirmed"


def step_meetings(settings: Settings, dsn: str, as_of: date) -> str:
    from arp.storage.portfolio_store import portfolio_directories
    from arp.storage.portfolio_store_factory import build_portfolio_store

    store = build_portfolio_store(settings)
    securities, _ = portfolio_directories(store)
    held = {sec.company_id for hld in store.load_holdings_as_of(as_of.isoformat(), None) if (sec := securities.get(hld.security_id)) and sec.company_id}
    with transaction(dsn) as s:
        names = {c: n for c, n in s.execute(select(StwCompanyModel.company_id, StwCompanyModel.name)) if c in held}
        if len(names) < len(OFFSETS):
            raise ValueError(f"{len(names)} held companies have a stewardship row; {len(OFFSETS)} needed")
        companies = sorted(names, key=lambda c: (h(c), c))[: len(OFFSETS)]
        stored = {m.external_id: m for m in s.scalars(select(VoteMeetingModel).where(VoteMeetingModel.source == SOURCE))}
        items = {i.external_id: i for i in s.scalars(select(VoteItemModel).where(VoteItemModel.source == SOURCE))}
        for k, (company, offset) in enumerate(zip(companies, OFFSETS, strict=True)):
            ext = f"{SOURCE}:meeting:{k}"
            values = {
                "company_id": company, "issuer_name": names[company] or company,
                "isin": company[5:] if company.startswith("isin_") else None,
                "meeting_date": datetime.combine(as_of + timedelta(days=offset), datetime.min.time(), tzinfo=UTC).replace(hour=9),
                "meeting_type": "annual",
            }  # fmt: skip
            meeting = stored.get(ext)
            if meeting is None:
                meeting = VoteMeetingModel(meeting_id=new_id("mtg"), source=SOURCE, external_id=ext, **values)
                s.add(meeting)
                s.flush()
            else:
                for key, v in values.items():
                    if getattr(meeting, key) != v:
                        setattr(meeting, key, v)
            n = 10 + h("items:" + str(k)) % 13
            for i in range(1, n + 1):
                shareholder = k % 2 == 1 and i == n
                cats, text = _SHAREHOLDER if shareholder else _ITEMS[(i - 1) % len(_ITEMS)]
                item_ext = f"{ext}:item:{i}"
                if item_ext not in items:
                    s.add(VoteItemModel(
                        item_id=new_id("vitem"), source=SOURCE, external_id=item_ext, meeting_id=meeting.meeting_id, item_number=str(i),
                        description=text, categories=cats, proponent="shareholder" if shareholder else "issuer",
                        management_recommendation="for",
                    ))  # fmt: skip
    return f"{len(OFFSETS)} upcoming"


def seed_cockpit_demo(settings: Settings, dsn: str, as_of: date, echo: Callable[[str], None]) -> bool:
    """Prints `ok|FAIL <step>: <detail>` per step; stops at the first FAIL and returns False."""
    steps = [
        ("planned", lambda: step_planned(dsn, as_of)),
        ("escalation", lambda: step_escalation(dsn)),
        ("tiers", lambda: step_tiers(settings, dsn)),
        ("meetings", lambda: step_meetings(settings, dsn, as_of)),
    ]
    for name, run in steps:
        try:
            detail = run()
        except Exception as exc:  # one line per step, whatever went wrong
            echo(f"FAIL {name}: {exc}")
            return False
        echo(f"ok {name}: {detail}")
    return True
