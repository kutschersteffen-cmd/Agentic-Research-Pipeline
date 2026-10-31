import json
from pathlib import Path

from arp.presets.green import build_green_schema
from arp.presets.transition_capex import BOOLEAN_FIELDS, build_transition_capex_schema
from arp.presets.transition_plan import build_transition_plan_schema
from arp.schemas.datapoints import FieldDataType
from arp.schemas.transition_plan import IndicatorCategory
from arp.transition_plan.indicators import load_indicators

# field_id -> version and document_routing of the three presets before table routing (this branch, before Task 5)
_MAIN = json.loads((Path(__file__).parent / "fixtures" / "table_routing_presets_main.json").read_text())


def _green(m: str):
    return [f for f in build_green_schema().fields if f.field_id.startswith((f"{m}_", f"green_{m}_", f"transition_{m}_"))]


def test_ac19_green_capex_fields_route_to_the_capex_table():
    fields = _green("capex")
    assert {"capex_total", "transition_capex_total", "green_capex_total"} <= {f.field_id for f in fields}
    assert all(f.document_routing.table_kinds == ["eu_taxonomy_capex"] for f in fields)


def test_ac19e_green_revenue_fields_route_to_the_turnover_table():
    assert all(f.document_routing.table_kinds == ["eu_taxonomy_turnover"] for f in _green("revenue"))


def test_ac19f_green_opex_fields_route_to_the_opex_table():
    assert all(f.document_routing.table_kinds == ["eu_taxonomy_opex"] for f in _green("opex"))


def test_ac19c_transition_capex_routing():
    fields = {f.field_id: f for f in build_transition_capex_schema().fields}
    for f in fields.values():
        if f.data_type in (FieldDataType.CURRENCY_AMOUNT, FieldDataType.PERCENTAGE, FieldDataType.ENUM):
            assert f.document_routing.table_kinds == ["eu_taxonomy_capex"], f.field_id
    assert BOOLEAN_FIELDS == ("tc_new_unabated_coal", "tc_new_blast_furnace", "tc_new_oil_gas_project")
    for fid in BOOLEAN_FIELDS:
        assert fields[fid].document_routing.section_tags == ["transition_plan", "climate_targets"]


def test_ac19d_transition_plan_routing_by_category():
    want = {
        IndicatorCategory.TARGET: ["climate_targets", "ghg_emissions", "transition_plan"],
        IndicatorCategory.TRACKING: ["climate_targets", "ghg_emissions", "transition_plan"],
        IndicatorCategory.GOVERNANCE: ["governance", "remuneration"],
        IndicatorCategory.STRATEGY: ["transition_plan", "climate_targets", "biodiversity", "water", "workforce"],
    }
    fields = {f.name: f for f in build_transition_plan_schema().fields}
    for i in load_indicators():
        assert fields[i.identifier].document_routing.section_tags == want[i.category], i.identifier


def test_ac19g_only_rerouted_fields_go_up_one_version():
    for schema in (build_green_schema(), build_transition_capex_schema(), build_transition_plan_schema()):
        main = _MAIN[schema.schema_id]
        assert set(main) == {f.field_id for f in schema.fields}
        for f in schema.fields:
            routing = f.document_routing and f.document_routing.model_dump(mode="json")
            changed = routing != main[f.field_id]["document_routing"]
            assert f.version == main[f.field_id]["version"] + changed, f.field_id
