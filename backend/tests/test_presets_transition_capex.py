import json
from pathlib import Path

from arp.planning.applicability import plan_fields
from arp.presets.registry import PRESETS
from arp.presets.transition_capex import (
    BOOLEAN_FIELDS,
    FIELD_IDS,
    build_transition_capex_schema,
    bundled_prefixes,
)
from arp.schemas.common import CompanyRef
from arp.schemas.datapoints import FieldDataType, ValueState

SNAPSHOT = Path(__file__).parent / "fixtures" / "transition_alignment" / "presets_main.json"


def _shape(f):
    return {"field_id": f.field_id, "data_type": f.data_type.value, "version": f.version,
            "high_risk": f.high_risk, "extraction_instructions": f.extraction_instructions}


def test_ac47_existing_presets_unchanged():
    snap = json.loads(SNAPSHOT.read_text())
    for pid, fields in snap.items():
        assert [_shape(f) for f in PRESETS[pid]().fields] == fields
    assert set(PRESETS) == set(snap) | {"sch_transition_capex"}  # phase 2 adds sch_transition_plan_actions


def test_capex_fields_and_types():
    s = build_transition_capex_schema()
    assert [f.field_id for f in s.fields] == list(FIELD_IDS) and len(FIELD_IDS) == 15
    assert all(f.high_risk and not f.required for f in s.fields)
    assert {f.field_id for f in s.fields if f.data_type == FieldDataType.BOOLEAN} == set(BOOLEAN_FIELDS)


def test_sector_codes_are_bundled_union():
    assert all(f.applicability_rules.sector_codes == bundled_prefixes() for f in build_transition_capex_schema().fields)
    assert {"241", "351", "2394", "1050"} - set(bundled_prefixes()) == {"1050"}


def test_ac48_out_of_scope_company_extracts_nothing():
    to_extract, skipped = plan_fields(
        build_transition_capex_schema(), CompanyRef(company_id="q", name="Fixture Foods SA", isic_code="1050"))
    assert to_extract == [] and {f.value_state for f in skipped} == {ValueState.NOT_APPLICABLE}


def test_lowcarbon_instructions_exclude_eligible_not_aligned():
    f = {f.field_id: f for f in build_transition_capex_schema().fields}["tc_lowcarbon_capex"]
    assert "eligible" in f.extraction_instructions and "nuclear" in f.extraction_instructions
