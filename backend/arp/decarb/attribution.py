"""Log-ratio attribution of changes in a weighted carbon intensity metric.

Implements the decomposition LSEG (2026, Appendix IV) use to split a change
in weighted average carbon intensity into an emissions term, a normalisation
term and an allocation term. Their headline result is that the second and
third dominate the first, which is the empirical foundation for most of the
review's argument.

Method. WACI at time t is

    M_t = sum_k w_kt * E_kt / R_kt

Writing m_kt for the k-th summand, the exact additive decomposition is the
Logarithmic Mean Divisia Index (LMDI-I):

    dM = sum_k L(m_kt, m_kt-1) * [ ln(w_kt/w_kt-1)
                                 + ln(E_kt/E_kt-1)
                                 - ln(R_kt/R_kt-1) ]

where L is the logarithmic mean (stats.log_mean). The three bracketed terms
map onto allocation, emissions and normalisation respectively. The identity
is exact: `Attribution.residual` should be zero to floating-point precision
for a panel of continuing constituents, and the tests assert this.

Entries and exits have no log ratio, so their full contribution is assigned
to allocation. That matches the economic meaning (a constituent joining or
leaving is a pure composition effect) and keeps the decomposition additive.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from arp.decarb.schemas import FirmYear
from arp.decarb.stats import log_mean

__all__ = ["Attribution", "decompose_waci", "waci"]


@dataclass(slots=True)
class Attribution:
    """Additive contributions to the change in a weighted intensity metric."""

    start_value: float
    end_value: float
    emissions: float
    normalisation: float
    allocation: float
    n_continuing: int
    n_entered: int
    n_exited: int

    @property
    def total_change(self) -> float:
        return self.end_value - self.start_value

    @property
    def explained(self) -> float:
        return self.emissions + self.normalisation + self.allocation

    @property
    def residual(self) -> float:
        """Should be ~0. A non-trivial value means the identity broke."""
        return self.total_change - self.explained

    def as_pct_of_start(self) -> dict[str, float]:
        """Contributions rescaled to percent of the starting value, which is
        how attribution waterfalls are normally presented."""
        if self.start_value == 0:
            return {"emissions": float("nan"), "normalisation": float("nan"), "allocation": float("nan")}
        return {
            "emissions": self.emissions / self.start_value,
            "normalisation": self.normalisation / self.start_value,
            "allocation": self.allocation / self.start_value,
        }


def _weights(rows: dict[str, FirmYear]) -> dict[str, float]:
    """Portfolio weights. Uses an explicit weight where given, else equal."""
    explicit = {f: r.weight for f, r in rows.items() if r.weight is not None}
    if len(explicit) == len(rows) and rows:
        total = math.fsum(explicit.values())
        if total > 0:
            return {f: w / total for f, w in explicit.items()}
    n = len(rows)
    return {f: 1.0 / n for f in rows} if n else {}


def _usable(row: FirmYear) -> bool:
    return row.scope12 is not None and row.scope12 > 0 and bool(row.revenue) and row.revenue > 0


def waci(rows: dict[str, FirmYear]) -> float:
    """Weighted average carbon intensity over the usable rows."""
    usable = {f: r for f, r in rows.items() if _usable(r)}
    w = _weights(usable)
    return math.fsum(w[f] * (r.scope12 / r.revenue) for f, r in usable.items())


def decompose_waci(start_rows: dict[str, FirmYear], end_rows: dict[str, FirmYear]) -> Attribution:
    """Split the change in WACI between two periods into its three drivers.

    Only constituents with positive emissions and positive revenue in the
    relevant period enter the calculation; others cannot contribute a log
    ratio and are excluded rather than imputed.
    """
    start = {f: r for f, r in start_rows.items() if _usable(r)}
    end = {f: r for f, r in end_rows.items() if _usable(r)}
    w0, w1 = _weights(start), _weights(end)

    m0 = {f: w0[f] * (r.scope12 / r.revenue) for f, r in start.items()}
    m1 = {f: w1[f] * (r.scope12 / r.revenue) for f, r in end.items()}

    continuing = sorted(set(start) & set(end))
    entered = sorted(set(end) - set(start))
    exited = sorted(set(start) - set(end))

    emissions = normalisation = allocation = 0.0

    for f in continuing:
        a, b = m0[f], m1[f]
        if a <= 0.0 or b <= 0.0:
            allocation += b - a
            continue
        weight = log_mean(b, a)
        emissions += weight * math.log(end[f].scope12 / start[f].scope12)
        normalisation += -weight * math.log(end[f].revenue / start[f].revenue)
        allocation += weight * math.log(w1[f] / w0[f])

    # Perimeter changes are pure composition.
    for f in entered:
        allocation += m1[f]
    for f in exited:
        allocation -= m0[f]

    return Attribution(
        start_value=math.fsum(m0.values()),
        end_value=math.fsum(m1.values()),
        emissions=emissions,
        normalisation=normalisation,
        allocation=allocation,
        n_continuing=len(continuing),
        n_entered=len(entered),
        n_exited=len(exited),
    )
