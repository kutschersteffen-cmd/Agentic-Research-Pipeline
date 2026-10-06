"""/api/extraction/start hands each profile to that pipeline's own start endpoint."""

import asyncio
import json

import pytest
from fastapi import HTTPException

from arp.api.routers import extraction, financials, tnfd, transition_plan
from arp.config import Settings
from arp.extraction.steps import StepSettings
from arp.schemas.common import CompanyRef
from arp.schemas.datapoints import DataPointSchema
from arp.storage.run_store import RunStore


def _fake(name, calls):
    async def start(req, **kwargs):
        calls.append((name, req, kwargs))
        return {"run_id": f"{name}-1", "company_count": 1}

    return start


@pytest.fixture
def calls(monkeypatch):
    calls: list = []
    monkeypatch.setattr(extraction, "start_extraction_run", _fake("custom", calls))
    monkeypatch.setattr(financials, "start_financials_extraction_run", _fake("financials", calls))
    monkeypatch.setattr(tnfd, "start_tnfd_extraction_run", _fake("tnfd", calls))
    monkeypatch.setattr(transition_plan, "start_transition_plan_run", _fake("transition_plan", calls))
    return calls


def _start(run_store=None, settings=None, **body):
    req = extraction.StartRequest(companies=[CompanyRef(company_id="c1", name="Acme")], decision_framework_id="fw", **body)
    return asyncio.run(
        extraction.start_extraction(
            req, settings=settings or Settings(), run_store=run_store or _Store(), registry=None, decision_store=None, xbrl_source="xbrl"
        )
    )


class _Store:
    """Just enough RunStore for /start: somewhere to write step_settings.json."""

    def run_dir(self, run_id):
        import tempfile
        from pathlib import Path

        return Path(tempfile.mkdtemp())


def test_each_profile_reaches_its_pipeline(calls):
    schema = DataPointSchema.model_validate({"schema_id": "s", "name": "s", "fields": []})
    assert _start(profile="custom", datapoint_schema=schema)["run_type"] == "extraction"
    assert _start(profile="financials")["run_type"] == "financials"
    assert _start(profile="tnfd", as_of="FY2025")["run_type"] == "tnfd"
    started = _start(profile="transition_plan")
    assert started == {"run_id": "transition_plan-1", "company_count": 1, "run_type": "transition_plan"}

    assert [c[0] for c in calls] == ["custom", "financials", "tnfd", "transition_plan"]
    assert calls[0][1].datapoint_schema == schema
    assert calls[1][2]["xbrl_source"] == "xbrl"
    assert calls[2][1].as_of == "FY2025"
    assert "xbrl_source" not in calls[3][2]
    assert all([x.company_id for x in c[1].companies] == ["c1"] and c[1].decision_framework_id == "fw" for c in calls)


@pytest.mark.parametrize("profile", ["custom", "tnfd"])
def test_missing_profile_input_is_a_400(calls, profile):
    with pytest.raises(HTTPException) as err:
        _start(profile=profile)
    assert err.value.status_code == 400
    assert calls == []


def test_step_settings_reach_the_pipeline_and_are_recorded(calls, tmp_path):
    store = RunStore(tmp_path)
    base = Settings(llm_model="model-a", hybrid_retrieval_enabled=True)
    started = _start(
        run_store=store,
        settings=base,
        profile="tnfd",
        as_of="FY2025",
        step_settings=StepSettings(llm_model="model-b", hybrid_retrieval_enabled=False),
    )
    used = calls[0][2]["settings"]
    assert used.llm_model == "model-b" and used.hybrid_retrieval_enabled is False
    assert used.llm_verifier_model == base.llm_verifier_model  # left out, kept
    recorded = StepSettings.model_validate_json((store.run_dir(started["run_id"]) / "step_settings.json").read_text())
    assert recorded.llm_model == "model-b" and recorded.grounding_fuzzy_threshold == base.grounding_fuzzy_threshold


def test_the_saved_universe_a_run_read_is_recorded(calls, tmp_path):
    store = RunStore(tmp_path)
    universe = tmp_path / "u.json"
    universe.write_text(json.dumps([{"company_id": "c1", "name": "Acme"}]))
    started = _start(run_store=store, profile="tnfd", as_of="FY2025", universe_path=str(universe))
    assert json.loads((store.run_dir(started["run_id"]) / "inputs.json").read_text()) == {"universe_path": str(universe)}
    without = _start(run_store=store, profile="financials")  # companies passed directly: no saved universe to record
    assert not (store.run_dir(without["run_id"]) / "inputs.json").exists()


def test_step_settings_are_bounded():
    with pytest.raises(ValueError):
        StepSettings(grounding_fuzzy_threshold=0.2)


def _finished_run(store, calls, **body):
    """A run started through /start, then marked finished."""
    from arp.orchestration.job_manager import JobManager

    run_id = JobManager(store).create_run("tnfd", {}, 2).run_id
    fake = calls  # the fixture's fakes return a fixed run id; give it a real one

    async def start(req, **kwargs):
        fake.append(("tnfd", req, kwargs))
        return {"run_id": run_id, "company_count": len(req.companies)}

    tnfd.start_tnfd_extraction_run = start
    req = extraction.StartRequest(
        profile="tnfd", as_of="FY2025",
        companies=[CompanyRef(company_id="c1", name="Acme"), CompanyRef(company_id="c2", name="Beta")],
        step_settings=StepSettings(llm_model="model-b"), **body,
    )
    asyncio.run(extraction.start_extraction(req, settings=Settings(), run_store=store, registry=None, decision_store=None, xbrl_source=None))
    JobManager(store).finish_run(run_id)
    return run_id


def _restart(store, run_id, **body):
    return asyncio.run(
        extraction.restart_run(run_id, extraction.RestartRequest(**body), settings=Settings(), run_store=store, decision_store=None, xbrl_source=None)
    )


def test_restart_from_a_step_reruns_one_company_with_fresh_steps(calls, tmp_path, monkeypatch):
    monkeypatch.setattr(extraction, "get_registry", lambda: "registry")
    store = RunStore(tmp_path)
    run_id = _finished_run(store, calls)
    store.results_path(run_id).write_text(json.dumps({"company_id": "c1", "name": "Acme"}) + "\n")
    companies = extraction.get_run_companies(run_id, run_store=store)["companies"]
    assert [(c["company_id"], c["status"]) for c in companies] == [("c1", "done"), ("c2", "waiting")]
    calls.clear()

    _restart(store, run_id, from_step="verify", company_ids=["c2"])
    (_, req, kwargs), = calls
    assert [c.company_id for c in req.companies] == ["c2"] and req.as_of == "FY2025"
    assert kwargs["settings"].llm_model == "model-b"  # the run's own step settings carry over
    assert kwargs["settings"].llm_verifier_cache_refresh is True and kwargs["settings"].llm_cache_refresh is False
    restarted = json.loads((store.run_dir(run_id) / "restarted_from.json").read_text())
    assert restarted == {"run_id": run_id, "step": "verify", "company_count": 1}



def test_restart_refuses_a_running_run_or_an_unknown_step(calls, tmp_path, monkeypatch):
    from arp.orchestration.job_manager import JobManager

    monkeypatch.setattr(extraction, "get_registry", lambda: "registry")
    store = RunStore(tmp_path)
    run_id = _finished_run(store, calls)
    with pytest.raises(HTTPException) as err:
        _restart(store, run_id, from_step="answer")  # a transition plan step, not a TNFD one
    assert err.value.status_code == 400
    running = JobManager(store).create_run("tnfd", {}, 1).run_id
    with pytest.raises(HTTPException) as err:
        _restart(store, running, from_step="verify")
    assert err.value.status_code == 409


def test_restart_of_a_pre_gate_custom_run_runs_as_trial(calls, tmp_path, monkeypatch):
    # A start_request.json saved before the release gate has no `trial`: that run was ungated,
    # so its restart runs as a trial rather than being refused for draft fields.
    from arp.orchestration.job_manager import JobManager

    monkeypatch.setattr(extraction, "get_registry", lambda: "registry")
    store = RunStore(tmp_path)
    run_id = JobManager(store).create_run("extraction", {}, 1).run_id
    JobManager(store).finish_run(run_id)
    saved = {
        "profile": "custom",
        "datapoint_schema": {"schema_id": "s", "name": "s", "fields": []},
        "companies": [{"company_id": "c1", "name": "Acme"}],
    }
    (store.run_dir(run_id) / "start_request.json").write_text(json.dumps(saved))
    _restart(store, run_id, from_step="extract")
    (_, req, _), = calls
    assert req.trial is True

    calls.clear()  # a saved request that says trial=false stays gated
    (store.run_dir(run_id) / "start_request.json").write_text(json.dumps({**saved, "trial": False}))
    _restart(store, run_id, from_step="extract")
    (_, req, _), = calls
    assert req.trial is False
