"""Risk models for the tracking-error stage.

Stage 2 of `docs/OPTIMIZATION_TOOLING.md` section 9. The formulation that
consumes a risk model is a few lines; the risk model itself is the
commitment, which is why it lives behind one small interface:

    RiskModel  ->  names, a covariance (dense or in factor form), and a
                   provenance record of how it was built

Everything downstream -- the tracking-error constraint, the minimum-TE
objective, the independent verification -- depends only on that interface.
Swapping an estimated model for a licensed vendor factor model
(loadings, factor covariance, specific risk) is therefore a
`RiskModel.from_factors(...)` call and a data feed, not a rewrite of the
weighting engine. That separation is the whole point of this module: the
licence decision stays a data-sourcing decision.

Three estimators ship, none of which needs a licence:

- `sample`       -- the plain sample covariance. Honest, and singular
                    whenever the history is shorter than the universe,
                    which for an index it almost always is.
- `ledoit_wolf`  -- Ledoit-Wolf (2004) shrinkage toward a scaled identity.
                    Well-conditioned at any history length, and the
                    shrinkage intensity is derived from the data rather
                    than chosen. The sensible default.
- `factor`       -- a cross-sectional (Barra-shaped) factor model built
                    from characteristics the candidates already carry:
                    factor returns by period-wise OLS, then
                    `Sigma = B F B' + D`. Scales to a large universe
                    because the optimiser never forms the dense matrix.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import sqrt

import numpy as np

from arp.index.fields import category_value, metric_value
from arp.schemas.index import IndexCandidate, RiskModelSpec


class RiskModelError(ValueError):
    """Raised when a risk model cannot be built from what was supplied.

    Always a hard error rather than a silent fallback: a tracking-error
    budget computed against a covariance nobody vouched for is worse than
    no budget at all, because it reads as a control.
    """


@dataclass
class RiskModel:
    """An annualised covariance over a named universe.

    Held in factor form (`loadings`, `factor_covariance`, `specific_var`)
    when one is available, because the optimiser can then express tracking
    error in K + N terms rather than N**2 -- the difference between a
    tractable and an intractable problem at index scale. `covariance()`
    materialises the dense matrix for verification and reporting only.
    """

    names: list[str]
    source: str
    periods: int
    periods_per_year: float
    dense: np.ndarray | None = None
    loadings: np.ndarray | None = None          # N x K
    factor_covariance: np.ndarray | None = None  # K x K
    specific_var: np.ndarray | None = None       # N
    factor_names: list[str] = field(default_factory=list)
    shrinkage: float | None = None

    @property
    def factor_form(self) -> bool:
        return self.loadings is not None and self.factor_covariance is not None and self.specific_var is not None

    def index_of(self) -> dict[str, int]:
        return {name: i for i, name in enumerate(self.names)}

    def covariance(self) -> np.ndarray:
        if self.dense is not None:
            return self.dense
        if not self.factor_form:  # pragma: no cover -- constructors guarantee one or the other
            raise RiskModelError("risk model carries neither a dense covariance nor a factor form")
        return self.loadings @ self.factor_covariance @ self.loadings.T + np.diag(self.specific_var)

    def root(self) -> np.ndarray:
        """A matrix `R` with `R'R = Sigma`, via a clipped eigendecomposition.

        Used instead of `quad_form` in the optimiser: `sum_squares(R @ x)`
        is convex by construction, so a covariance that is a hair
        non-PSD from estimation noise cannot make the problem fail a
        convexity check.
        """
        covariance = self.covariance()
        eigenvalues, eigenvectors = np.linalg.eigh((covariance + covariance.T) / 2.0)
        eigenvalues = np.clip(eigenvalues, 0.0, None)
        return (eigenvectors * np.sqrt(eigenvalues)).T

    def tracking_error(self, weights: dict[str, float], benchmark: dict[str, float]) -> float:
        """Annualised tracking error of `weights` against `benchmark`.

        Names absent from the model contribute nothing, which is a real
        understatement rather than a rounding one -- callers check coverage
        (`coverage_of`) before trusting the number.
        """
        index_of = self.index_of()
        active = np.zeros(len(self.names))
        for name, weight in weights.items():
            if name in index_of:
                active[index_of[name]] += weight
        for name, weight in benchmark.items():
            if name in index_of:
                active[index_of[name]] -= weight
        variance = float(active @ self.covariance() @ active)
        return sqrt(max(variance, 0.0))

    def coverage_of(self, weights: dict[str, float]) -> float:
        covered = set(self.names)
        total = sum(weights.values())
        if total <= 0:
            return 0.0
        return sum(w for n, w in weights.items() if n in covered) / total


# --------------------------------------------------------------- estimators


def _returns_matrix(panel: dict[str, dict[str, float]], names: list[str]) -> tuple[np.ndarray, list[str]]:
    """Periods x names matrix from `{period: {company_id: return}}`.

    Periods are taken in sorted order and only periods with a value for
    every name are used -- a ragged panel silently filled with zeros would
    understate every covariance it touches.
    """
    periods = sorted(panel)
    usable = [p for p in periods if all(n in panel[p] for n in names)]
    if not usable:
        raise RiskModelError("no period in the returns panel covers every name in the universe")
    matrix = np.array([[panel[p][n] for n in names] for p in usable], dtype=float)
    return matrix, usable


def _ledoit_wolf(returns: np.ndarray) -> tuple[np.ndarray, float]:
    """Ledoit-Wolf (2004) shrinkage of the sample covariance toward a
    scaled identity, with the intensity derived from the data.

    Returns (covariance, shrinkage intensity). The per-period covariance;
    annualisation is the caller's.
    """
    periods, n = returns.shape
    centred = returns - returns.mean(axis=0, keepdims=True)
    sample = centred.T @ centred / periods

    mu = float(np.trace(sample)) / n
    target = mu * np.eye(n)

    d2 = float(np.sum((sample - target) ** 2)) / n
    if d2 <= 0:
        return sample, 0.0

    b2_bar = 0.0
    for t in range(periods):
        x = centred[t : t + 1].T  # n x 1
        b2_bar += float(np.sum((x @ x.T - sample) ** 2))
    b2_bar /= periods**2 * n
    b2 = min(b2_bar, d2)
    intensity = b2 / d2
    return intensity * target + (1.0 - intensity) * sample, intensity


def _build_loadings(
    candidates: list[IndexCandidate], names: list[str], factor_fields: list[str]
) -> tuple[np.ndarray, list[str]]:
    """Characteristic loadings: categorical fields become one-hot columns,
    numeric fields become cross-sectionally standardised columns, plus a
    market column of ones."""
    by_id = {c.company_id: c for c in candidates}
    columns: list[np.ndarray] = [np.ones(len(names))]
    labels: list[str] = ["market"]

    for field_name in factor_fields:
        numeric = [metric_value(by_id[n], field_name) for n in names]
        if all(v is not None for v in numeric):
            values = np.array(numeric, dtype=float)
            sd = values.std()
            columns.append((values - values.mean()) / sd if sd > 1e-12 else np.zeros(len(names)))
            labels.append(field_name)
            continue
        categories = [category_value(by_id[n], field_name) for n in names]
        distinct = sorted({c for c in categories if c is not None})
        # Drop one level: with a market column present, a full set of dummies
        # is collinear and the cross-sectional regression becomes singular.
        for level in distinct[1:]:
            columns.append(np.array([1.0 if c == level else 0.0 for c in categories]))
            labels.append(f"{field_name}={level}")
    return np.column_stack(columns), labels


def _factor_model(
    returns: np.ndarray, loadings: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Cross-sectional factor returns by period-wise least squares, then the
    factor covariance and specific variances. Per period; annualisation is
    the caller's."""
    periods = returns.shape[0]
    factor_returns = np.zeros((periods, loadings.shape[1]))
    residuals = np.zeros_like(returns)
    for t in range(periods):
        solution, *_ = np.linalg.lstsq(loadings, returns[t], rcond=None)
        factor_returns[t] = solution
        residuals[t] = returns[t] - loadings @ solution
    centred = factor_returns - factor_returns.mean(axis=0, keepdims=True)
    factor_covariance = centred.T @ centred / periods
    specific_var = residuals.var(axis=0)
    return factor_covariance, specific_var


def build_risk_model(
    spec: RiskModelSpec,
    candidates: list[IndexCandidate],
    returns_panel: dict[str, dict[str, float]],
) -> RiskModel:
    """Estimates a risk model from a returns panel.

    Deterministic: names are sorted, periods are taken in sorted order, and
    every estimator is a closed-form linear-algebra expression with no
    randomness or iteration count.
    """
    names = sorted({c.company_id for c in candidates})
    if not names:
        raise RiskModelError("cannot build a risk model over an empty universe")

    returns, periods_used = _returns_matrix(returns_panel, names)
    if len(periods_used) < spec.min_observations:
        raise RiskModelError(
            f"risk model needs at least {spec.min_observations} periods, the panel supplies {len(periods_used)}"
        )
    if spec.lookback_periods and len(periods_used) > spec.lookback_periods:
        returns = returns[-spec.lookback_periods :]
        periods_used = periods_used[-spec.lookback_periods :]

    annualise = spec.periods_per_year

    if spec.source == "sample":
        centred = returns - returns.mean(axis=0, keepdims=True)
        dense = centred.T @ centred / returns.shape[0]
        if returns.shape[0] <= len(names):
            # Not an error -- it is a fact about the estimate, and the caller
            # should see it rather than discover a singular matrix later.
            pass
        return RiskModel(
            names=names,
            source="sample",
            periods=returns.shape[0],
            periods_per_year=annualise,
            dense=dense * annualise,
        )

    if spec.source == "ledoit_wolf":
        dense, intensity = _ledoit_wolf(returns)
        return RiskModel(
            names=names,
            source="ledoit_wolf",
            periods=returns.shape[0],
            periods_per_year=annualise,
            dense=dense * annualise,
            shrinkage=intensity,
        )

    if spec.source == "factor":
        if not spec.factor_fields:
            raise RiskModelError("source='factor' needs at least one entry in factor_fields")
        loadings, labels = _build_loadings(candidates, names, spec.factor_fields)
        factor_covariance, specific_var = _factor_model(returns, loadings)
        return RiskModel(
            names=names,
            source="factor",
            periods=returns.shape[0],
            periods_per_year=annualise,
            loadings=loadings,
            factor_covariance=factor_covariance * annualise,
            specific_var=specific_var * annualise,
            factor_names=labels,
        )

    raise RiskModelError(f"unknown risk model source: {spec.source!r}")


def supplied_factor_model(
    names: list[str],
    loadings: list[list[float]],
    factor_covariance: list[list[float]],
    specific_var: list[float],
    *,
    factor_names: list[str] | None = None,
    periods_per_year: float = 252.0,
) -> RiskModel:
    """Wraps a vendor factor model -- loadings, factor covariance and
    specific risk -- in the same interface the estimators produce.

    This is the licensed path: a Barra or Axioma model file parses into
    exactly these three arrays, and nothing downstream changes. The inputs
    are assumed already annualised, because vendor files are.
    """
    loadings_array = np.asarray(loadings, dtype=float)
    factor_array = np.asarray(factor_covariance, dtype=float)
    specific_array = np.asarray(specific_var, dtype=float)
    if loadings_array.shape[0] != len(names):
        raise RiskModelError(f"loadings has {loadings_array.shape[0]} rows for {len(names)} names")
    if factor_array.shape[0] != loadings_array.shape[1] or factor_array.shape[0] != factor_array.shape[1]:
        raise RiskModelError("factor covariance must be square and match the loadings' factor count")
    if specific_array.shape[0] != len(names):
        raise RiskModelError("specific variance must have one entry per name")
    return RiskModel(
        names=list(names),
        source="supplied",
        periods=0,
        periods_per_year=periods_per_year,
        loadings=loadings_array,
        factor_covariance=factor_array,
        specific_var=specific_array,
        factor_names=factor_names or [f"f{i}" for i in range(factor_array.shape[0])],
    )
