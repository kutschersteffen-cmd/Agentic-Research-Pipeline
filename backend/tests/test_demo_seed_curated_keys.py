"""Spec showcase-curated-company-keys: the demo seed keys its 15 curated companies `isin_<ISIN>` with the name,
country and sector `arp showcase load` writes, so a database with both loads holds each of them once.
`fixtures/demo_seed_on_main.json` holds the seed's values on main at 7085a7e (holdings, ISINs, headlines by slug)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from arp.config import REPO_ROOT, Settings
from arp.portfolio.mock_data import SNAPSHOT_DATES, generate_demo_dataset
from arp.showcase.load import load
from arp.storage.portfolio_store import PortfolioStore

ON_MAIN = json.loads((Path(__file__).parent / "fixtures" / "demo_seed_on_main.json").read_text())

# table T: slug -> (company key, name, country, sector)
T = {
    "bmw": ("isin_DE0005190003", "BMW", "Germany", "Consumer Discretionary"),
    "mercedes": ("isin_DE0007100000", "MERCEDES-BENZ GROUP N AG", "Germany", "Consumer Discretionary"),
    "siemens": ("isin_DE0007236101", "SIEMENS N AG", "Germany", "Industrials"),
    "sap": ("isin_DE0007164600", "SAP", "Germany", "Information Technology"),
    "allianz": ("isin_DE0008404005", "ALLIANZ", "Germany", "Financials"),
    "totalenergies": ("isin_FR0000120271", "TOTALENERGIES", "France", "Energy"),
    "lvmh": ("isin_FR0000121014", "LVMH", "France", "Consumer Discretionary"),
    "airbus": ("isin_NL0000235190", "AIRBUS", "France", "Industrials"),
    "iberdrola": ("isin_ES0144580Y14", "IBERDROLA", "Spain", "Utilities"),
    "novartis": ("isin_CH0012005267", "NOVARTIS AG", "Switzerland", "Health Care"),
    "nestle": ("isin_CH0038863350", "NESTLE SA", "Switzerland", "Consumer Staples"),
    "asml": ("isin_NL0010273215", "ASML HOLDING", "Netherlands", "Information Technology"),
    "shell": ("isin_GB00BP6MXD84", "SHELL", "Netherlands", "Energy"),
    "orsted": ("isin_DK0060094928", "OERSTED", "Denmark", "Utilities"),
    "enel": ("isin_IT0003128367", "ENEL", "Italy", "Utilities"),
}
T_KEYS = {key for key, *_ in T.values()}
OLD_SLUGS = (set(T) - {"mercedes"}) | {"volkswagen"}
BOND_ISSUERS = ["bmw", "totalenergies", "shell", "siemens", "mercedes", "enel", "airbus", "nestle"]
CLIMATE_FIELDS = ["climate_scope1_tco2e", "climate_scope2_tco2e", "climate_scope3_tco2e", "climate_carbon_intensity",
                  "climate_evic_eur_m", "climate_green_revenue_pct"]
MERCEDES = {"mercedes_eq", "mercedes_bond1"}
# `arp showcase load` alone on a fresh Postgres schema, as on main (captured at 7085a7e)
LOAD_ALONE_COMPANIES = 2587
LOAD_ALONE_OBSERVATIONS_PER_FIELD = 6  # one simulated value a month, 2026-06 to 2026-11
DEUTSCHE_BANK = ("isin_DE0005140008", "DEUTSCHE BANK AG", "Germany", "Financials")


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    store = PortfolioStore(tmp_path_factory.mktemp("pf"))
    summary = asyncio.run(generate_demo_dataset(store))
    return store, summary


def _rows(store):
    return {c.company_id: (c.name, c.country, c.sector) for c in store.list_companies()}


def _assert_t_once(store):
    companies = store.list_companies()
    for key, name, country, sector in T.values():
        [row] = [c for c in companies if c.company_id == key]
        assert (row.name, row.country, row.sector) == (name, country, sector)
    assert not {c.company_id for c in companies} & OLD_SLUGS


def test_companies_are_the_t_keys(seeded):  # AC-5
    store, summary = seeded
    assert {c.company_id for c in store.list_companies()} == T_KEYS and len(store.list_companies()) == 15
    assert summary.company_count == 15 and summary.security_count == 24
    assert summary.climate_mismatch_companies == ["isin_FR0000120271", "isin_GB00BP6MXD84"]
    _assert_t_once(store)


def test_securities_keep_their_ids_and_point_at_the_t_keys(seeded):  # AC-6, AC-7, AC-8, AC-9, AC-29
    store, _ = seeded
    securities = {s.security_id: s for s in store.list_securities()}
    expected = {f"{slug}_eq" for slug in T} | {f"{slug}_bond1" for slug in BOND_ISSUERS} | {"unmapped_note_1"}
    assert set(securities) == expected and len(securities) == 24
    for sid, security in securities.items():
        slug = sid.rsplit("_", 1)[0]
        assert security.company_id == (None if sid == "unmapped_note_1" else T[slug][0])
    assert securities["totalenergies_eq"].name == "TOTALENERGIES (Ordinary Shares)"
    assert securities["totalenergies_bond1"].name == "TOTALENERGIES 3.25% 2030"
    assert (securities["mercedes_eq"].isin, securities["mercedes_bond1"].isin) == ("DE0MOCK00020", "DE0MOCK0005B")
    assert {sid: s.isin for sid, s in securities.items() if sid not in MERCEDES} == ON_MAIN["isins"]


def test_holdings_are_as_on_main_apart_from_the_mercedes_swap(seeded):  # AC-10, AC-11, AC-12, AC-32
    store, _ = seeded
    assert {p.portfolio_id for p in store.list_portfolios()} == {
        "core_equity_europe", "sustainable_leaders", "multi_asset_balanced", "corporate_bond_income"}
    holdings = {}
    for p in store.list_portfolios():
        for d in SNAPSHOT_DATES:
            rows = store.load_snapshot(p.portfolio_id, d)
            assert not any(h.security_id.startswith("volkswagen") for h in rows)
            holdings.update({f"{p.portfolio_id}|{d}|{h.security_id}": [h.quantity, h.price, h.market_value, h.fx_rate_to_eur,
                                                                    h.market_value_eur]
                             for h in rows if h.security_id not in MERCEDES})
    assert holdings == ON_MAIN["holdings"]
    for d in SNAPSHOT_DATES:
        assert "mercedes_eq" in {h.security_id for h in store.load_snapshot("multi_asset_balanced", d)}
        assert "mercedes_bond1" in {h.security_id for h in store.load_snapshot("corporate_bond_income", d)}


def test_news_moves_to_the_t_keys_with_the_same_headlines(seeded):  # AC-13, AC-14
    store, _ = seeded
    assert {n.company_id for n in store.list_news()} <= T_KEYS
    for slug, (key, *_) in T.items():
        assert sorted(n.headline for n in store.list_news(key)) == ON_MAIN["headlines"].get(slug, [])


def test_climate_observations_are_on_the_t_keys(seeded):  # AC-15, AC-16
    store, _ = seeded
    for key in T_KEYS:
        for field in CLIMATE_FIELDS:
            assert sorted(o.period for o in store.load_observations(key, field)) == [f"snapshot:{d}" for d in SNAPSHOT_DATES]
    for slug in OLD_SLUGS:
        for field in CLIMATE_FIELDS:
            assert store.load_observations(slug, field) == []


@pytest.fixture
def pg_store(pg, tmp_path):
    from arp.storage.postgres_portfolio_store import PostgresPortfolioStore

    settings = Settings(engagements_dir=tmp_path / "eng", stewardship_streams_dir=tmp_path / "streams",
                        frameworks_dir=tmp_path / "fw", runs_dir=tmp_path / "runs")
    store = PostgresPortfolioStore(pg, PortfolioStore(tmp_path / "files"))

    def run_load():
        lines = []
        assert load(store, settings, REPO_ROOT / "data/holdings", REPO_ROOT / "data/simulated/esg_simulated.csv", lines.append), lines

    return store, run_load


def _simulated(store, key, field="climate_scope1_tco2e"):
    return [o for o in store.load_observations(key, field) if o.source == "simulated"]


@pytest.mark.slow
def test_load_then_seed_keeps_one_row_per_company(pg_store):  # AC-20, AC-21, AC-22, AC-25, AC-30, AC-31
    store, run_load = pg_store
    run_load()
    assert len(store.list_companies()) == LOAD_ALONE_COMPANIES
    assert _rows(store)[DEUTSCHE_BANK[0]] == DEUTSCHE_BANK[1:]
    for field in CLIMATE_FIELDS:
        assert len(store.load_observations(DEUTSCHE_BANK[0], field)) == LOAD_ALONE_OBSERVATIONS_PER_FIELD
    asyncio.run(generate_demo_dataset(store))
    _assert_t_once(store)
    assert len(store.list_companies()) == -1  # THROWAWAY: fails on purpose in shard 2 (AC-42)


@pytest.mark.slow
def test_seed_then_load_keeps_one_row_per_company_and_both_sources(pg_store):  # AC-17, AC-18, AC-19, AC-23, AC-24
    store, run_load = pg_store
    asyncio.run(generate_demo_dataset(store))
    run_load()
    _assert_t_once(store)
    assert len(store.list_companies()) == LOAD_ALONE_COMPANIES
    internal = [o for o in store.load_observations("isin_FR0000120271", "climate_scope1_tco2e") if o.source == "internal_api"]
    assert len(internal) == 4 and all(o.period.startswith("snapshot:") for o in internal)
    assert len(_simulated(store, "isin_FR0000120271")) == LOAD_ALONE_OBSERVATIONS_PER_FIELD
