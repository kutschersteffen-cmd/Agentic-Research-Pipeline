"""Capability catalog and the two new plan steps (spec agent-panel-code-mode AC-11 to AC-16)."""
from __future__ import annotations

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from arp.api.main import app
from arp.cli import plan as plan_cli
from arp.orchestration.plan_api import STEPS
from arp.orchestration.plan_planner import SYSTEM, step_stubs

SANDBOX = ["benchmark_sectors", "portfolio_exposure", "smart_search", "transition_plan"]
PLAN = ["decision_score", "document_discovery", "extraction", "financials_extraction", "identity_resolution",
        "index_construct", "report_render", "tnfd_extraction", "universe_build", "xbrl_facts"]


def test_route_orders_sandbox_then_plan():  # AC-11, AC-12
    resp = TestClient(app).get("/api/capabilities")
    assert resp.status_code == 200
    body = resp.json()
    assert [c["id"] for c in body] == SANDBOX + PLAN
    assert all(c["lane"] == "sandbox" and c["effect"] == "read" for c in body[:4])
    assert all(c["lane"] == "plan" and c["effect"] == "run" for c in body[4:])
    tnfd = next(c for c in body if c["id"] == "tnfd_extraction")
    assert tnfd["input_schema"]["required"] == ["universe_run_id", "as_of"]
    bench = next(c for c in body if c["id"] == "benchmark_sectors")
    assert "required" not in bench["input_schema"]  # an omitted benchmark_id means null


def test_steps_are_the_plan_lane():
    assert sorted(STEPS) == PLAN


def _check(tmp_path, script: str):
    path = tmp_path / "s.py"
    path.write_text(script)
    return CliRunner().invoke(plan_cli.plan_app, ["check", str(path)])


def test_check_refuses_a_sandbox_capability(tmp_path):  # AC-13
    result = _check(tmp_path, 'smart_search(query="x")\n')
    assert result.exit_code == 1
    assert "line 1: call to smart_search not allowed" in result.stdout


def test_check_accepts_identity_resolution(tmp_path):  # AC-14
    result = _check(tmp_path, 'u = universe_build(taxonomy_id="t", source="s.csv")\n'
                              "identity_resolution(universe_run_id=u.run_id)\n")
    assert result.exit_code == 0
    assert result.stdout.strip() == "ok"


def test_check_refuses_unknown_tnfd_argument(tmp_path):  # AC-15
    result = _check(tmp_path, 'tnfd_extraction(universe_run_id="r", as_of="2025-12-31", foo=1)\n')
    assert result.exit_code == 1
    assert "line 1: tnfd_extraction: unexpected argument foo" in result.stdout


def test_planner_prompt_lists_the_plan_lane_only():  # AC-16 (the prompt draft_plan sends)
    system = SYSTEM.replace("{stubs}", step_stubs())
    assert "def identity_resolution(" in system and "def tnfd_extraction(" in system
    assert "def smart_search(" not in system
