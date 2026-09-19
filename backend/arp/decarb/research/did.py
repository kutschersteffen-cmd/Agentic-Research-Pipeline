"""Staggered difference-in-differences event study.

This is the identification strategy the corpus runs on. Dietz and Hastreiter
(2026) use staggered DiD with matching to ask whether adopting a long-term net
zero target changes near-term emissions and climate governance. Schüder and
Zülch (2026) use matching plus a stacked DiD robustness check.

Implemented here as group-time average treatment effects in the style of
Callaway and Sant'Anna (2021) rather than two-way fixed effects. The reason
matters: with staggered adoption and heterogeneous effects, TWFE uses
already-treated units as controls for later-treated ones and can return an
estimate with the wrong sign even when every underlying effect shares a sign.
`twfe_event_study` is provided for comparison, with that caveat attached.

The building block is a 2x2: for cohort g (firms adopting in year g) and
period t, compare the change in outcome from g-1 to t for cohort g against
the same change for a control group, either never-treated firms or those not
yet treated at t.

    ATT(g,t) = E[Y_t - Y_{g-1} | G=g] - E[Y_t - Y_{g-1} | control]

Event-time aggregation averages ATT(g,t) over cohorts at each e = t - g,
weighted by cohort size. Standard errors come from a firm-level block
bootstrap, which respects the within-firm correlation that makes naive
standard errors far too small in panel data.

Pre-treatment estimates (e < 0) are the parallel-trends check. They are
reported, never dropped: Dietz and Hastreiter find a significant t-1
coefficient on their weighted management score and interpret it as firms
acting shortly before they announce, which changes the reading of the result.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

__all__ = ["EventStudyResult", "group_time_att", "event_study", "twfe_event_study"]

_RNG = np.random.default_rng(20260919)


@dataclass(slots=True)
class EventStudyResult:
    """Event-time ATTs with bootstrap inference."""

    effects: pd.DataFrame  # event_time, att, se, ci_low, ci_high, n_treated
    group_time: pd.DataFrame
    outcome: str
    control_group: str
    n_cohorts: int
    n_bootstrap: int
    warnings: list[str] = field(default_factory=list)

    def pre_trend_test(self, *, alpha: float = 0.05) -> tuple[bool, str]:
        """Whether any pre-treatment effect is distinguishable from zero.

        A failed test does not always invalidate the design. It can also mean
        firms act in anticipation, which is a finding rather than a defect,
        but it has to be stated either way.
        """
        pre = self.effects[self.effects["event_time"] < 0].dropna(subset=["se"])
        pre = pre[pre["se"] > 0]
        if pre.empty:
            return True, "No pre-treatment periods available to test."
        z = (pre["att"] / pre["se"]).abs()
        crit = 1.96 if alpha == 0.05 else float(abs(np.round(np.sqrt(2) * 1.386, 3)))
        bad = pre[z > crit]
        if bad.empty:
            return True, f"No pre-treatment effect significant at {alpha:.0%} ({len(pre)} periods tested)."
        worst = bad.loc[(bad["att"] / bad["se"]).abs().idxmax()]
        return False, (
            f"Pre-treatment effect at e={int(worst['event_time'])} is "
            f"{worst['att']:+.4f} (se {worst['se']:.4f}), significant at {alpha:.0%}. "
            "Either parallel trends fails or firms are acting before they announce."
        )

    def post_average(self) -> tuple[float, float]:
        """Simple average of post-treatment ATTs and its bootstrap se."""
        post = self.effects[self.effects["event_time"] >= 0]
        if post.empty:
            return (float("nan"), float("nan"))
        att = float(post["att"].mean())
        se = float(np.sqrt((post["se"] ** 2).sum()) / len(post)) if post["se"].notna().all() else float("nan")
        return att, se

    def summary(self) -> str:
        att, se = self.post_average()
        ok, msg = self.pre_trend_test()
        lines = [
            f"Outcome: {self.outcome}   controls: {self.control_group}   "
            f"cohorts: {self.n_cohorts}   bootstrap: {self.n_bootstrap}",
            f"Average post-treatment ATT: {att:+.4f} (se {se:.4f})",
            f"Pre-trend check: {'PASS' if ok else 'FAIL'} - {msg}",
            "",
            f"{'e':>4}{'ATT':>10}{'se':>9}{'95% CI':>20}{'n':>7}",
        ]
        for _, r in self.effects.iterrows():
            ci = f"[{r['ci_low']:+.3f}, {r['ci_high']:+.3f}]" if pd.notna(r["se"]) else "n/a"
            lines.append(
                f"{int(r['event_time']):>4}{r['att']:>10.4f}{r['se']:>9.4f}{ci:>20}{int(r['n_treated']):>7}"
            )
        for w in self.warnings:
            lines.append(f"warning: {w}")
        return "\n".join(lines)


def _cohorts(frame: pd.DataFrame, cohort_col: str) -> list[int]:
    vals = frame[cohort_col].dropna().unique()
    return sorted(int(v) for v in vals)


def group_time_att(
    frame: pd.DataFrame,
    *,
    outcome: str,
    cohort_col: str = "ltnz_adoption_year",
    time_col: str = "year",
    unit_col: str = "firm_id",
    control_group: str = "not_yet_treated",
    weights_col: str | None = None,
) -> pd.DataFrame:
    """ATT(g,t) for every cohort and period.

    `control_group` is "not_yet_treated" (default) or "never_treated".
    Not-yet-treated uses more data; never-treated is cleaner when treatment
    effects are long-lived. Both are reported in the literature, and the
    choice should be stated.
    """
    if control_group not in {"not_yet_treated", "never_treated"}:
        raise ValueError("control_group must be 'not_yet_treated' or 'never_treated'")

    work = frame[[unit_col, time_col, cohort_col, outcome] + ([weights_col] if weights_col else [])].copy()
    work = work.dropna(subset=[outcome])
    wide = work.pivot_table(index=unit_col, columns=time_col, values=outcome, aggfunc="first")
    cohort_of = work.groupby(unit_col)[cohort_col].first()
    weight_of = (
        work.groupby(unit_col)[weights_col].first() if weights_col else pd.Series(1.0, index=wide.index)
    )

    periods = sorted(wide.columns)
    rows = []
    for g in _cohorts(work, cohort_col):
        base = g - 1
        if base not in wide.columns:
            continue
        treated_units = cohort_of[cohort_of == g].index
        treated_units = [u for u in treated_units if u in wide.index]
        if not treated_units:
            continue
        for t in periods:
            if t == base:
                continue
            if control_group == "never_treated":
                ctrl_units = cohort_of[cohort_of.isna()].index
            else:
                ctrl_units = cohort_of[(cohort_of.isna()) | (cohort_of > max(t, g))].index
            ctrl_units = [u for u in ctrl_units if u in wide.index]
            if not ctrl_units:
                continue

            d_treat = (wide.loc[treated_units, t] - wide.loc[treated_units, base]).dropna()
            d_ctrl = (wide.loc[ctrl_units, t] - wide.loc[ctrl_units, base]).dropna()
            if len(d_treat) < 2 or len(d_ctrl) < 2:
                continue
            wt = weight_of.reindex(d_treat.index).fillna(1.0).to_numpy(dtype=float)
            wc = weight_of.reindex(d_ctrl.index).fillna(1.0).to_numpy(dtype=float)
            att = float(np.average(d_treat.to_numpy(float), weights=wt) - np.average(d_ctrl.to_numpy(float), weights=wc))
            rows.append(
                {
                    "cohort": g,
                    "time": t,
                    "event_time": t - g,
                    "att": att,
                    "n_treated": len(d_treat),
                    "n_control": len(d_ctrl),
                }
            )
    return pd.DataFrame(rows)


def event_study(
    frame: pd.DataFrame,
    *,
    outcome: str,
    cohort_col: str = "ltnz_adoption_year",
    time_col: str = "year",
    unit_col: str = "firm_id",
    control_group: str = "not_yet_treated",
    weights_col: str | None = None,
    min_event_time: int = -4,
    max_event_time: int = 4,
    n_bootstrap: int = 300,
) -> EventStudyResult:
    """Cohort-size-weighted event-time ATTs with a firm-level block bootstrap.

    The bootstrap resamples firms, not firm-years. Resampling rows would treat
    a firm's nine observations as nine independent draws and shrink the
    standard errors by roughly a factor of three.
    """
    gt = group_time_att(
        frame,
        outcome=outcome,
        cohort_col=cohort_col,
        time_col=time_col,
        unit_col=unit_col,
        control_group=control_group,
        weights_col=weights_col,
    )
    warnings: list[str] = []
    if gt.empty:
        return EventStudyResult(pd.DataFrame(), gt, outcome, control_group, 0, 0, ["No estimable (g,t) cells."])

    gt = gt[(gt["event_time"] >= min_event_time) & (gt["event_time"] <= max_event_time)]

    def aggregate(table: pd.DataFrame) -> pd.Series:
        grouped = table.groupby("event_time").apply(
            lambda d: np.average(d["att"], weights=d["n_treated"]), include_groups=False
        )
        return grouped

    point = aggregate(gt)

    units = frame[unit_col].unique()
    draws: list[pd.Series] = []
    for _ in range(n_bootstrap):
        sampled = _RNG.choice(units, size=len(units), replace=True)
        idx = pd.DataFrame({unit_col: sampled}).merge(frame, on=unit_col, how="left")
        # Re-key duplicated firms so a firm drawn twice counts as two units.
        idx["__rep"] = idx.groupby([unit_col, time_col]).cumcount()
        idx[unit_col] = idx[unit_col].astype(str) + "_" + idx["__rep"].astype(str)
        try:
            b_gt = group_time_att(
                idx,
                outcome=outcome,
                cohort_col=cohort_col,
                time_col=time_col,
                unit_col=unit_col,
                control_group=control_group,
                weights_col=weights_col,
            )
        except Exception:  # pragma: no cover - bootstrap draws can degenerate
            continue
        if b_gt.empty:
            continue
        b_gt = b_gt[(b_gt["event_time"] >= min_event_time) & (b_gt["event_time"] <= max_event_time)]
        if b_gt.empty:
            continue
        draws.append(aggregate(b_gt))

    if len(draws) < max(20, n_bootstrap // 10):
        warnings.append(f"Only {len(draws)} of {n_bootstrap} bootstrap draws were estimable; SEs are unreliable.")

    boot = pd.DataFrame(draws)
    effects = []
    counts = gt.groupby("event_time")["n_treated"].sum()
    for e in sorted(point.index):
        col = boot[e].dropna() if e in boot.columns else pd.Series(dtype=float)
        se = float(col.std(ddof=1)) if len(col) > 2 else float("nan")
        effects.append(
            {
                "event_time": int(e),
                "att": float(point[e]),
                "se": se,
                "ci_low": float(point[e] - 1.96 * se) if se == se else float("nan"),
                "ci_high": float(point[e] + 1.96 * se) if se == se else float("nan"),
                "n_treated": int(counts.get(e, 0)),
            }
        )

    return EventStudyResult(
        effects=pd.DataFrame(effects).sort_values("event_time").reset_index(drop=True),
        group_time=gt,
        outcome=outcome,
        control_group=control_group,
        n_cohorts=gt["cohort"].nunique(),
        n_bootstrap=len(draws),
        warnings=warnings,
    )


def twfe_event_study(
    frame: pd.DataFrame,
    *,
    outcome: str,
    cohort_col: str = "ltnz_adoption_year",
    time_col: str = "year",
    unit_col: str = "firm_id",
    min_event_time: int = -4,
    max_event_time: int = 4,
) -> pd.DataFrame:
    """Two-way fixed effects event study, for comparison only.

    Provided so a user can see the gap against `event_study`. Under staggered
    adoption with heterogeneous effects, TWFE weights some 2x2 comparisons
    negatively because already-treated units serve as controls. Where the two
    estimators disagree, the group-time estimator is the one to trust.
    """
    import statsmodels.formula.api as smf

    work = frame.dropna(subset=[outcome]).copy()
    work["__event"] = work[time_col] - work[cohort_col]
    work.loc[work[cohort_col].isna(), "__event"] = np.nan

    for e in range(min_event_time, max_event_time + 1):
        if e == -1:
            continue  # reference period
        work[f"d{'m' if e < 0 else 'p'}{abs(e)}"] = (work["__event"] == e).astype(float)

    dummies = [c for c in work.columns if c.startswith(("dm", "dp")) and c[2:].isdigit()]
    formula = f"{outcome} ~ " + " + ".join(dummies) + f" + C({unit_col}) + C({time_col})"
    model = smf.ols(formula, data=work).fit(cov_type="cluster", cov_kwds={"groups": work[unit_col]})

    rows = []
    for c in dummies:
        e = int(c[2:]) * (-1 if c.startswith("dm") else 1)
        rows.append(
            {
                "event_time": e,
                "att": float(model.params.get(c, np.nan)),
                "se": float(model.bse.get(c, np.nan)),
                "pvalue": float(model.pvalues.get(c, np.nan)),
            }
        )
    rows.append({"event_time": -1, "att": 0.0, "se": 0.0, "pvalue": np.nan})
    return pd.DataFrame(rows).sort_values("event_time").reset_index(drop=True)
