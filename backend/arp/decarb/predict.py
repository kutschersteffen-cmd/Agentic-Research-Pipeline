"""Predictive evaluation against a persistence baseline.

Design rule 2 of the review: beat persistence before claiming a finding.

Emissions trajectories are strongly autocorrelated, so a model given lagged
emissions growth will look impressive while having learned nothing about
transition behaviour. The only interpretable quantity is the *increment* a
feature set adds over that baseline, measured out of time.

The module also guards against the failure mode in Xu, Wei & Ji (2026). They
report R^2 of 0.85 predicting carbon intensity without carbon inputs, which
sounds like governance predicting decarbonisation but is mostly the model
recovering sector and size. Predicting which firms are dirty is a different
problem from predicting which are getting cleaner. `Target.LEVEL` and
`Target.CHANGE` make the choice explicit and `evaluate` warns when a level
target is used with a decarbonisation framing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

from arp.decarb.stats import auc, logistic_regression, ols

__all__ = ["Target", "Design", "IncrementResult", "evaluate", "sector_region_dummies"]


class Target(str, Enum):
    LEVEL = "level"
    CHANGE = "change"


@dataclass(slots=True)
class Design:
    """An out-of-time evaluation design.

    `train_years` and `test_years` must not overlap. Cross-sectional k-fold
    on a firm-year panel leaks: the same firm appears in train and test with
    adjacent years and near-identical features, which inflates every score.
    """

    train_years: list[int]
    test_years: list[int]
    target: Target = Target.CHANGE

    def __post_init__(self) -> None:
        overlap = set(self.train_years) & set(self.test_years)
        if overlap:
            raise ValueError(f"train and test years overlap: {sorted(overlap)}")
        if not self.train_years or not self.test_years:
            raise ValueError("both train_years and test_years must be non-empty")
        if max(self.train_years) >= min(self.test_years):
            raise ValueError("test years must follow train years; no look-ahead")


@dataclass(slots=True)
class IncrementResult:
    """What a feature block adds over the persistence baseline, out of time."""

    baseline_auc: float
    augmented_auc: float
    baseline_r2: float
    augmented_r2: float
    n_train: int
    n_test: int
    n_features: int
    warnings: list[str] = field(default_factory=list)

    @property
    def delta_auc(self) -> float:
        return self.augmented_auc - self.baseline_auc

    @property
    def delta_r2(self) -> float:
        return self.augmented_r2 - self.baseline_r2

    def verdict(self, *, min_delta_auc: float = 0.02) -> str:
        if self.delta_auc < min_delta_auc:
            return (
                f"No material gain over persistence (dAUC {self.delta_auc:+.3f}, "
                f"dR2 {self.delta_r2:+.3f}). The feature block is not carrying "
                "information the lagged trajectory did not already contain."
            )
        return (
            f"Adds {self.delta_auc:+.3f} AUC and {self.delta_r2:+.3f} R2 over persistence "
            f"out of time ({self.n_test} test observations)."
        )


def sector_region_dummies(sectors: list[str | None], regions: list[str | None]) -> list[list[float]]:
    """One-hot sector and region controls, first level dropped to avoid
    collinearity with the intercept.

    These belong in the baseline, not the feature block. Sector is the single
    largest determinant of carbon intensity, and a feature set credited with
    sector's explanatory power will look far stronger than it is.
    """
    s_levels = sorted({s for s in sectors if s})
    r_levels = sorted({r for r in regions if r})
    s_cols, r_cols = s_levels[1:], r_levels[1:]
    out: list[list[float]] = []
    for s, r in zip(sectors, regions):
        out.append(
            [1.0 if s == lvl else 0.0 for lvl in s_cols] + [1.0 if r == lvl else 0.0 for lvl in r_cols]
        )
    return out


def _fit_predict(
    x_train: list[list[float]],
    y_train_bin: list[bool],
    y_train_num: list[float],
    x_test: list[list[float]],
) -> tuple[list[float], list[float]]:
    """Return (probability scores, numeric predictions) for the test rows."""
    beta = logistic_regression(x_train, y_train_bin)
    scores = [
        1.0 / (1.0 + math.exp(-max(-500.0, min(500.0, beta[0] + math.fsum(b * v for b, v in zip(beta[1:], row))))))
        for row in x_test
    ]
    fit = ols(x_train, y_train_num)
    preds = [fit.predict(row) for row in x_test]
    return scores, preds


def _r2(actual: list[float], predicted: list[float]) -> float:
    if len(actual) < 2:
        return float("nan")
    abar = math.fsum(actual) / len(actual)
    ss_tot = math.fsum((a - abar) ** 2 for a in actual)
    ss_res = math.fsum((a - p) ** 2 for a, p in zip(actual, predicted))
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0


def evaluate(
    *,
    baseline_features: list[list[float]],
    extra_features: list[list[float]],
    outcome_numeric: list[float],
    outcome_binary: list[bool],
    years: list[int],
    design: Design,
) -> IncrementResult:
    """Fit baseline and augmented models, evaluate out of time, return the increment.

    `baseline_features` should contain lagged emissions growth plus sector and
    region controls. `extra_features` is the block under test. All four input
    lists are row-aligned with `years`.
    """
    warnings: list[str] = []
    if design.target is Target.LEVEL:
        warnings.append(
            "Target.LEVEL predicts how carbon-intensive a firm is, not whether it is "
            "decarbonising. Do not report this as evidence about transition behaviour."
        )

    n = len(outcome_numeric)
    if not (len(baseline_features) == len(extra_features) == len(outcome_binary) == len(years) == n):
        raise ValueError("all inputs must be row-aligned")

    tr = [i for i, y in enumerate(years) if y in set(design.train_years)]
    te = [i for i, y in enumerate(years) if y in set(design.test_years)]
    if len(tr) < 10 or len(te) < 5:
        raise ValueError(f"insufficient data: {len(tr)} train rows, {len(te)} test rows")

    if len(set(outcome_binary[i] for i in tr)) < 2:
        raise ValueError("training outcome has only one class; widen the window or move the threshold")
    if len(set(outcome_binary[i] for i in te)) < 2:
        warnings.append("Test outcome has only one class; AUC is undefined and reported as 0.5.")

    base_tr = [baseline_features[i] for i in tr]
    base_te = [baseline_features[i] for i in te]
    aug_tr = [baseline_features[i] + extra_features[i] for i in tr]
    aug_te = [baseline_features[i] + extra_features[i] for i in te]

    y_bin_tr = [outcome_binary[i] for i in tr]
    y_num_tr = [outcome_numeric[i] for i in tr]
    y_bin_te = [outcome_binary[i] for i in te]
    y_num_te = [outcome_numeric[i] for i in te]

    b_scores, b_preds = _fit_predict(base_tr, y_bin_tr, y_num_tr, base_te)
    a_scores, a_preds = _fit_predict(aug_tr, y_bin_tr, y_num_tr, aug_te)

    n_extra = len(extra_features[0]) if extra_features and extra_features[0] else 0
    if len(tr) < 10 * max(1, n_extra):
        warnings.append(
            f"{len(tr)} training rows for {n_extra} extra features. The increment is likely "
            "to be overfitting rather than signal."
        )

    return IncrementResult(
        baseline_auc=auc(b_scores, y_bin_te),
        augmented_auc=auc(a_scores, y_bin_te),
        baseline_r2=_r2(y_num_te, b_preds),
        augmented_r2=_r2(y_num_te, a_preds),
        n_train=len(tr),
        n_test=len(te),
        n_features=n_extra,
        warnings=warnings,
    )
