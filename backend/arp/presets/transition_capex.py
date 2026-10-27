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

# (field_id, name, type, definition, extra instructions, enum values, seed keywords)
_FIELDS = [
    ("tc_capex_total", "Total capex", T.CURRENCY_AMOUNT,
     "Total capital expenditure for the year: the denominator the company uses with its low-carbon share.", "", None, ["capital expenditure", "capex", "additions to property, plant and equipment", "investments", "cash used in investing"]),
    ("tc_capex_denominator", "Capex denominator", T.ENUM,
     "Which total the capex figure is: EU Taxonomy capex, cash-flow capex, or another.", "", ["eu_taxonomy", "cash_flow", "other"], ["capex denominator", "taxonomy capex", "cash flow capex", "total capex basis"]),
    ("tc_lowcarbon_capex", "Low-carbon capex", T.CURRENCY_AMOUNT, "Low-carbon capital expenditure for the year.", _LOWCARBON, None, ["low-carbon capex", "green capex", "taxonomy-aligned capex", "CapEx KPI", "transition capex"]),
    ("tc_lowcarbon_capex_share_pct", "Low-carbon capex share", T.PERCENTAGE,
     "Low-carbon capex as a percentage of total capex, as the company discloses it.", _LOWCARBON, None, ["low-carbon capex share", "green capex share", "taxonomy-aligned capex %", "CapEx KPI", "share of capex"]),
    ("tc_capex_total_planned", "Total capex, planned", T.CURRENCY_AMOUNT, "Total capex planned for a future year.", _PLANNED, None, ["planned capex", "capex guidance", "capex plan", "expected capital expenditure", "capex outlook"]),
    ("tc_lowcarbon_capex_planned", "Low-carbon capex, planned", T.CURRENCY_AMOUNT,
     "Low-carbon capex planned for a future year.", _PLANNED + _LOWCARBON, None, ["planned low-carbon capex", "low-carbon capex plan", "green capex target", "capex alignment plan", "future green investment"]),
    ("tc_lowcarbon_capex_share_pct_planned", "Low-carbon capex share, planned", T.PERCENTAGE,
     "Planned low-carbon capex share for a future year.", _PLANNED + _LOWCARBON, None, ["planned low-carbon capex share", "capex alignment target", "green capex target %", "taxonomy-aligned capex plan"]),
    ("tc_carbon_intensive_capex", "Carbon-intensive capex", T.CURRENCY_AMOUNT,
     "Capital expenditure on fossil or carbon-intensive assets.", "", None, ["carbon-intensive capex", "fossil fuel capex", "upstream oil and gas capex", "coal capex", "high-carbon assets"]),
    ("tc_rnd_total", "Total R&D spend", T.CURRENCY_AMOUNT, "Total research and development spend for the year.", "", None, ["research and development", "R&D", "R&D expenditure", "R&D spend", "innovation spend"]),
    ("tc_lowcarbon_rnd", "Low-carbon R&D", T.CURRENCY_AMOUNT, "R&D spend on low-carbon technologies.", _LOWCARBON, None, ["low-carbon R&D", "clean technology R&D", "decarbonisation R&D", "green R&D", "innovation"]),
    ("tc_lowcarbon_rnd_share_pct", "Low-carbon R&D share", T.PERCENTAGE,
     "Low-carbon share of R&D as the company discloses it.", _LOWCARBON, None, ["low-carbon R&D share", "share of R&D", "clean technology R&D %", "green R&D %"]),
    ("tc_lowcarbon_rnd_early", "Early-stage low-carbon R&D", T.CURRENCY_AMOUNT,
     "Low-carbon R&D spend on early-stage (not yet mature) technology.", _LOWCARBON, None, ["early-stage R&D", "low-carbon R&D early stage", "pilot and demonstration", "technology readiness level", "venture investments"]),
    ("tc_new_unabated_coal", "New unabated coal plant", T.BOOLEAN,
     "The company builds, approves or plans a new unabated coal plant (Yes or No).", "", None, ["new coal plant", "unabated coal", "coal-fired", "coal power expansion", "coal phase-out"]),
    ("tc_new_blast_furnace", "New blast furnace", T.BOOLEAN,
     "The company builds, approves or plans new blast furnace capacity without CCS or a near-zero route (Yes or No).",
     " Relining or rebuilding an existing furnace at the same capacity is not new build.", None, ["blast furnace", "new blast furnace", "new capacity", "BF-BOF", "ironmaking capacity"]),
    ("tc_new_oil_gas_project", "New oil or gas project", T.BOOLEAN,
     "The company approved a new long-lead-time conventional oil or gas project after 2023 (Yes or No).", "", None, ["new oil and gas project", "final investment decision", "sanctioned", "long-lead-time project", "FID"]),
]
FIELD_IDS = tuple(f[0] for f in _FIELDS)
AMOUNT_FIELDS = tuple(f[0] for f in _FIELDS if f[2] == T.CURRENCY_AMOUNT)  # preset field order


def bundled_prefixes() -> list[str]:
    path = Path(__file__).parents[1] / "transition_alignment" / "data" / "benchmarks.json"
    sectors = json.loads(path.read_text(encoding="utf8"))["sectors"]
    return sorted({p for s in sectors.values() for p in s["isic_prefixes"]})


_PLANNED_OF = {"tc_capex_total": "tc_capex_total_planned", "tc_lowcarbon_capex": "tc_lowcarbon_capex_planned",
               "tc_lowcarbon_capex_share_pct": "tc_lowcarbon_capex_share_pct_planned"}


def _field(spec: tuple, prefixes: list[str]) -> FieldDefinition:
    fid, name, dtype, definition, extra, allowed, keywords = spec
    kw: dict = {}
    if dtype == T.CURRENCY_AMOUNT:
        kw["check_config"] = CheckConfig(non_negative=True)
    elif dtype == T.PERCENTAGE:
        kw.update(unit="%", check_config=CheckConfig(min_value=0, max_value=100))
    elif dtype == T.ENUM:
        kw["allowed_values"] = allowed
    return FieldDefinition(
        field_id=fid, name=name, description=definition, data_type=dtype,
        extraction_instructions=f"{definition} {_COMMON}{extra}", seed_keywords=keywords,
        required=False, high_risk=True, version=1, planned_field_id=_PLANNED_OF.get(fid),
        applicability_rules=ApplicabilityRules(sector_codes=prefixes), **kw,
    )


def build_transition_capex_schema() -> DataPointSchema:
    prefixes = bundled_prefixes()
    return DataPointSchema(
        schema_id=SCHEMA_ID, name="Transition capex, R&D and redline facts",
        description="Capex, R&D and new-build facts for the transition-plan alignment score; transition-barrier sectors only.",
        fields=[_field(s, prefixes) for s in _FIELDS],
    )
