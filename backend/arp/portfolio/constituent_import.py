"""Importer for ETF holdings files: "Constituent_<ISIN>.xlsx" (`import_constituent_files`) and any other
name (`import_holdings_file`); `import_holdings_files` sends each file the right way.

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
(`isin_<ISIN>`), so several share classes of one issuer are separate
companies. The id must pass `safe_id` (it becomes a path segment in
analytics/documents); an ISIN that cannot fails the import, naming the
file, row and ISIN. Country/sector are German or English in the files and translated below;
unknown values are kept verbatim and reported. A row without a numeric weight registers its
company and security but gets no holding. Each import records an `ok` holdings load for the
sheet date's month, once per file content.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path

import openpyxl

from arp.portfolio.loads import LoadRecord, latest_load, record_load
from arp.projects.store import ID_RE
from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import Holding, Portfolio, SecurityRef
from arp.storage.portfolio_store import PortfolioStore
from arp.storage.safe_path import UnsafeIdentifierError, safe_id

NOTIONAL_EUR = 100_000_000  # assumed fund size when none is given

ASSET_CLASS = {
    "Aktien": "equity",
    "Equities": "equity",
    "Depository Receipts": "equity",
    "Preferred Stock": "equity",
    "Cash": "cash",
    "Mutual Fund": "fund",
    "Share Class": "fund",
    "Warrants": "derivative",
    "Future": "derivative",
    "Right": "derivative",
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
    "Ägypten": "Egypt",
    "Griechenland": "Greece",
    "Indien": "India",
    "Indonesien": "Indonesia",
    "Kasachstan": "Kazakhstan",
    "Kolumbien": "Colombia",
    "Kuwait": "Kuwait",
    "Malaysia": "Malaysia",
    "Mexiko": "Mexico",
    "Peru": "Peru",
    "Philippinen": "Philippines",
    "Polen": "Poland",
    "Qatar": "Qatar",
    "Rumänien": "Romania",
    "Russland": "Russia",
    "Saudi Arabien": "Saudi Arabia",
    "Südafrika": "South Africa",
    "Tschechische Republik": "Czech Republic",
    "Türkei": "Turkey",
    "Ungarn": "Hungary",
    # English values, as the AI_Big_Data file writes them
    **{c: c for c in ("Australia", "Canada", "Germany", "Ireland", "Sweden", "United Kingdom", "United States")},
    "Korea, Republic of": "South Korea",
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
    "Grundstoffe": "Basic Materials",
    # English values, as the AI_Big_Data file writes them
    **{x: x for x in ("Consumer Discretionary", "Financials", "Industrials", "Technology", "Telecommunications")},
    "unknown": "Unknown",
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


def _read_sheet(path: Path) -> tuple[str, list[str], list[tuple]]:
    """(as-of date, header of row 4, data rows from row 5)."""
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:  # read-only workbooks keep the file open until closed
        ws = wb.worksheets[0]
        title = ws.title
        rows = list(ws.iter_rows(min_row=4, values_only=True))
    finally:
        wb.close()
    try:
        as_of = date.fromisoformat(title.strip()).isoformat()
    except ValueError:
        raise ValueError(f"{path.name}: sheet title {title!r} is not an ISO date (YYYY-MM-DD)") from None
    header = [str(c).strip() if c is not None else "" for c in rows[0]] if rows else []
    missing = {"Name", "ISIN", "Weighting"} - set(header)
    if missing:
        raise ValueError(f"{path.name}: header row 4 lacks column(s) {sorted(missing)}")
    return as_of, header, rows[1:]


def _import_rows(
    store: PortfolioStore,
    path: Path,
    sheet: tuple[str, list[str], list[tuple]],
    portfolio: Portfolio,
    notional_eur: float,
    untranslated: set[str],
    other_asset_classes: set[str],
) -> dict:
    as_of, header, rows = sheet
    portfolio_id = portfolio.portfolio_id
    store.save_portfolio(portfolio)
    holdings: list[Holding] = []
    skipped: list[dict] = []
    rows_read = 0
    for row_no, raw in enumerate(rows, 5):
        r = dict(zip(header, raw, strict=False))
        name, isin = r.get("Name"), r.get("ISIN")
        if not name or not isin:
            continue
        rows_read += 1
        isin, name = str(isin).strip(), str(name).strip()
        sec_type = r.get("Type of Security")
        if sec_type not in ASSET_CLASS:
            other_asset_classes.add("(blank)" if sec_type in _BLANK else str(sec_type))
        company_id = f"isin_{isin}"
        try:  # company ids become path segments downstream (analytics, documents)
            safe_id(company_id, label="company_id")
        except UnsafeIdentifierError:
            raise ValueError(f"{path.name} row {row_no}: ISIN {isin!r} cannot form a valid company_id {company_id!r}") from None
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
        weight = r.get("Weighting")
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            skipped.append({"name": name, "isin": isin, "weighting": weight})  # known to the app, held by nobody
            continue
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
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    last = latest_load(store, "holdings", portfolio_id, as_of[:7])
    if last is None or last.content_hash != digest:  # the monthly run needs an ok holdings load for the month
        record_load(store, LoadRecord(kind="holdings", source_id=portfolio_id, month=as_of[:7], status="ok",
                                      content_hash=digest, detail=f"constituent import {path.name}"))
    return {
        "portfolio_id": portfolio_id,
        "as_of_date": as_of,
        "rows_read": rows_read,
        "holdings_written": len(holdings),
        "skipped_no_weight": skipped,
        "weight_sum": round(sum(h.weight_pct for h in holdings) / 100, 6),
    }


def import_constituent_file(
    store: PortfolioStore,
    path: Path,
    notional_eur: float,
    untranslated: set[str],
    other_asset_classes: set[str],
    project_id: str | None = None,
) -> dict:
    m = _FILE_RE.search(path.name)
    if not m:
        raise ValueError(f"{path.name}: expected a file name like Constituent_<ISIN>.xlsx")
    fund_isin = m.group(1).upper()
    sheet = _read_sheet(path)
    tags = ["source:constituents", f"sizing:assumed-notional-eur-{notional_eur:.15g}", f"fund_isin:{fund_isin}"]
    if project_id is None:
        portfolio_id = f"portfolio_{fund_isin.lower()}"
    else:
        portfolio_id = f"{project_id}-portfolio-{fund_isin.lower()}"
        tags.append(f"project:{project_id}")
    portfolio = Portfolio(portfolio_id=portfolio_id, name=f"Portfolio {fund_isin}", tags=tags)
    return _import_rows(store, path, sheet, portfolio, notional_eur, untranslated, other_asset_classes)


def import_holdings_file(
    store: PortfolioStore,
    path: Path,
    portfolio_id: str,
    name: str,
    notional_eur: float = NOTIONAL_EUR,
    fund_isin: str | None = None,
    project_id: str | None = None,
    *,
    untranslated: set[str] | None = None,
    other_asset_classes: set[str] | None = None,
) -> dict:
    """A holdings file of any name, as the portfolio id and name given. `project_id` only adds the tag."""
    sheet = _read_sheet(path)
    tags = [f"source:{path.name}", f"sizing:assumed-notional-eur-{notional_eur:.15g}"]
    if fund_isin:
        tags.append(f"fund_isin:{fund_isin}")
    if project_id is not None:
        tags.append(f"project:{project_id}")
    old = store.get_portfolio(portfolio_id)  # a re-import must not unlabel simulated history (arp showcase load)
    tags += [t for t in (old.tags if old else []) if t.startswith("history:")]
    portfolio = Portfolio(portfolio_id=portfolio_id, name=name, tags=tags)
    return _import_rows(
        store, path, sheet, portfolio, notional_eur,
        set() if untranslated is None else untranslated, set() if other_asset_classes is None else other_asset_classes,
    )


def _check_project_id(project_id: str | None) -> None:
    if project_id is None:
        return
    try:
        safe_id(project_id, label="project_id")
    except UnsafeIdentifierError as exc:
        raise ValueError(str(exc)) from None
    if not ID_RE.fullmatch(project_id):
        raise ValueError(f"project_id {project_id!r} must match {ID_RE.pattern}")


def import_constituent_files(
    store: PortfolioStore, paths: list[Path], notional_eur: float, project_id: str | None = None
) -> dict:
    _check_project_id(project_id)
    untranslated: set[str] = set()
    other: set[str] = set()
    portfolios = [import_constituent_file(store, p, notional_eur, untranslated, other, project_id) for p in paths]
    return {
        "notional_eur": notional_eur,
        "portfolios": portfolios,
        "untranslated": sorted(untranslated),
        "other_asset_classes": sorted(other),
    }


def import_holdings_files(
    store: PortfolioStore,
    paths: list[Path],
    notional_eur: float = NOTIONAL_EUR,
    fund_isin: str | None = None,
    project_id: str | None = None,
) -> dict:
    """`Constituent_<ISIN>.xlsx` files the old way; any other file as `portfolio_<stem>`, named after the file
    and its sheet date. `fund_isin` tags a file whose name carries no ISIN, so it takes one file only."""
    if fund_isin and len(paths) != 1:
        raise ValueError(f"--fund-isin names one fund, so it takes one file only; got {len(paths)} files")
    _check_project_id(project_id)
    untranslated: set[str] = set()
    other: set[str] = set()
    portfolios = []
    for path in paths:
        if _FILE_RE.search(path.name):
            portfolios.append(import_constituent_file(store, path, notional_eur, untranslated, other, project_id))
            continue
        stem = re.sub(r"[^a-z0-9]", "_", path.stem.lower())
        portfolio_id = f"portfolio_{stem}" if project_id is None else f"{project_id}-portfolio-{stem}"
        name = f"{path.stem.replace('_', ' ')} (public ETF holdings, {_read_sheet(path)[0]})"
        portfolios.append(
            import_holdings_file(store, path, portfolio_id, name, notional_eur, fund_isin, project_id,
                                 untranslated=untranslated, other_asset_classes=other)
        )
    return {
        "notional_eur": notional_eur,
        "portfolios": portfolios,
        "untranslated": sorted(untranslated),
        "other_asset_classes": sorted(other),
    }
