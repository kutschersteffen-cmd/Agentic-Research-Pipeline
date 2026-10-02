"""Loads DWS ETF "Constituent_<ISIN>.xlsx" exports as test portfolios and index universes.

    python backend/scripts/import_dws_constituents.py data/sample/dws_constituents \
        [--nav-eur 100000000] [--portfolios-dir portfolios] [--universe-dir data/sample/dws_constituents/universe]

Portfolios: one per file (id = the fund ISIN), all rows, market value = weight * NAV.
Index universes: one IndexCandidate JSON per file for `arp index ... --universe-file`,
equities with a positive weight only.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from arp.config import get_settings
from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import Holding, Portfolio, SecurityRef
from arp.storage.portfolio_store import PortfolioStore

ASSET_CLASS = {"Aktien": "equity", "Cash": "cash", "Mutual Fund": "fund", "Future": "derivative"}


def read_constituents(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, header=3).iloc[:, 1:]  # row 4 is the header; col A is the rank
    return df[df["ISIN"].notna() & df["Weighting"].notna()]


def import_portfolio(store: PortfolioStore, path: Path, nav: float, as_of: str) -> int:
    fund = path.stem.split("_")[1]
    store.save_portfolio(Portfolio(portfolio_id=fund, name=f"DWS {fund}", tags=["test:dws", "mandate:equity"]))
    holdings = []
    for r in read_constituents(path).itertuples(index=False):
        asset_class = ASSET_CLASS.get(r[5], "other")  # 'Type of Security'
        is_equity = asset_class == "equity"
        company_id = r.ISIN if is_equity else None
        if is_equity:
            store.save_company(CompanyRef(company_id=company_id, name=r.Name, country=r.Country, sector=r[8]))
        store.save_security(SecurityRef(security_id=r.ISIN, isin=r.ISIN if is_equity else None, name=r.Name,
                                        asset_class=asset_class, currency=r.Currency, company_id=company_id))
        mv = r.Weighting * nav
        holdings.append(Holding(portfolio_id=fund, security_id=r.ISIN, as_of_date=as_of, quantity=mv, price=1.0,
                                market_value=mv, market_value_eur=mv,  # ponytail: EUR throughout, native FX ignored
                                 weight_pct=r.Weighting * 100))
    store.save_snapshot(fund, as_of, holdings)
    return len(holdings)


def write_universe(path: Path, out_dir: Path) -> int:
    df = read_constituents(path)
    df = df[(df["Type of Security"] == "Aktien") & (df["Weighting"] > 0)]
    # weight -> market cap: price 1, shares proportional to weight, so cap weights reproduce the file
    rows = [{"company_id": r.ISIN, "name": r.Name, "sector": r[8], "country": r.Country, "currency": "EUR",
             "price": 1.0, "shares_outstanding": r.Weighting * 1e9} for r in df.itertuples(index=False)]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{path.stem.split('_')[1]}.json").write_text(json.dumps(rows, indent=1))
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("--nav-eur", type=float, default=100_000_000)
    ap.add_argument("--portfolios-dir", type=Path, default=get_settings().portfolios_dir)
    ap.add_argument("--universe-dir", type=Path)
    a = ap.parse_args()
    store = PortfolioStore(a.portfolios_dir)
    for f in sorted(a.src.glob("Constituent_*.xlsx")):
        as_of = pd.ExcelFile(f).sheet_names[0]  # the sheet is named after the export date
        n = import_portfolio(store, f, a.nav_eur, as_of)
        m = write_universe(f, a.universe_dir or a.src / "universe")
        print(f"{f.name}: {n} holdings @ {as_of}, {m} index candidates")


if __name__ == "__main__":
    main()
