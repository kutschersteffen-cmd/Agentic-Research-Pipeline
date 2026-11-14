"""Votes from the vote ledger (vote_meetings, vote_items, vote_decisions) in the `voting_feed.items()` row shape,
so monitoring reads them like Proxy Voting votes."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select

from arp.db import models as m
from arp.db.company_view import resolve_ref
from arp.db.session import transaction
from arp.storage.postgres_models import VoteDecisionModel, VoteItemModel, VoteMeetingModel


def ledger_rows(dsn: str, window_days: int) -> list[dict]:
    """One row per decision on a meeting within `window_days` before the ledger's newest meeting_date."""
    with transaction(dsn) as s:
        newest = s.scalar(select(func.max(VoteMeetingModel.meeting_date)))
        if newest is None:
            return []
        q = (
            select(VoteMeetingModel, VoteItemModel, VoteDecisionModel)
            .join(VoteItemModel, VoteItemModel.meeting_id == VoteMeetingModel.meeting_id)
            .join(VoteDecisionModel, VoteDecisionModel.item_id == VoteItemModel.item_id)
            .where(VoteMeetingModel.meeting_date >= newest - timedelta(days=window_days))
        )
        rows = []
        by_isin: dict[str, str] = {}  # one registry lookup per distinct ISIN
        house: dict[str, str] | None = None
        held: dict[str, str] | None = None  # ISIN -> issuer id of a security the house portfolios hold
        for meeting, item, d in s.execute(q):
            # monitoring keys on house issuer ids: the house issuer holding the ISIN first; else the stw_companies
            # key (set only for a known company); else the registry's universe id for the ISIN; else `isin_<ISIN>`
            if held is None:
                from arp.stewardship.process import house_isins

                held = house_isins()
            company_id = held.get(meeting.isin or "") or meeting.company_id
            if company_id is None and meeting.isin:
                if meeting.isin not in by_isin:
                    uid = resolve_ref(s, f"ISIN:{meeting.isin}")
                    values = uid and s.scalars(
                        select(m.CompanyIdentifier.value).where(
                            m.CompanyIdentifier.company_id == uid,
                            m.CompanyIdentifier.scheme == m.IdScheme.UNIVERSE,
                            m.CompanyIdentifier.valid_to.is_(None),
                        )
                    ).all()
                    if values and house is None:  # the registry upper-cases UNIVERSE values; issuer ids keep their case
                        from arp.stewardship.process import house_universe

                        house = {i["issuer_id"].upper(): i["issuer_id"] for i in house_universe()["issuers"]}
                    # a company outside the house universe keeps the showcase key
                    by_isin[meeting.isin] = next((house[v.upper()] for v in values or () if v.upper() in house), f"isin_{meeting.isin}")
                company_id = by_isin[meeting.isin]
            if company_id is None:
                continue
            rows.append(
                {
                    "run_id": d.run_id,
                    "company_id": company_id,
                    "company": meeting.issuer_name,
                    "meeting_date": meeting.meeting_date.date().isoformat(),
                    "item": item.item_number,
                    "type": None,
                    "management": item.management_recommendation,
                    "policy": None,
                    "vote": d.vote,
                    "status": "cast",
                    "decided_by": d.decided_by or "",
                    "co_signed_by": None,
                    "note": None,
                    "overrode_policy": False,
                    "against_management": bool(d.against_management),
                }
            )
        return rows
