"""Log-ratio attribution of changes in a weighted carbon intensity metric.

Splits a change in weighted average carbon intensity into an emissions term,
a normalisation term and an allocation term, which is the decomposition LSEG
(2026) use to show that the second and third dominate the first.

**On fidelity to LSEG.** Their Appendix IV states the method in prose -
"taking the logarithmic change of individual factors (index weight, carbon
emissions, revenues)" - but the equation itself is a raster image in the
published PDF and could not be read, so this was written from the prose.

Two candidate readings turn out to be the same estimator. Writing the three
log changes for a constituent as l_em, l_norm and l_alloc, their sum is
ln(m1/m0), and the logarithmic mean satisfies L(m1,m0) = (m1-m0)/ln(m1/m0).
So the LMDI contribution

    L(m1, m0) * l_em

is identically

    (m1 - m0) * l_em / (l_em + l_norm + l_alloc)

which is the same number as apportioning the realised change in proportion to
the log changes. The two readings coincide everywhere except where the three
log changes sum to zero, that is where a constituent's factors exactly cancel
and its contribution to WACI is unchanged.

That single case is the one LSEG's footnote 39 legislates: "in the unlikely
event that changes in individual factors exactly cancel ... the relative
contributions of individual factors will also be 0". LMDI does not do that -
it returns equal and opposite non-zero contributions summing to zero.
`decompose_waci_proportional` implements the footnote's rule; `decompose_waci`
implements LMDI. On any real panel the difference is confined to constituents
sitting exactly on that knife edge, so the two agree to displayed precision,
but the footnote is the one place their published method is pinned down and it
is worth matching exactly.

Method (LMDI-I). WACI at time t is

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

__all__ = ["Attribution", "decompose_waci", "decompose_waci_proportional", "waci"]


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


def decompose_waci_proportional(
    start_rows: dict[str, FirmYear], end_rows: dict[str, FirmYear]
) -> Attribution:
    """Apportion the realised WACI change in proportion to log factor changes.

    For each continuing constituent, the three log changes (weight, emissions,
    revenue) are computed, and that constituent's realised change in its
    contribution m_k is split between them in proportion to their signed log
    changes. Entries and exits go wholly to allocation, as in
    `decompose_waci`.

    Where the three log changes sum to zero for a constituent, its factor
    contributions are set to zero, which is the behaviour LSEG's footnote 39
    describes and the reason this variant exists.

    Like `decompose_waci`, the result is exactly additive.
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
        delta = m1[f] - m0[f]
        l_em = math.log(end[f].scope12 / start[f].scope12)
        l_norm = -math.log(end[f].revenue / start[f].revenue)
        l_alloc = math.log(w1[f] / w0[f])
        total_log = l_em + l_norm + l_alloc
        if abs(total_log) < 1e-15:
            # Factors exactly cancel: contributions are zero by construction.
            # Any residual delta is numerical and is charged to allocation so
            # the decomposition stays additive.
            allocation += delta
            continue
        emissions += delta * (l_em / total_log)
        normalisation += delta * (l_norm / total_log)
        allocation += delta * (l_alloc / total_log)

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
