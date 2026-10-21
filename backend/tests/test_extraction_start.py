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
from tests.postgres_helpers import replace_results


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


def test_each_profile_reaches_its_pipeline(calls, pg):
    schema = DataPointSchema.model_validate({"schema_id": "s", "name": "s", "fields": []})
    assert _start(profile="custom", datapoint_schema=schema)["run_type"] == "extraction"
    assert _start(profile="financials")["run_type"] == "financials"
    assert _start(profile="tnfd", as_of="FY2025")["run_type"] == "tnfd"
    started = _start(profile="transition_plan")
    assert started == {"run_id": "custom-1", "company_count": 1, "run_type": "extraction"}

    assert [c[0] for c in calls] == ["custom", "financials", "tnfd", "custom"]
    assert calls[0][1].datapoint_schema == schema
    assert calls[1][2]["xbrl_source"] == "xbrl"
    assert calls[2][1].as_of == "FY2025"
    assert calls[3][1].datapoint_schema.schema_id == "transition_plan_indicators" and calls[3][1].trial is False
    assert all([x.company_id for x in c[1].companies] == ["c1"] and c[1].decision_framework_id == "fw" for c in calls)


@pytest.mark.parametrize("profile", ["custom", "tnfd"])
def test_missing_profile_input_is_a_400(calls, profile):
    with pytest.raises(HTTPException) as err:
        _start(profile=profile)
    assert err.value.status_code == 400
    assert calls == []


def test_step_settings_reach_the_pipeline_and_are_recorded(calls, tmp_path, pg):
    store = RunStore(pg, tmp_path)
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


def test_the_saved_universe_a_run_read_is_recorded(calls, tmp_path, pg):
    store = RunStore(pg, tmp_path)
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


def test_restart_from_a_step_reruns_one_company_with_fresh_steps(calls, tmp_path, monkeypatch, pg):
    monkeypatch.setattr(extraction, "get_registry", lambda: "registry")
    store = RunStore(pg, tmp_path)
    run_id = _finished_run(store, calls)
    replace_results(store, run_id, [{"company_id": "c1", "name": "Acme"}])
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



def test_restart_refuses_a_running_run_or_an_unknown_step(calls, tmp_path, monkeypatch, pg):
    from arp.orchestration.job_manager import JobManager

    monkeypatch.setattr(extraction, "get_registry", lambda: "registry")
    store = RunStore(pg, tmp_path)
    run_id = _finished_run(store, calls)
    with pytest.raises(HTTPException) as err:
        _restart(store, run_id, from_step="answer")  # a transition plan step, not a TNFD one
    assert err.value.status_code == 400
    running = JobManager(store).create_run("tnfd", {}, 1).run_id
    with pytest.raises(HTTPException) as err:
        _restart(store, running, from_step="verify")
    assert err.value.status_code == 409


def test_restart_of_a_pre_gate_custom_run_runs_as_trial(calls, tmp_path, monkeypatch, pg):
    # A start_request.json saved before the release gate has no `trial`: that run was ungated,
    # so its restart runs as a trial rather than being refused for draft fields.
    from arp.orchestration.job_manager import JobManager

    monkeypatch.setattr(extraction, "get_registry", lambda: "registry")
    store = RunStore(pg, tmp_path)
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


# --- transition_plan runs on the installed preset (spec 2026-10-21-retire-transition-plan-pipeline-design, section 1) ---

ACME = {"company_id": "c1", "name": "Acme"}


@pytest.fixture
def api(monkeypatch, tmp_path, pg):
    """The real /start route over the real registry; the background run is never launched."""
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    from arp.api import run_scheduling
    from arp.api.auth import Principal, current_user
    from arp.api.deps import get_decision_store, get_registry, get_run_store, get_xbrl_source, settings_dep
    from arp.storage.decision_store import DecisionStore

    class _NoLaunch:
        def launch(self, run_id, job):
            pass

    monkeypatch.setattr(run_scheduling, "get_job_launcher", _NoLaunch)
    monkeypatch.setattr(run_scheduling, "build_llm_client", lambda s: object())
    monkeypatch.setattr(run_scheduling, "build_verifier_llm_client", lambda s: object())
    settings = Settings(anthropic_api_key="x", runs_dir=tmp_path / "runs")
    store, decisions = RunStore(pg, settings.runs_dir), DecisionStore(tmp_path / "frameworks")
    app = FastAPI()
    app.include_router(extraction.router)

    @app.exception_handler(ValueError)  # as arp.api.main maps the release gate's refusal
    async def _ve(request, exc):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    app.dependency_overrides[settings_dep] = lambda: settings
    app.dependency_overrides[get_run_store] = lambda: store
    app.dependency_overrides[get_decision_store] = lambda: decisions
    app.dependency_overrides[get_registry] = lambda: None
    app.dependency_overrides[get_xbrl_source] = lambda: None
    app.dependency_overrides[current_user] = lambda: Principal(user_id="u", name="U", role="approver")
    client = TestClient(app)
    client.store, client.decisions, client.pg = store, decisions, pg
    return client


def _tp_start(api, **body):
    return api.post("/api/extraction/start", json={"profile": "transition_plan", "companies": [ACME], **body})


def _release_preset(pg, preset=None):
    from arp.db.fields import SchemaRegistry
    from arp.presets.transition_plan import build_transition_plan_schema

    reg = SchemaRegistry(pg)
    saved = reg.save(preset or build_transition_plan_schema())
    return reg.release(saved.schema_id, saved.version)


def test_transition_plan_starts_a_generic_extraction_run_on_the_preset(api):  # AC-1, AC-2, AC-30
    _release_preset(api.pg)
    r = _tp_start(api)
    assert r.status_code == 200, r.text
    assert r.json()["run_type"] == "extraction"
    params = api.store.load_manifest(r.json()["run_id"]).params
    assert params["schema_id"] == "transition_plan_indicators" and params["trial"] is False


def _main_preset():
    """The preset as `main` shipped it: before the contradiction rules."""
    import json
    from pathlib import Path

    from arp.schemas.datapoints import DataPointSchema, FieldDefinition

    fields = json.loads((Path(__file__).parent / "fixtures" / "transition_plan_preset_main.json").read_text())
    from arp.presets.transition_plan import build_transition_plan_schema

    built = build_transition_plan_schema()
    return DataPointSchema(schema_id=built.schema_id, name=built.name, fields=[FieldDefinition.model_validate(f) for f in fields])


def test_unreleased_preset_version_is_refused_unless_trial_then_released_starts(api):  # AC-3, AC-4, AC-31, AC-32
    _release_preset(api.pg, _main_preset())
    refused = _tp_start(api)
    assert refused.status_code == 400 and "is not released" in refused.text
    trial = _tp_start(api, trial=True)
    assert trial.status_code == 200
    assert api.store.load_manifest(trial.json()["run_id"]).params["trial"] is True

    from arp.db.fields import SchemaRegistry

    reg = SchemaRegistry(api.pg)
    reg.release("transition_plan_indicators", reg.get("transition_plan_indicators").version)
    ok = _tp_start(api)
    assert ok.status_code == 200, ok.text
    params = api.store.load_manifest(ok.json()["run_id"]).params
    schema_id, version = params["schema_version"].split(":v")
    field = {f.field_id: f for f in reg.get(schema_id, int(version)).fields}["tp_a_headline_2"]
    assert field.version == 2 and "tp_r_req_headline_2" in [r.rule_id for r in field.rules]


def test_transition_plan_pipeline_shape_equals_custom(api):  # AC-33
    tp = api.get("/api/extraction/pipeline", params={"profile": "transition_plan"})
    custom = api.get("/api/extraction/pipeline", params={"profile": "custom"})
    assert tp.status_code == 200
    assert {**tp.json(), "profile": None} == {**custom.json(), "profile": None}


def test_custom_profile_still_starts_on_its_own_schema(api):  # AC-47
    from arp.db.fields import SchemaRegistry
    from arp.schemas.datapoints import FieldDataType, FieldDefinition

    field = FieldDefinition(name="capex", description="Capex.", data_type=FieldDataType.NUMBER, extraction_instructions="Find it.", seed_keywords=["capex"])
    reg = SchemaRegistry(api.pg)
    saved = reg.save(DataPointSchema(name="S", fields=[field]))
    released = reg.release(saved.schema_id, saved.version)
    r = api.post("/api/extraction/start", json={"profile": "custom", "datapoint_schema": released.model_dump(mode="json"), "companies": [ACME]})
    assert r.status_code == 200, r.text
    assert r.json()["run_type"] == "extraction"
    assert api.store.load_manifest(r.json()["run_id"]).params["schema_id"] == released.schema_id


def test_a_framework_needing_the_indicator_count_is_accepted_at_start(api):  # AC-20 at start
    from arp.schemas.decision import MechanismConfig

    config = api.decisions.save(MechanismConfig(name="TP", criteria=[], gates=[], label_column="Indicators_Disclosed_Count"))
    api.decisions.ratify(config.framework_id, config.version)
    _release_preset(api.pg)
    r = _tp_start(api, decision_framework_id=config.framework_id)
    assert r.status_code == 200, r.text
