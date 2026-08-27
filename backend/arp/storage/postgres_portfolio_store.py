from __future__ import annotations

"""Postgres-backed alternative to arp/storage/portfolio_store.py::PortfolioStore
for Portfolios/Securities/Companies/Holdings specifically -- see the module
docstring in postgres_models.py for why the scope stops there (everything
else -- observations, news, flags, analytics specs -- stays file-based).

Selected via Settings.portfolio_backend == "postgres" (requires
Settings.postgres_dsn); the file-based PortfolioStore remains the default
and is entirely unaffected when this isn't opted into.
"""

from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import DataPointObservation, Holding, NewsItem, NewsRiskFlag, Portfolio, SecurityRef, SecurityResolution
from arp.storage.portfolio_store import PortfolioStore
from arp.storage.postgres import get_engine


class PostgresPortfolioStore:
    """A genuine drop-in for PortfolioStore: portfolios/securities/
    companies/holdings-snapshots/resolutions are relational (Postgres),
    everything else (observations, news, flags, analytics specs -- none of
    which have the multi-way join access pattern that justifies a
    relational engine) delegates to a wrapped file-based PortfolioStore,
    so every caller of get_portfolio_store() keeps working unmodified
    regardless of which backend is configured.
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

    def observations_path(self, company_id: str, field_id: str):
        return self._files.observations_path(company_id, field_id)

    def append_observation(self, obs: DataPointObservation) -> None:
        self._files.append_observation(obs)

    def load_observations(self, company_id: str, field_id: str) -> list[DataPointObservation]:
        return self._files.load_observations(company_id, field_id)

    def latest_observation(self, company_id: str, field_id: str, as_of: str | None = None) -> DataPointObservation | None:
        return self._files.latest_observation(company_id, field_id, as_of)

    def news_path(self):
        return self._files.news_path()

    def append_news(self, item: NewsItem) -> None:
        self._files.append_news(item)

    def list_news(self, company_id: str | None = None) -> list[NewsItem]:
        return self._files.list_news(company_id)

    def flags_path(self):
        return self._files.flags_path()

    def append_flag(self, flag: NewsRiskFlag) -> None:
        self._files.append_flag(flag)

    def list_flags(self, company_id: str | None = None) -> list[NewsRiskFlag]:
        return self._files.list_flags(company_id)

    def analytics_path(self):
        return self._files.analytics_path()

    def save_analytic(self, spec_json: dict) -> None:
        self._files.save_analytic(spec_json)

    def list_analytics(self) -> list[dict]:
        return self._files.list_analytics()

    def get_analytic(self, analytic_id: str) -> dict | None:
        return self._files.get_analytic(analytic_id)

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
        from arp.storage.postgres_models import SecurityModel

        with self._session() as session:
            session.merge(
                SecurityModel(
                    security_id=security.security_id, isin=security.isin, name=security.name,
                    asset_class=security.asset_class, currency=security.currency, company_id=security.company_id,
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
        from arp.storage.postgres_models import SecurityResolutionModel

        with self._session() as session:
            session.merge(
                SecurityResolutionModel(
                    security_id=resolution.security_id, company_id=resolution.company_id,
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

    def save_snapshot(self, portfolio_id: str, as_of_date: str, holdings: list[Holding]) -> None:
        """Replaces any existing rows for this exact (portfolio_id,
        as_of_date) before inserting -- makes re-running an ingestion for
        the same date idempotent (matches PortfolioStore.save_snapshot's
        file-overwrite semantics) rather than accumulating duplicate rows.
        """
        from sqlalchemy import delete

        from arp.storage.postgres_models import HoldingModel

        with self._session() as session:
            session.execute(
                delete(HoldingModel).where(
                    HoldingModel.portfolio_id == portfolio_id, HoldingModel.as_of_date == as_of_date
                )
            )
            session.add_all(
                [
                    HoldingModel(
                        portfolio_id=h.portfolio_id, security_id=h.security_id, as_of_date=h.as_of_date,
                        quantity=h.quantity, price=h.price, market_value=h.market_value,
                        fx_rate_to_eur=h.fx_rate_to_eur, market_value_eur=h.market_value_eur, weight_pct=h.weight_pct,
                    )
                    for h in holdings
                ]
            )
            session.commit()

    def load_snapshot(self, portfolio_id: str, as_of_date: str) -> list[Holding]:
        return self.load_holdings_as_of(as_of_date, portfolio_ids=[portfolio_id])

    def list_snapshot_dates(self, portfolio_id: str) -> list[str]:
        from sqlalchemy import select

        from arp.storage.postgres_models import HoldingModel

        with self._session() as session:
            rows = session.scalars(
                select(HoldingModel.as_of_date)
                .where(HoldingModel.portfolio_id == portfolio_id)
                .distinct()
                .order_by(HoldingModel.as_of_date)
            ).all()
            return list(rows)

    def latest_snapshot_date(self, portfolio_id: str) -> str | None:
        dates = self.list_snapshot_dates(portfolio_id)
        return dates[-1] if dates else None

    def all_snapshot_dates(self) -> list[str]:
        from sqlalchemy import select

        from arp.storage.postgres_models import HoldingModel

        with self._session() as session:
            rows = session.scalars(select(HoldingModel.as_of_date).distinct().order_by(HoldingModel.as_of_date)).all()
            return list(rows)

    def load_holdings_as_of(self, as_of_date: str, portfolio_ids: list[str] | None = None) -> list[Holding]:
        from sqlalchemy import select

        from arp.storage.postgres_models import HoldingModel

        with self._session() as session:
            stmt = select(HoldingModel).where(HoldingModel.as_of_date == as_of_date)
            if portfolio_ids:
                stmt = stmt.where(HoldingModel.portfolio_id.in_(portfolio_ids))
            rows = session.scalars(stmt).all()
            return [
                Holding(
                    portfolio_id=r.portfolio_id, security_id=r.security_id, as_of_date=r.as_of_date,
                    quantity=r.quantity, price=r.price, market_value=r.market_value,
                    fx_rate_to_eur=r.fx_rate_to_eur, market_value_eur=r.market_value_eur, weight_pct=r.weight_pct,
                )
                for r in rows
            ]

    # --- the payoff: a real relational join, not available cheaply over the file store ---

    def aggregate_market_value_eur(
        self, as_of_date: str, group_by: str, portfolio_ids: list[str] | None = None
    ) -> list[tuple[str | None, float]]:
        """Sums market_value_eur across holdings, grouped by a Holding/
        Security/Company field -- a three-way join (holdings x securities
        x companies) done in one SQL query instead of loading every JSONL
        snapshot into Python and grouping by hand, which is what the
        equivalent file-based aggregation.py necessarily does today. This
        is the concrete case docs/METHODOLOGY.md's architecture-review
        gap analysis names as where a relational store actually earns its
        cost at this system's scale (many portfolios x many dates).

        `group_by` must be one of: portfolio_id, security_id, asset_class,
        currency, company_id, sector, country -- the first four resolve
        straight off `holdings`/`securities`, the last three require the
        join into `companies`.
        """
        from sqlalchemy import func, select

        from arp.storage.postgres_models import CompanyModel, HoldingModel, SecurityModel

        holding_cols = {"portfolio_id", "security_id"}
        security_cols = {"asset_class", "currency"}
        company_cols = {"sector", "country", "company_id"}
        if group_by not in holding_cols | security_cols | company_cols:
            raise ValueError(f"Unsupported group_by: {group_by!r}")

        if group_by in holding_cols:
            group_col = getattr(HoldingModel, group_by)
            stmt = select(group_col, func.sum(HoldingModel.market_value_eur)).where(HoldingModel.as_of_date == as_of_date)
        elif group_by in security_cols:
            group_col = getattr(SecurityModel, group_by)
            stmt = (
                select(group_col, func.sum(HoldingModel.market_value_eur))
                .join(SecurityModel, SecurityModel.security_id == HoldingModel.security_id)
                .where(HoldingModel.as_of_date == as_of_date)
            )
        else:
            group_col = SecurityModel.company_id if group_by == "company_id" else getattr(CompanyModel, group_by)
            stmt = (
                select(group_col, func.sum(HoldingModel.market_value_eur))
                .join(SecurityModel, SecurityModel.security_id == HoldingModel.security_id)
                .outerjoin(CompanyModel, CompanyModel.company_id == SecurityModel.company_id)
                .where(HoldingModel.as_of_date == as_of_date)
            )

        if portfolio_ids:
            stmt = stmt.where(HoldingModel.portfolio_id.in_(portfolio_ids))
        stmt = stmt.group_by(group_col).order_by(func.sum(HoldingModel.market_value_eur).desc())

        with self._session() as session:
            return [(key, float(total)) for key, total in session.execute(stmt).all()]


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
