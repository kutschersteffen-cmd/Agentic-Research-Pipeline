"""The location-based against market-based Scope 2 wedge.

Section 2.3 of the review argues that the clearest single diagnostic for
whether measured progress is physical or procedural is the gap between the
two Scope 2 accounting methods for firms that report both.

Reference points from the literature, used by `wedge_summary` for context:
  - LSEG (2026): among FTSE All-World constituents dual-reporting 2020-2024,
    Technology location-based Scope 2 rose 60% against 22% market-based.
  - Schüder & Zülch (2026): SBTi effect significant for market-based Scope 2
    at t+2 and t+3, not significant for location-based.
  - Ruiz Manuel & Blok (2023): 71% of renewable energy purchased by the
    initiative members studied used low-additionality sourcing models.

A large positive wedge (location growing faster than market) means reported
progress is coming from procurement while grid-physical emissions rise.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from arp.decarb.labels import annualised_change
from arp.decarb.schemas import Panel

__all__ = ["Scope2Wedge", "dual_reporters", "wedge_summary", "wedge_by_group"]


@dataclass(slots=True)
class Scope2Wedge:
    """Divergence between the two Scope 2 bases over a window."""

    n_firms: int
    location_change_pct: float
    market_change_pct: float

    @property
    def wedge_pct(self) -> float:
        """Location-based growth minus market-based growth.

        Positive means the market-based series understates the change in
        physical grid emissions.
        """
        return self.location_change_pct - self.market_change_pct

    @property
    def procurement_share(self) -> float:
        """Fraction of the location-based change offset in the market series.

        Only meaningful when the location series rose; returns nan otherwise,
        because the ratio has no clean interpretation when both fall.
        """
        if self.location_change_pct <= 0:
            return float("nan")
        return 1.0 - (self.market_change_pct / self.location_change_pct)


def dual_reporters(panel: Panel, start_year: int, end_year: int) -> list[str]:
    """Firms reporting both Scope 2 bases in both years.

    The dual-reporting subset is itself selected: firms that publish both
    numbers are more likely to be sophisticated reporters. Any conclusion
    drawn from the wedge inherits that selection, and callers should say so.
    """
    start, end = panel.by_year(start_year), panel.by_year(end_year)
    out = []
    for firm_id in sorted(set(start) & set(end)):
        a, b = start[firm_id], end[firm_id]
        if None in (a.scope2_location, a.scope2_market, b.scope2_location, b.scope2_market):
            continue
        if min(a.scope2_location, a.scope2_market, b.scope2_location, b.scope2_market) <= 0:
            continue
        out.append(firm_id)
    return out


def wedge_summary(panel: Panel, start_year: int, end_year: int) -> Scope2Wedge:
    """Aggregate wedge across dual reporters over the window."""
    firms = dual_reporters(panel, start_year, end_year)
    start, end = panel.by_year(start_year), panel.by_year(end_year)
    if not firms:
        return Scope2Wedge(0, float("nan"), float("nan"))
    loc0 = math.fsum(start[f].scope2_location for f in firms)
    loc1 = math.fsum(end[f].scope2_location for f in firms)
    mkt0 = math.fsum(start[f].scope2_market for f in firms)
    mkt1 = math.fsum(end[f].scope2_market for f in firms)
    return Scope2Wedge(
        n_firms=len(firms),
        location_change_pct=(loc1 / loc0 - 1.0) if loc0 > 0 else float("nan"),
        market_change_pct=(mkt1 / mkt0 - 1.0) if mkt0 > 0 else float("nan"),
    )


def wedge_by_group(panel: Panel, start_year: int, end_year: int, *, key: str = "sector") -> dict[str, Scope2Wedge]:
    """Wedge computed separately per sector or region.

    Sector is the default because the wedge is concentrated: LSEG find it in
    Technology, where electricity demand growth from data centres is running
    ahead of clean procurement.
    """
    if key not in {"sector", "region"}:
        raise ValueError("key must be 'sector' or 'region'")
    groups = sorted({getattr(r, key) for r in panel.rows if getattr(r, key) is not None})
    out: dict[str, Scope2Wedge] = {}
    for g in groups:
        sub = panel.filter(lambda r, g=g: getattr(r, key) == g)
        summary = wedge_summary(sub, start_year, end_year)
        if summary.n_firms:
            out[g] = summary
    return out


def annualised_wedge(panel: Panel, start_year: int, end_year: int) -> tuple[float, float]:
    """Annualised location and market growth rates across dual reporters."""
    w = wedge_summary(panel, start_year, end_year)
    span = end_year - start_year
    if not w.n_firms or span <= 0:
        return (float("nan"), float("nan"))
    return (
        annualised_change(1.0, 1.0 + w.location_change_pct, span),
        annualised_change(1.0, 1.0 + w.market_change_pct, span),
    )
