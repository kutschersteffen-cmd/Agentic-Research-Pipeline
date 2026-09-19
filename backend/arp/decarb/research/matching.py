"""Coarsened exact matching.

Schüder and Zülch (2026) apply CEM before estimating SBTi effects on 3,113
listed firms. The method is simple and the reason it matters here is not:
adoption of a climate target is voluntary and strongly selected, so an
unmatched adopter/non-adopter comparison mostly measures who chose to adopt.

CEM coarsens covariates into bins, keeps only strata containing both treated
and control units, and discards the rest. What survives is a sample where
treated and control firms are comparable on the coarsened covariates by
construction, at the cost of dropping units that have no counterpart.

The discard is the point and should always be reported: `MatchResult.n_dropped`
and `pruning_rate` exist so it cannot be quietly ignored.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

__all__ = ["MatchResult", "coarsen", "coarsened_exact_match", "balance_table"]


@dataclass(slots=True)
class MatchResult:
    matched: pd.DataFrame
    n_treated_in: int
    n_control_in: int
    n_treated_out: int
    n_control_out: int
    strata_kept: int
    strata_total: int
    weights_column: str = "cem_weight"
    warnings: list[str] = field(default_factory=list)

    @property
    def n_dropped(self) -> int:
        return (self.n_treated_in + self.n_control_in) - (self.n_treated_out + self.n_control_out)

    @property
    def pruning_rate(self) -> float:
        total = self.n_treated_in + self.n_control_in
        return self.n_dropped / total if total else 0.0

    def explain(self) -> str:
        return (
            f"CEM kept {self.strata_kept}/{self.strata_total} strata, "
            f"{self.n_treated_out}/{self.n_treated_in} treated and "
            f"{self.n_control_out}/{self.n_control_in} control units "
            f"({self.pruning_rate:.0%} pruned)."
        )


def coarsen(series: pd.Series, *, bins: int = 5, method: str = "quantile") -> pd.Series:
    """Bin a covariate. Categorical inputs pass through unchanged.

    Quantile binning is the default because firm-level financials are heavily
    skewed and equal-width bins would put almost every firm in one bucket.
    """
    if not pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series):
        return series.astype(str)
    clean = series.astype(float)
    if clean.notna().sum() == 0:
        return pd.Series(["NA"] * len(series), index=series.index)
    if method == "quantile":
        try:
            binned = pd.qcut(clean, q=bins, duplicates="drop")
        except ValueError:
            binned = pd.cut(clean, bins=bins)
    elif method == "width":
        binned = pd.cut(clean, bins=bins)
    else:
        raise ValueError("method must be 'quantile' or 'width'")
    return binned.astype(str).fillna("NA")


def coarsened_exact_match(
    frame: pd.DataFrame,
    *,
    treatment: str,
    covariates: list[str],
    bins: int = 5,
    method: str = "quantile",
) -> MatchResult:
    """Match treated to control units within coarsened covariate strata.

    Returns the matched subset with a `cem_weight` column. Treated units get
    weight 1; control units within a stratum share the treated-to-control
    ratio so each stratum contributes proportionally, which is the standard
    CEM weighting.
    """
    missing = [c for c in [treatment, *covariates] if c not in frame.columns]
    if missing:
        raise ValueError(f"columns not in frame: {missing}")

    work = frame.copy()
    treat = work[treatment].astype(bool)
    strata_cols = []
    for cov in covariates:
        col = f"__cem_{cov}"
        work[col] = coarsen(work[cov], bins=bins, method=method)
        strata_cols.append(col)

    work["__stratum"] = work[strata_cols].agg("|".join, axis=1)
    counts = work.groupby("__stratum")[treatment].agg(["sum", "count"])
    counts["n_treated"] = counts["sum"].astype(int)
    counts["n_control"] = (counts["count"] - counts["sum"]).astype(int)
    keep = counts[(counts["n_treated"] > 0) & (counts["n_control"] > 0)].index

    matched = work[work["__stratum"].isin(keep)].copy()
    weights = np.ones(len(matched), dtype=float)
    if len(matched):
        ratios = counts.loc[keep, "n_treated"] / counts.loc[keep, "n_control"]
        is_ctrl = ~matched[treatment].astype(bool)
        weights[is_ctrl.to_numpy()] = matched.loc[is_ctrl, "__stratum"].map(ratios).to_numpy(dtype=float)
    matched["cem_weight"] = weights

    warnings: list[str] = []
    result = MatchResult(
        matched=matched.drop(columns=strata_cols),
        n_treated_in=int(treat.sum()),
        n_control_in=int((~treat).sum()),
        n_treated_out=int(matched[treatment].astype(bool).sum()),
        n_control_out=int((~matched[treatment].astype(bool)).sum()),
        strata_kept=len(keep),
        strata_total=int(counts.shape[0]),
        warnings=warnings,
    )
    if result.pruning_rate > 0.5:
        warnings.append(
            f"{result.pruning_rate:.0%} of units pruned. The matched sample may no longer "
            "represent the population; consider fewer covariates or coarser bins."
        )
    if result.n_treated_out < 20:
        warnings.append(f"Only {result.n_treated_out} treated units survived matching; estimates will be noisy.")
    return result


def balance_table(
    frame: pd.DataFrame,
    *,
    treatment: str,
    covariates: list[str],
    weights: str | None = None,
) -> pd.DataFrame:
    """Standardised mean differences before and after weighting.

    The convention is that |SMD| below 0.1 counts as balanced. Reporting this
    is what distinguishes a matching procedure that worked from one that only
    ran.
    """
    rows = []
    treat = frame[treatment].astype(bool)
    w = frame[weights].astype(float) if weights else pd.Series(1.0, index=frame.index)
    for cov in covariates:
        series = frame[cov]
        if not pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series):
            series = series.astype("category").cat.codes
        series = series.astype(float)
        t_vals, c_vals = series[treat], series[~treat]
        t_w, c_w = w[treat], w[~treat]
        if len(t_vals) == 0 or len(c_vals) == 0:
            continue
        t_mean = np.average(t_vals, weights=t_w) if t_w.sum() else np.nan
        c_mean = np.average(c_vals, weights=c_w) if c_w.sum() else np.nan
        pooled_sd = np.sqrt((t_vals.var(ddof=1) + c_vals.var(ddof=1)) / 2.0)
        smd = (t_mean - c_mean) / pooled_sd if pooled_sd > 0 else 0.0
        rows.append(
            {
                "covariate": cov,
                "treated_mean": t_mean,
                "control_mean": c_mean,
                "smd": smd,
                "balanced": abs(smd) < 0.1,
            }
        )
    return pd.DataFrame(rows)
