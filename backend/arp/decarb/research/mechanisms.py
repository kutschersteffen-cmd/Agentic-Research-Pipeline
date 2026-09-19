"""Sector x region as three measurable mechanisms rather than a dummy.

See docs/SECTOR_REGION_MECHANISMS.md.

Every design in the review conditions on sector x region. That is correct for
identification and costly in three ways: it absorbs the mechanism instead of
measuring it, it cannot extrapolate to a cell never observed, and a cell-by-year
effect also removes the average firm response to a common shock.

The alternative is to measure what the cell stands for. Abatement happens where
three forces clear together, and they are complements rather than substitutes:

    regulation   effective carbon rate faced, net of free allocation,
                 times the share of the firm's emissions covered
    technology   cost of the cheapest scaled abatement option for the
                 sector's dominant process, $/tCO2e
    demand       observed green premium times the share of revenue in
                 products that can carry it

Electricity cleared all three first - priced by ETS from the start, solar and
wind on 20-24% learning curves, and no demand channel needed because electrons
are fungible. Cement clears none. That is why Ruiz Manuel & Blok find 86% of
member abatement in eight electricity and heavy-industry firms.

Two things here. `variance_decomposition` tells you whether you are studying a
problem where cells dominate or one where firms do. `mechanism_sufficiency`
tests whether measured mechanisms can replace the dummies: add the mechanisms,
then add the cell dummies on top, and if the dummies still carry explanatory
power the mechanism measures are incomplete.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

__all__ = [
    "MECHANISM_SOURCES",
    "VarianceDecomposition",
    "SufficiencyResult",
    "variance_decomposition",
    "mechanism_sufficiency",
    "cell_summary",
]

# Where each mechanism variable can actually be sourced. Recorded here because
# the hardest part of this approach is assembly, not estimation.
MECHANISM_SOURCES: dict[str, dict[str, str]] = {
    "regulation": {
        "construct": "effective carbon rate net of free allocation x share of emissions covered",
        "sources": "OECD Carbon Pricing and Energy Taxation Database; ETS registries; World Bank Carbon Pricing Dashboard",
        "granularity": "sector x country x year",
        "caution": (
            "A binary 'covered by an ETS' flag is too coarse. Colmer et al. find EU ETS "
            "Phase I effects indistinguishable from zero and Phase II effects large, so "
            "stringency is the variable, not coverage."
        ),
    },
    "technology": {
        "construct": "cost of the cheapest scaled abatement option for the dominant process, $/tCO2e",
        "sources": "sector MACC literature; IEA Energy Technology Perspectives",
        "granularity": "sector x year, occasionally sector x region",
        "caution": (
            "Mass-manufactured technologies ride learning curves (solar PV ~24%, battery "
            "packs ~20% per doubling); capital-intensive process plant does not. Do not "
            "extrapolate one to the other."
        ),
    },
    "demand": {
        "construct": "observed green premium x share of revenue in products that can carry it",
        "sources": "commodity price assessments; disclosed offtake agreements; public procurement rules",
        "granularity": "product x region x year",
        "caution": (
            "Varies by region for the same product: European green steel premiums of "
            "EUR120-180/t against a Chinese willingness to pay capped near $20/t on a "
            "~$140/t cost gap. Premium quotes are market commentary and move fast."
        ),
    },
}


@dataclass(slots=True)
class VarianceDecomposition:
    """Nested R-squared, plus the between/within-cell split of firm means."""

    nested: dict[str, float]
    between_cell_share: float
    within_cell_share: float
    n_cells: int
    n_firms: int
    median_firms_per_cell: float

    def verdict(self, *, cell_dominant_threshold: float = 0.40) -> str:
        if self.between_cell_share >= cell_dominant_threshold:
            return (
                f"Cells dominate: {self.between_cell_share:.0%} of firm-level variance is "
                f"between cells across {self.n_cells} cells. Most apparent firm-level "
                "predictive power will be cell membership. Condition hard, and prefer "
                "measured mechanisms to dummies so the cell effect stays interpretable."
            )
        return (
            f"Firms dominate: {self.within_cell_share:.0%} of firm-level variance is within "
            f"cells. There is room for a firm-level indicator to matter, but it must be "
            "evaluated within cell, not pooled."
        )


def variance_decomposition(
    frame: pd.DataFrame,
    *,
    outcome: str = "g_scope12",
    sector: str = "sector",
    region: str = "region",
    year: str = "year",
    firm: str = "firm_id",
) -> VarianceDecomposition:
    """How much of the outcome is cell, and how much is firm.

    Run this before choosing a specification. It tells you whether a firm-level
    indicator has anything to explain once the cell is accounted for, which
    determines the ceiling on everything downstream.
    """
    import statsmodels.formula.api as smf

    work = frame.dropna(subset=[outcome, sector, region]).copy()
    if work.empty:
        raise ValueError("no complete cases")
    work["__cell"] = work[sector].astype(str) + "_" + work[region].astype(str)

    def r2(formula: str) -> float:
        return float(smf.ols(formula, data=work).fit().rsquared)

    nested = {
        "year": r2(f"{outcome} ~ C({year})"),
        "+ sector": r2(f"{outcome} ~ C({year}) + C({sector})"),
        "+ region": r2(f"{outcome} ~ C({year}) + C({sector}) + C({region})"),
        "+ sector x region": r2(f"{outcome} ~ C({year}) + C(__cell)"),
        "+ firm": r2(f"{outcome} ~ C({year}) + C({firm})"),
    }

    firm_mean = work.groupby([firm, "__cell"])[outcome].mean().reset_index()
    total_var = float(firm_mean[outcome].var(ddof=1))
    if total_var <= 0:
        raise ValueError("no variation in firm means")
    between = float(firm_mean.groupby("__cell")[outcome].transform("mean").var(ddof=1))
    within = float(
        firm_mean.groupby("__cell")[outcome].transform(lambda s: s - s.mean()).var(ddof=1)
    )

    return VarianceDecomposition(
        nested=nested,
        between_cell_share=between / total_var,
        within_cell_share=within / total_var,
        n_cells=int(firm_mean["__cell"].nunique()),
        n_firms=int(firm_mean[firm].nunique()),
        median_firms_per_cell=float(firm_mean.groupby("__cell").size().median()),
    )


@dataclass(slots=True)
class SufficiencyResult:
    """Do measured mechanisms make the cell dummies redundant?"""

    r2_mechanisms: float
    r2_mechanisms_plus_cells: float
    r2_cells_only: float
    f_statistic: float
    p_value: float
    n_cells: int
    nobs: int
    warnings: list[str] = field(default_factory=list)

    @property
    def incremental_r2(self) -> float:
        """What the dummies add on top of the mechanisms."""
        return self.r2_mechanisms_plus_cells - self.r2_mechanisms

    def verdict(self, *, alpha: float = 0.05) -> str:
        if any("cell-invariant" in w for w in self.warnings):
            return (
                "Test is degenerate: at least one mechanism variable has no within-cell "
                "variation, so it is a relabelling of the dummy rather than a measurement. "
                "See the warnings."
            )
        if self.p_value < alpha:
            return (
                f"Mechanisms are incomplete. Cell dummies add {self.incremental_r2:+.3f} R2 "
                f"on top (F = {self.f_statistic:.1f}, p = {self.p_value:.3g}), so something "
                "the cell captures is not in the three measures. Keep the dummies and treat "
                "the mechanisms as partial."
            )
        return (
            f"Mechanisms are sufficient on this panel. Cell dummies add only "
            f"{self.incremental_r2:+.3f} R2 (p = {self.p_value:.3g}), so three interpretable "
            f"variables can replace {self.n_cells} dummies without losing fit."
        )


def mechanism_sufficiency(
    frame: pd.DataFrame,
    *,
    outcome: str = "g_scope12",
    mechanisms: list[str] | None = None,
    sector: str = "sector",
    region: str = "region",
    year: str = "year",
    firm: str = "firm_id",
) -> SufficiencyResult:
    """Test whether cell dummies still matter once mechanisms are measured.

    Nested F-test of the cell dummies against a model already containing the
    mechanism variables. A rejection means the mechanisms are missing something
    the cell knows, which is useful either way: it is a diagnostic on the
    mechanism measures, not a verdict on the approach.
    """
    import statsmodels.formula.api as smf
    from statsmodels.stats.anova import anova_lm

    mechanisms = mechanisms or ["regulation", "technology", "demand"]
    missing = [m for m in mechanisms if m not in frame.columns]
    if missing:
        raise ValueError(
            f"mechanism columns not in frame: {missing}. "
            f"See MECHANISM_SOURCES for how each is constructed."
        )

    work = frame.dropna(subset=[outcome, *mechanisms, sector, region]).copy()
    work["__cell"] = work[sector].astype(str) + "_" + work[region].astype(str)
    if work["__cell"].nunique() < 3:
        raise ValueError("need at least 3 cells to test dummy redundancy")

    # Mechanism variables must vary within cell, or they are a
    # reparameterisation of the dummy and the nested test is degenerate.
    # Real mechanisms do vary: carbon prices rise, abatement costs fall,
    # premiums move. A cell-constant mechanism means the variable was built
    # from a lookup keyed on sector and region rather than measured over time.
    degenerate = [
        m for m in mechanisms
        if work.groupby("__cell")[m].nunique(dropna=False).max() <= 1
    ]

    mech_terms = " + ".join(mechanisms)
    small = smf.ols(f"{outcome} ~ {mech_terms} + C({year})", data=work).fit()
    large = smf.ols(f"{outcome} ~ {mech_terms} + C({year}) + C(__cell)", data=work).fit()
    cells_only = smf.ols(f"{outcome} ~ C({year}) + C(__cell)", data=work).fit()

    table = anova_lm(small, large)
    f_stat = float(table["F"].iloc[-1])
    p_val = float(table["Pr(>F)"].iloc[-1])

    warnings: list[str] = []
    if degenerate:
        warnings.append(
            f"cell-invariant mechanism variables: {', '.join(degenerate)}. These carry no "
            "within-cell variation, so they cannot be distinguished from the dummies and "
            "this test cannot reject. Build them as measured time series at "
            "sector x region x year, not as a lookup table."
        )
    if work["__cell"].nunique() > work.shape[0] / 20:
        warnings.append(
            f"{work['__cell'].nunique()} cells for {work.shape[0]} observations; the dummy "
            "model is close to saturated and the test has little power."
        )

    return SufficiencyResult(
        r2_mechanisms=float(small.rsquared),
        r2_mechanisms_plus_cells=float(large.rsquared),
        r2_cells_only=float(cells_only.rsquared),
        f_statistic=f_stat,
        p_value=p_val,
        n_cells=int(work["__cell"].nunique()),
        nobs=int(large.nobs),
        warnings=warnings,
    )


def cell_summary(
    frame: pd.DataFrame,
    *,
    outcome: str = "g_scope12",
    sector: str = "sector",
    region: str = "region",
    min_firms: int = 5,
) -> pd.DataFrame:
    """Per-cell mean outcome, dispersion and firm count.

    Cells below `min_firms` are flagged rather than dropped: a thin cell is not
    evidence of anything, and silently removing it changes the population the
    study describes.
    """
    work = frame.dropna(subset=[outcome, sector, region]).copy()
    work["__cell"] = work[sector].astype(str) + "_" + work[region].astype(str)
    grouped = work.groupby(["__cell", sector, region]).agg(
        mean_outcome=(outcome, "mean"),
        sd_outcome=(outcome, "std"),
        n_obs=(outcome, "size"),
    ).reset_index()
    firms = work.groupby("__cell")["firm_id"].nunique() if "firm_id" in work.columns else None
    if firms is not None:
        grouped["n_firms"] = grouped["__cell"].map(firms)
        grouped["thin"] = grouped["n_firms"] < min_firms
    return grouped.sort_values("mean_outcome").reset_index(drop=True)
