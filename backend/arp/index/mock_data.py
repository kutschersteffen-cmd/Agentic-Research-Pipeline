"""A deterministic demo universe, so the engine and the UI are usable
without a licensed data feed.

Every figure is derived from a SHA-256 of the company id, not from
`random` -- so the dataset is byte-identical on every machine and every
run, which is the same property the index engine itself must have. It is
illustrative only: no figure here is a real company's real data.
"""

from __future__ import annotations

import hashlib

from arp.schemas.index import IndexCandidate

SECTORS = [
    "Energy",
    "Materials",
    "Industrials",
    "Utilities",
    "Information Technology",
    "Health Care",
    "Consumer Discretionary",
    "Financials",
]
COUNTRIES = ["DE", "FR", "NL", "US", "JP", "GB", "CH", "ES"]
LCT_CATEGORIES = ["solutions", "neutral", "operational_transition", "product_transition", "asset_stranding"]

# Sector-typical GHG intensity (tCO2e per EUR m revenue), so the demo
# behaves like a real universe: the decarbonisation trajectory has to trade
# off against sector exposure rather than picking free lunches.
SECTOR_INTENSITY = {
    "Energy": 900.0,
    "Materials": 700.0,
    "Utilities": 800.0,
    "Industrials": 180.0,
    "Consumer Discretionary": 90.0,
    "Information Technology": 30.0,
    "Health Care": 40.0,
    "Financials": 15.0,
}


def _draws(company_id: str, count: int = 12) -> list[float]:
    """`count` reproducible pseudo-random numbers in [0, 1) from the id."""
    digest = hashlib.sha256(company_id.encode()).digest()
    while len(digest) < count * 2:
        digest += hashlib.sha256(digest).digest()
    return [int.from_bytes(digest[i * 2 : i * 2 + 2], "big") / 65536.0 for i in range(count)]


def demo_universe(size: int = 60) -> list[IndexCandidate]:
    candidates: list[IndexCandidate] = []
    for i in range(size):
        company_id = f"demo{i:03d}"
        d = _draws(company_id)
        sector = SECTORS[i % len(SECTORS)]
        country = COUNTRIES[int(d[0] * len(COUNTRIES)) % len(COUNTRIES)]
        base_intensity = SECTOR_INTENSITY[sector]
        intensity = round(base_intensity * (0.35 + 1.3 * d[1]), 2)
        fossil_sector = sector in ("Energy", "Utilities", "Materials")
        candidates.append(
            IndexCandidate(
                company_id=company_id,
                name=f"Demo {sector.split()[0]} {i:03d}",
                sector=sector,
                country=country,
                currency="EUR",
                price=round(10.0 + 190.0 * d[2], 2),
                fx_rate=1.0,
                shares_outstanding=round(2_000_000 + 400_000_000 * d[3]),
                free_float_factor=round(0.35 + 0.6 * d[4], 4),
                metrics={
                    "esg_score": round(1.0 + 9.0 * d[5], 3),
                    "esg_trend": round(0.6 + 0.8 * d[6], 3),
                    "ghg_intensity": intensity,
                    "lct_score": round(10.0 * (1.0 - d[1]) * (0.6 + 0.4 * d[7]), 3),
                    "relevance": round(d[7] ** 1.5, 4),
                    "adv_3m": round(200_000 + 40_000_000 * d[8]),
                    "coal_revenue_pct": round(0.30 * d[9], 4) if fossil_sector else 0.0,
                    "oil_revenue_pct": round(0.60 * d[9], 4) if sector == "Energy" else 0.0,
                    "gas_revenue_pct": round(0.70 * d[10], 4) if sector in ("Energy", "Utilities") else 0.0,
                    "high_intensity_power_revenue_pct": round(0.90 * d[10], 4) if sector == "Utilities" else 0.0,
                    "tobacco_revenue_pct": 0.0,
                    "green_revenue_pct": round(d[11] ** 2, 4),
                },
                flags={
                    "norms_violation": d[9] > 0.94,
                    "controversial_weapons": d[10] > 0.97,
                    "severe_controversy": d[8] > 0.93,
                },
                categories={
                    "lct_category": LCT_CATEGORIES[min(int(d[1] * 5), 4)],
                    "iss_prime": "prime" if d[5] > 0.55 else "not_prime",
                },
            )
        )
    return candidates


def demo_price_panel(candidates: list[IndexCandidate], dates: list[str]) -> dict[str, dict[str, float]]:
    """A reproducible price path per company across `dates`, for the index
    level series. Drift and volatility come from the same id-derived draws,
    so the whole demo remains byte-identical run to run."""
    panel: dict[str, dict[str, float]] = {}
    for step, as_of in enumerate(sorted(dates)):
        prices: dict[str, float] = {}
        for candidate in candidates:
            d = _draws(candidate.company_id)
            drift = (d[2] - 0.45) * 0.02
            wobble = (_draws(f"{candidate.company_id}:{as_of}")[0] - 0.5) * 0.06
            prices[candidate.company_id] = round(candidate.price * (1.0 + drift) ** step * (1.0 + wobble), 4)
        panel[as_of] = prices
    return panel


def demo_returns_panel(candidates: list[IndexCandidate], periods: int = 260) -> dict[str, dict[str, float]]:
    """A reproducible daily return panel with genuine factor structure.

    A price path built from independent wobbles produces a near-diagonal
    covariance, against which a tracking-error budget never binds and so
    proves nothing. This panel instead layers a market factor, a sector
    factor and an idiosyncratic term -- so names in the same sector
    co-move, excluding a sector costs real active risk, and the budget
    behaves the way it would on real data.

    Every draw comes from a SHA-256 of the company id and period, so the
    panel is byte-identical on every machine, exactly like the universe.
    """
    sectors = sorted({c.sector or "unclassified" for c in candidates})
    panel: dict[str, dict[str, float]] = {}
    for step in range(periods):
        as_of = f"p{step:04d}"
        market = (_draws(f"market:{step}")[0] - 0.5) * 0.02
        sector_shocks = {s: (_draws(f"sector:{s}:{step}")[0] - 0.5) * 0.02 for s in sectors}
        row: dict[str, float] = {}
        for candidate in candidates:
            d = _draws(f"{candidate.company_id}:ret:{step}")
            beta = 0.6 + 1.0 * _draws(candidate.company_id)[3]
            idiosyncratic = (d[0] - 0.5) * 0.03
            row[candidate.company_id] = round(
                beta * market + 0.7 * sector_shocks[candidate.sector or "unclassified"] + idiosyncratic, 8
            )
        panel[as_of] = row
    return panel


def demo_risk_model(candidates: list[IndexCandidate] | None = None, spec=None):
    """A risk model estimated from the demo returns panel.

    Lets the tracking-error objectives be exercised before any returns feed
    or vendor factor model exists. It is illustrative only -- the panel is
    synthetic, so the covariance describes nothing real.
    """
    from arp.index.risk import build_risk_model
    from arp.schemas.index import RiskModelSpec

    universe = candidates if candidates is not None else demo_universe()
    return build_risk_model(spec or RiskModelSpec(source="ledoit_wolf"), universe, demo_returns_panel(universe, 260))
