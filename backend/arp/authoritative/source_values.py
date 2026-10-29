"""The "All source values" dataset: one row per company, each picked field's latest current fact as of a date,
with its status, source, period and observation alongside, so a rule graph can pick and combine them."""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, time
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session

from arp.db import models as m
from arp.decision.dataset import Dataset

_ALIAS = re.compile(r"[a-z][a-z0-9_]*")
COMPANION = ("unit", "period_end", "status", "source", "provider", "method", "confidence", "observed_at", "observation_id")
PORTFOLIO_COMPANION = ("unit", "period", "source", "observed_at")


class SourcePick(BaseModel):
    field_id: str
    alias: str | None = None
    portfolio_source: str | None = None  # set: field_id is a portfolio-store field, read from this source only


def default_alias(field_id: str, portfolio_source: str | None = None) -> str:
    alias = re.sub(r"[^a-z0-9_]", "_", field_id.lower())
    return f"portfolio_{portfolio_source}_{alias}" if portfolio_source else alias


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal | int | float):
        return format(Decimal(str(value)).normalize(), "f")
    if isinstance(value, dict | list):
        return json.dumps(value)
    return str(value)


def _as_of_end(as_of: str) -> datetime:
    """A date means the end of that day (UTC), as publish reads do; a datetime is taken as given."""
    if len(as_of) == 10:
        return datetime.combine(date.fromisoformat(as_of), time.max, tzinfo=UTC)
    at = datetime.fromisoformat(as_of)
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def _latest_facts(session: Session, field_id: str, company_ids: list[UUID], at: datetime) -> dict[UUID, dict[str, str]]:
    rows = session.execute(
        select(m.CompanyFact, m.FieldObservation, m.DataSource.slug)
        .join(m.FieldObservation, m.FieldObservation.id == m.CompanyFact.observation_id)
        .outerjoin(m.DataSource, m.DataSource.source_id == m.FieldObservation.source_id)
        .where(
            m.CompanyFact.field_id == field_id,
            m.CompanyFact.company_id.in_(company_ids),
            m.CompanyFact.valid_from <= at,
            or_(m.CompanyFact.valid_to.is_(None), m.CompanyFact.valid_to > at),
        )
        .order_by(m.CompanyFact.period_end.desc().nulls_last(), case((m.CompanyFact.basis == "", 0), else_=1))
    ).all()
    out: dict[UUID, dict[str, str]] = {}
    for fact, obs, slug in rows:
        if fact.company_id in out:
            continue
        out[fact.company_id] = {
            "": _cell(fact.canonical_value if fact.canonical_value is not None else fact.value),
            "unit": _cell(fact.canonical_unit or obs.unit),
            "period_end": _cell(fact.period_end),
            "status": str(fact.status),
            "source": str(obs.source_kind),
            "provider": _cell(slug),
            "method": _cell(obs.method),
            "confidence": _cell(obs.confidence),
            "observed_at": obs.created_at.isoformat(),
            "observation_id": str(obs.id),
        }
    return out


def _universe_ids(session: Session, company_ids: list[UUID]) -> dict[UUID, list[str]]:
    out: dict[UUID, list[str]] = {}
    for cid, value in session.execute(
        select(m.CompanyIdentifier.company_id, m.CompanyIdentifier.value).where(
            m.CompanyIdentifier.company_id.in_(company_ids), m.CompanyIdentifier.scheme == m.IdScheme.UNIVERSE
        )
    ):
        out.setdefault(cid, []).append(value)
    return out


def _portfolio_values(store, pick: SourcePick, universe_ids: dict[UUID, list[str]], as_of: str) -> dict[UUID, dict[str, str]]:
    out: dict[UUID, dict[str, str]] = {}
    for cid, ids in universe_ids.items():
        obs = [
            o for uid in ids for o in store.load_observations(uid, pick.field_id)
            if o.source == pick.portfolio_source and o.observed_at[:10] <= as_of[:10]
        ]
        if obs:
            o = max(obs, key=lambda o: o.observed_at)
            out[cid] = {"": _cell(o.value), "unit": _cell(o.unit), "period": o.period, "source": o.source,
                        "observed_at": o.observed_at}
    return out


def from_source_values(
    session: Session, *, company_ids: list[str], picks: list[SourcePick], as_of: str, portfolio_store=None
) -> Dataset:
    """Raises ValueError for an unknown field, a portfolio pick without a store, or two picks sharing an alias.
    Company ids the registry does not know are skipped and counted in `source_ref`."""
    if not picks:
        raise ValueError("Pick at least one field.")
    aliases: dict[str, str] = {}
    for p in picks:
        alias = p.alias or default_alias(p.field_id, p.portfolio_source)
        if not _ALIAS.fullmatch(alias) or "__" in alias or alias in ("company_id", "Company"):
            raise ValueError(f"{alias!r} is not a usable column name for {p.field_id!r}: use lower-case letters, digits "
                             "and single underscores, starting with a letter.")
        if alias in aliases:
            raise ValueError(f"Fields {aliases[alias]!r} and {p.field_id!r} share the column name {alias!r}; rename one.")
        aliases[alias] = p.field_id
        if p.portfolio_source is None and session.get(m.Field, p.field_id) is None:
            raise ValueError(f"Unknown field {p.field_id!r}.")
        if p.portfolio_source is not None and portfolio_store is None:
            raise ValueError("Portfolio-store inputs need a portfolio store.")

    wanted: list[UUID] = []
    for raw in dict.fromkeys(company_ids):  # once each, in the order given
        try:
            wanted.append(UUID(raw))
        except ValueError:
            continue
    names = dict(session.execute(select(m.Company.id, m.Company.name).where(m.Company.id.in_(wanted))).all())
    known = list(dict.fromkeys(c for c in wanted if c in names))
    unknown = len(dict.fromkeys(company_ids)) - len(known)

    at = _as_of_end(as_of)
    universe = _universe_ids(session, known) if any(p.portfolio_source for p in picks) else {}
    columns = ["company_id", "Company"]
    values: list[tuple[str, tuple[str, ...], dict[UUID, dict[str, str]]]] = []
    for p in picks:
        alias = p.alias or default_alias(p.field_id, p.portfolio_source)
        if p.portfolio_source:
            values.append((alias, PORTFOLIO_COMPANION, _portfolio_values(portfolio_store, p, universe, as_of)))
        else:
            values.append((alias, COMPANION, _latest_facts(session, p.field_id, known, at)))
    for alias, companion, _ in values:
        columns += [alias, *(f"{alias}__{c}" for c in companion)]

    rows = []
    for cid in known:
        row = {"company_id": str(cid), "Company": names[cid]}
        for alias, companion, by_company in values:
            cells = by_company.get(cid, {})
            row[alias] = cells.get("", "")
            row.update({f"{alias}__{c}": cells.get(c, "") for c in companion})
        rows.append(row)
    return Dataset(
        name=f"All source values as of {as_of}", columns=columns, rows=rows, source="source_values",
        source_ref=f"{len(known)} companies, {unknown} unknown", as_of=as_of,
    )
