"""Data structures for the decarbonisation analyses.

Deliberately plain dataclasses rather than pydantic models: these are
research inputs assembled from whatever vendor panel the user has a licence
for, and validation belongs at the loading boundary, not on every row of a
firm-year panel.

The one piece of validation that is enforced here is `scope2_basis`, because
mixing location-based and market-based Scope 2 in a single series is the
error the review (section 3.1) identifies as most likely to produce a
spurious decarbonisation finding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

__all__ = [
    "Scope2Basis",
    "EmissionsBasis",
    "FirmYear",
    "Panel",
    "RED_FLAGS",
]


class Scope2Basis(str, Enum):
    """GHG Protocol Scope 2 accounting method.

    LOCATION reflects the grid the firm draws from; MARKET reflects the
    contracts and certificates it has bought. Schüder & Zülch (2026) find
    the SBTi effect present in MARKET and absent in LOCATION, so which one
    a study uses determines what it measures.
    """

    LOCATION = "location"
    MARKET = "market"


class EmissionsBasis(str, Enum):
    """Whether the figure was disclosed by the firm or modelled by a vendor.

    Kept as a first-class field because vendor estimation models are partly
    functions of revenue and sector, so a label built on estimated data
    partly encodes the estimator rather than the firm's behaviour.
    """

    REPORTED = "reported"
    ESTIMATED = "estimated"


@dataclass(slots=True)
class FirmYear:
    """One firm-year observation.

    Only `firm_id`, `year` and `scope1` are required. Everything else is
    optional because real panels are sparse, and the analyses here are
    written to degrade rather than to drop firms silently.
    """

    firm_id: str
    year: int
    scope1: float | None = None
    scope2: float | None = None
    scope2_basis: Scope2Basis | None = None
    scope2_market: float | None = None
    scope2_location: float | None = None
    scope3_material: float | None = None
    revenue: float | None = None
    evic: float | None = None
    basis: EmissionsBasis = EmissionsBasis.REPORTED
    sector: str | None = None
    region: str | None = None
    weight: float | None = None
    indicators: dict[str, bool] = field(default_factory=dict)
    red_flags: dict[str, bool] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)

    @property
    def scope12(self) -> float | None:
        if self.scope1 is None:
            return None
        return self.scope1 + (self.scope2 or 0.0)

    def intensity(self) -> float | None:
        """Scope 1+2 per unit revenue. None when revenue is absent or zero."""
        total = self.scope12
        if total is None or not self.revenue:
            return None
        return total / self.revenue


@dataclass(slots=True)
class Panel:
    """A firm-year panel, indexed lazily on construction."""

    rows: list[FirmYear]

    def __post_init__(self) -> None:
        bases = {r.scope2_basis for r in self.rows if r.scope2 is not None and r.scope2_basis is not None}
        if len(bases) > 1:
            raise ValueError(
                "Panel mixes Scope 2 accounting bases "
                f"({sorted(b.value for b in bases)}). Filter to one basis before analysis; "
                "see docs/CORPORATE_DECARBONISATION_REVIEW.md section 3.1."
            )

    @property
    def years(self) -> list[int]:
        return sorted({r.year for r in self.rows})

    @property
    def firm_ids(self) -> list[str]:
        return sorted({r.firm_id for r in self.rows})

    def by_year(self, year: int) -> dict[str, FirmYear]:
        return {r.firm_id: r for r in self.rows if r.year == year}

    def firm_series(self, firm_id: str) -> list[FirmYear]:
        return sorted((r for r in self.rows if r.firm_id == firm_id), key=lambda r: r.year)

    def filter(self, predicate) -> "Panel":
        return Panel([r for r in self.rows if predicate(r)])


# The seven dimensions from Brown, Hsu & Manya (2026), with the prevalence
# they report among pledging companies. Prevalence is carried here so that
# `redflags.compare_to_published_prevalence` can check whether a user's
# panel looks like the published population before conclusions are drawn.
RED_FLAGS: dict[str, float] = {
    "no_scope3_coverage": 0.70,
    "questionable_offsets": 0.40,
    "no_interim_targets": 0.21,
    "off_track_vs_target": 0.20,
    "no_implementation_plan": 0.18,
    "scope_disconnect": 0.11,
    "misaligned_lobbying": 0.10,
}
