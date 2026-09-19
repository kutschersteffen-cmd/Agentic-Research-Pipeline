"""Replication package for Silvia et al. (2026).

*Do credible climate transition plans matter for carbon performance? Evidence
from Fortune Global 500 firms.* Frontiers in Environmental Science 14:1907357.

**What this is.** A complete, executable implementation of their instrument and
their specifications, with a harness that verifies the estimator recovers their
published coefficients when given data carrying their published correlation
structure.

**What this is not.** Their empirical result. Reproducing that needs the CTPCI
coded by hand from 1,126 firm-year reports plus emissions, financial, governance
and ownership data, none of which is reachable here. `verify_against_published`
tests the *estimator*, not the finding.

Two departures from the paper are forced and are flagged wherever they matter.

Their Appendix A holds the item-level coding checklist and is not in the
published PDF, which ends at the publisher's note; it is separately hosted
supplementary material. `data/ctpci_items.json` therefore carries their 24 item
*labels*, taken verbatim from their Table 2, with coding rules written here.
The instrument's content is theirs; the decision rules are a reconstruction and
a different coder would score some items differently.

Their Appendix B holds the country-year regulatory coding scheme and is likewise
unavailable, so `RegulatoryEnvironment` is supplied by the caller.

Specification, from their Methods:

    CarbonChange_{i,t+1} = (CO2e_{i,t+1} - CO2e_{i,t}) / Revenue_{i,t}

    CTPCI_{i,t} = disclosed items / total applicable items

    Model 1  CarbonChange_{i,t+1} ~ CTPCI_it + Controls + firm FE + year FE
    Model 2  + Assurance + CTPCI x Assurance
    Model 3  + Regulatory + CTPCI x Regulatory

Controls: Size (ln total assets), ROA (net income / total assets), Growth
(annual revenue growth), Leverage (total liabilities / total assets), BoardSize,
BoardIndependence, CEODuality, SOE, Big4. All continuous variables winsorised at
the 1st and 99th percentiles. Standard errors clustered at the firm level.

Published targets (their Table 5): CTPCI -0.066*** (0.019), -0.052** (0.021),
-0.057*** (0.020) across Models 1-3, and (Table 4) a raw correlation between
CTPCI and CarbonChange of -0.183***.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

__all__ = [
    "monte_carlo_check",
    "CTPCIItem",
    "DIMENSIONS",
    "PUBLISHED",
    "load_items",
    "score_ctpci",
    "carbon_change",
    "winsorise_frame",
    "estimate",
    "SilviaResult",
    "simulate_panel",
    "verify_against_published",
]

_ITEMS_PATH = Path(__file__).parent / "data" / "ctpci_items.json"

# Item counts per dimension, from their Table 2. Used to validate the
# instrument and to build the equal-weight robustness variant.
DIMENSIONS: dict[str, int] = {
    "target_credibility": 5,
    "emissions_scope_coverage": 3,
    "implementation_strategy": 5,
    "governance_accountability": 4,
    "risk_strategic_integration": 4,
    "progress_reporting": 3,
}

# Published results this package targets.
PUBLISHED = {
    "n_firms": 239,
    "n_obs": 1126,
    "period": (2018, 2023),
    "ctpci_model1": (-0.066, 0.019),
    "ctpci_model2": (-0.052, 0.021),
    "ctpci_model3": (-0.057, 0.020),
    "corr_ctpci_carbonchange": -0.183,
    "corr_ctpci_assurance": 0.273,
    "corr_ctpci_regulatory": 0.428,
    "corr_carbonchange_assurance": -0.152,
    "corr_carbonchange_regulatory": -0.153,
}


@dataclass(frozen=True, slots=True)
class CTPCIItem:
    item_id: str
    dimension: str
    label: str
    question: str
    coding_rule: str


@lru_cache
def load_items(path: Path | None = None) -> list[CTPCIItem]:
    """The 24 CTPCI items.

    Labels and dimension assignments are Silvia et al.'s, verbatim from their
    Table 2. The `question` and `coding_rule` fields are written here because
    their Appendix A checklist is not in the published PDF.
    """
    rows = json.loads((path or _ITEMS_PATH).read_text())
    items = [CTPCIItem(**r) for r in rows]
    counts: dict[str, int] = {}
    for it in items:
        counts[it.dimension] = counts.get(it.dimension, 0) + 1
    if counts != DIMENSIONS:
        raise ValueError(f"instrument does not match the published dimension counts: {counts}")
    return items


def score_ctpci(
    coded: dict[str, bool | None],
    *,
    equal_dimension_weight: bool = False,
) -> float:
    """CTPCI for one firm-year from coded items.

    `coded` maps item_id to True (disclosed), False (not disclosed) or None
    (not applicable). Their formula divides by *applicable* items, so None
    reduces the denominator rather than counting against the firm.

    `equal_dimension_weight` gives their robustness variant, in which each of
    the six dimensions carries equal weight so that item-rich dimensions do not
    dominate. External assurance is deliberately excluded from the index in
    both variants and enters the models as a moderator.
    """
    items = load_items()
    known = {i.item_id for i in items}
    unknown = set(coded) - known
    if unknown:
        raise ValueError(f"unknown CTPCI item ids: {sorted(unknown)}")

    if not equal_dimension_weight:
        applicable = [v for v in coded.values() if v is not None]
        if not applicable:
            return float("nan")
        return sum(1 for v in applicable if v) / len(applicable)

    by_dim = {d: [] for d in DIMENSIONS}
    for it in items:
        v = coded.get(it.item_id)
        if v is not None:
            by_dim[it.dimension].append(bool(v))
    scored = [sum(vals) / len(vals) for vals in by_dim.values() if vals]
    if not scored:
        return float("nan")
    return float(np.mean(scored))


def carbon_change(frame: pd.DataFrame, *, firm: str = "firm_id", year: str = "year") -> pd.Series:
    """Their dependent variable, aligned to the *base* year t.

        CarbonChange_{i,t+1} = (CO2e_{i,t+1} - CO2e_{i,t}) / Revenue_{i,t}

    Requires columns `co2e` (Scope 1 + 2) and `revenue`. The result is indexed
    on year t, so it lines up with CTPCI_it and the controls without a further
    shift. Scaling by *lagged* revenue is theirs and matters: it keeps the
    denominator predetermined, so a revenue shock in t+1 cannot mechanically
    move the outcome.
    """
    out = frame.sort_values([firm, year]).copy()
    lead_co2e = out.groupby(firm)["co2e"].shift(-1)
    lead_year = out.groupby(firm)[year].shift(-1)
    consecutive = (lead_year - out[year]) == 1
    change = (lead_co2e - out["co2e"]) / out["revenue"].replace(0, np.nan)
    return change.where(consecutive)


def winsorise_frame(frame: pd.DataFrame, columns: list[str], *, limits: tuple[float, float] = (0.01, 0.99)) -> pd.DataFrame:
    """Winsorise continuous variables at the 1st and 99th percentiles, as they do."""
    out = frame.copy()
    for col in columns:
        if col not in out.columns:
            continue
        s = out[col].astype(float)
        lo, hi = s.quantile(limits[0]), s.quantile(limits[1])
        out[col] = s.clip(lower=lo, upper=hi)
    return out


CONTROLS = ["Size", "ROA", "Growth", "Leverage", "BoardSize", "BoardIndependence", "CEODuality", "SOE", "Big4"]
CONTINUOUS = ["CarbonChange", "CTPCI", "Size", "ROA", "Growth", "Leverage", "BoardSize", "BoardIndependence"]


@dataclass(slots=True)
class SilviaResult:
    model: int
    params: pd.Series
    bse: pd.Series
    pvalues: pd.Series
    nobs: int
    n_firms: int
    rsquared: float
    warnings: list[str] = field(default_factory=list)

    @property
    def ctpci(self) -> tuple[float, float, float]:
        """(coefficient, standard error, p-value) on CTPCI."""
        return (
            float(self.params.get("CTPCI", np.nan)),
            float(self.bse.get("CTPCI", np.nan)),
            float(self.pvalues.get("CTPCI", np.nan)),
        )

    def compare_to_published(self) -> str:
        coef, se, p = self.ctpci
        target, target_se = PUBLISHED[f"ctpci_model{self.model}"]
        inside = abs(coef - target) <= 1.96 * max(se, 1e-12)
        stars = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.1 else ""
        return (
            f"Model {self.model}: CTPCI {coef:+.4f}{stars} ({se:.4f})  "
            f"published {target:+.3f} ({target_se:.3f})  "
            f"{'within' if inside else 'OUTSIDE'} 95% CI of the published point estimate"
        )


def estimate(
    frame: pd.DataFrame,
    *,
    model: int = 1,
    outcome: str = "CarbonChange",
    ctpci: str = "CTPCI",
    controls: list[str] | None = None,
    firm: str = "firm_id",
    year: str = "year",
    winsorise: bool = True,
    country_year_fe: bool = False,
) -> SilviaResult:
    """Estimate Model 1, 2 or 3 with firm and year fixed effects.

    Model 1 is the baseline, Model 2 adds External Assurance and its
    interaction with CTPCI, Model 3 adds Regulatory Environment and its
    interaction. Standard errors are clustered on the firm, as they specify.

    `country_year_fe` gives their robustness specification, in which
    country-by-year effects replace year effects.
    """
    import statsmodels.formula.api as smf

    if model not in (1, 2, 3):
        raise ValueError("model must be 1, 2 or 3")
    controls = controls if controls is not None else CONTROLS

    needed = [outcome, ctpci, firm, year, *controls]
    moderator = {2: "Assurance", 3: "Regulatory"}.get(model)
    if moderator:
        needed.append(moderator)
    if country_year_fe:
        needed.append("country")

    missing = [c for c in needed if c not in frame.columns]
    if missing:
        raise ValueError(f"missing columns: {missing}")

    work = frame[list(dict.fromkeys(needed))].dropna(subset=[outcome, ctpci]).copy()
    if winsorise:
        work = winsorise_frame(work, [c for c in CONTINUOUS if c in work.columns])

    # Controls that never vary within a firm are perfectly collinear with the
    # firm fixed effects. Left in, statsmodels returns a rank-deficient design
    # and coefficients that are not uniquely determined. Drop them and say so:
    # in real data Big4, SOE and CEODuality change rarely, so whether they
    # survive is a property of the sample, not of the specification.
    invariant = [
        c for c in controls
        if c in work.columns and work.groupby(firm)[c].nunique(dropna=False).max() <= 1
    ]
    controls = [c for c in controls if c not in invariant]

    terms = [ctpci, *controls]
    if moderator:
        terms += [moderator, f"{ctpci}:{moderator}"]
    terms.append(f"C({firm})")
    if country_year_fe:
        work["__cy"] = work["country"].astype(str) + "_" + work[year].astype(str)
        terms.append("C(__cy)")
    else:
        terms.append(f"C({year})")

    formula = f"{outcome} ~ " + " + ".join(terms)
    fit = smf.ols(formula, data=work).fit(cov_type="cluster", cov_kwds={"groups": work[firm]})

    warnings: list[str] = []
    if invariant:
        warnings.append(
            f"dropped firm-invariant controls under firm FE: {', '.join(invariant)} "
            "(collinear with the fixed effects)"
        )
    if work[firm].nunique() < 50:
        warnings.append(f"only {work[firm].nunique()} firms; clustered SEs are unreliable below ~50 clusters")
    if len(work) < 300:
        warnings.append(f"only {len(work)} observations against their 1,126")

    return SilviaResult(
        model=model,
        params=fit.params,
        bse=fit.bse,
        pvalues=fit.pvalues,
        nobs=int(fit.nobs),
        n_firms=int(work[firm].nunique()),
        rsquared=float(fit.rsquared),
        warnings=warnings,
    )


# --------------------------------------------------------------------------
# Verification harness
# --------------------------------------------------------------------------

def simulate_panel(
    *,
    n_firms: int = PUBLISHED["n_firms"],
    start_year: int = 2018,
    end_year: int = 2023,
    beta_ctpci: float = PUBLISHED["ctpci_model1"][0],
    seed: int = 20260919,
) -> pd.DataFrame:
    """A panel carrying the published correlation structure.

    Built to their Table 4 correlations and Table 5 coefficients so that the
    estimator can be checked against a known answer. CTPCI is generated with a
    firm-level component plus a rising time trend, correlated with assurance
    and the regulatory environment at roughly their reported magnitudes
    (0.273 and 0.428); CarbonChange is generated with `beta_ctpci` as the true
    coefficient.

    This is simulated data. It verifies the implementation. It is not evidence
    about any firm, and it cannot confirm their finding.
    """
    rng = np.random.default_rng(seed)
    years = list(range(start_year, end_year + 1))
    firm_effect = rng.normal(0, 1, n_firms)
    regulatory_propensity = rng.normal(0, 1, n_firms)

    rows = []
    for i in range(n_firms):
        size = rng.normal(11.5, 1.2)
        board = max(5, int(rng.normal(11, 3)))
        indep = np.clip(rng.beta(6, 3), 0, 1)
        duality = float(rng.random() < 0.35)
        soe = float(rng.random() < 0.15)
        big4 = float(rng.random() < 0.82)
        country = rng.choice(["US", "CN", "JP", "DE", "FR", "GB", "KR"], p=[.3, .22, .12, .1, .09, .09, .08])
        for t, year in enumerate(years):
            # CTPCI rises over the window and is firm-persistent. The within-
            # firm component has to be substantial or firm FE leaves nothing to
            # identify the coefficient from.
            latent = 0.55 * firm_effect[i] + 0.40 * regulatory_propensity[i] + 0.16 * t + rng.normal(0, 0.75)
            ctpci = float(np.clip(0.42 + 0.11 * latent, 0.0, 1.0))
            assurance = float(rng.random() < 1 / (1 + np.exp(-(0.60 * latent - 0.15))))
            regulatory = float(
                rng.random() < 1 / (1 + np.exp(-(1.5 * regulatory_propensity[i] + 1.15 * latent + 0.30 * t - 1.1)))
            )
            # Governance and ownership drift within firm, as they do in reality.
            # Without within-firm variation these are collinear with firm FE.
            board_t = max(5, board + int(rng.normal(0, 0.7)))
            indep_t = float(np.clip(indep + rng.normal(0, 0.03), 0, 1))
            duality_t = duality if rng.random() > 0.05 else 1.0 - duality
            soe_t = soe
            big4_t = big4 if rng.random() > 0.03 else 1.0 - big4
            roa = rng.normal(0.06, 0.05)
            growth = rng.normal(0.05, 0.12)
            leverage = np.clip(rng.normal(0.58, 0.16), 0.05, 0.95)
            carbon_change_val = (
                beta_ctpci * ctpci
                - 0.005 * size
                - 0.074 * roa
                + 0.045 * growth
                + 0.027 * leverage
                - 0.001 * board_t
                - 0.032 * indep_t
                + rng.normal(0, 0.045)
            )
            rows.append(
                {
                    "firm_id": f"F{i:03d}",
                    "year": year,
                    "country": country,
                    "CTPCI": ctpci,
                    "Assurance": assurance,
                    "Regulatory": regulatory,
                    "CarbonChange": carbon_change_val,
                    "Size": size + rng.normal(0, 0.05),
                    "ROA": roa,
                    "Growth": growth,
                    "Leverage": leverage,
                    "BoardSize": board_t,
                    "BoardIndependence": indep_t,
                    "CEODuality": duality_t,
                    "SOE": soe_t,
                    "Big4": big4_t,
                }
            )
    frame = pd.DataFrame(rows)
    # Their regression sample loses the final year to the lead structure.
    return frame[frame["year"] < end_year].reset_index(drop=True)


def verify_against_published(frame: pd.DataFrame | None = None) -> str:
    """Run all three models and report each against the published estimate."""
    panel = frame if frame is not None else simulate_panel()
    lines = [
        f"Sample: {panel['firm_id'].nunique()} firms, {len(panel)} firm-years "
        f"(published: {PUBLISHED['n_firms']} firms, {PUBLISHED['n_obs']} obs)",
        "",
    ]
    corr = panel["CTPCI"].corr(panel["CarbonChange"])
    lines.append(
        f"corr(CTPCI, CarbonChange) = {corr:+.3f}   published {PUBLISHED['corr_ctpci_carbonchange']:+.3f}"
    )
    lines.append(
        f"corr(CTPCI, Assurance)    = {panel['CTPCI'].corr(panel['Assurance']):+.3f}   "
        f"published {PUBLISHED['corr_ctpci_assurance']:+.3f}"
    )
    lines.append(
        f"corr(CTPCI, Regulatory)   = {panel['CTPCI'].corr(panel['Regulatory']):+.3f}   "
        f"published {PUBLISHED['corr_ctpci_regulatory']:+.3f}"
    )
    lines.append("")
    for m in (1, 2, 3):
        res = estimate(panel, model=m)
        lines.append(res.compare_to_published())
        for w in res.warnings:
            lines.append(f"    warning: {w}")
    lines.append("")
    lines.append(
        "A single panel is noisy: firm fixed effects absorb most of the between-firm\n"
        "variation in CTPCI, so a correct estimator lands two standard errors from the\n"
        "truth often enough that one draw proves nothing. The Monte Carlo below is the\n"
        "actual check."
    )
    if frame is None:
        mc = monte_carlo_check(n_seeds=30)
        lines.append("")
        lines.append(
            f"Monte Carlo over {mc['n_seeds']} panels built with beta = {mc['true_beta']:+.4f}: "
            f"mean estimate {mc['mean_estimate']:+.4f} (MC se {mc['mc_se']:.4f}), "
            f"bias {mc['bias']:+.4f}, 95% coverage {mc['coverage_95']:.0%}."
        )
    lines.append("")
    lines.append(
        "This verifies the estimator against data built to the published correlation\n"
        "structure. It does not reproduce their finding, which needs the CTPCI coded\n"
        "by hand from 1,126 firm-year reports plus emissions and financial data."
    )
    return "\n".join(lines)


def monte_carlo_check(
    *,
    n_seeds: int = 40,
    beta_ctpci: float = PUBLISHED["ctpci_model1"][0],
    model: int = 1,
    n_firms: int = PUBLISHED["n_firms"],
) -> dict[str, float]:
    """Is the estimator unbiased for the coefficient the panel was built with?

    A single simulated panel cannot answer this: with firm fixed effects
    absorbing most of the between-firm variation in CTPCI, one draw is noisy
    enough that a correct estimator will sometimes land two standard errors
    from the truth. Averaging over seeds separates sampling noise from a bug.

    Returns the mean estimate, its Monte Carlo standard error, the bias, and
    the share of draws whose 95% interval covers the true value. Coverage near
    0.95 is the real check; a mean close to the truth with poor coverage would
    indicate the standard errors are wrong even where the point estimate is
    right.
    """
    import warnings as _w

    estimates, covered = [], 0
    for seed in range(n_seeds):
        panel = simulate_panel(n_firms=n_firms, beta_ctpci=beta_ctpci, seed=seed)
        with _w.catch_warnings():
            _w.simplefilter("ignore")
            res = estimate(panel, model=model)
        coef, se, _ = res.ctpci
        if not np.isfinite(coef) or not np.isfinite(se):
            continue
        estimates.append(coef)
        if abs(coef - beta_ctpci) <= 1.96 * se:
            covered += 1
    if not estimates:
        raise RuntimeError("no estimable draws")
    arr = np.array(estimates)
    return {
        "n_seeds": len(arr),
        "true_beta": beta_ctpci,
        "mean_estimate": float(arr.mean()),
        "mc_se": float(arr.std(ddof=1) / np.sqrt(len(arr))),
        "bias": float(arr.mean() - beta_ctpci),
        "coverage_95": covered / len(arr),
    }
