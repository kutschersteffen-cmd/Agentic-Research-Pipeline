"""Plan actions, operating regions and assumed prices for the transition-plan alignment match (Part A).

A plan holds many actions, so the action fields repeat: the facts of one action share one `basis`
(`action:<doc_id>:<page>:<n>`) and have no period_end. Applies only to companies in a transition-barrier sector."""

from __future__ import annotations

import json
from pathlib import Path

from arp.presets.transition_capex import bundled_prefixes
from arp.schemas.datapoints import (
    ApplicabilityRules,
    CheckConfig,
    DataPointSchema,
    FieldDefinition,
)
from arp.schemas.datapoints import (
    FieldDataType as T,
)

SCHEMA_ID = "sch_transition_plan_actions"
ACTION_FIELDS = (
    "ta_action_text", "ta_action_id", "ta_action_status", "ta_action_year", "ta_action_region",
    "ta_action_ghg_saving", "ta_action_capex_needed", "ta_action_capex_allocated",
)
OPERATES_FIELDS = ("ta_operates_eu", "ta_operates_us", "ta_operates_cn")
ASSUMPTION_FIELDS = ("ta_assumed_carbon_price", "ta_assumed_h2_cost")

_REGIONS = ["European Union", "United States", "China", "other"]
_CAPEX = (
    " Report it in the reporting currency (never convert): give the unit as the ISO 4217 code with the scale word "
    "separate, for example 'EUR million'."
)


def bundled_action_ids() -> list[str]:
    """Every action id in the bundled rule book (not the env-selected one: a field definition must not vary)."""
    path = Path(__file__).parents[1] / "transition_barrier" / "data" / "rule_book.json"
    actions = json.loads(path.read_text(encoding="utf8"))["actions"]
    return [a["id"] for sector in actions.values() for a in sector]


# (field_id, name, type, definition + instructions, enum values, seed keywords)
_FIELDS = [
    ("ta_action_text", "Plan action", T.STRING,
     "The action as the transition plan states it: one specific measure, technology or asset. Vague intentions "
     "(for example 'we will reduce emissions') are not actions.", None,
     ["transition plan", "decarbonisation lever", "abatement measure", "key actions", "decarbonisation roadmap"]),
    ("ta_action_id", "Action classification", T.ENUM,
     "Classify the action with exactly one id from the allowed list, or 'other' if none fits.", "ALLOWED",
     ["decarbonisation lever", "abatement lever", "transition lever", "key actions", "technology pathway"]),
    ("ta_action_status", "Action status", T.ENUM,
     "Whether the action is already implemented (in operation) or planned.", ["implemented", "planned"],
     ["implemented", "in operation", "commissioned", "planned", "will be implemented"]),
    ("ta_action_year", "Action year", T.NUMBER,
     "The calendar year the action is (or was) in operation. Leave empty if the plan states no year.", None,
     ["by 2030", "commissioning year", "in operation by", "start of operation", "timeline"]),
    ("ta_action_region", "Action region", T.ENUM,
     "Where the action takes place, if the plan states it.", _REGIONS,
     ["region", "location", "site", "European Union", "United States", "China"]),
    ("ta_action_ghg_saving", "Action GHG saving", T.NUMBER,
     "The quantified greenhouse gas saving the plan links to this action. Give the unit exactly as stated: "
     "'tCO2e/yr', 'MtCO2e/yr' or '%'.", None,
     ["emissions reduction", "GHG saving", "tCO2e", "MtCO2e", "abatement potential", "emissions avoided"]),
    ("ta_action_capex_needed", "Action capex needed", T.CURRENCY_AMOUNT,
     "The investment this action needs." + _CAPEX, None,
     ["investment required", "capex needed", "capital required", "investment need", "estimated cost"]),
    ("ta_action_capex_allocated", "Action capex allocated", T.CURRENCY_AMOUNT,
     "The funds allocated or approved for this action." + _CAPEX, None,
     ["allocated", "approved capex", "committed investment", "funding secured", "budget allocated"]),
    ("ta_operates_eu", "Operates in the European Union", T.BOOLEAN,
     "The company owns or operates production sites, plants, fleets or fields in the European Union (Yes or No).",
     None, ["production sites", "plants in Europe", "European Union", "operations in the EU", "manufacturing locations"]),
    ("ta_operates_us", "Operates in the United States", T.BOOLEAN,
     "The company owns or operates production sites, plants, fleets or fields in the United States (Yes or No).",
     None, ["production sites", "plants in the US", "United States", "operations in the US", "manufacturing locations"]),
    ("ta_operates_cn", "Operates in China", T.BOOLEAN,
     "The company owns or operates production sites, plants, fleets or fields in China (Yes or No).",
     None, ["production sites", "plants in China", "China", "operations in China", "manufacturing locations"]),
    ("ta_assumed_carbon_price", "Assumed carbon price", T.NUMBER,
     "A carbon price the plan assumes. Give the unit as '<currency>/tCO2', for example 'EUR/tCO2'. Use basis "
     "'region:<Region>' for the region it applies to, or 'region:any'; report the year it applies to as period_end "
     "(31 December), if stated.", None,
     ["carbon price", "internal carbon price", "EU ETS price", "shadow price", "price of carbon", "tCO2"]),
    ("ta_assumed_h2_cost", "Assumed hydrogen cost", T.NUMBER,
     "A hydrogen cost the plan assumes. Give the unit as '<currency>/kg H2', for example 'EUR/kg H2'. Use basis "
     "'region:<Region>' or 'region:any'; report the year it applies to as period_end (31 December), if stated.", None,
     ["hydrogen cost", "green hydrogen price", "cost of hydrogen", "H2 cost", "kg H2", "electrolyser cost"]),
]
FIELD_IDS = tuple(f[0] for f in _FIELDS)


def _field(spec: tuple, prefixes: list[str]) -> FieldDefinition:
    fid, name, dtype, instructions, allowed, keywords = spec
    kw: dict = {}
    if dtype == T.CURRENCY_AMOUNT:
        kw["check_config"] = CheckConfig(non_negative=True)
    elif dtype == T.ENUM:
        kw["allowed_values"] = [*bundled_action_ids(), "other"] if allowed == "ALLOWED" else allowed
    return FieldDefinition(
        field_id=fid, name=name, description=instructions, data_type=dtype, extraction_instructions=instructions,
        seed_keywords=keywords, required=False, high_risk=True, version=1,
        applicability_rules=ApplicabilityRules(sector_codes=prefixes), **kw,
    )


def build_transition_plan_actions_schema() -> DataPointSchema:
    prefixes = bundled_prefixes()
    return DataPointSchema(
        schema_id=SCHEMA_ID, name="Transition plan actions, regions and assumptions",
        description="Plan actions, operating regions and assumed prices for the transition-plan alignment match; transition-barrier sectors only.",
        fields=[_field(s, prefixes) for s in _FIELDS],
    )
