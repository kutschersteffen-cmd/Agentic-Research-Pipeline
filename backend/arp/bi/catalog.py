"""Single source of truth for the BI layer: which datasets (views in the
``bi`` schema), columns, metrics and chart types the designer may use.
The views, validator, planner and compiler all import from here."""

from __future__ import annotations

from pydantic import BaseModel


class MetricDef(BaseModel):
    name: str
    expression: str
    description: str


class DatasetDef(BaseModel):
    table: str
    description: str
    columns: dict[str, str]  # column -> description
    metrics: list[MetricDef]


# Superset database (connection) that `arp bi bootstrap` registers for the `bi` schema.
BI_DATABASE = "arp_bi"

# The Superset viz_type values a generated chart may use.
VIZ_ALLOWLIST: tuple[str, ...] = (
    "big_number_total",
    "echarts_timeseries_bar",
    "echarts_timeseries_line",
    "pie",
    "table",
    "pivot_table_v2",
    "heatmap_v2",
    "treemap_v2",
)

_FACT_COLUMNS = {
    "company_id": "Company the fact is about.",
    "fact_key": "Name of the extracted field, e.g. a financial line item.",
    "fact_type": "Kind of value held: numeric or text.",
    "as_of": "Date the value applies to.",
    "value_num": "Numeric value, when the fact is numeric.",
    "value_text": "Text value, when the fact is textual.",
    "status": "Review status of the current fact.",
    "confidence": "Extraction confidence, 0 to 1.",
    "reviewer": "Reviewer who decided on the fact, if any.",
    "valid_from": "When this version of the fact became current.",
}

_FACT_METRICS = [
    MetricDef(name="Facts", expression="COUNT(*)", description="Number of facts."),
    MetricDef(name="Avg confidence", expression="AVG(confidence)", description="Mean extraction confidence."),
    MetricDef(
        name="Total value",
        expression="SUM(value_num)",
        description="Sum of numeric values. Only meaningful when filtered to a single fact_key.",
    ),
]

VIEW_DATASETS: dict[str, DatasetDef] = {
    "holdings": DatasetDef(
        table="holdings",
        description="Latest holdings snapshot per portfolio, joined to security and company.",
        columns={
            "portfolio_id": "Portfolio identifier.",
            "portfolio_name": "Portfolio name.",
            "as_of_date": "Snapshot date of the holding.",
            "security_id": "Security identifier.",
            "security_name": "Security name.",
            "isin": "ISIN of the security.",
            "asset_class": "Asset class of the security.",
            "currency": "Trading currency of the security.",
            "company_id": "Issuing company identifier.",
            "company_name": "Issuing company name.",
            "sector": "Sector of the issuing company.",
            "country": "Country of the issuing company.",
            "quantity": "Number of units held.",
            "market_value_eur": "Market value of the position in EUR.",
            "weight_pct": "Position weight in the portfolio, in percent.",
            "project_id": "Project the portfolio belongs to; NULL for portfolios outside any project.",
        },
        metrics=[
            MetricDef(name="Exposure (EUR)", expression="SUM(market_value_eur)", description="Total market value in EUR."),
            MetricDef(name="Holdings", expression="COUNT(*)", description="Number of positions."),
            MetricDef(name="Avg weight (%)", expression="AVG(weight_pct)", description="Mean position weight in percent."),
        ],
    ),
    "company_facts": DatasetDef(
        table="company_facts",
        description="Current approved, edited or auto-approved fact per company and field.",
        columns=_FACT_COLUMNS,
        metrics=_FACT_METRICS,
    ),
    "company_facts_pending": DatasetDef(
        table="company_facts_pending",
        description="Current facts still awaiting review (pending_review).",
        columns=_FACT_COLUMNS,
        metrics=_FACT_METRICS,
    ),
    "run_records": DatasetDef(
        table="run_records",
        description="One row per completed pipeline run result per company.",
        columns={
            "run_id": "Run identifier.",
            "run_type": "Pipeline that produced the record.",
            "company_id": "Company the record is about.",
            "needs_review": "Whether the record was flagged for human review.",
            "overall_confidence": "Overall confidence of the record, 0 to 1.",
            "generated_at": "When the record was generated.",
        },
        metrics=[
            MetricDef(name="Records", expression="COUNT(*)", description="Number of run records."),
            MetricDef(
                name="% needing review",
                expression="100.0 * AVG(CASE WHEN needs_review THEN 1 ELSE 0 END)",
                description="Share of records flagged for review, in percent.",
            ),
            MetricDef(name="Avg confidence", expression="AVG(overall_confidence)", description="Mean overall confidence."),
        ],
    ),
    "documents": DatasetDef(
        table="documents",
        description="Registry of ingested source documents.",
        columns={
            "doc_id": "Document identifier.",
            "company_id": "Company the document belongs to.",
            "doc_type": "Document type.",
            "title": "Document title.",
            "source_url": "Where the document was fetched from.",
            "first_seen_at": "When the document was first ingested.",
            "last_seen_at": "When the document was last seen at its source.",
        },
        metrics=[
            MetricDef(name="Documents", expression="COUNT(*)", description="Number of documents."),
            MetricDef(
                name="Companies with documents",
                expression="COUNT(DISTINCT company_id)",
                description="Distinct companies that have at least one document.",
            ),
        ],
    ),
    "portfolio_climate_metrics": DatasetDef(
        table="portfolio_climate_metrics",
        description="Monthly WACI, PCAF financed emissions and data coverage per portfolio, computed in Python by the monthly run.",
        columns={
            "portfolio_id": "Portfolio identifier.",
            "as_of_date": "Date the metrics were computed for (month end).",
            "waci": "Weighted-average carbon intensity.",
            "financed_emissions_tco2e": "Attributed Scope 1+2 financed emissions in tCO2e (PCAF).",
            "coverage_pct": "Share of market value covered by the emissions data, 0 to 1.",
            "uncovered_market_value_eur": "Market value in EUR excluded for lacking EVIC or Scope 1/2 data.",
        },
        metrics=[
            MetricDef(name="Avg WACI", expression="AVG(waci)", description="Mean weighted-average carbon intensity."),
            MetricDef(name="Avg coverage", expression="AVG(coverage_pct)", description="Mean data coverage, 0 to 1."),
            MetricDef(
                name="Avg financed emissions (tCO2e)",
                expression="AVG(financed_emissions_tco2e)",
                description="Mean financed emissions; one row per portfolio and month, so group by as_of_date.",
            ),
        ],
    ),
    "alerts": DatasetDef(
        table="alerts",
        description=(
            "Portfolio alerts as of each monthly run (one snapshot per month). "
            "Filter to one month, or counts repeat across months."
        ),
        columns={
            "month": "Monthly run (YYYY-MM) the snapshot belongs to.",
            "alert_id": "Alert identifier.",
            "portfolio_id": "Portfolio the alert is about; NULL for company-scoped alerts.",
            "company_id": "Company the alert is about; NULL for portfolio-scoped alerts.",
            "category": "Alert category.",
            "status": "Alert status: open, acknowledged, escalated, resolved or false_positive.",
            "triggered_at": "When the alert was raised.",
            "observed_value": "Value that breached the threshold.",
            "threshold_value": "Threshold that was breached.",
            "rationale": "Why the alert was raised.",
        },
        metrics=[
            MetricDef(
                name="Open alerts",
                expression="COUNT(CASE WHEN status = 'open' THEN 1 END)",
                description="Alerts with status open.",
            ),
            MetricDef(name="Alerts", expression="COUNT(*)", description="Alerts in the selected month(s); group by month."),
        ],
    ),
    "triggers": DatasetDef(
        table="triggers",
        description=(
            "Stewardship and risk triggers as of each monthly run (one snapshot per month). "
            "Filter to one month, or counts repeat across months."
        ),
        columns={
            "month": "Monthly run (YYYY-MM) the snapshot belongs to.",
            "trigger_id": "Trigger identifier.",
            "source": "Where the trigger came from: risk_alert or stewardship.",
            "issuer_id": "Issuer the trigger is about.",
            "type": "Trigger type.",
            "theme": "Stewardship theme.",
            "severity": "low, medium or high.",
            "status": "open, acknowledged or resolved.",
            "first_seen_month": "Month (YYYY-MM) the trigger first appeared.",
            "is_new": "Whether the trigger is new since the previous run.",
            "reason": "Why the trigger fired.",
        },
        metrics=[
            MetricDef(
                name="Open triggers",
                expression="COUNT(CASE WHEN status = 'open' THEN 1 END)",
                description="Triggers with status open.",
            ),
            MetricDef(name="Triggers", expression="COUNT(*)", description="Triggers in the selected month(s); group by month."),
        ],
    ),
    "company_profile": DatasetDef(
        table="company_profile",
        description=(
            "Latest resolved value per company and data field as of each monthly run (one snapshot per month). "
            "Filter to one month and one field_id."
        ),
        columns={
            "month": "Monthly run (YYYY-MM) the snapshot belongs to.",
            "company_id": "Company identifier.",
            "company_name": "Company name.",
            "field_id": "Data field identifier.",
            "field_name": "Data field name.",
            "value": "Numeric value; NULL when the field is not numeric.",
            "unit": "Unit of the value.",
            "as_of": "Date the value was observed.",
            "source": "Source of the value.",
        },
        metrics=[
            MetricDef(name="Avg value", expression="AVG(value)", description="Mean value. Only meaningful for a single field_id."),
            MetricDef(name="Companies", expression="COUNT(DISTINCT company_id)", description="Distinct companies."),
        ],
    ),
}

# Same columns and metrics as `holdings`, built from it so they cannot drift.
VIEW_DATASETS["holdings_history"] = VIEW_DATASETS["holdings"].model_copy(
    update={
        "table": "holdings_history",
        "description": (
            "Every holdings snapshot, joined to security and company. For charts over time only: "
            "the first groupby column must be as_of_date, because summing across snapshots double-counts. "
            "Use holdings for anything at a single as-of date."
        ),
    }
)

# Minimum groupby columns per viz type, as the compiler consumes them
# (axis charts: first column is the x axis; heatmap/pivot need a second one).
# big_number_total takes none and rejects any (see MAX_GROUPBY).
MIN_GROUPBY: dict[str, int] = {
    "big_number_total": 0,
    "echarts_timeseries_bar": 1,
    "echarts_timeseries_line": 1,
    "heatmap_v2": 2,
    "pivot_table_v2": 2,
    "pie": 1,
    "table": 0,
    "treemap_v2": 1,
}
# Columns the compiler would silently drop past this (heatmap: x and y axis only).
MAX_GROUPBY: dict[str, int] = {"big_number_total": 0, "heatmap_v2": 2}
# Viz types the compiler feeds a single `metric` (metrics[0]); a second one would be dropped.
MAX_METRICS: dict[str, int] = {"big_number_total": 1, "pie": 1, "heatmap_v2": 1, "treemap_v2": 1}

# Date/timestamp columns per dataset (cast with bi.safe_date / bi.safe_ts in views.py).
TEMPORAL_COLUMNS: dict[str, frozenset[str]] = {
    "holdings": frozenset({"as_of_date"}),
    "holdings_history": frozenset({"as_of_date"}),
    "company_facts": frozenset({"as_of", "valid_from"}),
    "company_facts_pending": frozenset({"as_of", "valid_from"}),
    "run_records": frozenset({"generated_at"}),
    "documents": frozenset({"first_seen_at", "last_seen_at"}),
    "portfolio_climate_metrics": frozenset({"as_of_date"}),
    "alerts": frozenset({"triggered_at"}),
    "triggers": frozenset(),
    "company_profile": frozenset({"as_of"}),
}
