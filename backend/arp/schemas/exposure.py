from __future__ import annotations

from pydantic import BaseModel, Field

from arp.schemas.common import now_iso


class RegionalExposure(BaseModel):
    """Upstream/downstream shares on the region-resolved model for the
    company's region group, split by the group of the core industry."""

    region: str
    upstream: float
    downstream: float
    upstream_by_region: dict[str, float]
    downstream_by_region: dict[str, float]


class IndirectExposureResult(BaseModel):
    """A company's structural (supply-chain) exposure to a theme's core
    industries, computed via Leontief input-output propagation -- entirely
    deterministic, no LLM judgment involved in the number itself.
    """

    company_id: str
    isic_code: str
    isic_label: str | None = None
    upstream_exposure: float = Field(
        ge=0.0, le=1.0, description="Share of this industry's total input requirement traceable to core sectors."
    )
    downstream_exposure: float = Field(
        ge=0.0, le=1.0, description="Share of this industry's total downstream propagation landing in core sectors."
    )
    core_sector: bool = Field(description="True if the company's own industry is itself one of the theme's core sectors.")
    critical_input: bool = Field(
        default=False,
        description="True if isic_code is one of the bundled USGS/IEA-flagged critical-mineral ISIC divisions "
        "(see arp.research.indirect_exposure.criticality) -- a coarse division-level heuristic, independent of "
        "the upstream/downstream Leontief exposure math.",
    )
    icio_edition: str = Field(description="Label identifying which input-output dataset produced this result.")
    end_market: dict[str, float] | None = Field(
        default=None,
        description="Share of the industry's final-demand-driven output by end market (households, government, "
        "investment, inventories). Null without final_demand.csv.",
    )
    theme_demand_share: float | None = Field(
        default=None, description="Share of the industry's output driven by final demand for the theme's core industries."
    )
    ghg_direct_t_per_meur: float | None = Field(default=None, description="Direct GHG intensity, t CO2e per million EUR output.")
    ghg_supply_chain_t_per_meur: float | None = Field(
        default=None, description="Direct plus supply-chain GHG intensity, t CO2e per million EUR output."
    )
    regional: RegionalExposure | None = Field(default=None, description="Exposure on the region-resolved model.")
    generated_at: str = Field(default_factory=now_iso)
