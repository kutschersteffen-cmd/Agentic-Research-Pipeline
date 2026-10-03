"""Importer for DWS "Constituent_<ISIN>.xlsx" ETF holdings files.

The files carry WEIGHTS ONLY: a fraction of fund NAV per line, with no
quantity, price or FX rate. Everything monetary here is therefore an
ASSUMPTION: each fund is sized at a caller-supplied notional in EUR, and
`market_value_eur = weight * notional_eur`. `quantity` is set to that EUR
amount with `price = 1.0` and `fx_rate_to_eur = 1.0` purely so the Holding
invariants hold; none of those three is real market data. Weights are not
renormalised (a file may sum to ~1.006); negative weights (cash, futures)
keep their sign.

Layout: sheet title = ISO as-of date; row 4 = header; data from row 5.
Issuer resolution is not performed: one CompanyRef per security
(`isin:<ISIN>`), so several share classes of one issuer are separate
companies. Country/sector are German in the files and translated below;
unknown values are kept verbatim and reported.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import openpyxl

from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import Holding, Portfolio, SecurityRef
from arp.storage.portfolio_store import PortfolioStore

ASSET_CLASS = {
    "Aktien": "equity",
    "Depository Receipts": "equity",
    "Cash": "cash",
    "Mutual Fund": "fund",
    "Warrants": "derivative",
    "Future": "derivative",
}

COUNTRY = {
    "Australien": "Australia",
    "Belgien": "Belgium",
    "Bermudas": "Bermuda",
    "Brasilien": "Brazil",
    "Chile": "Chile",
    "China": "China",
    "Deutschland": "Germany",
    "Dänemark": "Denmark",
    "Finnland": "Finland",
    "Frankreich": "France",
    "Färöer Inseln": "Faroe Islands",
    "Georgien": "Georgia",
    "Großbritannien (UK)": "United Kingdom",
    "Guernsey": "Guernsey",
    "Hong Kong": "Hong Kong",
    "Irland": "Ireland",
    "Isle of Man": "Isle of Man",
    "Israel": "Israel",
    "Italien": "Italy",
    "Japan": "Japan",
    "Jersey": "Jersey",
    "Jordanien": "Jordan",
    "Kaiman Inseln": "Cayman Islands",
    "Kanada": "Canada",
    "Liechtenstein": "Liechtenstein",
    "Litauen": "Lithuania",
    "Luxemburg": "Luxembourg",
    "Macao": "Macao",
    "Neuseeland": "New Zealand",
    "Niederlande": "Netherlands",
    "Norwegen": "Norway",
    "Portugal": "Portugal",
    "Sambia": "Zambia",
    "Schweden": "Sweden",
    "Schweiz": "Switzerland",
    "Singapur": "Singapore",
    "Spanien": "Spain",
    "Süd Korea": "South Korea",
    "Taiwan": "Taiwan",
    "Thailand": "Thailand",
    "Vereinigte Arabische Emirate": "United Arab Emirates",
    "Vereinigte Staaten von Amerika": "United States",
    "Zypern": "Cyprus",
    "Österreich": "Austria",
}

# The files mix two classification schemes (GICS-like and a legacy one); both are kept as given.
SECTOR = {
    "Basiskonsumgüter": "Consumer Staples",
    "Energie": "Energy",
    "Finanzdienstleister": "Financial Services",
    "Finanzen": "Financials",
    "Gesundheitswesen": "Health Care",
    "Immobilien": "Real Estate",
    "Industrieunternehmen": "Industrials",
    "Informationstechnologie": "Information Technology",
    "Kommunikationsdienste": "Communication Services",
    "Material": "Materials",
    "Nicht-Basiskonsumgüter": "Consumer Discretionary",
    "Technologie": "Technology",
    "Telekommunikation": "Telecommunications",
    "Verbrauchsgüter": "Consumer Goods",
    "Versorgungsunternehmen": "Utilities",
    "unbekannt": "Unknown",
}

_FILE_RE = re.compile(r"Constituent_([A-Z0-9]{12})\.xlsx$", re.IGNORECASE)
_BLANK = {None, "", "-"}


def _translate(value, table: dict[str, str], untranslated: set[str]) -> str | None:
    if value in _BLANK:
        return None
    value = str(value).strip()
    if value not in table:
        untranslated.add(value)
    return table.get(value, value)


def import_constituent_file(
    store: PortfolioStore, path: Path, notional_eur: float, untranslated: set[str], other_asset_classes: set[str]
) -> dict:
    m = _FILE_RE.search(path.name)
    if not m:
        raise ValueError(f"{path.name}: expected a file name like Constituent_<ISIN>.xlsx")
    fund_isin = m.group(1).upper()
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:  # read-only workbooks keep the file open until closed
        ws = wb.worksheets[0]
        title = ws.title
        rows = iter(list(ws.iter_rows(min_row=4, values_only=True)))
    finally:
        wb.close()
    try:
        as_of = date.fromisoformat(title.strip()).isoformat()
    except ValueError:
        raise ValueError(f"{path.name}: sheet title {title!r} is not an ISO date (YYYY-MM-DD)") from None

    header = [str(c).strip() if c is not None else "" for c in next(rows)]
    missing = {"Name", "ISIN", "Weighting"} - set(header)
    if missing:
        raise ValueError(f"{path.name}: header row 4 lacks column(s) {sorted(missing)}")

    portfolio_id = f"dws_{fund_isin.lower()}"
    store.save_portfolio(
        Portfolio(
            portfolio_id=portfolio_id,
            name=f"DWS ETF {fund_isin}",
            tags=["source:dws-constituents", f"sizing:assumed-notional-eur-{notional_eur:.15g}", f"fund_isin:{fund_isin}"],
        )
    )
    holdings: list[Holding] = []
    skipped: list[dict] = []
    rows_read = 0
    for raw in rows:
        r = dict(zip(header, raw, strict=False))
        name, isin = r.get("Name"), r.get("ISIN")
        if not name or not isin:
            continue
        rows_read += 1
        isin, name = str(isin).strip(), str(name).strip()
        weight = r.get("Weighting")
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            skipped.append({"name": name, "isin": isin, "weighting": weight})
            continue
        sec_type = r.get("Type of Security")
        if sec_type not in ASSET_CLASS:
            other_asset_classes.add("(blank)" if sec_type in _BLANK else str(sec_type))
        company_id = f"isin:{isin}"
        store.save_company(
            CompanyRef(
                company_id=company_id,
                name=name,
                country=_translate(r.get("Country"), COUNTRY, untranslated),
                sector=_translate(r.get("Industry Classification"), SECTOR, untranslated),
            )
        )
        store.save_security(
            SecurityRef(
                security_id=isin,
                isin=isin,
                name=name,
                asset_class=ASSET_CLASS.get(sec_type, "other"),
                currency=str(r.get("Currency") or "EUR").strip(),
                company_id=company_id,
            )
        )
        mv = weight * notional_eur
        holdings.append(
            Holding(
                portfolio_id=portfolio_id,
                security_id=isin,
                as_of_date=as_of,
                quantity=mv,
                price=1.0,
                market_value=mv,
                fx_rate_to_eur=1.0,
                market_value_eur=mv,
                weight_pct=weight * 100,
            )
        )
    store.save_snapshot(portfolio_id, as_of, holdings)
    return {
        "portfolio_id": portfolio_id,
        "as_of_date": as_of,
        "rows_read": rows_read,
        "holdings_written": len(holdings),
        "skipped_no_weight": skipped,
        "weight_sum": round(sum(h.weight_pct for h in holdings) / 100, 6),
    }


def import_constituent_files(store: PortfolioStore, paths: list[Path], notional_eur: float) -> dict:
    untranslated: set[str] = set()
    other: set[str] = set()
    portfolios = [import_constituent_file(store, p, notional_eur, untranslated, other) for p in paths]
    return {
        "notional_eur": notional_eur,
        "portfolios": portfolios,
        "untranslated": sorted(untranslated),
        "other_asset_classes": sorted(other),
    }
