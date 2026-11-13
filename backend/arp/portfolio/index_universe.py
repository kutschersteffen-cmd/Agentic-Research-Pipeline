"""Starting universes for Index Construction: a holdings file in `holdings_dir` or a stored portfolio.

The files and snapshots carry weights only, so every size here is a labelled ASSUMPTION: price 1 and
shares = weight x EUR 100,000,000. Simulated ESG fields (`simulated_esg_path`, when present) join by
company id. Everything is read on each call, so a changed file shows on the next request.
"""

from __future__ import annotations

import csv
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import openpyxl

from arp.portfolio.constituent_import import ASSET_CLASS, COUNTRY, SECTOR, _translate
from arp.schemas.index import IndexCandidate
from arp.storage.safe_path import UnsafeIdentifierError, safe_id

NOTIONAL_EUR = 100_000_000

# Exactly the columns of showcase-portfolio-data's "Fields for Index Construction" table.
ESG_METRICS = (
    "esg_score", "esg_trend", "ghg_intensity", "lct_score", "coal_revenue_pct", "oil_revenue_pct",
    "gas_revenue_pct", "high_intensity_power_revenue_pct", "tobacco_revenue_pct", "green_revenue_pct",
    "weapons_revenue_pct", "alcohol_revenue_pct", "gambling_revenue_pct", "esg_e_score", "esg_s_score",
    "esg_g_score", "controversy_level", "transition_score",
)  # fmt: skip
ESG_FLAGS = ("norms_violation", "controversial_weapons", "severe_controversy")
ESG_CATEGORIES = ("lct_category", "transition_grade")

_BUCKETS = ("cash", "other asset class", "zero or negative weight", "without a weight", "not linked to a company")


class UnknownUniverse(LookupError):
    def __init__(self, universe_id: str) -> None:
        super().__init__(f"Unknown starting universe: {universe_id}")


@dataclass
class LoadedUniverse:
    universe_id: str
    label: str
    kind: str
    as_of_date: str
    candidates: list[IndexCandidate]
    notes: list[str] = field(default_factory=list)


def _holdings_files(holdings_dir: Path) -> dict[str, Path]:
    """Only `*.xlsx` directly in the directory: any other stem is unknown, so no path traversal."""
    if not holdings_dir.is_dir():
        return {}
    return {p.stem: p for p in sorted(holdings_dir.glob("*.xlsx"), key=lambda p: p.stem) if p.is_file()}


def _read_sheet(path: Path) -> tuple[str, list[tuple]]:
    """(as-of date, rows from header row 4 on), with the importer's layout errors."""
    try:
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        try:  # read-only workbooks keep the file open until closed
            ws = wb.worksheets[0]
            title = ws.title
            rows = list(ws.iter_rows(min_row=4, values_only=True))
        finally:
            wb.close()
    except Exception:  # not a zip, not a workbook, an Excel lock file (~$DAX.xlsx): a 422, not a 500
        raise ValueError(f"{path.name}: not a readable .xlsx file") from None
    try:
        as_of = date.fromisoformat(title.strip()).isoformat()
    except ValueError:
        raise ValueError(f"{path.name}: sheet title {title!r} is not an ISO date (YYYY-MM-DD)") from None
    return as_of, rows


def _sheet_date(path: Path) -> str | None:
    try:
        wb = openpyxl.load_workbook(path, read_only=True)
        try:
            title = wb.worksheets[0].title
        finally:
            wb.close()
        return date.fromisoformat(title.strip()).isoformat()
    except Exception:  # a broken file is still listed; loading it names the problem
        return None


def _candidate(company_id: str, name: str, weight: float, sector: str | None, country: str | None) -> IndexCandidate:
    return IndexCandidate(
        company_id=company_id,
        name=name,
        sector=sector,
        country=country,
        currency="EUR",
        price=1.0,
        fx_rate=1.0,
        free_float_factor=1.0,
        shares_outstanding=weight * NOTIONAL_EUR,
    )


def _bucket(asset_class: str | None, weight: float) -> str | None:
    if asset_class == "cash":
        return "cash"
    if asset_class != "equity":
        return "other asset class"
    if weight <= 0:
        return "zero or negative weight"
    return None


def _is_number(value) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _from_file(universe_id: str, path: Path) -> LoadedUniverse:
    as_of, rows = _read_sheet(path)
    header = [str(c).strip() if c is not None else "" for c in rows[0]] if rows else []
    missing = {"Name", "ISIN", "Type of Security", "Weighting"} - set(header)
    if missing:
        raise ValueError(f"{path.name}: header row 4 lacks column(s) {sorted(missing)}")
    dropped = dict.fromkeys(_BUCKETS, 0)
    merged: dict[str, dict] = {}
    unused: set[str] = set()
    for raw in rows[1:]:
        r = dict(zip(header, raw, strict=False))
        name, isin = r.get("Name"), r.get("ISIN")
        if not name or not isin:
            continue
        weight = r.get("Weighting")
        if not _is_number(weight):
            dropped["without a weight"] += 1
            continue
        bucket = _bucket(ASSET_CLASS.get(r.get("Type of Security")), weight)
        if bucket:
            dropped[bucket] += 1
            continue
        company_id = f"isin_{str(isin).strip()}"
        try:  # the importer's rule: company ids become path segments downstream
            safe_id(company_id, label="company_id")
        except UnsafeIdentifierError:
            raise ValueError(f"{path.name}: ISIN {isin!r} cannot form a valid company_id {company_id!r}") from None
        if company_id in merged:  # the same ISIN listed twice is one company
            merged[company_id]["weight"] += weight
            continue
        merged[company_id] = {
            "name": str(name).strip(),
            "weight": weight,
            "sector": _translate(r.get("Industry Classification"), SECTOR, unused),
            "country": _translate(r.get("Country"), COUNTRY, unused),
        }
    candidates = [_candidate(cid, v["name"], v["weight"], v["sector"], v["country"]) for cid, v in merged.items()]
    return _finish(universe_id, path.name, "file", as_of, candidates, dropped)


def _from_portfolio(universe_id: str, portfolio_id: str, store) -> LoadedUniverse:
    portfolio = store.get_portfolio(portfolio_id)
    as_of = store.latest_snapshot_date(portfolio_id) if portfolio else None
    if portfolio is None or as_of is None:
        raise UnknownUniverse(universe_id)
    securities = {s.security_id: s for s in store.list_securities()}  # one query, not one per holding
    dropped = dict.fromkeys(_BUCKETS, 0)
    merged: dict[str, dict] = {}
    for holding in store.load_snapshot(portfolio_id, as_of):
        security = securities.get(holding.security_id)
        if security is None or not security.company_id:
            dropped["not linked to a company"] += 1
            continue
        if holding.weight_pct is None:
            dropped["without a weight"] += 1
            continue
        bucket = _bucket(security.asset_class, holding.weight_pct)
        if bucket:
            dropped[bucket] += 1
            continue
        entry = merged.setdefault(security.company_id, {"name": security.name, "weight": 0.0})
        entry["weight"] += holding.weight_pct / 100
    companies = {c.company_id: c for c in store.list_companies()} if merged else {}
    candidates = []
    for company_id, v in merged.items():
        company = companies.get(company_id)
        if company is None:
            candidates.append(_candidate(company_id, v["name"], v["weight"], None, None))
        else:
            candidates.append(_candidate(company_id, company.name, v["weight"], company.sector, company.country))
    return _finish(universe_id, portfolio.name, "portfolio", as_of, candidates, dropped)


def _finish(universe_id: str, label: str, kind: str, as_of: str, candidates: list[IndexCandidate], dropped: dict) -> LoadedUniverse:
    if not candidates:
        raise ValueError(f"{label}: no equity lines with a positive weight.")
    notes = [
        f"Starting universe: {label}, holdings as of {as_of}, {len(candidates)} companies.",
        f"Dropped {sum(dropped.values())} lines: " + ", ".join(f"{n} {bucket}" for bucket, n in dropped.items()) + ".",
        f"Size is a weight proxy: each company's free-float market cap is its weight × an assumed EUR "
        f"{NOTIONAL_EUR:,}, at price 1. It is not market data.",
    ]
    return LoadedUniverse(universe_id, label, kind, as_of, candidates, notes)


def _join_esg(universe: LoadedUniverse, dataset: Path) -> LoadedUniverse:
    if not dataset.is_file():
        universe.notes.append("Simulated ESG data: not available; loaded companies carry no ESG fields.")
        return universe
    with dataset.open(newline="", encoding="utf-8") as fh:
        rows = {row["company_id"]: row for row in csv.DictReader(fh) if row.get("company_id")}
    joined = []
    for c in universe.candidates:
        row = rows.get(c.company_id)
        if row is None:  # no row, no defaults
            joined.append(c)
            continue
        cell = {k: (row.get(k) or "").strip() for k in (*ESG_METRICS, *ESG_FLAGS, *ESG_CATEGORIES, "sector", "country")}
        joined.append(
            c.model_copy(
                update={
                    "metrics": _metrics(cell, c.company_id, dataset.name),
                    "flags": {k: cell[k].lower() == "true" for k in ESG_FLAGS if cell[k].lower() in ("true", "false")},
                    "categories": {k: cell[k] for k in ESG_CATEGORIES if cell[k]},
                    "sector": cell["sector"] or c.sector,
                    "country": cell["country"] or c.country,
                }
            )
        )
    matched = sum(1 for c in universe.candidates if c.company_id in rows)
    universe.candidates = joined
    universe.notes.append(f"Simulated ESG data: matched {matched} of {len(joined)} companies.")
    return universe


def _metrics(cell: dict[str, str], company_id: str, file_name: str) -> dict[str, float]:
    """Empty and NaN cells are not joined, so a rule on them meets its missing-value policy."""
    out = {}
    for k in ESG_METRICS:
        if not cell[k]:
            continue
        try:
            value = float(cell[k])
        except ValueError:
            raise ValueError(f"{file_name}: {k} of {company_id} is not a number: {cell[k]!r}") from None
        if not math.isnan(value):
            out[k] = value
    return out


def load_universe(universe_id: str, holdings_dir: Path, dataset: Path, portfolio_store: Callable[[], object]) -> LoadedUniverse:
    """A `file:<stem>` or `portfolio:<id>` universe. Raises UnknownUniverse for any other id, and
    ValueError (the importer's layout wording, or no candidates) for a file or portfolio it cannot use."""
    kind, _, ref = universe_id.partition(":")
    path = _holdings_files(holdings_dir).get(ref) if kind == "file" else None
    if path is not None:
        universe = _from_file(universe_id, path)
    elif kind == "portfolio" and ref:
        universe = _from_portfolio(universe_id, ref, portfolio_store())
    else:
        raise UnknownUniverse(universe_id)
    return _join_esg(universe, dataset)


def list_universes(holdings_dir: Path, portfolio_store: Callable[[], object]) -> list[dict]:
    """Files sorted by stem, then portfolios with at least one snapshot sorted by name."""
    entries = [
        {"universe_id": f"file:{stem}", "label": path.name, "kind": "file", "as_of_date": _sheet_date(path)}
        for stem, path in _holdings_files(holdings_dir).items()
    ]
    store = portfolio_store()
    portfolios = []
    for p in store.list_portfolios():
        as_of = store.latest_snapshot_date(p.portfolio_id)
        if as_of:
            portfolios.append({"universe_id": f"portfolio:{p.portfolio_id}", "label": p.name, "kind": "portfolio", "as_of_date": as_of})
    return entries + sorted(portfolios, key=lambda e: e["label"])
