from __future__ import annotations

import random
from dataclasses import dataclass, field

from arp.portfolio.climate import mock_esg_source, validation
from arp.portfolio.entity_resolution import SecurityMaster, resolve_all
from arp.portfolio.news.mock_source import MockNewsSource
from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import Holding, Portfolio, SecurityRef
from arp.storage.portfolio_store import PortfolioStore

# Illustrative demo dataset only. Company names are real, well-known
# public companies used purely as recognizable examples; every
# identifier, price, quantity, and ESG figure below is synthetic
# (deterministically seeded, not sourced from any real feed) --
# `security_id`s carry a "MOCK" marker for exactly this reason.

SNAPSHOT_DATES = ["2025-11-28", "2026-02-27", "2026-05-29", "2026-08-12"]

# company_id, name, country, GICS-style sector label, native currency
_COMPANIES: list[tuple[str, str, str, str, str]] = [
    ("bmw", "Bayerische Motoren Werke AG", "DE", "Automobiles", "EUR"),
    ("volkswagen", "Volkswagen AG", "DE", "Automobiles", "EUR"),
    ("siemens", "Siemens AG", "DE", "Industrials", "EUR"),
    ("sap", "SAP SE", "DE", "Software", "EUR"),
    ("allianz", "Allianz SE", "DE", "Insurance", "EUR"),
    ("totalenergies", "TotalEnergies SE", "FR", "Energy", "EUR"),
    ("lvmh", "LVMH Moet Hennessy Louis Vuitton SE", "FR", "Luxury Goods", "EUR"),
    ("airbus", "Airbus SE", "NL", "Aerospace & Defense", "EUR"),
    ("iberdrola", "Iberdrola SA", "ES", "Utilities", "EUR"),
    ("novartis", "Novartis AG", "CH", "Pharmaceuticals", "CHF"),
    ("nestle", "Nestle SA", "CH", "Food Products", "CHF"),
    ("asml", "ASML Holding NV", "NL", "Semiconductors", "EUR"),
    ("shell", "Shell plc", "GB", "Energy", "GBP"),
    ("orsted", "Orsted A/S", "DK", "Utilities", "DKK"),
    ("enel", "Enel SpA", "IT", "Utilities", "EUR"),
]

# Which companies also have a corporate bond issue in the mock dataset.
_BOND_ISSUERS = ["bmw", "totalenergies", "shell", "siemens", "volkswagen", "enel", "airbus", "nestle"]

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
        ("bmw", 18_000_000), ("volkswagen", 15_000_000), ("shell", 21_000_000),
        ("totalenergies", 17_000_000), ("allianz", 14_000_000), ("iberdrola", 12_000_000),
    ],
}

_PORTFOLIO_BOND_HOLDINGS: dict[str, list[tuple[str, float]]] = {
    "multi_asset_balanced": [("bmw", 9_000_000), ("totalenergies", 8_000_000), ("shell", 7_000_000), ("siemens", 6_000_000)],
    "corporate_bond_income": [
        ("volkswagen", 20_000_000), ("totalenergies", 24_000_000), ("shell", 19_000_000),
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
    for idx, (company_id, name, country, sector, currency) in enumerate(_COMPANIES, start=1):
        companies.append(CompanyRef(company_id=company_id, name=name, country=country, sector=sector))
        securities.append(
            SecurityRef(
                security_id=f"{company_id}_eq", isin=_isin(country, idx), name=f"{name} (Ordinary Shares)",
                asset_class="equity", currency=currency, company_id=company_id,
            )
        )
    for idx, company_id in enumerate(_BOND_ISSUERS, start=1):
        _, name, country, _, currency = next(c for c in _COMPANIES if c[0] == company_id)
        securities.append(
            SecurityRef(
                security_id=f"{company_id}_bond1", isin=_isin(country, idx, "B"), name=f"{name} 3.25% 2030",
                asset_class="corporate_bond", currency=currency, company_id=company_id,
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


def _build_holdings(securities_by_id: dict[str, SecurityRef]) -> dict[str, dict[str, list[Holding]]]:
    """Returns {portfolio_id: {as_of_date: [Holding, ...]}}."""
    holdings_by_portfolio: dict[str, dict[str, list[Holding]]] = {p.portfolio_id: {d: [] for d in SNAPSHOT_DATES} for p in _PORTFOLIOS}

    def add_positions(portfolio_id: str, security_id: str, base_market_value: float) -> None:
        security = securities_by_id[security_id]
        base_price = 120.0 if security.asset_class == "equity" else 101.0
        base_quantity = round(base_market_value / base_price)
        prices = _price_series(f"{portfolio_id}::{security_id}", base_price, SNAPSHOT_DATES)
        quantities = _quantity_series(f"{portfolio_id}::{security_id}", base_quantity, SNAPSHOT_DATES)
        fx = _fx_series(security.currency, SNAPSHOT_DATES)
        for d in SNAPSHOT_DATES:
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
    store: PortfolioStore, confidence_review_threshold: float = 0.6, climate_validation_tolerance_pct: float = 0.15
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
    companies, securities = _build_companies_and_securities()
    for c in companies:
        store.save_company(c)
    for s in securities:
        store.save_security(s)

    master = SecurityMaster(
        isin_to_company_id={s.isin: s.company_id for s in securities if s.isin and s.company_id},
        company_names={c.company_id: c.name for c in companies},
    )
    resolutions = resolve_all(securities, master, confidence_review_threshold)
    for r in resolutions:
        store.save_resolution(r)
    unresolved_ids = [r.security_id for r in resolutions if r.needs_review]

    for p in _PORTFOLIOS:
        store.save_portfolio(p)

    securities_by_id = {s.security_id: s for s in securities}
    holdings_by_portfolio = _build_holdings(securities_by_id)
    holding_rows = 0
    for portfolio_id, by_date in holdings_by_portfolio.items():
        for as_of_date, rows in by_date.items():
            store.save_snapshot(portfolio_id, as_of_date, rows)
            holding_rows += len(rows)

    observation_count = 0
    for company in companies:
        for as_of_date in SNAPSHOT_DATES:
            period = f"snapshot:{as_of_date}"
            internal_obs = mock_esg_source.generate_internal_api_observations(company, period, as_of_date)
            extracted_obs = mock_esg_source.generate_extracted_observations(
                company, internal_obs, period, as_of_date, mismatch=company.company_id in _CLIMATE_MISMATCH_COMPANIES
            )
            extracted_by_field = {o.field_id: o for o in extracted_obs}
            for obs in internal_obs:
                resolved = validation.cross_check_and_store(
                    store, obs, extracted_by_field.get(obs.field_id), tolerance_pct=climate_validation_tolerance_pct
                )
                if resolved is not None:
                    observation_count += 1

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
        snapshot_dates=list(SNAPSHOT_DATES),
        holding_rows=holding_rows,
        climate_observations=observation_count,
        climate_mismatch_companies=sorted(_CLIMATE_MISMATCH_COMPANIES),
        news_items=news_count,
        unresolved_security_ids=unresolved_ids,
    )
