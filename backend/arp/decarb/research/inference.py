"""Panel regression with fixed effects and clustered standard errors.

The stdlib `arp.decarb.stats.ols` returns coefficients and R-squared and no
inference at all, which is fine for the descriptive analyses it supports and
useless for anything a referee would read. This module supplies the missing
half.

Two defaults are opinionated.

Standard errors are clustered on the firm by default. Emissions are highly
persistent within a firm, so unclustered standard errors on a firm-year panel
are far too small and routinely turn noise into three stars.

Sector-by-year fixed effects are offered as a single option because sector
trends dominate emissions trajectories and are the confound most likely to
generate a spurious governance result. Schüder and Zülch use sector x year x
region effects for exactly this reason.

`sign_stability` exists because of a specific finding in the review: Oyewo
(2023) reports ESG-linked pay and board independence associated with *worse*
carbon performance, and Schüder and Zülch independently recover a positive
governance coefficient. A variable whose sign flips with the control set is
not a usable predictor, and this function makes that easy to check rather
than easy to miss.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

__all__ = ["PanelResult", "panel_ols", "sign_stability"]


@dataclass(slots=True)
class PanelResult:
    params: pd.Series
    bse: pd.Series
    pvalues: pd.Series
    conf_int: pd.DataFrame
    nobs: int
    n_groups: int
    rsquared: float
    formula: str
    cluster: str

    def table(self, terms: list[str] | None = None) -> pd.DataFrame:
        keep = terms or [i for i in self.params.index if not i.startswith("C(") and i != "Intercept"]
        keep = [k for k in keep if k in self.params.index]
        return pd.DataFrame(
            {
                "coef": self.params[keep],
                "se": self.bse[keep],
                "p": self.pvalues[keep],
                "ci_low": self.conf_int.loc[keep, 0],
                "ci_high": self.conf_int.loc[keep, 1],
                "sig": [_stars(p) for p in self.pvalues[keep]],
            }
        )


def _stars(p: float) -> str:
    if not np.isfinite(p):
        return ""
    return "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.1 else ""


def panel_ols(
    frame: pd.DataFrame,
    *,
    outcome: str,
    regressors: list[str],
    entity: str = "firm_id",
    time: str = "year",
    entity_fe: bool = True,
    time_fe: bool = True,
    sector_by_year_fe: bool = False,
    sector: str = "sector",
    cluster: str | None = None,
    weights: str | None = None,
) -> PanelResult:
    """OLS with the usual panel fixed effects and clustered standard errors.

    `cluster` defaults to `entity`. Pass an explicit column to cluster
    elsewhere, for instance on sector when treatment varies at that level.
    """
    cols = [outcome, *regressors, entity, time]
    if sector_by_year_fe:
        cols.append(sector)
    if weights:
        cols.append(weights)
    work = frame[list(dict.fromkeys(cols))].dropna(subset=[outcome, *regressors]).copy()
    if work.empty:
        raise ValueError("no complete cases after dropping missing outcome/regressors")

    terms = list(regressors)
    if entity_fe:
        terms.append(f"C({entity})")
    if sector_by_year_fe:
        work["__sector_year"] = work[sector].astype(str) + "_" + work[time].astype(str)
        terms.append("C(__sector_year)")
    elif time_fe:
        terms.append(f"C({time})")

    formula = f"{outcome} ~ " + " + ".join(terms)
    cluster_col = cluster or entity
    fit_kwargs = {"cov_type": "cluster", "cov_kwds": {"groups": work[cluster_col]}}
    if weights:
        model = smf.wls(formula, data=work, weights=work[weights]).fit(**fit_kwargs)
    else:
        model = smf.ols(formula, data=work).fit(**fit_kwargs)

    return PanelResult(
        params=model.params,
        bse=model.bse,
        pvalues=model.pvalues,
        conf_int=model.conf_int(),
        nobs=int(model.nobs),
        n_groups=int(work[cluster_col].nunique()),
        rsquared=float(model.rsquared),
        formula=formula,
        cluster=cluster_col,
    )


def sign_stability(
    frame: pd.DataFrame,
    *,
    outcome: str,
    focal: str,
    control_sets: dict[str, list[str]],
    entity: str = "firm_id",
    time: str = "year",
    **kwargs,
) -> pd.DataFrame:
    """Re-estimate one coefficient under several control sets.

    Returns a row per specification with the focal coefficient, its standard
    error and significance. If the sign flips across specifications the
    variable is not measuring what it is being asked to measure.
    """
    rows = []
    for name, controls in control_sets.items():
        regressors = [focal, *[c for c in controls if c != focal]]
        try:
            res = panel_ols(frame, outcome=outcome, regressors=regressors, entity=entity, time=time, **kwargs)
        except Exception as exc:  # pragma: no cover - specification can fail
            rows.append({"specification": name, "coef": np.nan, "se": np.nan, "p": np.nan, "error": str(exc)[:80]})
            continue
        rows.append(
            {
                "specification": name,
                "coef": float(res.params.get(focal, np.nan)),
                "se": float(res.bse.get(focal, np.nan)),
                "p": float(res.pvalues.get(focal, np.nan)),
                "sig": _stars(float(res.pvalues.get(focal, np.nan))),
                "n": res.nobs,
            }
        )
    out = pd.DataFrame(rows)
    if out["coef"].notna().any():
        signs = np.sign(out["coef"].dropna())
        out.attrs["sign_flips"] = bool(len(set(signs)) > 1)
    return out
