"""The dedicated transition-plan pipeline is gone: old `transition_plan` runs stay readable and
reviewable, but nothing starts, resumes or restarts them (spec
2026-10-21-retire-transition-plan-pipeline-design, sections 4 and 5)."""

import json
from pathlib import Path

import pytest
import typer
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from arp.api import run_scheduling
from arp.api.deps import get_decision_store, get_registry, get_run_store, get_xbrl_source, settings_dep
from arp.api.main import app
from arp.api.routers import extraction, runs
from arp.cli import app as cli
from arp.config import Settings
from arp.decision import sources
from arp.decision.indicator_list import build_framework, parse_indicator_list
from arp.decision.mechanism import apply_mechanism
from arp.decision.parsing import load_table
from arp.decision.templates import attach_to_run, import_template
from arp.orchestration.job_manager import JobManager
from arp.schemas.common import CompanyRef
from arp.schemas.decision import MechanismConfig
from arp.storage.decision_store import DecisionStore
from arp.storage.run_store import RunStore
from arp.transition_plan.indicators import load_indicators

RESUME = "Transition-plan runs can no longer be resumed: start a new transition-plan assessment."
RESTART = "Transition-plan runs can no longer be restarted: start a new transition-plan assessment."
COMPANIES = [CompanyRef(company_id="c1", name="Acme"), CompanyRef(company_id="c2", name="Beta")]


class _NoLaunch:
    def launch(self, *_a, **_k):
        pass


@pytest.fixture
def api(tmp_path, monkeypatch, pg):
    """The real app over test stores; nothing launched in the background."""
    settings = Settings(anthropic_api_key="x", runs_dir=tmp_path / "runs", cache_dir=tmp_path / "cache")
    store, decisions = RunStore(pg, settings.runs_dir), DecisionStore(tmp_path / "frameworks")
    monkeypatch.setattr(run_scheduling, "get_job_launcher", _NoLaunch)
    monkeypatch.setattr(run_scheduling, "build_llm_client", lambda s: object())
    monkeypatch.setattr(run_scheduling, "build_verifier_llm_client", lambda s: object())
    monkeypatch.setattr(runs, "get_job_launcher", _NoLaunch)
    monkeypatch.setattr(extraction, "get_registry", lambda: None)
    overrides = {
        settings_dep: lambda: settings, get_run_store: lambda: store, get_decision_store: lambda: decisions,
        get_registry: lambda: None, get_xbrl_source: lambda: None,
    }
    app.dependency_overrides.update(overrides)
    client = TestClient(app)
    client.store, client.decisions, client.pg = store, decisions, pg
    yield client
    for dep in overrides:
        app.dependency_overrides.pop(dep, None)


@pytest.fixture
def old_run(api):
    """Run `O`: a stored, failed `transition_plan` run with 2 result rows, 1 pending review item and a
    saved start_request.json."""
    store, jm = api.store, JobManager(api.store)
    run_id = jm.create_run("transition_plan", {}, 2, companies=COMPANIES).run_id
    for c in COMPANIES:
        store.append_result(run_id, {"_key": c.company_id, "company_id": c.company_id, "name": c.name, "run_id": run_id, "indicators": []})
    store.append_review_item(run_id, {"item_key": "c1", "company_id": "c1", "name": "Acme", "needs_review": True})
    start = {"profile": "transition_plan", "companies": [c.model_dump(mode="json") for c in COMPANIES]}
    (store.run_dir(run_id) / "start_request.json").write_text(json.dumps(start))
    jm.finish_run(run_id, error="killed")
    return run_id


def test_start_and_demo_seed_routes_are_gone(api):  # AC-5, AC-34
    assert api.post("/api/transition-plan/runs", json={"companies": [{"company_id": "c1", "name": "Acme"}]}).status_code == 404
    assert api.post("/api/transition-plan/demo/seed").status_code == 404


def test_cli_keeps_only_indicators(pg):  # AC-6, AC-35; pg: the CLI requires ARP_POSTGRES_DSN
    group = typer.main.get_command(cli).commands["transition-plan"]
    assert list(group.commands) == ["indicators"]
    help_out = CliRunner().invoke(cli, ["transition-plan", "--help"]).output
    assert "indicators" in help_out and "seed-demo" not in help_out
    res = CliRunner().invoke(cli, ["transition-plan", "indicators"])
    assert res.exit_code == 0, res.output
    assert all(i.identifier in res.output for i in load_indicators())


def test_indicators_route_stays(api):  # AC-36
    res = api.get("/api/transition-plan/indicators")
    assert res.status_code == 200
    assert res.json() == [i.model_dump(mode="json") for i in load_indicators()]
    assert len(res.json()) == 64


def test_old_run_reads_and_reviews(api, old_run):  # AC-21, AC-22, AC-48, AC-49, AC-50
    base = f"/api/transition-plan/runs/{old_run}"
    results = api.get(f"{base}/results")
    assert results.status_code == 200 and results.json()["total"] == 2
    queue = api.get(f"{base}/review-queue")
    assert queue.status_code == 200 and [r["item_key"] for r in queue.json()["pending"]] == ["c1"]
    decided = api.post(f"{base}/review", json={"item_key": "c1", "decision": "approve"})
    assert decided.status_code == 200, decided.text
    assert api.get(f"{base}/review-queue").json()["pending"] == []
    history = api.get(f"{base}/review-history", params={"item_key": "c1"}).json()["history"]
    assert [h["item_key"] for h in history] == ["c1"]
    assert list(api.get(f"{base}/review-decisions").json()["decisions"]) == ["c1"]


def test_old_run_cannot_be_resumed(api, old_run):  # AC-24
    res = api.post(f"/api/runs/{old_run}/resume")
    assert res.status_code == 400
    assert RESUME in res.text


@pytest.mark.parametrize("step", ["start", "rules"])
def test_old_run_cannot_be_restarted(api, old_run, step):  # AC-25, AC-51
    res = api.post(f"/api/extraction/runs/{old_run}/restart", json={"from_step": step})
    assert res.status_code == 400
    assert RESTART in res.text


def test_failed_extraction_run_still_resumes(api):  # AC-62
    jm = JobManager(api.store)
    run_id = jm.create_run("extraction", {"schema_id": "s"}, 1, companies=COMPANIES[:1]).run_id
    jm.finish_run(run_id, error="killed")
    res = api.post(f"/api/runs/{run_id}/resume")
    assert res.status_code == 200, res.text
    assert res.json() == {"run_id": run_id, "status": "resumed"}


def _release_preset(pg):
    from arp.db.fields import SchemaRegistry
    from arp.presets.transition_plan import build_transition_plan_schema

    reg = SchemaRegistry(pg)
    saved = reg.save(build_transition_plan_schema())
    return reg.release(saved.schema_id, saved.version)


def test_preset_run_restarts_from_start_and_rescores_from_rules(api):  # AC-63, AC-64
    _release_preset(api.pg)
    started = api.post("/api/extraction/start", json={"profile": "transition_plan", "companies": [{"company_id": "c1", "name": "Acme"}]})
    assert started.status_code == 200, started.text
    run_id = started.json()["run_id"]
    JobManager(api.store).finish_run(run_id)

    again = api.post(f"/api/extraction/runs/{run_id}/restart", json={"from_step": "start"})
    assert again.status_code == 200, again.text
    new_id = again.json()["run_id"]
    assert new_id != run_id
    assert api.store.load_manifest(new_id).params["schema_id"] == "transition_plan_indicators"
    assert api.store.load_manifest(new_id).params["schema_id"] == api.store.load_manifest(run_id).params["schema_id"]

    attach_to_run(api.store, run_id, MechanismConfig(name="TP", criteria=[], gates=[]))
    rescored = api.post(f"/api/extraction/runs/{run_id}/restart", json={"from_step": "rules"})
    assert rescored.status_code == 200, rescored.text
    assert rescored.json()["rescored"] is True


def test_completed_old_run_cannot_be_resumed(api, old_run):
    # Both companies have results: any other run type would say "already completed".
    assert JobManager(api.store).finish_run(old_run).status == "completed"
    res = api.post(f"/api/runs/{old_run}/resume")
    assert res.status_code == 400
    assert RESUME in res.text


# --- the shipped example framework still scores transition-plan runs (ported from the deleted
# test_transition_plan_demo.py, which ran them on the synthetic demo run) ---

TP_LIST = Path(__file__).resolve().parents[2] / "docs/decision-studio/example-framework/transition-plan/indicators.csv"


def _datasets(tmp_path, pg):
    """An old transition_plan run (main's stored records) and a preset run, as Decision Studio reads them."""
    from tests.test_decision_sources import old_run_o, preset_run_r

    store = RunStore(pg, tmp_path)
    return {kind: sources.from_transition_plan_run(store, make(store), include_indicators=True)
            for kind, make in (("old", old_run_o), ("preset", preset_run_r))}


def test_the_transition_plan_indicator_list_scores_the_run(tmp_path, pg):
    config, _ = build_framework(parse_indicator_list(load_table(TP_LIST)), name="TP")
    expected = {
        "old": {"Acme": "Tier 3", "c2": "Tier 3"},  # 22 and 21 of 64 disclosed: between the 0.25 and 0.5 cuts
        "preset": {"X": "Tier 3", "Y": "Tier 4"},  # X: the whole Targets group (1 of 4 balanced groups); Y: one target
    }
    for kind, dataset in _datasets(tmp_path, pg).items():
        result = apply_mechanism(dataset, config)
        assert not result.missing_columns
        tiers = {e.name: e.tier_name for e in result.entities}
        assert tiers == expected[kind], kind


def test_the_exported_framework_file_scores_the_run_the_same(tmp_path, pg):
    built, _ = build_framework(parse_indicator_list(load_table(TP_LIST)), name="TP")
    imported, _ = import_template(json.loads((TP_LIST.parent / "framework.json").read_text()))
    for kind, dataset in _datasets(tmp_path, pg).items():
        assert not apply_mechanism(dataset, imported).missing_columns, kind
        tiers = lambda config, dataset=dataset: {e.name: e.tier_name for e in apply_mechanism(dataset, config).entities}  # noqa: E731
        assert tiers(imported) == tiers(built)
