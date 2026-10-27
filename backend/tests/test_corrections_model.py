from arp.presets.transition_capex import build_transition_capex_schema
from arp.schemas.datapoints import Correction, ExtractedField
from arp.schemas.review import ReasonCode


def test_a_row_stored_before_corrections_loads_with_an_empty_list():  # AC-14
    row = ExtractedField.model_validate({"field_id": "f", "field_name": "F", "value": 1.0, "confidence": 0.5})
    assert row.corrections == []


def test_correction_round_trips():
    c = Correction(rule="label_map", attribute="value", original="Cash flow", corrected="cash_flow", reason="x")
    assert Correction.model_validate(c.model_dump(mode="json")) == c


def test_transition_capex_links_actual_fields_to_planned_siblings():
    links = {f.field_id: f.planned_field_id for f in build_transition_capex_schema().fields if f.planned_field_id}
    assert links == {"tc_capex_total": "tc_capex_total_planned", "tc_lowcarbon_capex": "tc_lowcarbon_capex_planned",
                     "tc_lowcarbon_capex_share_pct": "tc_lowcarbon_capex_share_pct_planned"}


def test_new_reason_codes():
    assert ReasonCode.AUTO_CORRECTED == "auto_corrected" and ReasonCode.PERIOD_MISSING == "period_missing"
