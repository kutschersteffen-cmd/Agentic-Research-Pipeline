from __future__ import annotations

import json
from pathlib import Path

from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import (
    DataPointObservation,
    Holding,
    NewsItem,
    NewsRiskFlag,
    Portfolio,
    SecurityRef,
    SecurityResolution,
)
from arp.storage.safe_path import safe_id


class PortfolioStore:
    """File-based persistence for portfolios, securities, and holdings
    snapshots -- same no-DB, append-don't-overwrite philosophy as
    RunStore/TaxonomyStore. Holdings snapshots are immutable once written:
    a refreshed pull for a date writes a new file, a corrected pull for a
    date it already has is a deliberate overwrite of that one file only,
    never a rewrite of history for other dates.

    Layout:
        portfolios/registry.json                          Portfolio metadata
        portfolios/securities.json                          SecurityRef reference data
        portfolios/security_resolutions.json                  ISIN -> company_id resolutions
        portfolios/<portfolio_id>/snapshots/<as_of_date>.jsonl  Holding[] per snapshot
    """

    def __init__(self, portfolios_dir: Path) -> None:
        self.portfolios_dir = portfolios_dir

    @staticmethod
    def _read_json(path: Path) -> dict:
        if not path.exists():
            return {}
        return json.loads(path.read_text())

    def _write_json(self, path: Path, data: dict) -> None:
        self.portfolios_dir.mkdir(parents=True, exist_ok=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2))

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict]:
        if not path.exists():
            return []
        rows = []
        with path.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return rows

    @staticmethod
    def _append_jsonl(path: Path, row: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps(row) + "\n")

    # --- portfolios ---

    def registry_path(self) -> Path:
        return self.portfolios_dir / "registry.json"

    def save_portfolio(self, portfolio: Portfolio) -> None:
        registry = self._read_json(self.registry_path())
        registry[portfolio.portfolio_id] = json.loads(portfolio.model_dump_json())
        self._write_json(self.registry_path(), registry)

    def get_portfolio(self, portfolio_id: str) -> Portfolio | None:
        row = self._read_json(self.registry_path()).get(portfolio_id)
        return Portfolio.model_validate(row) if row else None

    def list_portfolios(self) -> list[Portfolio]:
        return [Portfolio.model_validate(v) for v in self._read_json(self.registry_path()).values()]

    # --- securities ---

    def securities_path(self) -> Path:
        return self.portfolios_dir / "securities.json"

    def save_security(self, security: SecurityRef) -> None:
        data = self._read_json(self.securities_path())
        data[security.security_id] = json.loads(security.model_dump_json())
        self._write_json(self.securities_path(), data)

    def get_security(self, security_id: str) -> SecurityRef | None:
        row = self._read_json(self.securities_path()).get(security_id)
        return SecurityRef.model_validate(row) if row else None

    def list_securities(self) -> list[SecurityRef]:
        return [SecurityRef.model_validate(v) for v in self._read_json(self.securities_path()).values()]

    # --- companies (the issuer directory securities resolve into) ---

    def companies_path(self) -> Path:
        return self.portfolios_dir / "companies.json"

    def save_company(self, company: CompanyRef) -> None:
        data = self._read_json(self.companies_path())
        data[company.company_id] = json.loads(company.model_dump_json())
        self._write_json(self.companies_path(), data)

    def get_company(self, company_id: str) -> CompanyRef | None:
        row = self._read_json(self.companies_path()).get(company_id)
        return CompanyRef.model_validate(row) if row else None

    def list_companies(self) -> list[CompanyRef]:
        return [CompanyRef.model_validate(v) for v in self._read_json(self.companies_path()).values()]

    # --- security resolutions (ISIN/name -> company_id) ---

    def resolutions_path(self) -> Path:
        return self.portfolios_dir / "security_resolutions.json"

    def save_resolution(self, resolution: SecurityResolution) -> None:
        data = self._read_json(self.resolutions_path())
        data[resolution.security_id] = json.loads(resolution.model_dump_json())
        self._write_json(self.resolutions_path(), data)

    def get_resolution(self, security_id: str) -> SecurityResolution | None:
        row = self._read_json(self.resolutions_path()).get(security_id)
        return SecurityResolution.model_validate(row) if row else None

    def list_resolutions_needing_review(self) -> list[SecurityResolution]:
        return [
            SecurityResolution.model_validate(row)
            for row in self._read_json(self.resolutions_path()).values()
            if row.get("needs_review")
        ]

    # --- holdings snapshots ---

    def snapshot_path(self, portfolio_id: str, as_of_date: str) -> Path:
        return self.portfolios_dir / safe_id(portfolio_id, label="portfolio_id") / "snapshots" / f"{safe_id(as_of_date, label='as_of_date')}.jsonl"

    def save_snapshot(self, portfolio_id: str, as_of_date: str, holdings: list[Holding]) -> None:
        path = self.snapshot_path(portfolio_id, as_of_date)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as f:
            for h in holdings:
                f.write(h.model_dump_json() + "\n")

    def load_snapshot(self, portfolio_id: str, as_of_date: str) -> list[Holding]:
        return [Holding.model_validate(row) for row in self._read_jsonl(self.snapshot_path(portfolio_id, as_of_date))]

    def list_snapshot_dates(self, portfolio_id: str) -> list[str]:
        d = self.portfolios_dir / safe_id(portfolio_id, label="portfolio_id") / "snapshots"
        if not d.exists():
            return []
        return sorted(p.stem for p in d.glob("*.jsonl"))

    def latest_snapshot_date(self, portfolio_id: str) -> str | None:
        dates = self.list_snapshot_dates(portfolio_id)
        return dates[-1] if dates else None

    def all_snapshot_dates(self) -> list[str]:
        """Union of every snapshot date across all portfolios, sorted -- the
        candidate dates for a trend query's date_range."""
        dates: set[str] = set()
        for p in self.list_portfolios():
            dates.update(self.list_snapshot_dates(p.portfolio_id))
        return sorted(dates)

    def load_holdings_as_of(self, as_of_date: str, portfolio_ids: list[str] | None = None) -> list[Holding]:
        """Holdings across (optionally filtered) portfolios, using each
        portfolio's most recent snapshot on or before `as_of_date` --
        portfolios can be pulled/refreshed on independent schedules."""
        ids = portfolio_ids or [p.portfolio_id for p in self.list_portfolios()]
        holdings: list[Holding] = []
        for pid in ids:
            candidate_dates = [d for d in self.list_snapshot_dates(pid) if d <= as_of_date]
            if not candidate_dates:
                continue
            holdings.extend(self.load_snapshot(pid, candidate_dates[-1]))
        return holdings

    # --- data-point observation history ---

    def observations_path(self, company_id: str, field_id: str) -> Path:
        return self.portfolios_dir / "datapoints" / safe_id(company_id, label="company_id") / f"{safe_id(field_id, label='field_id')}.jsonl"

    def append_observation(self, obs: DataPointObservation) -> None:
        self._append_jsonl(self.observations_path(obs.company_id, obs.field_id), json.loads(obs.model_dump_json()))

    def load_observations(self, company_id: str, field_id: str) -> list[DataPointObservation]:
        return [
            DataPointObservation.model_validate(row)
            for row in self._read_jsonl(self.observations_path(company_id, field_id))
        ]

    def latest_observation(self, company_id: str, field_id: str, as_of: str | None = None) -> DataPointObservation | None:
        obs = self.load_observations(company_id, field_id)
        if as_of:
            obs = [o for o in obs if o.observed_at[:10] <= as_of]
        return obs[-1] if obs else None

    # --- news + risk flags ---

    def news_path(self) -> Path:
        return self.portfolios_dir / "news" / "items.jsonl"

    def append_news(self, item: NewsItem) -> None:
        self._append_jsonl(self.news_path(), json.loads(item.model_dump_json()))

    def list_news(self, company_id: str | None = None) -> list[NewsItem]:
        items = [NewsItem.model_validate(row) for row in self._read_jsonl(self.news_path())]
        return [i for i in items if company_id is None or i.company_id == company_id]

    def flags_path(self) -> Path:
        return self.portfolios_dir / "news" / "risk_flags.jsonl"

    def append_flag(self, flag: NewsRiskFlag) -> None:
        self._append_jsonl(self.flags_path(), json.loads(flag.model_dump_json()))

    def list_flags(self, company_id: str | None = None) -> list[NewsRiskFlag]:
        flags = [NewsRiskFlag.model_validate(row) for row in self._read_jsonl(self.flags_path())]
        return [f for f in flags if company_id is None or f.company_id == company_id]

    # --- saved analytics ---

    def analytics_path(self) -> Path:
        return self.portfolios_dir / "analytics.json"

    def save_analytic(self, spec_json: dict) -> None:
        data = self._read_json(self.analytics_path())
        data[spec_json["analytic_id"]] = spec_json
        self._write_json(self.analytics_path(), data)

    def list_analytics(self) -> list[dict]:
        return list(self._read_json(self.analytics_path()).values())

    def get_analytic(self, analytic_id: str) -> dict | None:
        return self._read_json(self.analytics_path()).get(analytic_id)
