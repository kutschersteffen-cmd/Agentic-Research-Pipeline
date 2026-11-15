"""Votes from the vote ledger (vote_meetings, vote_items, vote_decisions) in the `voting_feed.items()` row shape,
so monitoring reads them like Proxy Voting votes."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from arp.db import models as m
from arp.db.companies import normalise_identifier
from arp.db.session import transaction
from arp.storage.postgres_models import VoteDecisionModel, VoteItemModel, VoteMeetingModel


def ledger_rows(dsn: str, window_days: int, house_issuers: list[dict] | None = None) -> list[dict]:
    """One row per decision on a meeting within `window_days` before the ledger's newest meeting_date.
    `house_issuers`: `house_universe()["issuers"]` when the caller already built it (building it twice is slow)."""
    M, D = VoteMeetingModel, VoteDecisionModel
    with transaction(dsn) as s:
        newest = s.scalar(select(func.max(VoteMeetingModel.meeting_date)))
        if newest is None:
            return []
        q = (
            # columns, not ORM objects: building ~60k objects per read was a third of the worklist's ledger time
            select(
                M.isin, M.company_id, M.issuer_name, M.meeting_date, VoteItemModel.item_number,
                VoteItemModel.management_recommendation, D.run_id, D.vote, D.decided_by, D.against_management,
            )  # fmt: skip
            .join(VoteItemModel, VoteItemModel.meeting_id == VoteMeetingModel.meeting_id)
            .join(VoteDecisionModel, VoteDecisionModel.item_id == VoteItemModel.item_id)
            .where(VoteMeetingModel.meeting_date >= newest - timedelta(days=window_days))
        )
        found = s.execute(q).all()
        if not found:
            return []
        from arp.stewardship.process import house_isins

        held = house_isins()  # ISIN -> house issuer holding it in the latest snapshot
        # monitoring keys on house issuer ids: the house issuer that holds the ISIN wins; else the stw_companies
        # key (set only for a known company); else the registry's universe id for the ISIN; else `isin_<ISIN>`
        by_isin = _registry_ids(s, {r.isin for r in found if r.isin and not held.get(r.isin) and r.company_id is None}, house_issuers)
        rows = []
        for r in found:
            company_id = held.get(r.isin or "") or r.company_id or by_isin.get(r.isin or "")
            if company_id is None:
                continue
            rows.append(
                {
                    "run_id": r.run_id,
                    "company_id": company_id,
                    "company": r.issuer_name,
                    "meeting_date": r.meeting_date.date().isoformat(),
                    "item": r.item_number,
                    "type": None,
                    "management": r.management_recommendation,
                    "policy": None,
                    "vote": r.vote,
                    "status": "cast",
                    "decided_by": r.decided_by or "",
                    "co_signed_by": None,
                    "note": None,
                    "overrode_policy": False,
                    "against_management": bool(r.against_management),
                }
            )
        return rows


def _registry_ids(s, isins: set[str], house_issuers: list[dict] | None) -> dict[str, str]:
    """ISIN -> the house issuer the company registry names for it (through the company's active UNIVERSE ids), else
    `isin_<ISIN>`: a company outside the house universe keeps the showcase key. One query for every ISIN."""
    if not isins:
        return {}
    isin, universe = m.CompanyIdentifier, aliased(m.CompanyIdentifier)
    keys = {normalise_identifier(m.IdScheme.ISIN, i) for i in isins}
    q = (
        select(isin.value, isin.company_id, universe.value)
        .outerjoin(universe, (universe.company_id == isin.company_id) & (universe.scheme == m.IdScheme.UNIVERSE) & universe.valid_to.is_(None))
        .where(isin.scheme == m.IdScheme.ISIN, isin.value.in_(keys), isin.valid_to.is_(None))
    )
    company: dict[str, object] = {}  # the first company an ISIN names, as a single-row lookup would take
    values: dict[str, list[str]] = {}
    for key, company_id, value in s.execute(q):
        if company.setdefault(key, company_id) == company_id and value:
            values.setdefault(key, []).append(value)
    house: dict[str, str] = {}
    if values:  # the registry upper-cases UNIVERSE values; issuer ids keep their case
        from arp.stewardship.process import house_universe

        issuers = house_universe()["issuers"] if house_issuers is None else house_issuers
        house = {i["issuer_id"].upper(): i["issuer_id"] for i in issuers}
    out = {}
    for i in isins:
        found = values.get(normalise_identifier(m.IdScheme.ISIN, i), ())
        out[i] = next((house[v.upper()] for v in found if v.upper() in house), f"isin_{i}")
    return out
