import json
from pathlib import Path

from arp.extraction.routing import route
from arp.presets.registry import PRESETS
from arp.presets.transition_plan import REQUIRES_YES, SCHEMA_ID, build_transition_plan_schema
from arp.schemas.datapoints import FieldDataType, FieldQuality
from arp.transition_plan.indicators import load_indicators
from tests.test_presets_transition_plan_rules import _check, _released, _row, _series


def test_registered():
    assert SCHEMA_ID == "transition_plan_indicators"
    assert PRESETS[SCHEMA_ID] is build_transition_plan_schema


def test_one_high_risk_boolean_field_per_indicator():
    fields = build_transition_plan_schema().fields
    assert len(fields) == 72  # the 64 indicators, then the number-rule helper fields (own tests)
    fields = fields[:64]
    assert {f.name for f in fields} == {i.identifier for i in load_indicators()}
    assert all(f.data_type == FieldDataType.BOOLEAN and f.high_risk and not f.required for f in fields)
    assert all(f.derived_rule is None for f in fields)


def test_every_indicator_has_3_to_8_keywords():
    kw = json.loads((Path(__file__).parents[1] / "arp/presets/data/transition_plan_keywords.json").read_text())
    assert set(kw) == {i.identifier for i in load_indicators()}
    assert all(3 <= len(v) <= 8 and len(set(v)) == len(v) for v in kw.values())
    assert all(f.seed_keywords == kw[f.name] for f in build_transition_plan_schema().fields[:64])


def test_field_mirrors_source_indicator():
    f = next(f for f in build_transition_plan_schema().fields if f.name == "A_headline_1")
    src = next(i for i in load_indicators() if i.identifier == "A_headline_1")
    assert (f.field_id, f.description, f.extraction_instructions) == ("tp_a_headline_1", src.question, src.guideline)


def test_field_ids_are_whitespace_free_and_unique():
    ids = [f.field_id for f in build_transition_plan_schema().fields]
    assert not any(c.isspace() for i in ids for c in i)
    assert len(set(ids)) == len(ids)
    assert "tp_a_fossil_fuels_50" in ids


def test_scope_1_target_guideline_asks_about_scope_1():
    f = next(f for f in build_transition_plan_schema().fields if f.name == "A_coverage_6")
    assert "reported for scope 1 emissions" in f.extraction_instructions
    assert "scope 2 emissions of the company" not in f.extraction_instructions
    assert f.version == 4  # the guideline changed (v2), the requires rule (v3), section-tag routing (v4); a released version can't be overwritten


# --- contradiction rules (spec 2026-10-21-retire-transition-plan-pipeline-design, section 2) ---

_MAIN = {f["field_id"]: f for f in json.loads(
    (Path(__file__).parent / "fixtures" / "transition_plan_preset_main.json").read_text())}
_PAIRS = {  # child -> parent, written out so a wrong REQUIRES_YES cannot hide behind itself
    "tp_a_headline_2": "tp_a_headline_1", "tp_a_ambition_4": "tp_a_ambition_3",
    "tp_a_ambition_5": "tp_a_headline_1", "tp_a_coverage_6": "tp_a_headline_1",
    "tp_a_coverage_7": "tp_a_headline_1", "tp_a_coverage_8": "tp_a_headline_1",
    "tp_a_pathway_12": "tp_a_pathway_11", "tp_a_progress_67": "tp_a_emissions_59",
    "tp_a_progress_68": "tp_a_emissions_60", "tp_a_progress_69": "tp_a_emissions_61",
}
_NUMBER_RULE_CHILDREN = ["tp_a_ambition_5", "tp_a_progress_67", "tp_a_progress_68", "tp_a_progress_69"]
_RULE_BEARING = set(_PAIRS) | {"tp_a_progress_70", "tp_a_progress_71", "tp_a_progress_72"}


def _built():
    return {f.field_id: f for f in build_transition_plan_schema().fields}


def test_requires_yes_lists_the_ten_pairs():
    assert REQUIRES_YES == _PAIRS


def test_child_fields_carry_requires_rules():  # AC-7
    fields = _built()
    for child, parent in _PAIRS.items():
        rule = fields[child].rules[-1].model_dump(mode="json")
        want = {"kind": "requires", "rule_id": "tp_r_req_" + child.removeprefix("tp_a_"),
                "field": parent, "equals": True, "when": True}
        assert {k: rule[k] for k in want} == want, child


def test_two_rule_fields_keep_number_rule_first():  # AC-8
    fields = _built()
    for fid in _NUMBER_RULE_CHILDREN:
        assert len(fields[fid].rules) == 2, fid
        assert fields[fid].rules[0].model_dump(mode="json") == _MAIN[fid]["rules"][0], fid


def test_rule_bearing_fields_are_exactly_13():  # AC-9
    assert {fid for fid, f in _built().items() if f.rules} == _RULE_BEARING


def test_versions():  # AC-10
    for fid, f in _built().items():
        assert f.version == _MAIN[fid]["version"] + (fid in _PAIRS) + (f.document_routing is not None), fid  # +1: routing


def test_everything_else_unchanged():  # AC-26
    got = build_transition_plan_schema().model_dump(mode="json")["fields"]
    assert [f["field_id"] for f in got] == list(_MAIN) and len(got) == 72
    for f in got:
        want = _MAIN[f["field_id"]]
        skip = {"rules", "version"} if f["field_id"] in _PAIRS else set()
        if f["document_routing"] is not None:  # section-tag routing (spec 2026-10-31-table-aware-extraction): AC-19d, test_versions
            skip |= {"version", "document_routing"}
        assert {k: v for k, v in f.items() if k not in skip} == {k: v for k, v in want.items() if k not in skip}


async def _headline(parent=True, child=True):
    rows = [_row("tp_a_headline_2", child)] + ([_row("tp_a_headline_1", parent)] if parent is not None else [])
    return rows, await _check(rows)


def _res(rows, fid, rule_id):
    (row,) = [r for r in rows if r.field_id == fid]
    (res,) = [c for c in row.checks if c.check_id == f"rule.{rule_id}"]
    return row, res


async def test_headline_2_without_headline_1_goes_to_review():  # AC-11, AC-12, AC-37, AC-38
    _, rows = await _headline(parent=False)
    row, res = _res(rows, "tp_a_headline_2", "tp_r_req_headline_2")
    spec = next(f for f in _released().fields if f.field_id == "tp_a_headline_2")
    r = route(row, FieldQuality(field_id=spec.field_id, version=spec.version, first_audit_passed=True), spec)
    assert res.outcome == "fail"
    assert r.kind == "review" and "check:rule.tp_r_req_headline_2" in r.reasons
    assert row.value is True


async def test_headline_2_with_headline_1_passes():  # AC-13
    _, rows = await _headline()
    assert _res(rows, "tp_a_headline_2", "tp_r_req_headline_2")[1].outcome == "pass"


async def test_headline_2_no_is_not_checked():  # AC-14
    _, rows = await _headline(parent=False, child=False)
    assert _res(rows, "tp_a_headline_2", "tp_r_req_headline_2")[1].outcome == "not_applicable"


async def test_missing_parent_fails_and_goes_to_review():  # AC-55, AC-56
    _, rows = await _headline(parent=None)
    row, res = _res(rows, "tp_a_headline_2", "tp_r_req_headline_2")
    spec = next(f for f in _released().fields if f.field_id == "tp_a_headline_2")
    r = route(row, FieldQuality(field_id=spec.field_id, version=spec.version, first_audit_passed=True), spec)
    assert res.outcome == "fail" and r.kind == "review"


async def test_progress_67_requires_rule_fails_while_number_rule_passes():  # AC-39, AC-40
    five = {2020: 100.0, 2021: 95.0, 2022: 90.0, 2023: 85.0, 2024: 80.0}
    rows = await _check([_row("tp_a_progress_67", True), _row("tp_a_emissions_59", False),
                         *_series("tp_h_scope1_emissions", five, "tCO2e")])
    assert _res(rows, "tp_a_progress_67", "tp_r_req_progress_67")[1].outcome == "fail"
    assert _res(rows, "tp_a_progress_67", "tp_r_progress_67")[1].outcome == "pass"
