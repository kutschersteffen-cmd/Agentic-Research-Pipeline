"""Delivery KPIs for the transition-plan alignment score: sector percentages, one value per fiscal year.

Each field applies only to its KPI's ISIC prefixes."""

from __future__ import annotations

from arp.schemas.datapoints import (
    ApplicabilityRules,
    CheckConfig,
    DataPointSchema,
    FieldDefinition,
)
from arp.schemas.datapoints import (
    FieldDataType as T,
)

SCHEMA_ID = "sch_transition_delivery_kpis"

_COMMON = "Report each fiscal year disclosed under that year's period_end."

# (field_id, name, ISIC prefixes, extraction instruction, seed keywords)
_FIELDS = [
    ("tc_alt_fuel_share_pct", "Alternative-fuel share of kiln heat", ("2394",),
     "Share of kiln thermal energy from alternative fuels, biomass included, CCS/CCU excluded (CEM 2.C, p.49).",
     ["alternative fuels", "alternative fuel rate", "thermal substitution rate", "biomass", "kiln fuel mix"]),
    ("tc_nh3_electrolytic_pct", "Electrolytic share of ammonia", ("201",),
     "Share of ammonia tonnes made with electrolysis-based hydrogen (CH p.76).",
     ["green ammonia", "electrolytic ammonia", "electrolysis-based hydrogen", "low-carbon ammonia"]),
    ("tc_meoh_electrolytic_pct", "Electrolytic share of methanol", ("201",),
     "Share of methanol tonnes made with electrolysis-based hydrogen (CH p.76).",
     ["green methanol", "electrolytic methanol", "electrolysis-based hydrogen", "e-methanol"]),
    ("tc_electrolysis_lc_power_pct", "Low-carbon power share of electrolysis", ("201",),
     "Share of electrolysis power from low-carbon sources (CH p.77).",
     ["electrolysis power", "renewable electricity for electrolysis", "low-carbon power", "green hydrogen power"]),
    ("tc_ccs_capex_share_pct", "CCS, CCUS and CDR share of capex", ("061", "062"),
     "CDR, CCS and CCUS capex as a share of total capex, with enhanced oil recovery excluded (OG p.57).",
     ["CCS capex", "CCUS", "carbon capture", "carbon dioxide removal", "share of capex"]),
    ("tc_zev_sales_share_pct", "Zero-emission share of truck sales", ("2910",),
     "Battery-electric and fuel-cell trucks as a share of truck units sold; plug-in hybrids do not count (AU p.119).",
     ["zero-emission trucks", "battery-electric trucks", "fuel-cell trucks", "ZEV sales", "share of unit sales"]),
    ("tc_fleet_lc_share_pct", "Low-carbon share of truck fleet", ("4923",),
     "Low-carbon vehicles as a share of the fleet. An ICE vehicle counts in proportion to its low-carbon fuel share, "
     "and only with a supply contract and verification (TR p.54).",
     ["low-carbon fleet", "zero-emission vehicles", "fleet composition", "alternative fuel vehicles"]),
    ("tc_saf_share_pct", "Sustainable aviation fuel share of jet fuel", ("511",),
     "SAF and synthetic fuel as a share of jet fuel energy, under the same contract condition (TR p.54).",
     ["sustainable aviation fuel", "SAF", "synthetic fuel", "SAF share", "jet fuel mix"]),
    ("tc_ship_lc_fuel_share_pct", "Low-emission fuel share of ship energy", ("501", "502"),
     "Biofuels, hydrogen, ammonia and low-emission methanol as a share of fuel energy, under the same contract "
     "condition.",
     ["low-emission fuels", "biofuels", "green methanol", "ammonia fuel", "alternative marine fuels"]),
]
FIELD_PREFIXES = {f[0]: f[2] for f in _FIELDS}


def _field(spec: tuple) -> FieldDefinition:
    fid, name, prefixes, instruction, keywords = spec
    return FieldDefinition(
        field_id=fid, name=name, description=instruction, data_type=T.PERCENTAGE, unit="%",
        check_config=CheckConfig(min_value=0, max_value=100),
        extraction_instructions=f"{instruction} {_COMMON}", seed_keywords=keywords,
        required=False, high_risk=True, version=1,
        applicability_rules=ApplicabilityRules(sector_codes=list(prefixes)),
    )


def build_transition_delivery_kpis_schema() -> DataPointSchema:
    return DataPointSchema(
        schema_id=SCHEMA_ID, name="Transition delivery KPIs",
        description="Sector delivery KPIs for the transition-plan alignment score; one percentage per fiscal year.",
        fields=[_field(s) for s in _FIELDS],
    )
