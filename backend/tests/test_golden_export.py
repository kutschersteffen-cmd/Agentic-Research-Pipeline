from __future__ import annotations

from arp.golden_set.export import export_cases
from arp.schemas.common import CompanyRef
from arp.schemas.datapoints import ValueState
from arp.schemas.review import DecisionKind, DecisionReason, ReviewDecision, field_item_key

ISSUER = "lei:ACME:1"  # issuer keys contain ":" themselves


class StubStore:
    def __init__(self, rows, companies=None):
        self.rows, self.companies = rows, companies

    def read_results(self, run_id):
        return self.rows

    def load_companies(self, run_id):
        return self.companies


def _field(field_id, value, period_end=None, state="found"):
    return {"field_id": field_id, "value": value, "value_state": state, "period_end": period_end}


def _decision(field_id, kind, reason, *, period="unspecified", corrected=None, issuer=ISSUER, step="first", second_required=False):
    return ReviewDecision(
        item_key=field_item_key(issuer, field_id, period), decision=kind, reason_code=reason, reviewer="r", user_id="u",
        role="reviewer", corrected_value=corrected, snapshot_id="s", step=step, second_required=second_required,
    )


ROWS = [{
    "company_id": "acme", "name": "Acme", "ticker": "ACM", "issuer_key": ISSUER,
    "fields": [
        _field("scope1", 100.0, "2024-12-31"), _field("scope2", 50.0), _field("scope3", 9.0), _field("water", 7.0),
        _field("waste", 4.0),
    ],
}]


def test_export_maps_each_decision_and_skips_escalate():
    decisions = [
        _decision("scope1", DecisionKind.APPROVE, DecisionReason.CONFIRMED, period="2024-12-31"),
        _decision("scope2", DecisionKind.CORRECT, DecisionReason.WRONG_VALUE, corrected={"value": 55.0}),
        _decision("scope3", DecisionKind.REJECT, DecisionReason.NOT_DISCLOSED),
        _decision("water", DecisionKind.ESCALATE, DecisionReason.NEEDS_EXPERT),
        _decision("waste", DecisionKind.REJECT, DecisionReason.BAD_SOURCE),
        _decision("x", DecisionKind.APPROVE, DecisionReason.CONFIRMED, issuer="held"),  # not a row field
    ]
    [case] = export_cases(StubStore(ROWS), "run", decisions)
    got = {e.field_id: (e.period_end, e.value, e.value_state) for e in case.expected}
    assert got == {
        "scope1": ("2024-12-31", 100.0, ValueState.FOUND),
        "scope2": (None, 55.0, ValueState.FOUND),
        "scope3": (None, None, ValueState.NOT_FOUND),
    }
    assert case.company.company_id == "acme" and case.company.ticker == "ACM"


def test_last_decision_per_item_wins_and_uses_run_company():
    full = CompanyRef(company_id="acme", name="Acme", website="https://acme.example")
    decisions = [
        _decision("scope2", DecisionKind.APPROVE, DecisionReason.CONFIRMED),
        _decision("scope2", DecisionKind.CORRECT, DecisionReason.WRONG_VALUE, corrected={"value": 0}),
    ]
    [case] = export_cases(StubStore(ROWS, [full]), "run", decisions)
    assert [(e.value, e.value_state) for e in case.expected] == [(0, ValueState.ZERO)]
    assert case.company.website == "https://acme.example"


def test_only_final_decisions_are_exported():
    pending = _decision("scope2", DecisionKind.APPROVE, DecisionReason.CONFIRMED, second_required=True)
    assert export_cases(StubStore(ROWS), "run", [pending]) == []
    second = _decision("scope2", DecisionKind.APPROVE, DecisionReason.CONFIRMED, step="second")
    [case] = export_cases(StubStore(ROWS), "run", [pending, second])
    assert [e.field_id for e in case.expected] == ["scope2"]
    disagree = _decision("scope2", DecisionKind.REJECT, DecisionReason.NOT_DISCLOSED, step="second")
    assert export_cases(StubStore(ROWS), "run", [pending, disagree]) == []


def test_correction_to_not_disclosed_and_no_decisions():
    decisions = [_decision("scope2", DecisionKind.CORRECT, DecisionReason.NOT_DISCLOSED, corrected={"value": None})]
    [case] = export_cases(StubStore(ROWS), "run", decisions)
    assert [(e.value, e.value_state) for e in case.expected] == [(None, ValueState.NOT_FOUND)]
    assert export_cases(StubStore(ROWS), "run", []) == []


def test_cli_writes_cases_that_the_harness_loads(monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from arp.cli import golden_set as cli
    from arp.golden_set.precision import load_record_cases

    store = StubStore(ROWS)
    legacy = {"item_key": "k", "decision": "edit", "reviewer": "r", "edited_value": {"value": 1}}  # pre-step shape
    store.read_decisions = lambda run_id: [
        legacy, _decision("scope2", DecisionKind.APPROVE, DecisionReason.CONFIRMED).model_dump(mode="json")
    ]
    monkeypatch.setattr(cli, "_run_store", lambda: store)
    out = tmp_path / "cases.json"
    result = CliRunner().invoke(cli.golden_set_app, ["export-labels", "--run-id", "run", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "Skipped 1 legacy decision row(s)" in result.output
    [case] = load_record_cases(out)
    assert [(e.field_id, e.value) for e in case.expected] == [("scope2", 50.0)]
