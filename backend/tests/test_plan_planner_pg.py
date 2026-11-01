"""Research Orchestrator planner (spec AC-11, AC-12)."""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from arp.cli import plan as plan_cli
from arp.orchestration.plan_planner import PlanScript, draft_plan, step_stubs
from arp.orchestration.plan_store import PlanStore

GOOD = PlanScript(script='u = universe_build(theme="grid storage")\n')
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
    result = CliRunner().invoke(plan_cli.plan_app, ["draft", "x"])
    assert result.exit_code == 1
    assert "line 1: arithmetic not allowed" in result.stdout


def test_cli_draft_prints_plan(pg, fake_llm, monkeypatch):
    monkeypatch.setattr(plan_cli, "_llm", lambda: fake_llm({"PlanScript": [GOOD]}))
    result = CliRunner().invoke(plan_cli.plan_app, ["draft", "grid storage"])
    assert result.exit_code == 0, result.stdout
    assert result.stdout.startswith("plan_")
    assert "1 universe_build" in result.stdout


def test_stubs_list_every_step():
    stubs = step_stubs()
    assert "def extraction(*, universe_id: str, schema_id: str, companies: list[str] | None = None)" in stubs
    assert stubs.count("def ") == 8


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch):
    monkeypatch.setenv("ARP_ANTHROPIC_API_KEY", "")
