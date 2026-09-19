"""Statistical primitives, pure standard library.

The rest of `arp.decarb` deliberately avoids numpy/pandas/sklearn so the
analyses underpinning docs/CORPORATE_DECARBONISATION_REVIEW.md run in any
Python 3.11 environment with no install step. Research code that cannot be
re-run is not reproducible, and a carbon-data pipeline is already dependent
on enough licensed inputs without adding a scientific stack to the list.

Everything here is intentionally small and testable against hand-computed
values; see backend/tests/test_decarb_stats.py.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

__all__ = [
    "mean",
    "stdev",
    "pearson",
    "rank",
    "spearman",
    "phi_coefficient",
    "auc",
    "auc_stratified",
    "ols",
    "OLSResult",
    "logistic_regression",
    "winsorise",
    "log_mean",
]


def mean(xs: Sequence[float]) -> float:
    if not xs:
        raise ValueError("mean of empty sequence")
    return math.fsum(xs) / len(xs)


def stdev(xs: Sequence[float], *, sample: bool = True) -> float:
    n = len(xs)
    if n < 2:
        raise ValueError("stdev needs at least 2 observations")
    mu = mean(xs)
    ss = math.fsum((x - mu) ** 2 for x in xs)
    return math.sqrt(ss / (n - 1 if sample else n))


def pearson(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Pearson correlation. Returns 0.0 when either series is constant,
    which is the convention the callers here want: a constant indicator
    carries no information rather than an undefined amount of it.
    """
    if len(xs) != len(ys):
        raise ValueError("pearson requires equal-length sequences")
    if len(xs) < 2:
        raise ValueError("pearson needs at least 2 observations")
    mx, my = mean(xs), mean(ys)
    num = math.fsum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(math.fsum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(math.fsum((y - my) ** 2 for y in ys))
    if dx == 0.0 or dy == 0.0:
        return 0.0
    return num / (dx * dy)


def rank(xs: Sequence[float]) -> list[float]:
    """Fractional ranks with ties averaged, as Spearman requires."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        shared = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = shared
        i = j + 1
    return ranks


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Spearman rank correlation.

    Used for the transition-metric divergence matrix (Fliegel 2026), where
    rank correlation is the right choice because the metrics are on
    incomparable scales and only the ordering of firms is meaningful.
    """
    return pearson(rank(xs), rank(ys))


def phi_coefficient(a: Sequence[bool], b: Sequence[bool]) -> float:
    """Phi coefficient for two binary indicators (Pearson on 0/1).

    This is the statistic Brown, Hsu & Manya (2026) report between
    greenwashing red flags. Their finding that it is near zero for most
    pairs is what motivates `redflags.profile_is_multidimensional`.
    """
    if len(a) != len(b):
        raise ValueError("phi requires equal-length sequences")
    n11 = sum(1 for x, y in zip(a, b) if x and y)
    n10 = sum(1 for x, y in zip(a, b) if x and not y)
    n01 = sum(1 for x, y in zip(a, b) if not x and y)
    n00 = sum(1 for x, y in zip(a, b) if not x and not y)
    num = n11 * n00 - n10 * n01
    den = math.sqrt((n11 + n10) * (n01 + n00) * (n11 + n01) * (n10 + n00))
    if den == 0:
        return 0.0
    return num / den


def auc(scores: Sequence[float], labels: Sequence[bool]) -> float:
    """Area under the ROC curve via the Mann-Whitney U identity, with ties
    counted as half. Returns 0.5 when either class is empty.

    AUC rather than accuracy because the decarboniser label is imbalanced
    in most real samples and a threshold-free measure is what the
    saturation analysis needs to compare indicators across years.
    """
    if len(scores) != len(labels):
        raise ValueError("auc requires equal-length sequences")
    pos = [s for s, y in zip(scores, labels) if y]
    neg = [s for s, y in zip(scores, labels) if not y]
    if not pos or not neg:
        return 0.5
    wins = 0.0
    for p in pos:
        for q in neg:
            if p > q:
                wins += 1.0
            elif p == q:
                wins += 0.5
    return wins / (len(pos) * len(neg))


def auc_stratified(
    scores: Sequence[float],
    labels: Sequence[bool],
    strata: Sequence[object],
) -> float:
    """AUC pooled over within-stratum comparisons only.

    Plain AUC across a whole panel measures whatever dominates the outcome,
    which for emissions is sector: in a sample where one sector's emissions
    are growing 4 points a year faster than the rest, an indicator that is
    slightly more common in that sector will score below 0.5 regardless of
    what it does inside a sector.

    Pooling concordant pairs within strata removes that. Pairs spanning two
    strata are never compared, which is the point. Returns 0.5 when no
    within-stratum pair exists.
    """
    if not (len(scores) == len(labels) == len(strata)):
        raise ValueError("auc_stratified requires equal-length sequences")
    groups: dict[object, list[tuple[float, bool]]] = {}
    for s_, y, g in zip(scores, labels, strata):
        groups.setdefault(g, []).append((s_, y))
    wins = 0.0
    total = 0
    for rows in groups.values():
        pos = [s_ for s_, y in rows if y]
        neg = [s_ for s_, y in rows if not y]
        if not pos or not neg:
            continue
        for a in pos:
            for b in neg:
                if a > b:
                    wins += 1.0
                elif a == b:
                    wins += 0.5
        total += len(pos) * len(neg)
    if total == 0:
        return 0.5
    return wins / total


class OLSResult:
    """Coefficients plus the fit statistics the review actually quotes."""

    def __init__(self, coefficients: list[float], r_squared: float, n: int, k: int) -> None:
        self.coefficients = coefficients
        self.r_squared = r_squared
        self.n = n
        self.k = k

    @property
    def adj_r_squared(self) -> float:
        if self.n - self.k - 1 <= 0:
            return float("nan")
        return 1.0 - (1.0 - self.r_squared) * (self.n - 1) / (self.n - self.k - 1)

    def predict(self, row: Sequence[float]) -> float:
        return self.coefficients[0] + math.fsum(c * x for c, x in zip(self.coefficients[1:], row))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"OLSResult(n={self.n}, k={self.k}, r2={self.r_squared:.4f})"


def _solve(matrix: list[list[float]], rhs: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting."""
    n = len(matrix)
    aug = [row[:] + [rhs[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) < 1e-12:
            raise ValueError("singular design matrix; check for collinear regressors")
        aug[col], aug[pivot] = aug[pivot], aug[col]
        pv = aug[col][col]
        for r in range(n):
            if r == col:
                continue
            factor = aug[r][col] / pv
            if factor == 0.0:
                continue
            for c in range(col, n + 1):
                aug[r][c] -= factor * aug[col][c]
    return [aug[i][n] / aug[i][i] for i in range(n)]


def ols(x: Sequence[Sequence[float]], y: Sequence[float], *, ridge: float = 1e-8) -> OLSResult:
    """Ordinary least squares with an intercept, solved via normal equations.

    `ridge` is a tiny Tikhonov term for numerical stability only. It is not
    meant as regularisation; if a real design needs shrinkage the caller
    should say so explicitly rather than relying on this default.
    """
    n = len(y)
    if n == 0:
        raise ValueError("ols on empty sample")
    if len(x) != n:
        raise ValueError("ols requires len(x) == len(y)")
    k = len(x[0]) if x[0] is not None else 0
    design = [[1.0, *row] for row in x]
    p = k + 1
    if n <= p:
        raise ValueError(f"ols needs more observations ({n}) than parameters ({p})")
    xtx = [[math.fsum(design[i][a] * design[i][b] for i in range(n)) for b in range(p)] for a in range(p)]
    for i in range(p):
        xtx[i][i] += ridge
    xty = [math.fsum(design[i][a] * y[i] for i in range(n)) for a in range(p)]
    beta = _solve(xtx, xty)
    ybar = mean(y)
    ss_tot = math.fsum((v - ybar) ** 2 for v in y)
    ss_res = math.fsum((y[i] - math.fsum(beta[a] * design[i][a] for a in range(p))) ** 2 for i in range(n))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return OLSResult(beta, r2, n, k)


def logistic_regression(
    x: Sequence[Sequence[float]],
    y: Sequence[bool],
    *,
    max_iter: int = 100,
    tol: float = 1e-8,
    l2: float = 1e-4,
) -> list[float]:
    """Binary logistic regression by Newton-Raphson (IRLS), intercept first.

    L2 penalty defaults to a small positive value because separable
    indicator combinations are common in this data (a red flag that
    perfectly predicts the label inside one sector, for instance) and
    unpenalised IRLS diverges on them.
    """
    n = len(y)
    if n == 0:
        raise ValueError("logistic_regression on empty sample")
    k = len(x[0]) if n else 0
    design = [[1.0, *row] for row in x]
    p = k + 1
    beta = [0.0] * p
    for _ in range(max_iter):
        eta = [math.fsum(beta[a] * design[i][a] for a in range(p)) for i in range(n)]
        mu = [1.0 / (1.0 + math.exp(-max(-500.0, min(500.0, e)))) for e in eta]
        w = [max(m * (1.0 - m), 1e-10) for m in mu]
        grad = [
            math.fsum(design[i][a] * ((1.0 if y[i] else 0.0) - mu[i]) for i in range(n)) - l2 * beta[a]
            for a in range(p)
        ]
        hess = [
            [math.fsum(w[i] * design[i][a] * design[i][b] for i in range(n)) + (l2 if a == b else 0.0) for b in range(p)]
            for a in range(p)
        ]
        try:
            step = _solve(hess, grad)
        except ValueError:
            break
        beta = [beta[a] + step[a] for a in range(p)]
        if max(abs(s) for s in step) < tol:
            break
    return beta


def winsorise(xs: Sequence[float], *, lower: float = 0.01, upper: float = 0.99) -> list[float]:
    """Clip to empirical quantiles.

    Emissions growth rates have heavy tails, largely from restatements and
    from small denominators, and a handful of firms otherwise dominate any
    mean. Winsorising is preferred to dropping because the affected firms
    are not missing at random.
    """
    if not 0.0 <= lower < upper <= 1.0:
        raise ValueError("require 0 <= lower < upper <= 1")
    if not xs:
        return []
    ordered = sorted(xs)
    lo = ordered[min(len(ordered) - 1, int(lower * (len(ordered) - 1)))]
    hi = ordered[min(len(ordered) - 1, int(math.ceil(upper * (len(ordered) - 1))))]
    return [min(max(v, lo), hi) for v in xs]


def log_mean(a: float, b: float) -> float:
    """Logarithmic mean L(a,b) = (a-b)/(ln a - ln b), with L(a,a) = a.

    This is the weight function that makes the LMDI decomposition in
    `attribution.py` exactly additive. Defined for positive arguments only.
    """
    if a <= 0.0 or b <= 0.0:
        raise ValueError("log_mean requires strictly positive arguments")
    if abs(a - b) < 1e-15:
        return a
    return (a - b) / (math.log(a) - math.log(b))
