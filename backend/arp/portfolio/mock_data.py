from __future__ import annotations

import random
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date

from arp.portfolio.climate import mock_esg_source
from arp.portfolio.entity_resolution import SecurityMaster, resolve_all
from arp.portfolio.loads import LoadRecord, record_load
from arp.portfolio.news.mock_source import MockNewsSource
from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import Holding, Portfolio, SecurityRef
from arp.storage.portfolio_store import PortfolioStore

# Illustrative demo dataset only. Company names are real, well-known
# public companies used purely as recognizable examples; every
# identifier, price, quantity, and ESG figure below is synthetic
# (deterministically seeded, not sourced from any real feed) --
# `security_id`s carry a "MOCK" marker for exactly this reason.



def snapshot_dates(today: date) -> list[str]:
    """Four quarterly month ends, the newest being the last month end before `today`: the month the feeds
    overview and the monthly run expect, so a fresh seed is never "behind"."""
    months = today.year * 12 + today.month - 2  # the previous month, counted from year 0
    out = []
    for back in (9, 6, 3, 0):
        year, month = divmod(months - back, 12)
        out.append(date(year, month + 1, monthrange(year, month + 1)[1]).isoformat())
    return out


# The default: fixed, so anything built on a seeded store is reproducible. The seed command and the app's
# "Seed demo dataset" pass today's date instead (snapshot_dates), so what a person sees is current.
SNAPSHOT_DATES = ["2025-11-28", "2026-02-27", "2026-05-29", "2026-08-12"]

# slug (the internal key of the tables below and of the security ids), ISIN, then name, country and sector as the
# holdings files write them (what `arp showcase load` stores, so both commands write the same company row under
# `isin_<ISIN>`), the mock climate generator's baseline label, the two-letter code of the mock ISINs, native currency
_COMPANIES: list[tuple[str, str, str, str, str, str, str, str]] = [
    ("bmw", "DE0005190003", "BMW", "Germany", "Consumer Discretionary", "Automobiles", "DE", "EUR"),
    ("mercedes", "DE0007100000", "MERCEDES-BENZ GROUP N AG", "Germany", "Consumer Discretionary", "Automobiles", "DE", "EUR"),
    ("siemens", "DE0007236101", "SIEMENS N AG", "Germany", "Industrials", "Industrials", "DE", "EUR"),
    ("sap", "DE0007164600", "SAP", "Germany", "Information Technology", "Software", "DE", "EUR"),
    ("allianz", "DE0008404005", "ALLIANZ", "Germany", "Financials", "Insurance", "DE", "EUR"),
    ("totalenergies", "FR0000120271", "TOTALENERGIES", "France", "Energy", "Energy", "FR", "EUR"),
    ("lvmh", "FR0000121014", "LVMH", "France", "Consumer Discretionary", "Luxury Goods", "FR", "EUR"),
    ("airbus", "NL0000235190", "AIRBUS", "France", "Industrials", "Aerospace & Defense", "NL", "EUR"),
    ("iberdrola", "ES0144580Y14", "IBERDROLA", "Spain", "Utilities", "Utilities", "ES", "EUR"),
    ("novartis", "CH0012005267", "NOVARTIS AG", "Switzerland", "Health Care", "Pharmaceuticals", "CH", "CHF"),
    ("nestle", "CH0038863350", "NESTLE SA", "Switzerland", "Consumer Staples", "Food Products", "CH", "CHF"),
    ("asml", "NL0010273215", "ASML HOLDING", "Netherlands", "Information Technology", "Semiconductors", "NL", "EUR"),
    ("shell", "GB00BP6MXD84", "SHELL", "Netherlands", "Energy", "Energy", "GB", "GBP"),
    ("orsted", "DK0060094928", "OERSTED", "Denmark", "Utilities", "Utilities", "DK", "DKK"),
    ("enel", "IT0003128367", "ENEL", "Italy", "Utilities", "Utilities", "IT", "EUR"),
]
_COMPANY_ID = {slug: f"isin_{isin}" for slug, isin, *_ in _COMPANIES}
_CLIMATE_BASELINE = {f"isin_{isin}": baseline for _, isin, _, _, _, baseline, _, _ in _COMPANIES}

# Which companies also have a corporate bond issue in the mock dataset.
_BOND_ISSUERS = ["bmw", "totalenergies", "shell", "siemens", "mercedes", "enel", "airbus", "nestle"]

_FX_BASE = {"EUR": 1.0, "CHF": 1.05, "GBP": 1.17, "DKK": 0.1341}

# Emissions/carbon-intensity figures for these issuers are deliberately
# generated with a wide internal-API/extracted gap, so the §6a cross-check
# has something real to flag in the demo.
_CLIMATE_MISMATCH_COMPANIES = {"totalenergies", "shell"}

# portfolio_id -> [(company_id, asset_class, base_market_value_eur), ...]
_PORTFOLIO_EQUITY_HOLDINGS: dict[str, list[tuple[str, float]]] = {
    "core_equity_europe": [
        ("bmw", 42_000_000), ("siemens", 55_000_000), ("sap", 61_000_000), ("allianz", 38_000_000),
        ("totalenergies", 47_000_000), ("lvmh", 33_000_000), ("airbus", 29_000_000),
        ("novartis", 44_000_000), ("nestle", 40_000_000), ("asml", 58_000_000),
    ],
    "sustainable_leaders": [
        ("iberdrola", 36_000_000), ("orsted", 24_000_000), ("enel", 31_000_000),
        ("asml", 27_000_000), ("siemens", 22_000_000), ("novartis", 19_000_000), ("sap", 25_000_000),
    ],
    "multi_asset_balanced": [
        ("bmw", 18_000_000), ("mercedes", 15_000_000), ("shell", 21_000_000),
        ("totalenergies", 17_000_000), ("allianz", 14_000_000), ("iberdrola", 12_000_000),
    ],
}

_PORTFOLIO_BOND_HOLDINGS: dict[str, list[tuple[str, float]]] = {
    "multi_asset_balanced": [("bmw", 9_000_000), ("totalenergies", 8_000_000), ("shell", 7_000_000), ("siemens", 6_000_000)],
    "corporate_bond_income": [
        ("mercedes", 20_000_000), ("totalenergies", 24_000_000), ("shell", 19_000_000),
        ("enel", 17_000_000), ("airbus", 15_000_000), ("nestle", 16_000_000),
    ],
}

_PORTFOLIOS = [
    Portfolio(portfolio_id="core_equity_europe", name="Core Equity Europe", tags=["mandate:equity", "region:europe"]),
    Portfolio(portfolio_id="sustainable_leaders", name="Sustainable Leaders Fund", tags=["mandate:equity", "strategy:climate-tilted"]),
    Portfolio(portfolio_id="multi_asset_balanced", name="Multi-Asset Balanced", tags=["mandate:multi-asset"]),
    Portfolio(portfolio_id="corporate_bond_income", name="Corporate Bond Income", tags=["mandate:fixed-income"]),
]


@dataclass
class DemoDatasetSummary:
    company_count: int = 0
    security_count: int = 0
    portfolio_count: int = 0
    snapshot_dates: list[str] = field(default_factory=list)
    holding_rows: int = 0
    climate_observations: int = 0
    climate_mismatch_companies: list[str] = field(default_factory=list)
    news_items: int = 0
    unresolved_security_ids: list[str] = field(default_factory=list)


def _rng(key: str) -> random.Random:
    return random.Random(f"mockdata::{key}")


def _isin(country: str, idx: int, suffix: str = "") -> str:
    return f"{country}0MOCK{idx:04d}{suffix or '0'}"


def _price_series(security_id: str, base_price: float, dates: list[str]) -> dict[str, float]:
    rng = _rng(f"price::{security_id}")
    price = base_price
    series = {}
    for d in dates:
        price *= 1 + rng.uniform(-0.06, 0.07)
        series[d] = round(price, 2)
    return series


def _quantity_series(security_id: str, base_quantity: float, dates: list[str]) -> dict[str, float]:
    rng = _rng(f"qty::{security_id}")
    qty = base_quantity
    series = {}
    for d in dates:
        if rng.random() < 0.3:
            qty *= 1 + rng.uniform(-0.15, 0.15)
        series[d] = round(qty)
    return series


def _fx_series(currency: str, dates: list[str]) -> dict[str, float]:
    if currency == "EUR":
        return {d: 1.0 for d in dates}
    rng = _rng(f"fx::{currency}")
    rate = _FX_BASE[currency]
    series = {}
    for d in dates:
        rate *= 1 + rng.uniform(-0.02, 0.02)
        series[d] = round(rate, 4)
    return series


def _build_companies_and_securities() -> tuple[list[CompanyRef], list[SecurityRef]]:
    companies: list[CompanyRef] = []
    securities: list[SecurityRef] = []
    for idx, (slug, _, name, country, sector, _, code, currency) in enumerate(_COMPANIES, start=1):
        companies.append(CompanyRef(company_id=_COMPANY_ID[slug], name=name, country=country, sector=sector))
        securities.append(
            SecurityRef(
                security_id=f"{slug}_eq", isin=_isin(code, idx), name=f"{name} (Ordinary Shares)",
                asset_class="equity", currency=currency, company_id=_COMPANY_ID[slug],
            )
        )
    for idx, slug in enumerate(_BOND_ISSUERS, start=1):
        _, _, name, _, _, _, code, currency = next(c for c in _COMPANIES if c[0] == slug)
        securities.append(
            SecurityRef(
                security_id=f"{slug}_bond1", isin=_isin(code, idx, "B"), name=f"{name} 3.25% 2030",
                asset_class="corporate_bond", currency=currency, company_id=_COMPANY_ID[slug],
            )
        )
    # A deliberately unresolved instrument -- simulates a custodian feed
    # row whose ISIN isn't in the security master and whose name doesn't
    # cleanly match any known issuer, to demonstrate entity_resolution.py
    # routing a low-confidence match to review instead of guessing.
    securities.append(
        SecurityRef(
            security_id="unmapped_note_1", isin="ZZ0MOCK99990", name="Special Situations Basket Note Series 4",
            asset_class="other", currency="EUR", company_id=None,
        )
    )
    return companies, securities


def _build_holdings(securities_by_id: dict[str, SecurityRef], dates: list[str]) -> dict[str, dict[str, list[Holding]]]:
    """Returns {portfolio_id: {as_of_date: [Holding, ...]}}."""
    holdings_by_portfolio: dict[str, dict[str, list[Holding]]] = {p.portfolio_id: {d: [] for d in dates} for p in _PORTFOLIOS}

    def add_positions(portfolio_id: str, security_id: str, base_market_value: float) -> None:
        security = securities_by_id[security_id]
        base_price = 120.0 if security.asset_class == "equity" else 101.0
        base_quantity = round(base_market_value / base_price)
        prices = _price_series(f"{portfolio_id}::{security_id}", base_price, dates)
        quantities = _quantity_series(f"{portfolio_id}::{security_id}", base_quantity, dates)
        fx = _fx_series(security.currency, dates)
        for d in dates:
            market_value = round(prices[d] * quantities[d], 2)
            holdings_by_portfolio[portfolio_id][d].append(
                Holding(
                    portfolio_id=portfolio_id, security_id=security_id, as_of_date=d,
                    quantity=quantities[d], price=prices[d], market_value=market_value,
                    fx_rate_to_eur=fx[d], market_value_eur=round(market_value * fx[d], 2),
                )
            )

    for portfolio_id, rows in _PORTFOLIO_EQUITY_HOLDINGS.items():
        for company_id, base_mv in rows:
            add_positions(portfolio_id, f"{company_id}_eq", base_mv)
    for portfolio_id, rows in _PORTFOLIO_BOND_HOLDINGS.items():
        for company_id, base_mv in rows:
            add_positions(portfolio_id, f"{company_id}_bond1", base_mv)

    # A small position in the unresolved instrument, in the balanced fund.
    add_positions("multi_asset_balanced", "unmapped_note_1", 3_000_000)

    return holdings_by_portfolio


async def generate_demo_dataset(
    store: PortfolioStore, today: date | None = None,
) -> DemoDatasetSummary:
    """Seeds a realistic, deterministic multi-portfolio demo dataset into
    `store`: companies, securities (with one deliberately unresolved
    instrument), 4 quarterly holdings snapshots across 4 portfolios,
    climate data-point observations (internal API + validated-against-
    extraction, with two issuers' figures deliberately mismatched), and
    ingested (not yet classified) news items.

    Every price/quantity/FX/ESG figure is synthetic and seeded off
    `company_id`/`security_id`, so re-running this against a fresh store
    always reproduces the same dataset.
    """
    dates = snapshot_dates(today) if today else SNAPSHOT_DATES  # `today`: snapshots that end at the last month end
    companies, securities = _build_companies_and_securities()
    for c in companies:
        store.save_company(c)
    for s in securities:
        store.save_security(s)

    master = SecurityMaster(isin_to_company_id={s.isin: s.company_id for s in securities if s.isin and s.company_id})
    resolutions = resolve_all(securities, master)
    for r in resolutions:
        store.save_resolution(r)
    unresolved_ids = [r.security_id for r in resolutions if r.needs_review]

    for p in _PORTFOLIOS:
        store.save_portfolio(p)

    securities_by_id = {s.security_id: s for s in securities}
    holdings_by_portfolio = _build_holdings(securities_by_id, dates)
    holding_rows = 0
    for portfolio_id, by_date in holdings_by_portfolio.items():
        for as_of_date, rows in by_date.items():
            store.save_snapshot(portfolio_id, as_of_date, rows)
            holding_rows += len(rows)
            # the monthly run is blocked without an ok load per portfolio and month
            record_load(store, LoadRecord(kind="holdings", source_id=portfolio_id, month=as_of_date[:7], status="ok", content_hash="demo"))

    observation_count = 0
    for company in companies:
        for as_of_date in dates:
            period = f"snapshot:{as_of_date}"
            # the curated baseline label, not the stored sector, so each company keeps its order of magnitude
            basis = company.model_copy(update={"sector": _CLIMATE_BASELINE[company.company_id]})
            internal_obs = mock_esg_source.generate_internal_api_observations(basis, period, as_of_date)
            for obs in internal_obs:
                store.append_observation(obs)
                observation_count += 1

    record_load(store, LoadRecord(kind="esg", source_id="default", month=dates[-1][:7], status="ok", content_hash="demo"))

    news_source = MockNewsSource()
    already_ingested = {(n.company_id, n.headline) for n in store.list_news()}
    news_count = 0
    for company in companies:
        for item in await news_source.fetch(company):
            if (item.company_id, item.headline) in already_ingested:
                continue  # news_id is randomly generated per fetch, so dedupe on content to keep re-seeding idempotent
            store.append_news(item)
            news_count += 1

    return DemoDatasetSummary(
        company_count=len(companies),
        security_count=len(securities),
        portfolio_count=len(_PORTFOLIOS),
        snapshot_dates=list(dates),
        holding_rows=holding_rows,
        climate_observations=observation_count,
        climate_mismatch_companies=sorted(_COMPANY_ID[slug] for slug in _CLIMATE_MISMATCH_COMPANIES),
        news_items=news_count,
        unresolved_security_ids=unresolved_ids,
    )
