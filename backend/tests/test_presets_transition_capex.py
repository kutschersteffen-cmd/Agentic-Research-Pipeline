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
from arp.presets.transition_plan import REQUIRES_YES
from arp.schemas.common import CompanyRef
from arp.schemas.datapoints import FieldDataType, ValueState

SNAPSHOT = Path(__file__).parent / "fixtures" / "transition_alignment" / "presets_main.json"


def _shape(f):
    return {"field_id": f.field_id, "data_type": f.data_type.value, "version": f.version,
            "high_risk": f.high_risk, "extraction_instructions": f.extraction_instructions}


def test_ac47_existing_presets_unchanged():
    snap = json.loads(SNAPSHOT.read_text())
    for pid, fields in snap.items():
        if pid == "transition_plan_indicators":  # the 10 contradiction-rule children moved up one version (spec 2026-10-21)
            fields = [{**f, "version": f["version"] + (f["field_id"] in REQUIRES_YES)} for f in fields]
        if pid == "sch_green_lowcarbon":  # the three share fields moved to version 3 (spec 2026-10-31-extraction-quick-wins)
            fields = [{**f, "version": 3 if f["field_id"].endswith("_share_pct") else f["version"]} for f in fields]
        assert [_shape(f) for f in PRESETS[pid]().fields] == fields
    assert set(PRESETS) == set(snap) | {"sch_transition_capex", "sch_transition_plan_actions", "sch_transition_delivery_kpis"}


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


def test_every_field_has_3_to_8_unique_keywords():
    for f in build_transition_capex_schema().fields:
        kws = f.seed_keywords
        assert 3 <= len(kws) <= 8 and all(k.strip() for k in kws) and len(set(kws)) == len(kws), f.field_id


def test_planned_and_blast_furnace_sentences():
    by = {f.field_id: f for f in build_transition_capex_schema().fields}
    for fid in ("tc_capex_total_planned", "tc_lowcarbon_capex_planned", "tc_lowcarbon_capex_share_pct_planned"):
        assert "period_end of the planned fiscal year" in by[fid].extraction_instructions
    assert "same capacity is not new build" in by["tc_new_blast_furnace"].extraction_instructions
