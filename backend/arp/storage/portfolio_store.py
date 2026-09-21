from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from arp.schemas.common import CompanyRef, now_iso
from arp.schemas.portfolio import (
    DataPointObservation,
    Holding,
    NewsItem,
    NewsRiskFlag,
    Portfolio,
    SecurityRef,
    SecurityResolution,
)
from arp.schemas.portfolio_monitoring import AlertRule
from arp.storage.atomic_io import atomic_write_text
from arp.storage.jsonl_io import append_jsonl, read_jsonl
from arp.storage.locks import KeyedLock
from arp.storage.safe_path import safe_id


def _sidecar_lock_path(key: str) -> Path:
    """`.<filename>.lock` beside the file a PortfolioStore write targets --
    this store's lock keys are paths, unlike the other stores' opaque ids.
    A dotted sibling rather than a suffix change so it never matches the
    `*.jsonl` / `*.json` globs the listing methods use."""
    path = Path(key)
    return path.parent / f".{path.name}.lock"


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

    The registry-style files above (`registry.json`, `securities.json`,
    `companies.json`, `security_resolutions.json`, `analytics.json`,
    `monitoring/rules.json`) each hold *many* records in one JSON object,
    so saving one record is a read-modify-write of the whole file. Those
    go through `_put_json_entry`, which takes a per-file KeyedLock and
    writes atomically -- exactly what RunStore/EngagementStore already do
    for their own read-modify-write cycles, and for the same reason: this
    store is an lru_cached singleton (api/deps.py::get_portfolio_store)
    shared by every sync route handler's worker thread, so two concurrent
    saves against one file otherwise lose one side's record outright and
    a concurrent reader can observe the file mid-truncation.
    """

    def __init__(self, portfolios_dir: Path) -> None:
        self.portfolios_dir = portfolios_dir
        # Keyed by the file being written, and locked across processes as
        # well as threads: an `arp portfolio ...` CLI command writes the
        # same registry files as a live API process. See KeyedLock.
        self._locks = KeyedLock(lock_path=_sidecar_lock_path)

    @contextmanager
    def _lock(self, path: Path) -> Iterator[None]:
        """Serializes access to one file within this process, keyed by
        path. Deliberately not public, unlike RunStore.lock/
        EngagementStore.lock: those exist because JobManager and the
        engagement orchestrator wrap several of their calls in one
        cycle, whereas every read-modify-write here is a single save. A
        caller wanting two of these saves to land together would need
        more than a shared lock anyway -- they touch different files,
        which no lock makes atomic as a pair."""
        with self._locks.acquire(str(path)):
            yield

    @staticmethod
    def _read_json(path: Path) -> dict:
        if not path.exists():
            return {}
        return json.loads(path.read_text())

    def _write_json(self, path: Path, data: dict) -> None:
        self.portfolios_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, json.dumps(data, indent=2))

    def _put_json_entry(self, path: Path, key: str, value: dict) -> None:
        """Sets one record in a registry file, serialized against other
        writers of the same file and atomic for readers."""
        with self._lock(path):
            data = self._read_json(path)
            data[key] = value
            self._write_json(path, data)

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict]:
        return read_jsonl(path)

    def _append_jsonl(self, path: Path, row: dict) -> None:
        with self._lock(path):
            append_jsonl(path, row)

    # --- portfolios ---

    def registry_path(self) -> Path:
        return self.portfolios_dir / "registry.json"

    def save_portfolio(self, portfolio: Portfolio) -> None:
        self._put_json_entry(self.registry_path(), portfolio.portfolio_id, json.loads(portfolio.model_dump_json()))

    def get_portfolio(self, portfolio_id: str) -> Portfolio | None:
        row = self._read_json(self.registry_path()).get(portfolio_id)
        return Portfolio.model_validate(row) if row else None

    def list_portfolios(self) -> list[Portfolio]:
        return [Portfolio.model_validate(v) for v in self._read_json(self.registry_path()).values()]

    # --- securities ---

    def securities_path(self) -> Path:
        return self.portfolios_dir / "securities.json"

    def save_security(self, security: SecurityRef) -> None:
        self._put_json_entry(self.securities_path(), security.security_id, json.loads(security.model_dump_json()))

    def get_security(self, security_id: str) -> SecurityRef | None:
        row = self._read_json(self.securities_path()).get(security_id)
        return SecurityRef.model_validate(row) if row else None

    def list_securities(self) -> list[SecurityRef]:
        return [SecurityRef.model_validate(v) for v in self._read_json(self.securities_path()).values()]

    # --- companies (the issuer directory securities resolve into) ---

    def companies_path(self) -> Path:
        return self.portfolios_dir / "companies.json"

    def save_company(self, company: CompanyRef) -> None:
        self._put_json_entry(self.companies_path(), company.company_id, json.loads(company.model_dump_json()))

    def get_company(self, company_id: str) -> CompanyRef | None:
        row = self._read_json(self.companies_path()).get(company_id)
        return CompanyRef.model_validate(row) if row else None

    def list_companies(self) -> list[CompanyRef]:
        return [CompanyRef.model_validate(v) for v in self._read_json(self.companies_path()).values()]

    # --- security resolutions (ISIN/name -> company_id) ---

    def resolutions_path(self) -> Path:
        return self.portfolios_dir / "security_resolutions.json"

    def save_resolution(self, resolution: SecurityResolution) -> None:
        self._put_json_entry(self.resolutions_path(), resolution.security_id, json.loads(resolution.model_dump_json()))

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
        """Writes one snapshot file whole. Atomic (and locked) because a
        re-pull for a date already on disk is a deliberate overwrite: a
        reader must see the previous pull or the new one, never a file
        truncated to the first N holdings of the new one."""
        path = self.snapshot_path(portfolio_id, as_of_date)
        with self._lock(path):
            atomic_write_text(path, "".join(h.model_dump_json() + "\n" for h in holdings))

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

    def list_observation_keys(self) -> list[tuple[str, str]]:
        """Every (company_id, field_id) pair with at least one recorded
        observation -- a pure directory listing, no resolution logic (see
        `datapoint_mapping.list_conflicting_observations` for the cascade-
        aware conflict scan built on top of this)."""
        datapoints_dir = self.portfolios_dir / "datapoints"
        if not datapoints_dir.exists():
            return []
        return sorted((path.parent.name, path.stem) for path in datapoints_dir.glob("*/*.jsonl"))

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
        self._put_json_entry(self.analytics_path(), spec_json["analytic_id"], spec_json)

    def list_analytics(self) -> list[dict]:
        return list(self._read_json(self.analytics_path()).values())

    def get_analytic(self, analytic_id: str) -> dict | None:
        return self._read_json(self.analytics_path()).get(analytic_id)

    # --- saved generative-BI dashboards ---

    def dashboards_path(self) -> Path:
        return self.portfolios_dir / "dashboards.json"

    def save_dashboard(self, spec_json: dict) -> None:
        """Persists a `DashboardSpec` -- the re-runnable plan, never the
        generated prose or the figures it described. Re-running a stored
        dashboard recomputes everything from live holdings, so a saved
        dashboard can't serve a stale number under a current date."""
        data = self._read_json(self.dashboards_path())
        data[spec_json["dashboard_id"]] = spec_json
        self._write_json(self.dashboards_path(), data)

    def list_dashboards(self) -> list[dict]:
        return list(self._read_json(self.dashboards_path()).values())

    def get_dashboard(self, dashboard_id: str) -> dict | None:
        return self._read_json(self.dashboards_path()).get(dashboard_id)

    # --- continuous monitoring & alerting (arp/portfolio/monitoring/) ---

    def rules_path(self) -> Path:
        return self.portfolios_dir / "monitoring" / "rules.json"

    def save_rule(self, rule: AlertRule) -> None:
        self._put_json_entry(self.rules_path(), rule.rule_id, json.loads(rule.model_dump_json()))

    def get_rule(self, rule_id: str) -> AlertRule | None:
        row = self._read_json(self.rules_path()).get(rule_id)
        return AlertRule.model_validate(row) if row else None

    def list_rules(self, enabled_only: bool = False) -> list[AlertRule]:
        rules = [AlertRule.model_validate(v) for v in self._read_json(self.rules_path()).values()]
        return [r for r in rules if r.enabled] if enabled_only else rules

    def alert_events_path(self, scope_id: str) -> Path:
        """One append-only event log per scope -- generalizes
        EngagementStore's per-company `events.jsonl` sharding to this
        module's two scope kinds (a bare company_id, or
        "portfolio__<portfolio_id>" for portfolio-scoped rules; the double
        underscore keeps the id within safe_id's allowed character set,
        which rejects the ":" a "portfolio:<id>" convention would need).
        Two event types land here: "alert_raised" (the full Alert payload,
        no decided_by -- system-generated, same as engagement's
        open_issue never logging an EscalationTransition) and
        "status_changed" (an AlertTransition, decided_by required).
        """
        return self.portfolios_dir / "monitoring" / safe_id(scope_id, label="scope_id") / "events.jsonl"

    def append_alert_event(self, scope_id: str, event_type: str, payload: dict) -> None:
        self._append_jsonl(self.alert_events_path(scope_id), {"event_type": event_type, "at": now_iso(), **payload})

    def list_alert_events(self, scope_id: str) -> list[dict]:
        return self._read_jsonl(self.alert_events_path(scope_id))

    def list_all_alert_scope_ids(self) -> list[str]:
        d = self.portfolios_dir / "monitoring"
        if not d.exists():
            return []
        return sorted(p.name for p in d.iterdir() if p.is_dir())

    # --- governance & workflow (arp/portfolio/governance.py) ---

    def governance_events_path(self) -> Path:
        """One unified append-only log for every governance event type
        (decision_recorded / policy_changed / owner_assigned) -- not
        sharded per-item like alert_events_path, since a climate-conflict
        item_key ("{company_id}:{field_id}") contains a ":" that safe_id()
        rejects as a path segment, and this data is low-volume enough that
        a single small fold per page-load is fine."""
        return self.portfolios_dir / "governance" / "events.jsonl"

    def append_governance_event(self, event_type: str, payload: dict) -> None:
        self._append_jsonl(self.governance_events_path(), {"event_type": event_type, "at": now_iso(), **payload})

    def list_governance_events(self) -> list[dict]:
        return self._read_jsonl(self.governance_events_path())


def portfolio_directories(store: PortfolioStore) -> tuple[dict[str, SecurityRef], dict[str, CompanyRef]]:
    """The (securities, companies) id -> reference lookups every caller
    that resolves holdings needs. One definition so a future filter,
    cache, or unresolved-company_id fallback lands everywhere at once
    rather than in whichever call site the author happened to open.
    """
    securities = {s.security_id: s for s in store.list_securities()}
    companies = {c.company_id: c for c in store.list_companies()}
    return securities, companies
