"""The 64 transition-plan indicators (Colesanti Senni et al. 2024) as a boolean criteria schema.

Each indicator is one high-risk boolean field running through the generic field pipeline. No derived
rule ships: the owner defines the aggregation later. New preset, so field versions stay at the default."""

from __future__ import annotations

import json
from pathlib import Path

from arp.schemas.datapoints import DataPointSchema, FieldDataType, FieldDefinition
from arp.transition_plan.indicators import load_indicators

SCHEMA_ID = "transition_plan_indicators"
_KEYWORDS = Path(__file__).parent / "data" / "transition_plan_keywords.json"


def build_transition_plan_schema() -> DataPointSchema:
    keywords = json.loads(_KEYWORDS.read_text(encoding="utf8"))
    return DataPointSchema(
        schema_id=SCHEMA_ID,
        name="Transition plan indicators",
        description="The 64 yes/no assessment indicators for corporate climate transition plans "
                    "(targets, governance, strategy, tracking).",
        fields=[
            FieldDefinition(
                field_id=f"tp_{i.identifier.lower()}", name=i.identifier, description=i.question,
                data_type=FieldDataType.BOOLEAN, extraction_instructions=i.guideline,
                seed_keywords=keywords[i.identifier], required=False, high_risk=True,
            )
            for i in load_indicators()
        ],
    )
