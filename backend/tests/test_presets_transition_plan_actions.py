import json
from pathlib import Path

from arp.presets.registry import PRESETS
from arp.presets.transition_plan_actions import (
    ACTION_FIELDS,
    ASSUMPTION_FIELDS,
    FIELD_IDS,
    OPERATES_FIELDS,
    SCHEMA_ID,
    build_transition_plan_actions_schema,
    bundled_prefixes,
)
from arp.schemas.common import DocType
from arp.schemas.datapoints import FieldDataType as T

BUNDLED_RULE_BOOK = Path(__file__).parents[1] / "arp" / "transition_barrier" / "data" / "rule_book.json"


def _by_id():
    return {f.field_id: f for f in build_transition_plan_actions_schema().fields}


def test_fields_match_spec():
    f = _by_id()
    assert list(f) == list(FIELD_IDS) == [*ACTION_FIELDS, *OPERATES_FIELDS, *ASSUMPTION_FIELDS]
    assert ACTION_FIELDS == ("ta_action_text", "ta_action_id", "ta_action_status", "ta_action_year",
                             "ta_action_region", "ta_action_ghg_saving", "ta_action_capex_needed",
                             "ta_action_capex_allocated")
    assert {k: v.data_type for k, v in f.items()} == {
        "ta_action_text": T.STRING, "ta_action_id": T.ENUM, "ta_action_status": T.ENUM, "ta_action_year": T.NUMBER,
        "ta_action_region": T.ENUM, "ta_action_ghg_saving": T.NUMBER, "ta_action_capex_needed": T.CURRENCY_AMOUNT,
        "ta_action_capex_allocated": T.CURRENCY_AMOUNT, "ta_operates_eu": T.BOOLEAN, "ta_operates_us": T.BOOLEAN,
        "ta_operates_cn": T.BOOLEAN, "ta_assumed_carbon_price": T.NUMBER, "ta_assumed_h2_cost": T.NUMBER}
    assert f["ta_action_status"].allowed_values == ["implemented", "planned"]
    assert f["ta_action_region"].allowed_values == ["European Union", "United States", "China", "other"]
    assert all(u in f["ta_action_ghg_saving"].extraction_instructions for u in ("tCO2e/yr", "MtCO2e/yr", "%"))
    assert "/tCO2" in f["ta_assumed_carbon_price"].extraction_instructions
    assert "/kg H2" in f["ta_assumed_h2_cost"].extraction_instructions
    assert all(v.high_risk and not v.required and v.version == 1 for v in f.values())


def test_action_id_allowed_values():
    actions = json.loads(BUNDLED_RULE_BOOK.read_text())["actions"]
    ids = [a["id"] for sector in actions.values() for a in sector]
    allowed = _by_id()["ta_action_id"].allowed_values
    assert len(ids) == 29 and allowed == [*ids, "other"]


def test_sector_codes_and_keywords():
    for f in build_transition_plan_actions_schema().fields:
        assert f.applicability_rules.sector_codes == bundled_prefixes(), f.field_id
        kws = f.seed_keywords
        assert 3 <= len(kws) <= 8 and len(set(kws)) == len(kws), f.field_id


def test_registered():
    assert PRESETS[SCHEMA_ID]().schema_id == "sch_transition_plan_actions"


def test_doc_type_transition_plan():
    assert DocType("transition_plan") is DocType.TRANSITION_PLAN
