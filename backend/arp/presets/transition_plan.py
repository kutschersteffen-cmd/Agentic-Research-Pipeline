"""The 64 transition-plan indicators (Colesanti Senni et al. 2024) as a boolean criteria schema.

Each indicator is one high-risk boolean field running through the generic field pipeline. No derived
rule ships: the owner defines the aggregation later. Field versions stay at the default unless the
indicator's text changed after the preset shipped (_VERSIONS)."""

from __future__ import annotations

import json
from pathlib import Path

from arp.schemas.datapoints import DataPointSchema, FieldDataType, FieldDefinition
from arp.transition_plan.indicators import load_indicators

SCHEMA_ID = "transition_plan_indicators"
_KEYWORDS = Path(__file__).parent / "data" / "transition_plan_keywords.json"
_VERSIONS = {"A_coverage_6": 2}  # v2: guideline said "scope 2" in the scope 1 question


def build_transition_plan_schema() -> DataPointSchema:
    keywords = json.loads(_KEYWORDS.read_text(encoding="utf8"))
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
                version=_VERSIONS.get(i.identifier, 1),
            )
            for i in load_indicators()
        ],
    )
