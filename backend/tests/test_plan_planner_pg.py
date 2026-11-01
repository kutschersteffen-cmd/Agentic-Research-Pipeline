"""Research Orchestrator planner (spec AC-11, AC-12)."""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from arp.cli import plan as plan_cli
from arp.orchestration.plan_planner import PlanScript, draft_plan, planner_context, step_stubs
from arp.orchestration.plan_store import PlanStore

GOOD = PlanScript(script='u = universe_build(taxonomy_id="t_grid storage", source="u.csv")\n')
BAD = PlanScript(script="import os\n")
BAD2 = PlanScript(script="w = x * 2\n")


async def test_retry_once_then_store_draft(pg, fake_llm):  # AC-11
    llm = fake_llm({"PlanScript": [BAD, GOOD]})
    store = PlanStore(pg)
    plan_id = await draft_plan("grid storage", llm, store)
    assert store.get(plan_id)["status"] == "draft"
    assert llm.calls == ["PlanScript", "PlanScript"]
    assert "line 1: import not allowed" in llm.prompts[1]


def test_cli_rejected_twice(pg, fake_llm, monkeypatch):  # AC-12
    monkeypatch.setattr(plan_cli, "_llm", lambda: fake_llm({"PlanScript": [BAD, BAD2]}))
    monkeypatch.setattr(plan_cli, "_context", lambda: "")
    result = CliRunner().invoke(plan_cli.plan_app, ["draft", "x"])
    assert result.exit_code == 1
    assert "line 1: arithmetic not allowed" in result.stdout


def test_cli_draft_prints_plan(pg, fake_llm, monkeypatch):
    monkeypatch.setattr(plan_cli, "_llm", lambda: fake_llm({"PlanScript": [GOOD]}))
    monkeypatch.setattr(plan_cli, "_context", lambda: "")
    result = CliRunner().invoke(plan_cli.plan_app, ["draft", "grid storage"])
    assert result.exit_code == 0, result.stdout
    assert result.stdout.startswith("plan_")
    assert "1 universe_build" in result.stdout


def test_context_lists_only_ratified():
    from types import SimpleNamespace as NS

    tax = [NS(taxonomy_id="tax_a", theme=NS(name="Grid storage"), status="ratified"),
           NS(taxonomy_id="tax_b", theme=NS(name="Draft theme"), status="draft")]
    fw = [NS(framework_id="fw_1", name="Capex quality", ratified=True), NS(framework_id="fw_2", name="x", ratified=False)]
    ctx = planner_context(tax, fw)
    assert "- tax_a: Grid storage" in ctx and "tax_b" not in ctx
    assert "- fw_1: Capex quality" in ctx and "fw_2" not in ctx


def test_stubs_list_every_step():
    stubs = step_stubs()
    assert "def extraction(*, universe_run_id: str, schema_id: str, companies: list[str] | None = None)" in stubs
    assert stubs.count("def ") == 8


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch):
    monkeypatch.setenv("ARP_ANTHROPIC_API_KEY", "")


async def test_dry_run_error_is_retried(pg, fake_llm):  # review: dry-run failures get the one retry
    undefined = PlanScript(script='extraction(universe_run_id=nope.run_id, schema_id="s")\n')
    llm = fake_llm({"PlanScript": [undefined, GOOD]})
    plan_id = await draft_plan("b", llm, PlanStore(pg))
    assert "name nope is not defined" in llm.prompts[1]
    assert PlanStore(pg).get(plan_id)["status"] == "draft"


def test_context_lists_index_calibrations():
    from types import SimpleNamespace as NS

    ctx = planner_context([], [], [NS(calibration_id="cal_pab", name="EU PAB")])
    assert "- cal_pab: EU PAB" in ctx
    assert "not available" not in ctx
