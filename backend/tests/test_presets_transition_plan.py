import json
from pathlib import Path

from arp.presets.registry import PRESETS
from arp.presets.transition_plan import SCHEMA_ID, build_transition_plan_schema
from arp.schemas.datapoints import FieldDataType
from arp.transition_plan.indicators import load_indicators


def test_registered():
    assert SCHEMA_ID == "transition_plan_indicators"
    assert PRESETS[SCHEMA_ID] is build_transition_plan_schema


def test_one_high_risk_boolean_field_per_indicator():
    fields = build_transition_plan_schema().fields
    assert len(fields) == 64
    assert {f.name for f in fields} == {i.identifier for i in load_indicators()}
    assert all(f.data_type == FieldDataType.BOOLEAN and f.high_risk and not f.required for f in fields)
    assert all(f.derived_rule is None for f in fields)


def test_every_indicator_has_3_to_8_keywords():
    kw = json.loads((Path(__file__).parents[1] / "arp/presets/data/transition_plan_keywords.json").read_text())
    assert set(kw) == {i.identifier for i in load_indicators()}
    assert all(3 <= len(v) <= 8 and len(set(v)) == len(v) for v in kw.values())
    assert all(f.seed_keywords == kw[f.name] for f in build_transition_plan_schema().fields)


def test_field_mirrors_source_indicator():
    f = next(f for f in build_transition_plan_schema().fields if f.name == "A_headline_1")
    src = next(i for i in load_indicators() if i.identifier == "A_headline_1")
    assert (f.field_id, f.description, f.extraction_instructions) == ("tp_a_headline_1", src.question, src.guideline)


def test_field_ids_are_whitespace_free_and_unique():
    ids = [f.field_id for f in build_transition_plan_schema().fields]
    assert not any(c.isspace() for i in ids for c in i)
    assert len(set(ids)) == len(ids)
    assert "tp_a_fossil_fuels_50" in ids
