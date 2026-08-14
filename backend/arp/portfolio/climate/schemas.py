from __future__ import annotations

from arp.schemas.datapoints import DataPointSchema, FieldDataType, FieldDefinition

CLIMATE_SCHEMA_ID = "sch_climate_core_v1"

FIELD_SCOPE1 = "climate_scope1_tco2e"
FIELD_SCOPE2 = "climate_scope2_tco2e"
FIELD_SCOPE3 = "climate_scope3_tco2e"
FIELD_CARBON_INTENSITY = "climate_carbon_intensity"
FIELD_EVIC = "climate_evic_eur_m"
FIELD_GREEN_REVENUE_PCT = "climate_green_revenue_pct"

_FIELDS: list[FieldDefinition] = [
    FieldDefinition(
        field_id=FIELD_SCOPE1,
        name="Scope 1 GHG emissions",
        data_type=FieldDataType.NUMBER,
        unit="tCO2e",
        description="Direct GHG emissions from owned/controlled sources, per the GHG Protocol.",
        extraction_instructions=(
            "Look in the sustainability report's GHG inventory table or CDP disclosure for 'Scope 1' "
            "emissions, most recent fiscal year."
        ),
        seed_keywords=["scope 1", "direct emissions", "GHG inventory"],
    ),
    FieldDefinition(
        field_id=FIELD_SCOPE2,
        name="Scope 2 GHG emissions",
        data_type=FieldDataType.NUMBER,
        unit="tCO2e",
        description="Indirect GHG emissions from purchased energy (location-based), per the GHG Protocol.",
        extraction_instructions=(
            "Look for 'Scope 2 (location-based)' in the same GHG inventory table as Scope 1; prefer "
            "location-based over market-based if both are disclosed."
        ),
        seed_keywords=["scope 2", "purchased energy", "location-based"],
    ),
    FieldDefinition(
        field_id=FIELD_SCOPE3,
        name="Scope 3 GHG emissions",
        data_type=FieldDataType.NUMBER,
        unit="tCO2e",
        description="Value-chain GHG emissions across the GHG Protocol's 15 categories, combined.",
        extraction_instructions="Sum disclosed Scope 3 category totals if broken out, otherwise use the disclosed aggregate figure.",
        seed_keywords=["scope 3", "value chain emissions"],
        required=False,
    ),
    FieldDefinition(
        field_id=FIELD_CARBON_INTENSITY,
        name="Carbon intensity",
        data_type=FieldDataType.NUMBER,
        unit="tCO2e / EUR M revenue",
        description="Scope 1+2 emissions normalized by total revenue.",
        extraction_instructions=(
            "Prefer a disclosed intensity figure directly; otherwise compute Scope 1 + Scope 2 divided by "
            "total revenue in EUR millions."
        ),
        seed_keywords=["carbon intensity", "emissions intensity"],
    ),
    FieldDefinition(
        field_id=FIELD_EVIC,
        name="Enterprise value including cash (EVIC)",
        data_type=FieldDataType.CURRENCY_AMOUNT,
        unit="EUR M",
        description=(
            "Market cap + total debt + minority interest + cash & equivalents -- the PCAF financed-emissions "
            "attribution denominator."
        ),
        extraction_instructions="Compute from balance sheet and market data as of the same fiscal year-end as the emissions figures.",
        seed_keywords=["enterprise value", "EVIC"],
    ),
    FieldDefinition(
        field_id=FIELD_GREEN_REVENUE_PCT,
        name="Green revenue share",
        data_type=FieldDataType.PERCENTAGE,
        unit="%",
        description=(
            "Share of revenue from taxonomy-aligned / low-carbon activities. Deliberately reuses the "
            "revenue-exposure cascade with 'green' as the taxonomy rather than a separate computation."
        ),
        extraction_instructions="Use the resolved revenue-exposure result for the company's mapped green taxonomy activities; do not re-derive independently.",
        seed_keywords=["green revenue", "taxonomy-aligned revenue", "EU taxonomy"],
        required=False,
    ),
]

_FIELDS_BY_ID = {f.field_id: f for f in _FIELDS}


def build_climate_schema() -> DataPointSchema:
    """The built-in, shipped climate data-point schema (§6 of the portfolio
    risk plan) -- every deployment starts with this consistent definition,
    but it's an ordinary `DataPointSchema` and editable the same way any
    user-authored one is.
    """
    return DataPointSchema(
        schema_id=CLIMATE_SCHEMA_ID,
        name="Climate Core Metrics",
        description="Built-in data-point schema for portfolio climate analytics.",
        fields=list(_FIELDS),
    )


def field_name(field_id: str) -> str:
    field = _FIELDS_BY_ID.get(field_id)
    return field.name if field else field_id
