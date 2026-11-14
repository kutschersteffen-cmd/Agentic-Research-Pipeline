"""Votes from the vote ledger (vote_meetings, vote_items, vote_decisions) in the `voting_feed.items()` row shape,
so monitoring reads them like Proxy Voting votes."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select

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
        for meeting, item, d in s.execute(q):
            # the FK to stw_companies is set only for a known company; a meeting with an ISIN is the showcase issuer
            company_id = meeting.company_id or (f"isin_{meeting.isin}" if meeting.isin else None)
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
