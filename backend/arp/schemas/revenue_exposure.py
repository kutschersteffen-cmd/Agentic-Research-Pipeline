from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from arp.schemas.common import Citation

RevenueCapexMetric = Literal["revenue", "capex"]
ExposureDataSource = Literal["catalogue", "extracted", "qualitative", "unresolved", "news"]


class CatalogueDataPoint(BaseModel):
    """One row of a user-supplied structured revenue/capex data catalogue
    (e.g. a vendor's revenue-by-product-line feed) -- the "path 1" hard-
    number source. Nothing here is fetched or fabricated by this system;
    the catalogue is always user-supplied, same as every other external
    dataset this codebase integrates (OECD ICIO, NACE/NAICS/SIC crosswalks,
    fund holdings).
    """

    data_point_id: str
    company_id: str
    metric: RevenueCapexMetric
    label: str = Field(description="The catalogue's own category/segment/product label for this line item.")
    description: str = ""
    value: float | None = Field(default=None, description="Absolute reported value. May be omitted if the row only carries as_pct_of_total.")
    unit: str = "USD"
    period: str = ""
    as_pct_of_total: float | None = Field(
        default=None,
        description="If the catalogue already expresses this row as a share of the company's total for this metric, use it directly. Otherwise share is computed against a label=\"Total Revenue\"/\"Total CapEx\" row for the same company.",
    )


class ActivityCatalogueMapping(BaseModel):
    """LLM-suggested (reviewable, never auto-applied) crosswalk from one
    taxonomy activity to one or more catalogue labels, for one metric."""

    activity_id: str
    metric: RevenueCapexMetric
    matched_labels: list[str] = Field(default_factory=list)
    rationale: str = ""


class ExposureCitation(Citation):
    schema_version: str = Field(default="", description="`<schema_id>:v<version>` of the schema the value was extracted under.")


class MetricExposure(BaseModel):
    """The resolved (or unresolved) 0-1 exposure signal for one company x
    activity x metric, and which source produced it. Originally
    revenue/capex-share-specific; also reused as-is by
    arp.schemas.rd_exposure.RDExposureResult for R&D-intensity and
    news-mention signals, since the shape (a fractional value, its
    provenance, a confidence, an optional grounded citation) is generic
    to any "resolved quantitative signal, maybe unresolved" result."""

    value_pct: float | None = None
    source: ExposureDataSource = "unresolved"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="1.0 for catalogue (deterministic); the extractor/verifier-derived confidence for extracted.")
    matched_catalogue_labels: list[str] = Field(default_factory=list)
    citation: ExposureCitation | None = None
    notes: str = ""


class RevenueExposureResult(BaseModel):
    """A company's revenue/capex/opex-based exposure to one taxonomy activity,
    resolved via the catalogue -> extraction -> qualitative cascade."""

    activity_id: str
    revenue: MetricExposure
    capex: MetricExposure
    opex: MetricExposure = Field(default_factory=MetricExposure, description="Extraction only: OpEx has no catalogue mapping.")
    sector_relevant: bool = Field(
        description="Whether the company's resolved ISIC code plausibly overlaps this activity's core_isic_codes -- gates whether path 2 (extraction) was attempted."
    )
