"""Planner golden-set runner (spec AC-36), with a scripted model."""
from __future__ import annotations

from typer.testing import CliRunner

from arp.cli import plan as plan_cli
from arp.orchestration.plan_golden import in_order
from arp.orchestration.plan_planner import PlanScript

U = 'u = universe_build(taxonomy_id="tax_grid_storage", source="data/universes/eu_listed.csv")\n'
UE = U + 'e = extraction(universe_run_id=u.run_id, schema_id="green_capex")\n'


def test_in_order_allows_extra_steps_but_not_reordering():
    assert in_order(["universe_build", "document_discovery", "extraction"], ["universe_build", "extraction"])
    assert not in_order(["extraction", "universe_build"], ["universe_build", "extraction"])
    assert not in_order(["universe_build"], ["universe_build", "extraction"])


def _run(tmp_path, monkeypatch, fake_llm, scripts, min_pass):
    cases = tmp_path / "cases.jsonl"
    cases.write_text('{"id": "a", "brief": "x", "expected_kinds": ["universe_build", "extraction"]}\n'
                     '{"id": "b", "brief": "y", "expected_kinds": ["universe_build"]}\n')
    monkeypatch.setattr(plan_cli, "_llm", lambda: fake_llm({"PlanScript": [PlanScript(script=s) for s in scripts]}))
    return CliRunner().invoke(plan_cli.plan_app, ["golden", "--cases", str(cases), "--min-pass", str(min_pass)])


def test_golden_passes_at_threshold(tmp_path, monkeypatch, fake_llm):
    result = _run(tmp_path, monkeypatch, fake_llm, [UE, U], 2)
    assert result.exit_code == 0, result.stdout
    assert "2/2 passed (need 2)" in result.stdout


def test_golden_fails_below_threshold(tmp_path, monkeypatch, fake_llm):
    # case a: wrong steps; case b: rejected twice
    result = _run(tmp_path, monkeypatch, fake_llm, [U, "import os\n", "import os\n"], 2)
    assert result.exit_code == 1
    assert "FAIL  a: universe_build" in result.stdout
    assert "FAIL  b: rejected: line 1: import not allowed" in result.stdout
    assert "0/2 passed (need 2)" in result.stdout


def test_shipped_cases_are_well_formed():
    from pathlib import Path

    from arp.orchestration.plan_api import STEPS
    from arp.orchestration.plan_golden import load_cases

    cases = load_cases(Path(__file__).parent / "golden" / "plans" / "plans.jsonl")
    assert len(cases) == 10
    assert all(set(c["expected_kinds"]) <= set(STEPS) and c["expected_kinds"][0] == "universe_build" for c in cases)
