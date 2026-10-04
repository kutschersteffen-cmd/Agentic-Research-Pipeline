"""EU Taxonomy reported KPIs (E22 B): the shares and totals a company prints in its mandatory Article 8 tables.

Extracted apart from the green schema (green.py): these are the company's own reported Taxonomy figures,
never derived. Amounts stay in the reporting currency (no FX)."""

from __future__ import annotations

from arp.schemas.datapoints import CheckConfig, DataPointSchema, FieldDataType, FieldDefinition

SCHEMA_ID = "sch_eu_taxonomy"
KPIS = {"turnover": "turnover", "capex": "capital expenditure (CapEx)", "opex": "operating expenditure (OpEx)"}
OBJECTIVES = {
    "ccm": "climate change mitigation", "cca": "climate change adaptation", "wtr": "water and marine resources",
    "ce": "circular economy", "ppc": "pollution prevention and control", "bio": "biodiversity and ecosystems",
}


def _common(k: str) -> str:
    return (
        f"Read the company's mandatory EU Taxonomy KPI tables (Article 8 Taxonomy Regulation, Disclosures Delegated Act "
        f"templates) for {KPIS[k]}. Report the figure exactly as the company prints it for each fiscal year disclosed; "
        "never compute or infer one. Use the company-wide total row, not a single activity. Percentages are 0-100."
    )


def _pct(k: str, suffix: str, name: str, what: str, keywords: list[str], **checks) -> FieldDefinition:
    return FieldDefinition(
        field_id=f"eut_{k}_{suffix}_pct", name=f"{name} ({KPIS[k]})", data_type=FieldDataType.PERCENTAGE, unit="%",
        description=f"{what} as a percentage of total {KPIS[k]}.",
        extraction_instructions=f"{_common(k)} {what}.", seed_keywords=[f"taxonomy {k}", *keywords],
        required=False, check_config=CheckConfig(**checks),
    )


def _kpi_fields(k: str) -> list[FieldDefinition]:
    a = f"eut_{k}_aligned_pct"
    return [
        _pct(k, "aligned", "Taxonomy-aligned share", "The Taxonomy-aligned share", ["taxonomy-aligned", "aligned"]),
        _pct(k, "eligible_not_aligned", "Taxonomy-eligible, not aligned share",
             "The share that is Taxonomy-eligible but not aligned", ["taxonomy-eligible", "not aligned"]),
        _pct(k, "not_eligible", "Taxonomy-non-eligible share", "The Taxonomy-non-eligible share",
             ["non-eligible", "not eligible"], sum_of=[a, f"eut_{k}_eligible_not_aligned_pct"], sum_target=100),
        *(_pct(k, f"aligned_{o}", f"Aligned share, {label}", f"The aligned share contributing to {label} ({o})",
               [label, "environmental objective"], part_of=a) for o, label in OBJECTIVES.items()),
        _pct(k, "enabling", "Enabling share", "The aligned share from enabling activities", ["enabling"], le_of=[a]),
        _pct(k, "transitional", "Transitional share", "The aligned share from transitional activities",
             ["transitional"], le_of=[a]),
        FieldDefinition(
            field_id=f"eut_{k}_total_amount", name=f"Total {KPIS[k]} (Taxonomy denominator)",
            data_type=FieldDataType.CURRENCY_AMOUNT, description=f"The total {KPIS[k]} the Taxonomy shares divide by.",
            extraction_instructions=f"{_common(k)} Give the total (denominator) amount in the reporting currency, never "
                                    "converted: unit as the ISO 4217 code (USD, EUR, GBP, ...) with the scale word separate, "
                                    "for example 'EUR million'.",
            seed_keywords=[f"total {k}", f"taxonomy {k}", "denominator"], required=False,
            check_config=CheckConfig(non_negative=True),
        ),
    ]


def build_eu_taxonomy_schema() -> DataPointSchema:
    return DataPointSchema(
        schema_id=SCHEMA_ID,
        name="EU Taxonomy reported KPIs",
        description="Taxonomy-aligned, eligible and non-eligible shares of turnover, CapEx and OpEx as reported (Article 8).",
        fields=[
            *(f for k in KPIS for f in _kpi_fields(k)),
            FieldDefinition(
                field_id="eut_nuclear_gas_reported", name="Nuclear and fossil gas activities reported",
                data_type=FieldDataType.ENUM, allowed_values=["yes", "no", "not_disclosed"],
                description="Whether the company reports the nuclear and fossil gas activities of the Complementary Delegated Act.",
                extraction_instructions="Read the Complementary Delegated Act Template 1 (nuclear and fossil gas activities) "
                                        "in the EU Taxonomy KPI tables: 'yes' if the company reports any such activity, 'no' if it "
                                        "states it has none, 'not_disclosed' if the template is absent.",
                seed_keywords=["nuclear", "fossil gas", "Template 1", "Complementary Delegated Act"], required=False,
            ),
            FieldDefinition(
                field_id="eut_reporting_year", name="Taxonomy reporting year", data_type=FieldDataType.DATE,
                description="The fiscal year the Taxonomy KPI tables cover.",
                extraction_instructions="The fiscal year-end date the EU Taxonomy KPI tables (Article 8) cover.",
                seed_keywords=["reporting year", "fiscal year", "taxonomy"], required=False,
            ),
        ],
    )
