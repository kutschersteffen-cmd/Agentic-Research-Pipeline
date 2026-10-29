"""AC-12, AC-13 (values), AC-15 (trace), AC-17..AC-21, AC-29b: rule evaluation into verdicts, no database."""

from __future__ import annotations

import pytest

from arp.authoritative.evaluate import check_outputs, evaluate
from arp.authoritative.source_values import COMPANION
from arp.decision.dataset import Dataset
from arp.schemas.decision import AuthoritativeOutput, MechanismConfig

F_VALUE = "scope1_tco2e__status == 'approved' ? scope1_tco2e : prov_esg_demo_scope1"
F_PERIOD = "scope1_tco2e__status == 'approved' ? scope1_tco2e__period_end : prov_esg_demo_scope1__period_end"


def _row(company, prov, ext, ext_status):
    row = {"company_id": company, "Company": company}
    for alias, value, period, status, source, provider, obs in (
        ("prov_esg_demo_scope1", prov, "2026-09-30", "auto_accepted", "provider", "esg_demo", "11"),
        ("scope1_tco2e", ext, "2025-12-31", ext_status, "extraction", "", "12"),
    ):
        present = value != ""
        row[alias] = value
        row.update({f"{alias}__{c}": "" for c in COMPANION})
        if present:
            row.update({f"{alias}__period_end": period, f"{alias}__status": status, f"{alias}__source": source,
                        f"{alias}__provider": provider, f"{alias}__unit": "tCO2e", f"{alias}__observation_id": obs})
    return row


@pytest.fixture
def d1() -> Dataset:
    rows = [_row("A", "100", "90", "approved"), _row("B", "50", "", "")]
    return Dataset(dataset_id="ds_d1", name="D1", columns=list(rows[0]), rows=rows, source="source_values", as_of="2026-10-15")


def _graph(**expressions) -> dict:
    return {
        "nodes": [
            {"id": "in", "type": "inputNode", "name": "Input", "position": {"x": 0, "y": 0}},
            {"id": "rules", "type": "expressionNode", "name": "Authoritative", "position": {"x": 0, "y": 0},
             "content": {"expressions": [{"id": k, "key": k, "value": v} for k, v in expressions.items()]}},
            {"id": "out", "type": "outputNode", "name": "Output", "position": {"x": 0, "y": 0}},
        ],
        "edges": [{"id": "e1", "sourceId": "in", "targetId": "rules", "type": "edge"},
                  {"id": "e2", "sourceId": "rules", "targetId": "out", "type": "edge"}],
    }


def _config(outputs: list[str], **expressions) -> MechanismConfig:
    return MechanismConfig(
        framework_id="fw_f", version=1, purpose="authoritative", dataset_id="ds_d1", rule_graph=_graph(**expressions),
        outputs=[AuthoritativeOutput(column=c, name=c) for c in outputs],
    )


def _by(verdicts, company, output):
    return next(v for v in verdicts if v.company_id == company and v.output == output)


def test_ac_13_f_values_and_periods(d1):
    verdicts = evaluate(d1, _config(["auth_scope1"], auth_scope1=F_VALUE, auth_scope1__period_end=F_PERIOD), snapshot_id="s1")
    assert len(verdicts) == 2
    a, b = _by(verdicts, "A", "auth_scope1"), _by(verdicts, "B", "auth_scope1")
    assert (a.status, a.value, a.period_end) == ("value", 90, "2025-12-31")
    assert (b.status, b.value, b.period_end) == ("value", 50, "2026-09-30")


def test_ac_14_derivation_inputs(d1):
    a = _by(evaluate(d1, _config(["auth_scope1"], auth_scope1=F_VALUE), snapshot_id="s1"), "A", "auth_scope1")
    ext = a.derivation["inputs"]["scope1_tco2e"]
    assert ext == {"value": 90, "status": "approved", "source": "extraction", "provider": None,
                   "period_end": "2025-12-31", "unit": "tCO2e", "observation_id": 12}


def test_ac_15_trace_and_provenance(d1):
    config = _config(["auth_scope1"], auth_scope1=F_VALUE)
    a = _by(evaluate(d1, config, snapshot_id="s1"), "A", "auth_scope1")
    assert any(node["output"].get("auth_scope1") == 90 and F_VALUE in node["expressions"] for node in a.derivation["trace"])
    assert a.derivation["framework_id"] == "fw_f"
    assert a.derivation["framework_version"] == 1
    assert a.derivation["dataset_id"] == "ds_d1"
    assert a.derivation["dataset_as_of"] == "2026-10-15"
    assert a.derivation["snapshot_id"] == "s1"


def test_ac_17_rule_error_on_b(d1):
    b = _by(evaluate(d1, _config(["x"], x="100 / scope1_tco2e"), snapshot_id="s"), "B", "x")
    assert b.status == "no_value"
    assert b.reason.startswith("rule_error:")
    assert b.value is None


def test_ac_18_a_unaffected_by_b_error(d1):
    a = _by(evaluate(d1, _config(["x"], x="100 / scope1_tco2e"), snapshot_id="s"), "A", "x")
    assert a.status == "value"
    assert a.value == pytest.approx(100 / 90, abs=1e-9)


def test_ac_19_no_rule_value(d1):
    b = _by(evaluate(d1, _config(["y"], y="scope1_tco2e"), snapshot_id="s"), "B", "y")
    assert (b.status, b.reason) == ("no_value", "no_rule_value")


def test_ac_20_combining_lists_both_inputs(d1):
    a = _by(evaluate(d1, _config(["total"], total="scope1_tco2e + prov_esg_demo_scope1"), snapshot_id="s"), "A", "total")
    assert a.value == 190
    assert {"scope1_tco2e", "prov_esg_demo_scope1"} <= set(a.derivation["inputs"])


def test_ac_21_newer_period_wins(d1):
    expr = "date(prov_esg_demo_scope1__period_end) > date(scope1_tco2e__period_end) ? prov_esg_demo_scope1 : scope1_tco2e"
    a = _by(evaluate(d1, _config(["latest"], latest=expr), snapshot_id="s"), "A", "latest")
    assert a.value == 100


def test_ac_12_missing_output_is_named(d1):
    with pytest.raises(ValueError, match="auth_scope2"):
        check_outputs(d1, _config(["auth_scope1", "auth_scope2"], auth_scope1=F_VALUE))


def test_ac_29b_output_may_not_shadow_an_input_column(d1):
    with pytest.raises(ValueError, match="scope1_tco2e"):
        check_outputs(d1, _config(["scope1_tco2e"], scope1_tco2e="0"))


def test_check_outputs_passes_for_f(d1):
    check_outputs(d1, _config(["auth_scope1"], auth_scope1=F_VALUE))


def _plain(columns, rows):
    return Dataset(dataset_id="ds_x", name="x", columns=["company_id", "Company", *columns],
                   rows=[{"company_id": c, "Company": c, **r} for c, r in rows], source="source_values", as_of="2026-10-15")


def test_review_0_and_1_stay_numbers_whatever_the_other_rows_hold():
    ds = _plain(["s3"], [("A", {"s3": "1"}), ("B", {"s3": "0"})])
    verdicts = evaluate(ds, _config(["out"], out="s3 + 1"), snapshot_id="s")
    assert [_by(verdicts, c, "out").value for c in ("A", "B")] == [2, 1]


def test_review_a_text_cell_does_not_turn_another_rows_number_into_text():
    ds = _plain(["t"], [("A", {"t": "abc"}), ("B", {"t": "5"})])
    assert _by(evaluate(ds, _config(["out"], out="t + 1"), snapshot_id="s"), "B", "out").value == 6


def test_review_chained_nodes_list_the_source_input(d1):
    graph = {
        "nodes": [
            {"id": "in", "type": "inputNode", "name": "Input", "position": {"x": 0, "y": 0}},
            {"id": "n1", "type": "expressionNode", "name": "Step 1", "position": {"x": 0, "y": 0},
             "content": {"expressions": [{"id": "a", "key": "tmp", "value": "scope1_tco2e"}]}},
            {"id": "n2", "type": "expressionNode", "name": "Step 2", "position": {"x": 0, "y": 0},
             "content": {"expressions": [{"id": "b", "key": "auth", "value": "tmp * 2"}]}},
            {"id": "out", "type": "outputNode", "name": "Output", "position": {"x": 0, "y": 0}},
        ],
        "edges": [{"id": "e1", "sourceId": "in", "targetId": "n1", "type": "edge"},
                  {"id": "e2", "sourceId": "n1", "targetId": "n2", "type": "edge"},
                  {"id": "e3", "sourceId": "n2", "targetId": "out", "type": "edge"}],
    }
    config = _config(["auth"]).model_copy(update={"rule_graph": graph})
    a = _by(evaluate(d1, config, snapshot_id="s"), "A", "auth")
    assert a.value == 180
    assert "scope1_tco2e" in a.derivation["inputs"]
