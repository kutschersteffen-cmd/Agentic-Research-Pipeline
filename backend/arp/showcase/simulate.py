"""Simulated ESG dataset for the public holdings files (spec `showcase-portfolio-data`, PR 1).

SIMULATED DATA. No figure here is a real company's real data: every value is a sector-based
estimate drawn from a SHA-256 of the company's key (never `random`), so the same holdings files
and overrides always give the same bytes. The tables below are copied from the spec and repeated
in `data/simulated/README.md`.
"""

from __future__ import annotations

import csv
import hashlib
import statistics
from collections import defaultdict
from pathlib import Path

import openpyxl

from arp.portfolio.constituent_import import COUNTRY

# A company's name, country and sector come from its first line in this order.
FILE_ORDER = ("MSCI_World", "SP500", "MSCI_Europe", "MSCI_EM", "AI_Big_Data", "EURO_STOXX_50", "DAX")
EQUITY_TYPES = {"Aktien", "Equities", "Depository Receipts", "Preferred Stock"}
# Assumed index market cap in EUR M; the dict order is the order a company's weight is looked up in.
INDEX_MARKET_CAP_EUR_M = {
    "MSCI_World": 75_000_000,
    "MSCI_EM": 8_500_000,
    "MSCI_Europe": 14_000_000,
    "SP500": 52_000_000,
    "EURO_STOXX_50": 4_800_000,
    "DAX": 1_900_000,
}
_GICS_FILES = ("MSCI_World", "SP500", "MSCI_Europe", "MSCI_EM")  # then AI_Big_Data; DAX and EURO STOXX 50 labels are never used
_BLANK = (None, "", "-")

PEER_GROUP = {
    "Energie": "Energy",
    "Material": "Materials",
    "Industrieunternehmen": "Industrials",
    "Industrials": "Industrials",
    "Versorgungsunternehmen": "Utilities",
    "Basiskonsumgüter": "Consumer Staples",
    "Nicht-Basiskonsumgüter": "Consumer Discretionary",
    "Consumer Discretionary": "Consumer Discretionary",
    "Gesundheitswesen": "Health Care",
    "Finanzen": "Financials",
    "Financials": "Financials",
    "Informationstechnologie": "Information Technology",
    "Technology": "Information Technology",
    "Kommunikationsdienste": "Communication Services",
    "Telecommunications": "Communication Services",
    "Immobilien": "Real Estate",
    "unbekannt": "Unknown",
    "unknown": "Unknown",
}

# sector: intensity S1+2 range (t/EUR M), scope 1 share of S1+2, scope 3 multiple range, green % range, EV factor, EV-to-sales
SECTOR_TABLE = {
    "Utilities": ((150, 1500), 0.95, (0.5, 2), (10, 60), 1.6, 2.8),
    "Energy": ((150, 600), 0.85, (8, 15), (0, 8), 1.25, 1.2),
    "Materials": ((150, 1200), 0.75, (1, 4), (0, 15), 1.2, 1.6),
    "Industrials": ((15, 120), 0.50, (4, 20), (3, 35), 1.15, 2.0),
    "Consumer Staples": ((15, 80), 0.50, (5, 15), (0, 5), 1.1, 2.0),
    "Consumer Discretionary": ((8, 50), 0.35, (5, 20), (0, 25), 1.1, 1.8),
    "Real Estate": ((15, 80), 0.30, (1, 3), (0, 30), 1.6, 10),
    "Communication Services": ((3, 25), 0.15, (2, 6), (0, 5), 1.1, 4),
    "Health Care": ((5, 30), 0.40, (4, 10), (0, 5), 1.1, 4),
    "Information Technology": ((3, 40), 0.25, (4, 15), (0, 15), 1.05, 6),
    "Financials": ((0.5, 8), 0.20, (3, 10), (0, 5), 1.0, 3),
    "Unknown": ((10, 100), 0.50, (2, 8), (0, 5), 1.1, 2),
}
_HIGH_EMITTERS = ("Utilities", "Energy", "Materials")

# activity: ({sector: (probability, share range when present)}, override share range)
ACTIVITIES = {
    "coal": ({"Utilities": (0.30, (0.05, 0.40)), "Energy": (0.10, (0.05, 0.60)), "Materials": (0.10, (0.01, 0.15))}, (0.10, 1.00)),
    "oil": ({"Energy": (0.80, (0.20, 0.90)), "Utilities": (0.05, (0.01, 0.10)), "Materials": (0.05, (0.01, 0.10))}, (0.30, 0.90)),
    "gas": ({"Energy": (0.70, (0.10, 0.60)), "Utilities": (0.60, (0.05, 0.50))}, (0.10, 0.50)),
    "high_intensity_power": ({"Utilities": (0.50, (0.10, 0.70))}, (0.10, 1.00)),
    "tobacco": ({}, (0.50, 1.00)),
    "weapons": ({"Industrials": (0.10, (0.05, 0.60)), "Information Technology": (0.03, (0.01, 0.10))}, (0.10, 1.00)),
    "alcohol": ({"Consumer Staples": (0.08, (0.05, 0.40))}, (0.30, 1.00)),
    "gambling": ({"Consumer Discretionary": (0.03, (0.20, 1.00))}, (0.30, 1.00)),
}
OVERRIDE_FLAGS = ("controversial_weapons", "norms_violation")  # set only by an override, never by a draw

# letter, label, cumulative percent of the peer group: position r of n gets the first grade with r <= floor(pct * n / 100)
GRADES = (("A", "Leader", 10), ("B", "Credible", 30), ("C", "Gaps", 60), ("D", "Emerging", 85), ("E", "Not credible", 95), ("F", "Disqualified", 100))
_CONTROVERSY_CUMULATIVE = (0.60, 0.80, 0.92, 0.97, 0.99)  # levels 0 to 4; the last 1 % is level 5

COLUMNS = (
    ["isin", "company_id", "name", "country", "sector", "files", "data_status"]
    + ["climate_scope1_tco2e", "climate_scope2_tco2e", "climate_scope3_tco2e", "climate_carbon_intensity"]
    + ["climate_evic_eur_m", "climate_revenue_eur_m", "climate_green_revenue_pct"]
    + ["esg_e_score", "esg_s_score", "esg_g_score", "esg_score", "esg_trend", "controversy_level"]
    + [f"{activity}_revenue_pct" for activity in ("coal", "oil", "gas", "high_intensity_power", "tobacco", "weapons", "alcohol", "gambling")]
    + ["controversial_weapons", "norms_violation", "severe_controversy"]
    + ["ghg_intensity", "green_revenue_pct", "transition_score", "lct_score", "lct_category"]
    + ["transition_grade", "transition_grade_label"]
)


def read_holdings(holdings_dir: Path) -> list[dict]:
    """The equity lines of the seven holdings files, in `FILE_ORDER` then row order."""
    lines: list[dict] = []
    for stem in FILE_ORDER:
        path = Path(holdings_dir) / f"{stem}.xlsx"
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        try:  # read-only workbooks keep the file open until closed
            rows = iter(list(wb.worksheets[0].iter_rows(min_row=4, values_only=True)))
        finally:
            wb.close()
        header = [str(c).strip() if c is not None else "" for c in next(rows)]
        missing = {"Name", "ISIN", "Country", "Type of Security", "Industry Classification", "Weighting"} - set(header)
        if missing:
            raise ValueError(f"{path.name}: header row 4 lacks column(s) {sorted(missing)}")
        for raw in rows:
            r = dict(zip(header, raw, strict=False))
            if not r["Name"] or not r["ISIN"] or r["Type of Security"] not in EQUITY_TYPES:
                continue
            country, label, weight = r["Country"], r["Industry Classification"], r["Weighting"]
            lines.append(
                {
                    "file": stem,
                    "isin": str(r["ISIN"]).strip(),
                    "name": str(r["Name"]).strip(),
                    "country": None if country in _BLANK else COUNTRY.get(str(country).strip(), str(country).strip()),
                    "label": "" if label in _BLANK else str(label).strip(),
                    "weight": weight if isinstance(weight, (int, float)) and not isinstance(weight, bool) else None,
                }
            )
    return lines


def read_overrides(path: Path) -> list[dict]:
    with Path(path).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _draw(key: str, label: str, low: float = 0.0, high: float = 1.0) -> float:
    """A reproducible number in [low, high) from SHA-256 of the company key and the value's name."""
    digest = hashlib.sha256(f"{key}|{label}".encode()).digest()
    return low + (high - low) * int.from_bytes(digest[:8], "big") / 2**64


def _companies(lines: list[dict]) -> list[list[dict]]:
    """Lines grouped by company: keys (name + country) that share an ISIN are one company.
    Companies come in the order of their first line, each with its lines in input order."""
    parent: dict[tuple, tuple] = {}

    def find(key: tuple) -> tuple:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    isin_key: dict[str, tuple] = {}
    for line in lines:
        key = (line["name"].upper(), line["country"])
        parent.setdefault(key, key)
        parent[find(key)] = find(isin_key.setdefault(line["isin"], key))
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for line in lines:
        groups[find((line["name"].upper(), line["country"]))].append(line)
    return list(groups.values())


def _peer_group(company_lines: list[dict]) -> str:
    for stem in (*_GICS_FILES, "AI_Big_Data"):
        for line in company_lines:
            if line["file"] == stem and PEER_GROUP[line["label"]] != "Unknown":
                return PEER_GROUP[line["label"]]
    return "Unknown"


def _percentiles(values: list[float]) -> list[float]:
    """(rank - 1) / (n - 1), rank by ascending value, ties take the lowest rank; 0 when n = 1."""
    n = len(values)
    return [sum(other < v for other in values) / (n - 1) if n > 1 else 0.0 for v in values]


def _override_shares(overrides: list[dict], company_of_isin: dict[str, int], names_of_isin: dict[str, set[str]]) -> dict[tuple[int, str], float]:
    shares: dict[tuple[int, str], float] = {}
    for row_no, row in enumerate(overrides, 2):
        where = f"overrides row {row_no}"
        isin, activity = (row.get("isin") or "").strip(), (row.get("activity") or "").strip()
        if isin not in company_of_isin:
            raise ValueError(f"{where}: ISIN {isin!r} is not an equity line of the holdings files")
        if row.get("name") not in names_of_isin[isin]:
            raise ValueError(f"{where}: name {row.get('name')!r} is not the name of {isin} in a holdings file")
        if not (row.get("reason") or "").strip():
            raise ValueError(f"{where}: reason is blank")
        if activity in OVERRIDE_FLAGS:
            low = high = 1.0
        elif activity in ACTIVITIES:
            low, high = ACTIVITIES[activity][1]
        else:
            raise ValueError(f"{where}: unknown activity {activity!r}")
        try:
            share = float(row.get("share") or "")
        except ValueError:
            raise ValueError(f"{where}: share {row.get('share')!r} is not a number") from None
        if not low <= share <= high:
            raise ValueError(f"{where}: share {share} for {activity} is outside {low} to {high}")
        if shares.setdefault((company_of_isin[isin], activity), share) != share:
            raise ValueError(f"{where}: a second, different {activity} share for the company of {isin}")
    return shares


def simulate(lines: list[dict], overrides: list[dict]) -> list[dict[str, str]]:
    """One row per distinct ISIN, sorted by ISIN, with the columns of `COLUMNS` as text."""
    for line in lines:
        if line["file"] not in ("EURO_STOXX_50", "DAX") and line["label"] and line["label"] not in PEER_GROUP:
            raise ValueError(f"{line['file']}.xlsx: unknown Industry Classification {line['label']!r} ({line['name']}, {line['isin']})")
    lines = [{**line, "label": line["label"] or "unknown"} for line in lines]
    companies = _companies(lines)
    company_of_isin = {line["isin"]: i for i, company in enumerate(companies) for line in company}
    names_of_isin: dict[str, set[str]] = defaultdict(set)
    for line in lines:
        names_of_isin[line["isin"]].add(line["name"])
    override = _override_shares(overrides, company_of_isin, names_of_isin)

    values: list[dict] = []
    for company in companies:
        first = company[0]
        if first["country"] is None:
            raise ValueError(f"{first['file']}.xlsx: {first['name']} ({first['isin']}) has no country")
        v: dict = {"name": first["name"], "country": first["country"], "sector": _peer_group(company), "market_cap": None}
        v["key"] = f"{first['name'].upper()}|{first['country']}"
        v["min_isin"] = min(line["isin"] for line in company)
        for stem, index_cap in INDEX_MARKET_CAP_EUR_M.items():
            weights = [line["weight"] for line in company if line["file"] == stem and line["weight"] is not None]
            if weights:
                v["market_cap"] = sum(weights) * index_cap
                break
        values.append(v)

    by_sector: dict[str, list[int]] = defaultdict(list)
    for i, v in enumerate(values):
        by_sector[v["sector"]].append(i)

    for i, v in enumerate(values):
        key, sector = v["key"], v["sector"]
        intensity, scope1_share, scope3_multiple, green, ev_factor, ev_to_sales = SECTOR_TABLE[sector]
        market_cap = v["market_cap"]
        if market_cap is None:  # no numeric index weight (AI-only, or N/A): the median of the peer group's other companies
            sized = [values[j]["market_cap"] for j in by_sector[sector] if values[j]["market_cap"] is not None]
            if not sized:
                raise ValueError(f"{v['name']}: no company in peer group {sector} has an index weight to size it from")
            market_cap = statistics.median(sized)
        evic = market_cap * ev_factor
        v["evic"] = round(evic, 2)
        v["revenue"] = round(evic / ev_to_sales, 2)
        v["intensity"] = round(intensity[0] * (intensity[1] / intensity[0]) ** _draw(key, "intensity"), 4)
        scope12 = v["intensity"] * v["revenue"]  # from the rounded values, so the file's own numbers reproduce the intensity
        v["scope1"] = round(scope12 * scope1_share, 2)
        v["scope2"] = round(scope12 - v["scope1"], 2)
        v["scope3"] = round(scope12 * _draw(key, "scope3", *scope3_multiple), 2)
        v["green"] = round(_draw(key, "green", *green), 2)
        e_mean = 4.5 if sector in _HIGH_EMITTERS else 6.0
        v["e"] = round(_draw(key, "esg_e", e_mean - 2.5, e_mean + 2.5), 2)
        v["s"] = round(_draw(key, "esg_s", 3.5, 8.5), 2)
        v["g"] = round(_draw(key, "esg_g", 3.5, 8.5), 2)
        v["esg"] = round((v["e"] + v["s"] + v["g"]) / 3, 2)
        v["trend"] = round(_draw(key, "esg_trend", 0.80, 1.20), 2)
        controversy = _draw(key, "controversy")
        v["controversy"] = sum(controversy >= bound for bound in _CONTROVERSY_CUMULATIVE)
        for activity, (by_peer_group, _override_range) in ACTIVITIES.items():
            share = 0.0
            if (i, activity) in override:
                share = override[(i, activity)]
            elif sector in by_peer_group:
                probability, share_range = by_peer_group[sector]
                if _draw(key, f"{activity}_present") < probability:
                    share = _draw(key, f"{activity}_share", *share_range)
            v[activity] = round(share, 4)
        for flag in OVERRIDE_FLAGS:
            v[flag] = (i, flag) in override

    for sector, members in by_sector.items():
        n = len(members)
        intensity_pct = _percentiles([values[i]["intensity"] for i in members])
        green_pct = _percentiles([values[i]["green"] for i in members])
        for i, p_intensity, p_green in zip(members, intensity_pct, green_pct, strict=True):
            values[i]["score"] = round(0.5 * (1 - p_intensity) + 0.3 * p_green + 0.2 * values[i]["e"] / 10, 4)
        median_intensity = statistics.median(values[i]["intensity"] for i in members)
        ranked = sorted(members, key=lambda i: (-values[i]["score"], values[i]["min_isin"]))
        for position, i in enumerate(ranked, 1):
            v = values[i]
            v["grade"], v["grade_label"] = next((g, label) for g, label, pct in GRADES if position <= pct * n // 100)
            if v["green"] >= 50:
                v["lct_category"] = "solutions"
            elif sector in _HIGH_EMITTERS:
                v["lct_category"] = "asset_stranding" if v["grade"] in "DEF" else "operational_transition"
            elif sector in ("Industrials", "Consumer Discretionary") and v["intensity"] > median_intensity:
                v["lct_category"] = "product_transition"
            else:
                v["lct_category"] = "neutral"

    files_of_isin: dict[str, list[str]] = defaultdict(list)
    for line in lines:
        if line["file"] not in files_of_isin[line["isin"]]:
            files_of_isin[line["isin"]].append(line["file"])
    rows = []
    for isin in sorted(company_of_isin):
        v = values[company_of_isin[isin]]
        row = {
            "isin": isin,
            "company_id": f"isin_{isin}",
            "name": v["name"],
            "country": v["country"],
            "sector": v["sector"],
            "files": ";".join(files_of_isin[isin]),
            "data_status": "simulated",
            "climate_scope1_tco2e": f"{v['scope1']:.2f}",
            "climate_scope2_tco2e": f"{v['scope2']:.2f}",
            "climate_scope3_tco2e": f"{v['scope3']:.2f}",
            "climate_carbon_intensity": f"{v['intensity']:.4f}",
            "climate_evic_eur_m": f"{v['evic']:.2f}",
            "climate_revenue_eur_m": f"{v['revenue']:.2f}",
            "climate_green_revenue_pct": f"{v['green']:.2f}",
            "esg_e_score": f"{v['e']:.2f}",
            "esg_s_score": f"{v['s']:.2f}",
            "esg_g_score": f"{v['g']:.2f}",
            "esg_score": f"{v['esg']:.2f}",
            "esg_trend": f"{v['trend']:.2f}",
            "controversy_level": str(v["controversy"]),
            **{f"{activity}_revenue_pct": f"{v[activity]:.4f}" for activity in ACTIVITIES},
            **{flag: str(v[flag]).lower() for flag in OVERRIDE_FLAGS},
            "severe_controversy": str(v["controversy"] == 5).lower(),
            "ghg_intensity": f"{v['intensity']:.4f}",
            "green_revenue_pct": f"{v['green'] / 100:.4f}",
            "transition_score": f"{v['score']:.4f}",
            "lct_score": f"{10 * v['score']:.2f}",
            "lct_category": v["lct_category"],
            "transition_grade": v["grade"],
            "transition_grade_label": v["grade_label"],
        }
        rows.append({column: row[column] for column in COLUMNS})
    return rows


def write_dataset(rows: list[dict[str, str]], out: Path) -> None:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
