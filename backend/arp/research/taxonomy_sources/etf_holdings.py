from __future__ import annotations

import csv
import re
from pathlib import Path

from arp.schemas.common import CompanyRef
from arp.schemas.taxonomy_sources import HoldingRow

# Column names accepted per field, in priority order -- fund providers'
# holdings exports aren't standardized, so a few common variants are
# checked rather than requiring one exact header set.
_NAME_COLUMNS = ("name", "company", "holding", "security")
_TICKER_COLUMNS = ("ticker", "symbol")
_SECTOR_COLUMNS = ("sector", "industry", "gics_sector", "sub_industry")
_DESCRIPTION_COLUMNS = ("description", "business_description", "notes")
_WEIGHT_COLUMNS = ("weight", "weight (%)", "weighting", "% of net assets", "portfolio weight")


def _first_present(row: dict, columns: tuple[str, ...]) -> str | None:
    for col in columns:
        for key in row:
            if key.strip().lower() == col:
                value = row[key].strip()
                if value:
                    return value
    return None


_ID_COLUMNS = ("isin", "sedol", "lei", "cik")
_THOUSANDS = re.compile(r"^-?\d{1,3}(,\d{3})+(\.\d+)?%?$")
_CASH_WORDS = ("CASH", "CURRENCY", "POUND", "EURO", "DOLLAR", "YEN", "FRANC", "PAYABLE", "RECEIVABLE", "FUTURE", "SWAP")


def _parse_weight(raw: str | None) -> float | None:
    if not raw:
        return None
    raw = raw.strip()
    # a comma is a thousands separator only in "31,526.89" shape; otherwise it is a decimal comma ("16,20")
    raw = raw.replace(",", "") if _THOUSANDS.match(raw) else raw.replace(",", ".")
    try:
        return float(raw.rstrip("%"))
    except ValueError:
        return None


def _parse_holdings_rows(path: Path) -> list[dict]:
    """Shared CSV parsing for any fund/index holdings export -- every
    other function in this module is a projection of these normalized
    rows, so there's exactly one place that has to know about column-name
    variants across fund providers. Provider files may have preamble lines
    before the header, cash/currency lines and a trailing disclaimer.
    """
    with path.open(newline="", encoding="utf-8-sig") as f:
        all_rows = list(csv.reader(f))
    header_idx = next(
        (i for i, r in enumerate(all_rows) if {c.strip().lower() for c in r} & set(_NAME_COLUMNS + _TICKER_COLUMNS)), None
    )
    if header_idx is None:
        return []
    header = all_rows[header_idx]
    keys = {h.strip().lower() for h in header}
    has_ticker_col = bool(keys & set(_TICKER_COLUMNS))
    weight_col = next((h for c in _WEIGHT_COLUMNS for h in header if h.strip().lower() == c), None)
    rows: list[dict] = []
    raw_weights: list[str | None] = []
    for cells in all_rows[header_idx + 1 :]:
        if len(cells) < len(header):
            continue
        raw_row = dict(zip(header, cells, strict=False))
        name = _first_present(raw_row, _NAME_COLUMNS)
        ticker = _first_present(raw_row, _TICKER_COLUMNS)
        if not (name or ticker):
            continue
        if not ticker and (name or "").lower() in ("total", "totals"):
            continue
        # name-only exports have no ticker to tell cash lines apart, so real companies like "Dollar General" stay
        if not ticker and has_ticker_col and any(w in (name or "").upper() for w in _CASH_WORDS):
            continue
        rows.append(
            {
                "ticker": ticker,
                "name": name,
                "sector": _first_present(raw_row, _SECTOR_COLUMNS),
                "description": _first_present(raw_row, _DESCRIPTION_COLUMNS),
                **{c: _first_present(raw_row, (c,)) for c in _ID_COLUMNS},
            }
        )
        raw_weights.append((raw_row[weight_col].strip() or None) if weight_col else None)
    values = [_parse_weight(w) for w in raw_weights]
    is_percent = "%" in (weight_col or "") or any("%" in w for w in raw_weights if w) or any(v is not None and v > 1 for v in values)
    for row, v in zip(rows, values, strict=True):
        row["weight"] = v / 100 if (is_percent and v is not None) else v
    return rows


def load_universe_from_holdings(path: Path) -> list[CompanyRef]:
    """Projects a holdings export into a company universe -- the Universe
    Builder's path for constructing a universe from an index/sector fund's
    constituents instead of a hand-written list, reusing the exact same
    CSV parsing as the ETF-holdings taxonomy derivation method.
    """
    companies: list[CompanyRef] = []
    seen_ids: set[str] = set()
    for row in _parse_holdings_rows(path):
        company_id = row["ticker"] or row["name"]
        if not company_id or company_id in seen_ids:
            continue
        seen_ids.add(company_id)
        companies.append(CompanyRef(company_id=company_id, name=row["name"] or company_id, ticker=row["ticker"], sector=row["sector"]))
    return companies


def load_holdings_with_weights(path: Path) -> list[HoldingRow]:
    """Projects a holdings export into weighted rows for overlap
    computation (arp/research/taxonomy_sources/overlap.py)."""
    holdings: list[HoldingRow] = []
    for row in _parse_holdings_rows(path):
        ticker = row["ticker"] or row["name"]
        if not ticker:
            continue
        holdings.append(HoldingRow(
                ticker=ticker, name=row["name"], weight=row["weight"], sector=row["sector"], **{c: row[c] for c in _ID_COLUMNS}
            ))
    return holdings
