"""The transition-plan assessment: 64 indicators (Colesanti Senni et al. 2024) as a boolean criteria schema.

Each indicator is one high-risk boolean field running through the generic field pipeline. No derived
rule ships: the owner defines the aggregation later. Seven questions carry number rules that read eight
helper fields appended after the questions (spec 2026-10-18-transition-plan-number-rules-design). Ten
child questions also carry a `requires` rule that flags a YES whose parent question is not YES
(REQUIRES_YES; spec 2026-10-21-retire-transition-plan-pipeline-design). Field versions stay at the
default unless a field changed after the preset shipped (_VERSIONS)."""

from __future__ import annotations

import json
from pathlib import Path

from arp.schemas.datapoints import DataPointSchema, FieldDataType, FieldDefinition
from arp.schemas.rules import Condition, RequiresRule, SeriesRule, ThresholdRule
from arp.transition_plan.indicators import load_indicators

SCHEMA_ID = "transition_plan_indicators"
_KEYWORDS = Path(__file__).parent / "data" / "transition_plan_keywords.json"
REQUIRES_YES = {  # child field -> parent field that must also be YES
    "tp_a_headline_2": "tp_a_headline_1", "tp_a_ambition_4": "tp_a_ambition_3",
    "tp_a_ambition_5": "tp_a_headline_1", "tp_a_coverage_6": "tp_a_headline_1",
    "tp_a_coverage_7": "tp_a_headline_1", "tp_a_coverage_8": "tp_a_headline_1",
    "tp_a_pathway_12": "tp_a_pathway_11", "tp_a_progress_67": "tp_a_emissions_59",
    "tp_a_progress_68": "tp_a_emissions_60", "tp_a_progress_69": "tp_a_emissions_61",
}
_VERSIONS = {
    "A_coverage_6": 3,  # v2: guideline said "scope 2" in the scope 1 question; v3: requires rule
    "A_ambition_5": 3,  # v2: number rules added; v3: requires rule
    **{f"A_progress_{q}": 3 for q in range(67, 70)},
    **{f"A_progress_{q}": 2 for q in range(70, 73)},
    **{f"A_{n}": 2 for n in ("headline_2", "ambition_4", "coverage_7", "coverage_8", "pathway_12")},  # requires rule
}

_SERIES_INSTRUCTIONS = (
    "Report one value per fiscal year the document gives, for as many of the most recent years as it shows. "
    "Copy each number and its unit exactly as printed; never convert or estimate a year that is not given."
)


def _helpers() -> list[FieldDefinition]:
    """The numbers the number rules read. Ordinary, groupable fields: a rule flags, a reviewer decides."""
    def helper(field_id, name, data_type, unit, description, instructions, keywords):
        return FieldDefinition(
            field_id=field_id, name=name, description=description, data_type=data_type, unit=unit,
            extraction_instructions=instructions, seed_keywords=keywords, required=False,
        )

    target = (
        "The company's absolute GHG emission reduction target (not an intensity target) whose target year is "
        "nearest to and not after 2030; if it has none up to 2030, the absolute target with the nearest year. "
    )
    out = [
        helper("tp_h_target_pct", "Absolute target reduction", FieldDataType.PERCENTAGE, "%",
               "Percentage cut of the company's absolute GHG reduction target.",
               target + "Report its percentage reduction exactly as printed. Intensity targets never count.",
               ["absolute target", "reduction target", "GHG reduction", "emissions reduction", "% reduction",
                "2030 target"]),
        helper("tp_h_target_year", "Absolute target year", FieldDataType.NUMBER, None,
               "Target year of the company's absolute GHG reduction target.",
               target + "Report its target year as a four-digit year.",
               ["target year", "by 2030", "2030", "reduction target", "baseline"]),
    ]
    emissions = {
        1: ("Absolute scope 1 GHG emissions (direct emissions).", ["scope 1", "direct emissions", "GHG emissions", "tCO2e", "emissions table"]),
        2: ("Absolute scope 2 GHG emissions (purchased energy); market-based where both market- and location-based are given.",
            ["scope 2", "indirect emissions", "market-based", "location-based", "tCO2e"]),
        3: ("Absolute scope 3 GHG emissions, the total across categories.", ["scope 3", "value chain emissions", "indirect emissions", "tCO2e"]),
    }
    for scope, (what, keywords) in emissions.items():
        out.append(helper(f"tp_h_scope{scope}_emissions", f"Scope {scope} emissions", FieldDataType.NUMBER, "tCO2e",
                          what, f"{what} {_SERIES_INSTRUCTIONS}", keywords))
    for scope in (1, 2, 3):
        what = (f"Scope {scope} GHG emission intensity, in the company's own intensity unit "
                "(for example tCO2e per EUR million revenue).")
        out.append(helper(f"tp_h_scope{scope}_intensity", f"Scope {scope} intensity", FieldDataType.NUMBER, None,
                          what, f"{what} {_SERIES_INSTRUCTIONS}",
                          ["emission intensity", f"scope {scope} intensity", "tCO2e per", "intensity"]))
    return out


def _rules() -> dict[str, list]:
    """Each rule flags a YES whose numbers contradict it; it never changes the answer."""
    rules: dict[str, list] = {"A_ambition_5": [ThresholdRule(
        kind="threshold", rule_id="tp_r_ambition_5", when=True,
        conditions=[Condition(field="tp_h_target_pct", op=">=", value=50),
                    Condition(field="tp_h_target_year", op="<=", value=2030)],
    )]}
    for scope, (absolute, intensity) in {1: (67, 70), 2: (68, 71), 3: (69, 72)}.items():
        rules[f"A_progress_{absolute}"] = [SeriesRule(
            kind="series", rule_id=f"tp_r_progress_{absolute}", when=True,
            field=f"tp_h_scope{scope}_emissions", years=5, trend="none")]
        rules[f"A_progress_{intensity}"] = [SeriesRule(
            kind="series", rule_id=f"tp_r_progress_{intensity}", when=True,
            field=f"tp_h_scope{scope}_intensity", years=5, trend="down")]
    for child, parent in REQUIRES_YES.items():  # after any number rule
        identifier = "A_" + child.removeprefix("tp_a_")
        rules.setdefault(identifier, []).append(RequiresRule(
            kind="requires", rule_id="tp_r_req_" + child.removeprefix("tp_a_"), field=parent, equals=True, when=True))
    return rules


def build_transition_plan_schema() -> DataPointSchema:
    keywords = json.loads(_KEYWORDS.read_text(encoding="utf8"))
    rules = _rules()
    return DataPointSchema(
        schema_id=SCHEMA_ID,
        name="Transition plan indicators",
        description="The 64 yes/no assessment indicators for corporate climate transition plans "
                    "(targets, governance, strategy, tracking).",
        fields=[
            FieldDefinition(
                field_id="tp_" + i.identifier.lower().replace(" ", "_"), name=i.identifier, description=i.question,
                data_type=FieldDataType.BOOLEAN, extraction_instructions=i.guideline,
                seed_keywords=keywords[i.identifier], required=False, high_risk=True,
                version=_VERSIONS.get(i.identifier, 1), rules=rules.get(i.identifier, []),
            )
            for i in load_indicators()
        ] + _helpers(),
    )
