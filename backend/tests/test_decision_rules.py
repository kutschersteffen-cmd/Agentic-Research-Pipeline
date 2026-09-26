from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from arp.decision.dataset import build_dataset, dataset_from_file
from arp.decision.diffing import describe_changes
from arp.decision.mechanism import apply_mechanism, derive_mechanism
from arp.decision.rules import apply_rules
from arp.decision.sensitivity import tipping_points
from arp.schemas.decision import Criterion, GateRule, MechanismConfig

SAMPLE = Path(__file__).resolve().parents[1] / "arp" / "decision" / "sample_data" / "example_transition_universe.csv"


def _node(node_id: str, node_type: str, **content) -> dict:
    node = {"id": node_id, "type": node_type, "name": node_id, "position": {"x": 0, "y": 0}}
    if content:
        node["content"] = {"passThrough": False, "inputField": None, "outputPath": None, "executionMode": "single", **content}
    return node


def graph(*middle: dict) -> dict:
    """input -> each middle node -> output, the shape the JDM editor saves."""
    nodes = [_node("in", "inputNode"), *middle, _node("out", "outputNode")]
    edges = []
    for n in middle:
        edges += [
            {"id": f"in-{n['id']}", "sourceId": "in", "targetId": n["id"], "type": "edge"},
            {"id": f"{n['id']}-out", "sourceId": n["id"], "targetId": "out", "type": "edge"},
        ]
    return {"nodes": nodes, "edges": edges}


def expressions(**pairs: str) -> dict:
    return _node("calc", "expressionNode", expressions=[{"id": k, "key": k, "value": v} for k, v in pairs.items()])


@pytest.fixture(scope="module")
def sample():
    return dataset_from_file(SAMPLE)


def test_formula_becomes_a_column_the_engine_can_score(sample):
    augmented, audit = apply_rules(sample, graph(expressions(capex_x2="green_capex_share_pct * 2")))
    assert augmented.columns[-1] == "capex_x2"
    first = sample.rows[0]
    assert augmented.rows[0]["capex_x2"] == str(int(first["Green_Capex_Share_pct"]) * 2)
    assert audit[0].decision == "1 calculated column"
    assert sample.columns[-1] != "capex_x2", "the source dataset is not mutated"


def test_and_condition_gates_through_the_ordinary_gate_rule(sample):
    """AND/OR composition is a calculated yes/no column plus an `is Yes`
    gate -- no second gate system."""
    config, _ = derive_mechanism(sample)
    config.rule_graph = graph(expressions(coal_without_target="coal_expansion_flag and not sbti_validated_target"))
    config.gates = [GateRule(column="coal_without_target", op="is", value="Yes", outcome="exclude")]
    result = apply_mechanism(sample, config)

    expected = {r["Company"] for r in sample.rows if r["Coal_Expansion_Flag"] == "Yes" and r["SBTi_Validated_Target"] == "No"}
    excluded = {e.name for e in result.entities if e.status == "excluded"}
    assert expected, "the sample must contain at least one such company for this test to mean anything"
    assert excluded == expected
    assert any(a.stage == "Rules" and "coal_without_target" in a.item for a in result.audit)


def test_calculated_column_can_be_a_criterion(sample):
    config, _ = derive_mechanism(sample)
    config.rule_graph = graph(expressions(green_share_x_weight="green_capex_share_pct * portfolio_weight_bps"))
    config.criteria.append(Criterion(column="green_share_x_weight", dimension_id=config.dimensions[0].id))
    result = apply_mechanism(sample, config)
    assert "green_share_x_weight" in result.effective_weights


def test_decision_table_expresses_or_across_rows():
    data = build_dataset(
        "t", [["name", "intensity", "coal"], ["a", "300", "Yes"], ["b", "300", "No"], ["c", "10", "Yes"], ["d", "10", "No"]]
    )
    table = _node(
        "table",
        "decisionTableNode",
        hitPolicy="first",
        inputs=[{"id": "i1", "name": "Intensity", "field": "intensity"}, {"id": "i2", "name": "Coal", "field": "coal"}],
        outputs=[{"id": "o1", "name": "Risk", "field": "risky"}],
        rules=[
            {"_id": "r1", "i1": "> 200", "i2": "", "o1": "true"},
            {"_id": "r2", "i1": "", "i2": "true", "o1": "true"},
            {"_id": "r3", "i1": "", "i2": "", "o1": "false"},
        ],
    )
    augmented, _ = apply_rules(data, graph(table))
    assert [r["risky"] for r in augmented.rows] == ["Yes", "Yes", "Yes", "No"]


def test_a_row_that_cannot_evaluate_gets_blanks_and_a_flag():
    data = build_dataset("t", [["name", "capex", "revenue"], ["a", "10", "100"], ["b", "", "100"]])
    augmented, audit = apply_rules(data, graph(expressions(ratio="capex / revenue * 100")))
    assert [r["ratio"] for r in augmented.rows] == ["10", ""]
    failure = next(a for a in audit if a.decision == "calculated values left blank")
    assert failure.needs_check and failure.item == "1 of 2 rows"


def test_rules_never_overwrite_a_source_column():
    data = build_dataset("t", [["name", "capex"], ["a", "10"]])
    augmented, audit = apply_rules(data, graph(expressions(capex="capex * 1000")))
    assert augmented.rows[0]["capex"] == "10"
    assert any(a.decision == "output ignored" and a.item == "capex" for a in audit)


def test_columns_with_awkward_names_are_reachable_by_slug():
    data = build_dataset("t", [["name", "Scope 1 (t)"], ["a", "5"]])
    augmented, _ = apply_rules(data, graph(expressions(doubled="scope_1_t * 2")))
    assert augmented.rows[0]["doubled"] == "10"


def test_code_nodes_are_refused():
    with pytest.raises(ValidationError, match="functionNode"):
        MechanismConfig(rule_graph=graph(_node("js", "functionNode", source="export const handler = () => ({})")))


def test_sensitivity_runs_with_rules(sample):
    config, _ = derive_mechanism(sample)
    config.rule_graph = graph(expressions(green_share_x_weight="green_capex_share_pct * portfolio_weight_bps"))
    config.criteria.append(Criterion(column="green_share_x_weight", dimension_id=config.dimensions[0].id))
    assert tipping_points(sample, config, steps=3)


def test_editing_the_graph_is_a_human_audit_entry(sample):
    before, _ = derive_mechanism(sample)
    before.rule_graph = graph(expressions(a="1"))
    after = before.model_copy(deep=True)
    after.rule_graph["nodes"][1]["content"]["expressions"][0]["value"] = "2"
    moved = before.model_copy(deep=True)
    moved.rule_graph["nodes"][1]["position"] = {"x": 500, "y": 80}

    entries = [e for e in describe_changes(before, after) if e.item == "Rule graph"]
    assert entries and entries[0].origin == "human" and "edited calc" in entries[0].decision
    assert not [e for e in describe_changes(before, moved) if e.item == "Rule graph"], "dragging a node is not an edit"
