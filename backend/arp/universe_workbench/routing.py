from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from arp.schemas.common import CompanyRef
from arp.schemas.issuer import normalise_lei
from arp.universe_workbench.mapping import MasterIndex, enrich, map_company

Market = Literal["sec", "esef"]

# alpha-2 -> (alpha-3, English names)
_COUNTRIES: dict[str, tuple[str, tuple[str, ...]]] = {
    "US": ("USA", ("United States", "United States of America", "USA")),
    "GB": ("GBR", ("United Kingdom", "Great Britain", "UK")),
    "AT": ("AUT", ("Austria",)), "BE": ("BEL", ("Belgium",)), "BG": ("BGR", ("Bulgaria",)),
    "HR": ("HRV", ("Croatia",)), "CY": ("CYP", ("Cyprus",)), "CZ": ("CZE", ("Czechia", "Czech Republic")),
    "DK": ("DNK", ("Denmark",)), "EE": ("EST", ("Estonia",)), "FI": ("FIN", ("Finland",)),
    "FR": ("FRA", ("France",)), "DE": ("DEU", ("Germany",)), "GR": ("GRC", ("Greece",)),
    "HU": ("HUN", ("Hungary",)), "IE": ("IRL", ("Ireland",)), "IT": ("ITA", ("Italy",)),
    "LV": ("LVA", ("Latvia",)), "LT": ("LTU", ("Lithuania",)), "LU": ("LUX", ("Luxembourg",)),
    "MT": ("MLT", ("Malta",)), "NL": ("NLD", ("Netherlands", "The Netherlands")), "PL": ("POL", ("Poland",)),
    "PT": ("PRT", ("Portugal",)), "RO": ("ROU", ("Romania",)), "SK": ("SVK", ("Slovakia",)),
    "SI": ("SVN", ("Slovenia",)), "ES": ("ESP", ("Spain",)), "SE": ("SWE", ("Sweden",)),
    "IS": ("ISL", ("Iceland",)), "LI": ("LIE", ("Liechtenstein",)), "NO": ("NOR", ("Norway",)),
}
_MARKET: dict[str, Market] = {a2: "sec" if a2 == "US" else "esef" for a2 in _COUNTRIES}
_BY_NAME: dict[str, str] = {}
for _a2, (_a3, _names) in _COUNTRIES.items():
    for _k in (_a2, _a3, *_names):
        _BY_NAME[_k.upper()] = _a2

_UNROUTED = "no country or identifier: add an ISIN, LEI or CIK, or load it into the security master"


@dataclass(frozen=True)
class Route:
    market: Market | None
    status: Literal["routed", "no_source", "unrouted"]
    basis: str | None
    detail: str
    company: CompanyRef


def country_market(value: str | None) -> Market | None:
    a2 = _BY_NAME.get(" ".join((value or "").split()).upper())
    return _MARKET[a2] if a2 else None


def _rules(c: CompanyRef, *, final: bool = True) -> tuple[Market | None, str, str | None, str] | None:
    """Rules 1 to 3: (market, status, basis, detail), or None when none decides."""
    if m := country_market(c.country):
        return m, "routed", "country", f"country {c.country}"
    isin = "".join((c.isin or "").split()).upper()
    prefix = isin[:2]
    if len(prefix) == 2 and prefix.isalpha() and prefix not in ("XS", "EU"):
        if prefix in _MARKET:
            return _MARKET[prefix], "routed", "isin_prefix", f"ISIN prefix {prefix}"
        if final:
            return None, "no_source", "isin_prefix", f"no XBRL source for {prefix} yet"
    if "".join(ch for ch in (c.cik or "") if ch.isdigit()):
        return "sec", "routed", "cik", "CIK present"
    if normalise_lei(c.lei or ""):
        return "esef", "routed", "lei", "LEI present, no CIK"
    return None


def route_company(company: CompanyRef, index: MasterIndex | None = None) -> Route:
    note = ""
    if (company.country or "").strip() and country_market(company.country) is None:
        note = f"; country '{company.country}' not recognised"

    def done(r, c, basis=None):
        market, status, b, detail = r
        return Route(market, status, basis or b, detail + note, c)

    first = _rules(company)
    if first and first[1] == "routed":
        return done(first, company)
    # a no_source ISIN prefix is only final if the master cannot route the issuer
    enriched = enrich(company, map_company(company, index))
    r = _rules(enriched, final=False)  # master CIK/LEI may route past an unlisted prefix
    if r and r[1] == "routed":
        return done(r, enriched, "master")
    if first:
        return done(first, enriched)
    if (enriched.ticker or "").strip():
        return Route("sec", "routed", "ticker_fallback", "ticker only, assumed SEC" + note, enriched)
    return Route(None, "unrouted", None, _UNROUTED + note, enriched)


def route_universe(companies: list[CompanyRef], index: MasterIndex | None = None) -> list[Route]:
    return [route_company(c, index) for c in companies]
