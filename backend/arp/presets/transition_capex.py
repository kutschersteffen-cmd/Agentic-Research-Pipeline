"""Capex, R&D and redline facts for the transition-plan alignment score (D01.a), one value per fiscal year.

Amounts stay in the company's reporting currency (no FX). Applies only to companies in a transition-barrier sector."""

from __future__ import annotations

import json
from pathlib import Path

from arp.schemas.datapoints import (
    ApplicabilityRules,
    CheckConfig,
    DataPointSchema,
    FieldDefinition,
)
from arp.schemas.datapoints import (
    FieldDataType as T,
)

SCHEMA_ID = "sch_transition_capex"
BOOLEAN_FIELDS = ("tc_new_unabated_coal", "tc_new_blast_furnace", "tc_new_oil_gas_project")

_COMMON = (
    "Report each fiscal year disclosed under that year's period_end, in the reporting currency (never convert "
    "currencies): give the unit as the ISO 4217 code (USD, EUR, GBP, ...) with the scale word separate, for example "
    "'EUR million'."
)
_PLANNED = " This is a planned figure: report it under the period_end of the planned fiscal year."
_LOWCARBON = (
    " Low-carbon follows the ACT definition: nuclear and CCS/CCUS count; spending the company reports as EU "
    "Taxonomy-aligned counts; spending that is only Taxonomy-eligible but not aligned never counts; a company's own "
    "definition counts only if it states what it includes."
)

# (field_id, name, type, definition, extra instructions, enum values)
_FIELDS = [
    ("tc_capex_total", "Total capex", T.CURRENCY_AMOUNT,
     "Total capital expenditure for the year: the denominator the company uses with its low-carbon share.", "", None),
    ("tc_capex_denominator", "Capex denominator", T.ENUM,
     "Which total the capex figure is: EU Taxonomy capex, cash-flow capex, or another.", "", ["eu_taxonomy", "cash_flow", "other"]),
    ("tc_lowcarbon_capex", "Low-carbon capex", T.CURRENCY_AMOUNT, "Low-carbon capital expenditure for the year.", _LOWCARBON, None),
    ("tc_lowcarbon_capex_share_pct", "Low-carbon capex share", T.PERCENTAGE,
     "Low-carbon capex as a percentage of total capex, as the company discloses it.", _LOWCARBON, None),
    ("tc_capex_total_planned", "Total capex, planned", T.CURRENCY_AMOUNT, "Total capex planned for a future year.", _PLANNED, None),
    ("tc_lowcarbon_capex_planned", "Low-carbon capex, planned", T.CURRENCY_AMOUNT,
     "Low-carbon capex planned for a future year.", _PLANNED + _LOWCARBON, None),
    ("tc_lowcarbon_capex_share_pct_planned", "Low-carbon capex share, planned", T.PERCENTAGE,
     "Planned low-carbon capex share for a future year.", _PLANNED + _LOWCARBON, None),
    ("tc_carbon_intensive_capex", "Carbon-intensive capex", T.CURRENCY_AMOUNT,
     "Capital expenditure on fossil or carbon-intensive assets.", "", None),
    ("tc_rnd_total", "Total R&D spend", T.CURRENCY_AMOUNT, "Total research and development spend for the year.", "", None),
    ("tc_lowcarbon_rnd", "Low-carbon R&D", T.CURRENCY_AMOUNT, "R&D spend on low-carbon technologies.", _LOWCARBON, None),
    ("tc_lowcarbon_rnd_share_pct", "Low-carbon R&D share", T.PERCENTAGE,
     "Low-carbon share of R&D as the company discloses it.", _LOWCARBON, None),
    ("tc_lowcarbon_rnd_early", "Early-stage low-carbon R&D", T.CURRENCY_AMOUNT,
     "Low-carbon R&D spend on early-stage (not yet mature) technology.", _LOWCARBON, None),
    ("tc_new_unabated_coal", "New unabated coal plant", T.BOOLEAN,
     "The company builds, approves or plans a new unabated coal plant (Yes or No).", "", None),
    ("tc_new_blast_furnace", "New blast furnace", T.BOOLEAN,
     "The company builds, approves or plans new blast furnace capacity without CCS or a near-zero route (Yes or No).",
     " Relining or rebuilding an existing furnace at the same capacity is not new build.", None),
    ("tc_new_oil_gas_project", "New oil or gas project", T.BOOLEAN,
     "The company approved a new long-lead-time conventional oil or gas project after 2023 (Yes or No).", "", None),
]
FIELD_IDS = tuple(f[0] for f in _FIELDS)


def bundled_prefixes() -> list[str]:
    path = Path(__file__).parents[1] / "transition_alignment" / "data" / "benchmarks.json"
    sectors = json.loads(path.read_text(encoding="utf8"))["sectors"]
    return sorted({p for s in sectors.values() for p in s["isic_prefixes"]})


def _field(spec: tuple, prefixes: list[str]) -> FieldDefinition:
    fid, name, dtype, definition, extra, allowed = spec
    kw: dict = {}
    if dtype == T.CURRENCY_AMOUNT:
        kw["check_config"] = CheckConfig(non_negative=True)
    elif dtype == T.PERCENTAGE:
        kw.update(unit="%", check_config=CheckConfig(min_value=0, max_value=100))
    elif dtype == T.ENUM:
        kw["allowed_values"] = allowed
    return FieldDefinition(
        field_id=fid, name=name, description=definition, data_type=dtype,
        extraction_instructions=f"{definition} {_COMMON}{extra}", seed_keywords=[name.lower()],
        required=False, high_risk=True, version=1,
        applicability_rules=ApplicabilityRules(sector_codes=prefixes), **kw,
    )


def build_transition_capex_schema() -> DataPointSchema:
    prefixes = bundled_prefixes()
    return DataPointSchema(
        schema_id=SCHEMA_ID, name="Transition capex, R&D and redline facts",
        description="Capex, R&D and new-build facts for the transition-plan alignment score; transition-barrier sectors only.",
        fields=[_field(s, prefixes) for s in _FIELDS],
    )
