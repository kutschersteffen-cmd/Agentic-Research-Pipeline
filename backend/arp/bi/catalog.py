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
}
