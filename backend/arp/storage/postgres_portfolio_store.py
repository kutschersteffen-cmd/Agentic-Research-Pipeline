"""The portfolio store (arp/storage/portfolio_store_factory.py builds it): portfolios, securities,
companies (`legacy_companies`), holdings snapshots and security resolutions in Postgres; observations,
news, flags, analytics and monitoring rules/alerts delegate to the wrapped file-based PortfolioStore
(see postgres_models.py).
"""

from __future__ import annotations

from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import (
    DataPointObservation,
    HolderConfig,
    Holding,
    HoldingKind,
    NewsItem,
    NewsRiskFlag,
    Portfolio,
    PortfolioGroup,
    SecurityRef,
    SecurityResolution,
)
from arp.schemas.portfolio_monitoring import AlertRule
from arp.storage.portfolio_store import PortfolioStore
from arp.storage.postgres import get_engine


class PostgresPortfolioStore:
    """A genuine drop-in for PortfolioStore: portfolios/securities/
    companies/holdings-snapshots/resolutions are relational (Postgres),
    everything else (observations, news, flags, analytics,
    monitoring rules/alerts -- none of which have the multi-way join
    access pattern that justifies a relational engine) delegates to a wrapped file-based PortfolioStore,
    so every caller of get_portfolio_store() keeps working unmodified
    regardless of which backend is configured.

    "Drop-in" is enforced by tests/test_portfolio_store_parity.py, which
    runs one set of assertions against both stores and compares their
    public surfaces. The one deliberate difference it encodes: the
    `*_path()` accessors are absent here. For data this backend
    relationalizes (`registry_path`, `securities_path`, `companies_path`,
    `resolutions_path`, `snapshot_path`) there is no file behind them --
    returning the wrapped file store's path would hand a caller an empty or
    nonexistent file and call it the data. For concerns that stay
    file-backed, only the file store itself reads its paths.
    """

    def __init__(self, dsn: str, file_store: PortfolioStore) -> None:
        from sqlalchemy.orm import Session

        self._dsn = dsn
        self._engine = get_engine(dsn)
        self._Session = Session
        self._files = file_store

    def _session(self):
        return self._Session(self._engine)

    # --- delegated to the file store: no relational join access pattern ---

    def append_observation(self, obs: DataPointObservation) -> None:
        self._files.append_observation(obs)

    def load_observations(self, company_id: str, field_id: str) -> list[DataPointObservation]:
        return self._files.load_observations(company_id, field_id)

    def latest_observation(self, company_id: str, field_id: str, as_of: str | None = None) -> DataPointObservation | None:
        return self._files.latest_observation(company_id, field_id, as_of)

    def list_observation_keys(self) -> list[tuple[str, str]]:
        """Every (company_id, field_id) with a recorded observation."""
        return self._files.list_observation_keys()

    def append_news(self, item: NewsItem) -> None:
        self._files.append_news(item)

    def list_news(self, company_id: str | None = None) -> list[NewsItem]:
        return self._files.list_news(company_id)

    def append_flag(self, flag: NewsRiskFlag) -> None:
        self._files.append_flag(flag)

    def list_flags(self, company_id: str | None = None) -> list[NewsRiskFlag]:
        return self._files.list_flags(company_id)

    def save_analytic(self, spec_json: dict) -> None:
        self._files.save_analytic(spec_json)

    def list_analytics(self) -> list[dict]:
        return self._files.list_analytics()

    def get_analytic(self, analytic_id: str) -> dict | None:
        return self._files.get_analytic(analytic_id)

    def save_group(self, group: PortfolioGroup) -> None:
        self._files.save_group(group)

    def list_groups(self) -> list[PortfolioGroup]:
        return self._files.list_groups()

    def get_group(self, group_id: str) -> PortfolioGroup | None:
        return self._files.get_group(group_id)

    def save_rule(self, rule: AlertRule) -> None:
        self._files.save_rule(rule)

    def get_rule(self, rule_id: str) -> AlertRule | None:
        return self._files.get_rule(rule_id)

    def list_rules(self, enabled_only: bool = False) -> list[AlertRule]:
        return self._files.list_rules(enabled_only)

    def append_alert_event(self, scope_id: str, event_type: str, payload: dict) -> None:
        self._files.append_alert_event(scope_id, event_type, payload)

    def list_alert_events(self, scope_id: str) -> list[dict]:
        return self._files.list_alert_events(scope_id)

    def list_all_alert_scope_ids(self) -> list[str]:
        return self._files.list_all_alert_scope_ids()

    def append_governance_event(self, event_type: str, payload: dict) -> None:
        self._files.append_governance_event(event_type, payload)

    def list_governance_events(self) -> list[dict]:
        return self._files.list_governance_events()

    def save_revision(self, kind: HoldingKind, holder_id: str, as_of_date: str, revision: int, holdings: list[Holding]) -> None:
        self._files.save_revision(kind, holder_id, as_of_date, revision, holdings)

    def load_revision(self, kind: HoldingKind, holder_id: str, as_of_date: str, revision: int) -> list[Holding]:
        return self._files.load_revision(kind, holder_id, as_of_date, revision)

    def list_revisions(self, kind: HoldingKind, holder_id: str, as_of_date: str) -> list[int]:
        return self._files.list_revisions(kind, holder_id, as_of_date)

    def save_holder(self, cfg: HolderConfig) -> None:
        self._files.save_holder(cfg)

    def get_holder(self, kind: HoldingKind, holder_id: str) -> HolderConfig | None:
        return self._files.get_holder(kind, holder_id)

    def list_holders(self) -> list[HolderConfig]:
        return self._files.list_holders()

    def append_holdings_audit(self, row: dict) -> None:
        self._files.append_holdings_audit(row)

    # --- Superset datasets (arp/bi/published.py) ---

    def publish_rows(self, dataset: str, month: str, rows: list[dict]) -> None:
        """Replaces what was published for this (dataset, month); other months and datasets stay."""
        from sqlalchemy import delete

        from arp.storage.postgres_models import BiPublishedModel

        with self._session() as session:
            session.execute(delete(BiPublishedModel).where(BiPublishedModel.dataset == dataset, BiPublishedModel.month == month))
            session.add_all([BiPublishedModel(dataset=dataset, month=month, row=r) for r in rows])
            session.commit()

    # --- portfolios -----------------------------------------------------

    def save_portfolio(self, portfolio: Portfolio) -> None:
        from arp.storage.postgres_models import PortfolioModel

        with self._session() as session:
            session.merge(
                PortfolioModel(portfolio_id=portfolio.portfolio_id, name=portfolio.name, tags=list(portfolio.tags))
            )
            session.commit()

    def get_portfolio(self, portfolio_id: str) -> Portfolio | None:
        from arp.storage.postgres_models import PortfolioModel

        with self._session() as session:
            row = session.get(PortfolioModel, portfolio_id)
            return None if row is None else Portfolio(portfolio_id=row.portfolio_id, name=row.name, tags=list(row.tags))

    def list_portfolios(self) -> list[Portfolio]:
        from sqlalchemy import select

        from arp.storage.postgres_models import PortfolioModel

        with self._session() as session:
            rows = session.scalars(select(PortfolioModel).order_by(PortfolioModel.portfolio_id)).all()
            return [Portfolio(portfolio_id=r.portfolio_id, name=r.name, tags=list(r.tags)) for r in rows]

    # --- securities -------------------------------------------------------

    def save_security(self, security: SecurityRef) -> None:
        from arp.db.companies import company_for
        from arp.storage.postgres_models import SecurityModel

        with self._session() as session:
            session.merge(
                SecurityModel(
                    security_id=security.security_id, isin=security.isin, name=security.name,
                    asset_class=security.asset_class, currency=security.currency, company_id=security.company_id,
                    company_uuid=company_for(session, isin=security.isin, universe_id=security.company_id),
                )
            )
            session.commit()

    def get_security(self, security_id: str) -> SecurityRef | None:
        from arp.storage.postgres_models import SecurityModel

        with self._session() as session:
            row = session.get(SecurityModel, security_id)
            return None if row is None else _security_from_row(row)

    def list_securities(self) -> list[SecurityRef]:
        from sqlalchemy import select

        from arp.storage.postgres_models import SecurityModel

        with self._session() as session:
            rows = session.scalars(select(SecurityModel).order_by(SecurityModel.security_id)).all()
            return [_security_from_row(r) for r in rows]

    # --- companies --------------------------------------------------------

    def save_company(self, company: CompanyRef) -> None:
        from arp.storage.postgres_models import CompanyModel

        with self._session() as session:
            session.merge(
                CompanyModel(
                    company_id=company.company_id, name=company.name, ticker=company.ticker, website=company.website,
                    cik=company.cik, country=company.country, sector=company.sector, isic_code=company.isic_code,
                )
            )
            session.commit()

    def get_company(self, company_id: str) -> CompanyRef | None:
        from arp.storage.postgres_models import CompanyModel

        with self._session() as session:
            row = session.get(CompanyModel, company_id)
            return None if row is None else _company_from_row(row)

    def list_companies(self) -> list[CompanyRef]:
        from sqlalchemy import select

        from arp.storage.postgres_models import CompanyModel

        with self._session() as session:
            rows = session.scalars(select(CompanyModel).order_by(CompanyModel.company_id)).all()
            return [_company_from_row(r) for r in rows]

    # --- security resolutions ----------------------------------------------

    def save_resolution(self, resolution: SecurityResolution) -> None:
        from arp.db.companies import company_for
        from arp.storage.postgres_models import SecurityResolutionModel

        with self._session() as session:
            session.merge(
                SecurityResolutionModel(
                    security_id=resolution.security_id, company_id=resolution.company_id,
                    company_uuid=company_for(session, universe_id=resolution.company_id),
                    confidence=resolution.confidence, method=resolution.method,
                    needs_review=resolution.needs_review, resolved_at=resolution.resolved_at,
                )
            )
            session.commit()

    def get_resolution(self, security_id: str) -> SecurityResolution | None:
        from arp.storage.postgres_models import SecurityResolutionModel

        with self._session() as session:
            row = session.get(SecurityResolutionModel, security_id)
            return None if row is None else _resolution_from_row(row)

    def list_resolutions_needing_review(self) -> list[SecurityResolution]:
        from sqlalchemy import select

        from arp.storage.postgres_models import SecurityResolutionModel

        with self._session() as session:
            rows = session.scalars(
                select(SecurityResolutionModel).where(SecurityResolutionModel.needs_review.is_(True))
            ).all()
            return [_resolution_from_row(r) for r in rows]

    # --- holdings snapshots -------------------------------------------------

    def save_snapshot(self, holder_id: str, as_of_date: str, holdings: list[Holding], *, kind: HoldingKind = "portfolio") -> None:
        """Replaces any existing rows for this exact (kind, holder_id,
        as_of_date) before inserting -- makes re-running an ingestion for
        the same date idempotent (matches PortfolioStore.save_snapshot's
        file-overwrite semantics) rather than accumulating duplicate rows.
        """
        from functools import cache

        from sqlalchemy import delete

        from arp.db.companies import company_for
        from arp.storage.postgres_models import HoldingModel

        with self._session() as session:
            company = cache(lambda key, scheme, isin: company_for(session, issuer_key=key, issuer_scheme=scheme, isin=isin))
            session.execute(
                delete(HoldingModel).where(
                    HoldingModel.kind == kind, HoldingModel.portfolio_id == holder_id, HoldingModel.as_of_date == as_of_date
                )
            )
            session.add_all(
                [
                    HoldingModel(
                        kind=h.kind, portfolio_id=h.holder_id, security_id=h.security_id, as_of_date=h.as_of_date,
                        isin=h.isin, issuer_key=h.issuer_key, issuer_scheme=h.issuer_scheme, source=h.source,
                        source_ref=h.source_ref, currency=h.currency, quantity=h.quantity, price=h.price,
                        market_value=h.market_value, fx_rate_to_eur=h.fx_rate_to_eur,
                        market_value_eur=h.market_value_eur, shares=h.shares, free_float=h.free_float,
                        weight_pct=h.weight_pct, company_id=company(h.issuer_key, h.issuer_scheme, h.isin),
                    )
                    for h in holdings
                ]
            )
            session.commit()

    def load_snapshot(self, holder_id: str, as_of_date: str, *, kind: HoldingKind = "portfolio") -> list[Holding]:
        """One holder's holdings for *exactly* this date -- the
        relational equivalent of reading that one snapshot file, so it
        returns nothing for a date never pulled. Deliberately not routed
        through load_holdings_as_of, whose contract is the different
        "latest on or before" question."""
        from sqlalchemy import select

        from arp.storage.postgres_models import HoldingModel

        with self._session() as session:
            rows = session.scalars(
                select(HoldingModel).where(
                    HoldingModel.kind == kind, HoldingModel.portfolio_id == holder_id, HoldingModel.as_of_date == as_of_date
                )
            ).all()
            return [_holding_from_row(r) for r in rows]

    def list_snapshot_dates(self, holder_id: str, *, kind: HoldingKind = "portfolio") -> list[str]:
        from sqlalchemy import select

        from arp.storage.postgres_models import HoldingModel

        with self._session() as session:
            rows = session.scalars(
                select(HoldingModel.as_of_date)
                .where(HoldingModel.kind == kind, HoldingModel.portfolio_id == holder_id)
                .distinct()
                .order_by(HoldingModel.as_of_date)
            ).all()
            return list(rows)

    def latest_snapshot_date(self, holder_id: str, *, kind: HoldingKind = "portfolio") -> str | None:
        dates = self.list_snapshot_dates(holder_id, kind=kind)
        return dates[-1] if dates else None

    def all_snapshot_dates(self) -> list[str]:
        from sqlalchemy import select

        from arp.storage.postgres_models import HoldingModel

        with self._session() as session:
            rows = session.scalars(
                select(HoldingModel.as_of_date)
                .where(HoldingModel.kind == "portfolio")
                .distinct()
                .order_by(HoldingModel.as_of_date)
            ).all()
            return list(rows)

    def _latest_snapshot_per_portfolio(self, as_of_date: str, portfolio_ids: list[str] | None):
        """Subquery of (portfolio_id, as_of_date) giving each portfolio's
        most recent snapshot date on or before `as_of_date` -- the SQL
        form of PortfolioStore.load_holdings_as_of's per-portfolio
        `max(d for d in dates if d <= as_of)`.

        This exists because portfolios are pulled on independent
        schedules, so the requested date is usually *not* a date every
        portfolio has. Matching `as_of_date` exactly (what this store did
        before) silently dropped every portfolio not pulled on that exact
        day and returned nothing at all for a date between snapshots --
        producing a smaller number, not an error, for the same holdings
        the file store totals correctly.

        `as_of_date` is an ISO-8601 string column, so `<=` compares
        lexicographically, which for that format is chronological order --
        the same comparison the file store does on filenames.
        """
        from sqlalchemy import func, select

        from arp.storage.postgres_models import HoldingModel

        stmt = (
            select(
                HoldingModel.portfolio_id.label("portfolio_id"),
                func.max(HoldingModel.as_of_date).label("as_of_date"),
            )
            .where(HoldingModel.kind == "portfolio", HoldingModel.as_of_date <= as_of_date)
            .group_by(HoldingModel.portfolio_id)
        )
        if portfolio_ids:
            stmt = stmt.where(HoldingModel.portfolio_id.in_(portfolio_ids))
        return stmt.subquery()

    def _holdings_as_of_join(self, as_of_date: str, portfolio_ids: list[str] | None):
        """The join condition every as-of query shares: a holding row is
        in scope when its (portfolio_id, as_of_date) is that portfolio's
        latest snapshot on or before the requested date."""
        from arp.storage.postgres_models import HoldingModel

        latest = self._latest_snapshot_per_portfolio(as_of_date, portfolio_ids)
        return latest, (HoldingModel.kind == "portfolio") & (HoldingModel.portfolio_id == latest.c.portfolio_id) & (
            HoldingModel.as_of_date == latest.c.as_of_date
        )

    def load_holdings_as_of(self, as_of_date: str, portfolio_ids: list[str] | None = None) -> list[Holding]:
        """Holdings across (optionally filtered) portfolios, using each
        portfolio's most recent snapshot on or before `as_of_date` --
        identical semantics to PortfolioStore.load_holdings_as_of, which
        tests/test_portfolio_store_parity.py holds both stores to."""
        from sqlalchemy import select

        from arp.storage.postgres_models import HoldingModel

        latest, on_clause = self._holdings_as_of_join(as_of_date, portfolio_ids)
        with self._session() as session:
            rows = session.scalars(select(HoldingModel).join(latest, on_clause)).all()
            return [_holding_from_row(r) for r in rows]

    # --- the payoff: a real relational join, not available cheaply over the file store ---

    def _dimension_column(self, dimension: str):
        """SQL expression for one of aggregation.DIMENSIONS, matching
        aggregation._dimension_value exactly -- including `company_name`'s
        fall back to the security's own name when the issuer hasn't been
        resolved yet, which is what keeps an unresolved security visible in
        a result instead of silently dropping out of it.
        """
        from sqlalchemy import func

        from arp.storage.postgres_models import CompanyModel, HoldingModel, SecurityModel

        columns = {
            "portfolio_id": HoldingModel.portfolio_id,
            "asset_class": SecurityModel.asset_class,
            "currency": SecurityModel.currency,
            "company_id": SecurityModel.company_id,
            "company_name": func.coalesce(CompanyModel.name, SecurityModel.name),
            "sector": CompanyModel.sector,
            "country": CompanyModel.country,
        }
        if dimension not in columns:
            raise ValueError(f"Unknown aggregation dimension: {dimension!r}. Valid: {tuple(columns)}")
        return columns[dimension]

    def aggregate_holdings_by(
        self,
        as_of_date: str,
        group_by: str,
        *,
        portfolio_ids: list[str] | None = None,
        security_filter: dict[str, str] | None = None,
    ) -> tuple[list[tuple[str | None, float, int]], float]:
        """Grouped market-value sums plus holding counts, and the grand
        total -- everything `aggregation.aggregate` needs for the
        `market_value_sum` metric, computed in one SQL statement over the
        holdings x securities x companies join instead of loading every
        JSONL snapshot into Python.

        This is what makes the relational backend worth configuring:
        `arp/portfolio/analytics.py::execute` routes through here when the
        configured store offers it.

        Returns rows ordered by group value, with NULL group values left as
        None for the caller to label -- `aggregation.aggregate` renders
        those as "(unresolved)" and this store does not duplicate that
        decision. The date is resolved per portfolio exactly as
        load_holdings_as_of resolves it.
        """
        from sqlalchemy import func, select

        from arp.storage.postgres_models import CompanyModel, HoldingModel, SecurityModel

        group_col = self._dimension_column(group_by)
        latest, on_clause = self._holdings_as_of_join(as_of_date, portfolio_ids)
        market_value = func.sum(HoldingModel.market_value_eur)
        stmt = (
            select(group_col, market_value, func.count())
            .join(latest, on_clause)
            # Outer joins, so a holding whose security or issuer is missing
            # still contributes to the total -- the file store groups it
            # under "(unresolved)" rather than dropping it.
            .outerjoin(SecurityModel, SecurityModel.security_id == HoldingModel.security_id)
            .outerjoin(CompanyModel, CompanyModel.company_id == SecurityModel.company_id)
        )
        for key, value in (security_filter or {}).items():
            stmt = stmt.where(self._dimension_column(key) == value)
        stmt = stmt.group_by(group_col).order_by(group_col)

        with self._session() as session:
            rows = [
                (key, round(float(total), 2), int(count)) for key, total, count in session.execute(stmt).all()
            ]
        return rows, round(sum(total for _key, total, _count in rows), 2)


def _holding_from_row(row) -> Holding:
    return Holding(
        holder_id=row.portfolio_id, kind=row.kind, security_id=row.security_id, as_of_date=row.as_of_date,
        isin=row.isin, issuer_key=row.issuer_key, issuer_scheme=row.issuer_scheme, source=row.source,
        source_ref=row.source_ref, currency=row.currency, quantity=row.quantity, price=row.price,
        market_value=row.market_value, fx_rate_to_eur=row.fx_rate_to_eur, market_value_eur=row.market_value_eur,
        shares=row.shares, free_float=row.free_float, weight_pct=row.weight_pct,
    )


def _security_from_row(row) -> SecurityRef:
    return SecurityRef(
        security_id=row.security_id, isin=row.isin, name=row.name, asset_class=row.asset_class,
        currency=row.currency, company_id=row.company_id,
    )


def _company_from_row(row) -> CompanyRef:
    return CompanyRef(
        company_id=row.company_id, name=row.name, ticker=row.ticker, website=row.website, cik=row.cik,
        country=row.country, sector=row.sector, isic_code=row.isic_code,
    )


def _resolution_from_row(row) -> SecurityResolution:
    return SecurityResolution(
        security_id=row.security_id, company_id=row.company_id, confidence=row.confidence, method=row.method,
        needs_review=row.needs_review, resolved_at=row.resolved_at,
    )
