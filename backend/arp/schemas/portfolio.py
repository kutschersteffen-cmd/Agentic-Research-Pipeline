from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from arp.schemas.common import new_id, now_iso

AssetClass = Literal["equity", "corporate_bond", "government_bond", "fund", "etf", "derivative", "cash", "other"]
AggregationMetric = Literal["market_value_sum", "weighted_avg_datapoint", "count"]
DataPointObservationSource = Literal["internal_api", "extracted", "catalogue", "estimated_proxy"]


class SecurityRef(BaseModel):
    """A tradeable instrument. `company_id` is the join key into every
    company-level result the rest of this codebase already produces
    (GICS sector, thematic exposure, extracted data points) -- see
    `entity_resolution.py` for how it gets populated from a bare ISIN."""

    security_id: str = Field(description="Stable identifier -- ISIN preferred, ticker/internal ID fallback.")
    isin: str | None = None
    name: str
    asset_class: AssetClass
    currency: str = Field(description="ISO 4217 code of the security's native quote currency.")
    company_id: str | None = None


class SecurityResolution(BaseModel):
    """Result of resolving a SecurityRef's issuer to a company_id. Kept
    separate from SecurityRef so a re-resolution (e.g. a security-master
    correction) never requires rewriting the security reference or any
    already-ingested holding that points at it.
    """

    security_id: str
    company_id: str | None
    confidence: float = Field(ge=0.0, le=1.0)
    method: Literal["isin_exact", "name_fuzzy", "manual"] = "isin_exact"
    needs_review: bool = False
    resolved_at: str = Field(default_factory=now_iso)


class Holding(BaseModel):
    """One position: one security, in one portfolio, as of one date.
    Immutable once written -- a correction is a new snapshot, not an edit."""

    portfolio_id: str
    security_id: str
    as_of_date: str
    quantity: float
    price: float
    market_value: float = Field(description="quantity * price, in the security's native currency.")
    fx_rate_to_eur: float = Field(default=1.0, description="As supplied by the custodian feed for this as_of_date.")
    market_value_eur: float = Field(description="market_value * fx_rate_to_eur -- the only cross-portfolio unit.")
    weight_pct: float | None = Field(default=None, description="Of portfolio NAV, if supplied/derivable.")


class Portfolio(BaseModel):
    portfolio_id: str
    name: str
    tags: list[str] = Field(default_factory=list, description='e.g. "mandate:equity", "client:institutional".')


class DataPointObservation(BaseModel):
    """One resolved value of one data-point field for one company, at one
    point in time. Append-only: a later correction is a new observation
    with a later `observed_at`, never an edit to a prior one, so a trend
    query reflects what was actually known at each point in time.
    """

    company_id: str
    field_id: str
    field_name: str
    value: float | str | bool | None
    unit: str | None = None
    period: str = Field(default="", description='Fiscal period the value applies to, e.g. "FY2025".')
    observed_at: str = Field(default_factory=now_iso)
    source: DataPointObservationSource
    conflicting_sources: bool = Field(
        default=False, description="True if an independent extraction pass disagreed with this value beyond tolerance."
    )
    conflicting_value: float | str | bool | None = None
    conflicting_source_label: str | None = None
    notes: str = ""


class AnalyticSpec(BaseModel):
    """A saved, reusable analytic: filter -> group-by -> aggregation mode.
    Executed entirely by the deterministic engine in `aggregation.py` --
    an LLM may draft one (see `qa_agent.py`) but never computes the number
    itself.
    """

    analytic_id: str = Field(default_factory=lambda: new_id("an"))
    name: str
    portfolio_filter: list[str] = Field(default_factory=list, description="Portfolio IDs; empty = all portfolios.")
    security_filter: dict[str, str] = Field(default_factory=dict, description='e.g. {"asset_class": "equity"}.')
    group_by: str = Field(description="Aggregation dimension name -- see aggregation.DIMENSIONS.")
    metric: AggregationMetric
    data_point_field_id: str | None = Field(default=None, description="Required when metric == weighted_avg_datapoint.")
    as_of: str | None = Field(default=None, description="Single snapshot date; None = latest.")
    date_range: tuple[str, str] | None = Field(default=None, description="[start, end] -- trend mode, one row-set per snapshot date in range.")
    created_at: str = Field(default_factory=now_iso)


class AggregationRow(BaseModel):
    group_value: str
    market_value_eur: float | None = None
    weighted_avg_value: float | None = None
    coverage_pct: float | None = Field(default=None, description="Share of this row's market value that had a resolved data-point value.")
    holding_count: int = 0


class AggregationResult(BaseModel):
    spec_name: str
    as_of: str
    metric: AggregationMetric
    group_by: str
    rows: list[AggregationRow]
    total_market_value_eur: float
    unresolved_market_value_eur: float = Field(
        default=0.0, description="Market value excluded from a weighted_avg_datapoint result for lacking the data point -- never folded silently into the average."
    )


class TrendPoint(BaseModel):
    as_of: str
    result: AggregationResult


class PivotSpec(BaseModel):
    """A two-dimension permutation of the same primitives AnalyticSpec uses --
    e.g. sector (rows) x asset_class (columns), or company_id (rows) x
    portfolio_id (columns) to see one exposure figure broken out across
    every portfolio at once. Point-in-time only (no trend mode)."""

    name: str = ""
    portfolio_filter: list[str] = Field(default_factory=list)
    security_filter: dict[str, str] = Field(default_factory=dict)
    row_dim: str
    col_dim: str
    metric: AggregationMetric
    data_point_field_id: str | None = None
    as_of: str | None = None


class PivotCell(BaseModel):
    row_value: str
    col_value: str
    market_value_eur: float | None = None
    weighted_avg_value: float | None = None
    coverage_pct: float | None = None
    holding_count: int = 0


class PivotResult(BaseModel):
    spec_name: str
    as_of: str
    metric: AggregationMetric
    row_dim: str
    col_dim: str
    row_values: list[str]
    col_values: list[str]
    cells: list[PivotCell]
    total_market_value_eur: float
    unresolved_market_value_eur: float = 0.0


class NewsItem(BaseModel):
    news_id: str = Field(default_factory=lambda: new_id("news"))
    company_id: str | None = None
    headline: str
    excerpt: str
    source_url: str | None = None
    published_at: str


class NewsRiskFlag(BaseModel):
    """A climate/controversy signal derived from one NewsItem. `quote` must
    be a verbatim substring of the source item's headline/excerpt --
    checked by `grounding.is_grounded`, same as every other citation in
    this codebase -- so a flag is always traceable to real text, never an
    LLM paraphrase presented as fact.
    """

    flag_id: str = Field(default_factory=lambda: new_id("flag"))
    news_id: str
    company_id: str
    category: Literal["climate_controversy", "regulatory", "litigation", "other"]
    severity: Literal["low", "medium", "high"]
    rationale: str
    quote: str
    grounded: bool = False
    generated_at: str = Field(default_factory=now_iso)
