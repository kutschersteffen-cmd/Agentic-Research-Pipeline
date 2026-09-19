"""A synthetic firm-year panel calibrated to published magnitudes.

Nothing in `arp.decarb` requires licensed data to run. This generator builds
a panel whose headline statistics match the figures the review quotes, so the
analyses can be exercised, tested and demonstrated end to end.

Calibration targets:
  - Median annual Scope 1+2 change between 0% and -1%, with emissions still
    rising for roughly half of firms (LSEG 2026).
  - Wide dispersion: top quartile cutting >=7%/yr, bottom quartile growing
    >=8%/yr in the most recent year (LSEG 2026).
  - Technology location-based Scope 2 rising far faster than market-based,
    with the other sectors showing a narrower wedge (LSEG 2026).
  - Red-flag prevalences matching Brown, Hsu & Manya (2026), and flags drawn
    close to independently so the orthogonality result reproduces.
  - Governance indicators that saturate over time, so the Dietz & Hastreiter
    divergence between raw counts and rarity-weighted scores appears.

This is simulated data. It exists to prove the code runs and to make the
tests deterministic. No result produced from it is evidence about firms.
"""

from __future__ import annotations

import random

from arp.decarb.schemas import EmissionsBasis, FirmYear, Panel, RED_FLAGS, Scope2Basis

__all__ = ["make_panel", "GOVERNANCE_INDICATORS", "SECTORS", "REGIONS"]

SECTORS = ["Technology", "Utilities", "Industrials", "Consumer", "Financials", "Materials"]
REGIONS = ["North America", "Developed Europe", "Developed Asia", "Emerging"]

# Ordered from most to least commonly adopted, which is what produces the
# saturation gradient the analysis is designed to detect.
GOVERNANCE_INDICATORS = [
    "board_oversight",          # near-universal by the end of the window
    "discloses_scope12",
    "has_climate_target",
    "exec_pay_linked",
    "internal_carbon_price",
    "capex_aligned_plan",       # rare, demanding
    "scope3_supplier_program",  # rare, demanding
]

_BASE_ADOPTION = {
    "board_oversight": 0.55,
    "discloses_scope12": 0.50,
    "has_climate_target": 0.30,
    "exec_pay_linked": 0.18,
    "internal_carbon_price": 0.10,
    "capex_aligned_plan": 0.05,
    "scope3_supplier_program": 0.03,
}

# Annual adoption growth. The common indicators saturate; the demanding ones
# stay scarce, which is precisely why they keep discriminating.
_ADOPTION_GROWTH = {
    "board_oversight": 0.075,
    "discloses_scope12": 0.070,
    "has_climate_target": 0.075,
    "exec_pay_linked": 0.040,
    "internal_carbon_price": 0.022,
    "capex_aligned_plan": 0.012,
    "scope3_supplier_program": 0.008,
}

_DEMANDING = {"capex_aligned_plan", "scope3_supplier_program"}

_SECTOR_INTENSITY = {
    "Utilities": 1600.0,
    "Materials": 640.0,
    "Industrials": 150.0,
    "Consumer": 46.0,
    "Technology": 26.0,
    "Financials": 15.0,
}


def _drift(rng: random.Random, sector: str, has_demanding_practice: bool, ets_exposed: bool) -> float:
    """Firm-specific annual emissions drift.

    The generative story deliberately mirrors the review's conclusions so the
    analyses have something true to find: regulatory exposure and demanding
    management practice shift the drift, while the common governance
    indicators do not.

    Effect sizes are set larger than the literature's point estimates
    (-4.5pp/yr for demanding practice against Dietz & Hastreiter's noisy and
    imprecisely estimated effects) so that the mechanism is visible at the
    sample sizes used in tests and demos. Cross-firm dispersion is kept
    realistic, matching LSEG's reported quartiles, which means the effect is
    still not reliably recoverable from any single simulated panel. That is
    the honest situation in the real data too.
    """
    base = rng.gauss(0.005, 0.070)
    if has_demanding_practice:
        base -= 0.045
    if ets_exposed:
        base -= 0.028
    if sector == "Technology":
        base += 0.045
    if sector == "Utilities":
        base -= 0.022
    return base


def make_panel(
    *,
    n_firms: int = 400,
    start_year: int = 2010,
    end_year: int = 2024,
    seed: int = 20260919,
    scope2_basis: Scope2Basis = Scope2Basis.LOCATION,
) -> Panel:
    """Build a calibrated synthetic panel.

    `scope2_basis` sets which series populates `scope2`. Both bases are always
    populated on the row so the wedge analysis can run regardless.
    """
    rng = random.Random(seed)
    years = list(range(start_year, end_year + 1))
    rows: list[FirmYear] = []

    for i in range(n_firms):
        firm_id = f"F{i:04d}"
        sector = rng.choices(SECTORS, weights=[28, 6, 16, 20, 18, 12])[0]
        region = rng.choices(REGIONS, weights=[40, 22, 18, 20])[0]

        ets_exposed = region == "Developed Europe" and sector in {"Utilities", "Materials", "Industrials"}
        demanding_propensity = rng.random()

        revenue = rng.lognormvariate(8.4, 1.05)
        intensity = _SECTOR_INTENSITY[sector] * rng.lognormvariate(0.0, 0.55)
        scope1 = revenue * intensity / 1000.0 * 0.86
        scope2_loc = revenue * intensity / 1000.0 * 0.14
        scope2_mkt = scope2_loc * rng.uniform(0.80, 1.0)

        # Latent drivers so that metrics within a family agree and across
        # families do not, reproducing Fliegel's (2026) correlation structure.
        green_latent = rng.betavariate(1.4, 6.0)
        score_latent = rng.uniform(0, 100)

        # Index membership window. Real benchmarks turn over, and the gap
        # between the aggregate and chained series is exactly that turnover.
        enters = start_year if rng.random() > 0.18 else rng.randint(start_year + 1, end_year)
        exits = end_year if rng.random() > 0.15 else rng.randint(enters, end_year - 1) if enters < end_year else end_year

        # Long-term net zero adoption year, with selection into treatment.
        # Firms with a demanding-practice propensity adopt earlier, which is
        # exactly the selection Dietz & Hastreiter (2026) document. Adoption
        # has NO causal effect on emissions in this generator: any apparent
        # effect in a naive comparison is selection, and a correctly
        # specified DiD should recover approximately zero.
        adoption_pressure = demanding_propensity + rng.gauss(0.0, 0.25)
        if adoption_pressure > 0.45:
            offset = int(max(0.0, 9.0 - 7.0 * adoption_pressure + rng.gauss(0, 1.4)))
            ltnz_year = min(end_year, start_year + 6 + offset)
        else:
            ltnz_year = None

        drift = _drift(rng, sector, demanding_propensity > 0.80, ets_exposed)
        # Vendor-estimated firms are a minority and skew smaller.
        basis = EmissionsBasis.ESTIMATED if rng.random() < 0.22 else EmissionsBasis.REPORTED

        # Procurement offsets a growing share of the market-based series,
        # fastest in Technology. This is the wedge.
        procurement = 0.030 if sector == "Technology" else 0.012

        for t, year in enumerate(years):
            shock = rng.gauss(0.0, 0.035)
            if year == 2020:
                shock -= 0.055  # pandemic contraction
            g = drift + shock
            if t > 0:
                scope1 *= 1.0 + g
                scope2_loc *= 1.0 + g + (0.030 if sector == "Technology" else 0.0)
                scope2_mkt *= 1.0 + g + (0.030 if sector == "Technology" else 0.0) - procurement
                revenue *= 1.0 + rng.gauss(0.045, 0.06)

            adoption_year = t
            # Only the two demanding practices are tied to the firm's drift.
            # The common indicators diffuse independently of behaviour, which
            # is what makes a raw count lose discriminatory power as they
            # saturate while a rarity-weighted score keeps it.
            indicators = {}
            for ind in GOVERNANCE_INDICATORS:
                p_adopt = _BASE_ADOPTION[ind] + _ADOPTION_GROWTH[ind] * adoption_year
                if ind in _DEMANDING and demanding_propensity > 0.80:
                    p_adopt += 0.45
                indicators[ind] = rng.random() < min(0.985, p_adopt)

            flags = {flag: rng.random() < p for flag, p in RED_FLAGS.items()}

            if year < enters or year > exits:
                continue

            rows.append(
                FirmYear(
                    firm_id=firm_id,
                    year=year,
                    scope1=max(scope1, 1e-6),
                    scope2=max(scope2_loc if scope2_basis is Scope2Basis.LOCATION else scope2_mkt, 1e-6),
                    scope2_basis=scope2_basis,
                    scope2_location=max(scope2_loc, 1e-6),
                    scope2_market=max(scope2_mkt, 1e-6),
                    revenue=max(revenue, 1e-6),
                    evic=max(revenue * rng.uniform(1.2, 3.5), 1e-6),
                    basis=basis,
                    sector=sector,
                    region=region,
                    weight=None,
                    ltnz_adoption_year=ltnz_year,
                    indicators=indicators,
                    red_flags=flags,
                    metrics={
                        "emission_intensity": -(scope1 + scope2_loc) / max(revenue, 1e-9),
                        "emission_intensity_scope3": -(scope1 + scope2_loc) / max(revenue, 1e-9)
                        * rng.lognormvariate(0.0, 0.45),
                        "taxonomy_capex": max(0.0, green_latent + rng.gauss(0, 0.06)),
                        "taxonomy_revenue": max(0.0, green_latent + rng.gauss(0, 0.08)),
                        "e_score_refinitiv": max(0.0, min(100.0, score_latent + rng.gauss(0, 12))),
                        "e_score_msci": max(0.0, min(100.0, score_latent + rng.gauss(0, 14))),
                        "text_based": rng.gauss(0, 1),
                    },
                )
            )

    return Panel(rows)
