import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import arp.research.pipeline as research_pipeline
import arp.transition_plan.pipeline as tp_pipeline
from arp.api.auth import current_user
from arp.api.deps import get_run_store, settings_dep
from arp.api.main import app
from arp.cli.extraction import extract_app
from arp.config import Settings
from arp.extraction.financials_pipeline import create_financials_extraction_run
from arp.ingestion.registry import DocumentSourceRegistry
from arp.llm.base import LLMUsage
from arp.llm.batching_client import BatchingLLMClient
from arp.orchestration.job_manager import JobManager
from arp.orchestration.jobs import NotResumable, RunBusy, resume_run, run_lease
from arp.research.pipeline import create_theme_run
from arp.schemas.common import CompanyRef, JobStatus
from arp.schemas.thematic import ActivityDefinition, ThemeDefinition
from arp.schemas.transition_plan import TransitionPlanAssessmentRecord
from arp.storage.run_store import RunStore
from arp.transition_plan.pipeline import TransitionPlanAssessmentResult, create_transition_plan_run
from arp.voting.pipeline import create_voting_run

COMPANIES = [CompanyRef(company_id=f"c{i}", name=f"Co {i}") for i in range(1, 7)]
LLM = object()  # never called: the fake assessor stands in for every LLM step


def _settings(tmp_path) -> Settings:
    return Settings(anthropic_api_key="unused", runs_dir=tmp_path / "runs", cache_dir=tmp_path / "cache")


class FakeAssessor:
    """Stands in for _assess_company: records each call; once `block_after`
    companies have returned, every further call waits on `release`."""

    def __init__(self, block_after: int | None = None) -> None:
        self.calls: list[str] = []
        self.returned = 0
        self.block_after = block_after
        self.release = asyncio.Event()

    async def __call__(self, company, *, registry, llm, verifier_llm=None, settings):
        self.calls.append(company.company_id)
        if self.block_after is not None and self.returned >= self.block_after:
            await self.release.wait()
        self.returned += 1
        record = TransitionPlanAssessmentRecord(company_id=company.company_id, name=company.name, run_id="", needs_review=True)
        return TransitionPlanAssessmentResult(record, LLMUsage(), 0.0)


@pytest.fixture
def fake(monkeypatch):
    async def _prepare(company, **_kwargs):
        return company

    assessor = FakeAssessor()
    monkeypatch.setattr(tp_pipeline, "_assess_company", assessor)
    monkeypatch.setattr(tp_pipeline, "prepare_company", _prepare)
    return assessor


def _resume(run_id, settings, store, **kwargs):
    return resume_run(
        run_id, settings=settings, run_store=store, registry=DocumentSourceRegistry([]), llm=LLM, verifier_llm=LLM, **kwargs
    )


async def test_killed_worker_resumes_without_repeats(tmp_path, fake):
    settings = _settings(tmp_path)
    store = RunStore(settings.runs_dir)
    run_id = create_transition_plan_run(COMPANIES, settings, store)
    fake.block_after = 3

    task = asyncio.create_task(
        tp_pipeline.execute_transition_plan_run(
            run_id, COMPANIES, llm=LLM, verifier_llm=LLM, registry=DocumentSourceRegistry([]), settings=settings, run_store=store
        )
    )
    while len(store.read_jsonl(store.results_path(run_id))) < 3:
        await asyncio.sleep(0.01)
    task.cancel()  # the kill
    with pytest.raises(asyncio.CancelledError):
        await task
    done_before = {r["company_id"] for r in store.read_jsonl(store.results_path(run_id))}
    fake.release.set()

    assert await _resume(run_id, settings, store) == run_id

    ids = [r["company_id"] for r in store.read_jsonl(store.results_path(run_id))]
    assert sorted(ids) == sorted(c.company_id for c in COMPANIES)
    assert all(fake.calls.count(cid) == 1 for cid in done_before)
    manifest = store.load_manifest(run_id)
    assert manifest.completed_count == 6 and manifest.status == JobStatus.COMPLETED
    keys = [r["item_key"] for r in store.read_jsonl(store.review_queue_path(run_id))]
    assert len(keys) == len(set(keys)) == 6
    assert manifest.review_count == 6


async def test_resume_refuses_completed_run(tmp_path, fake):
    settings = _settings(tmp_path)
    store = RunStore(settings.runs_dir)
    run_id = create_transition_plan_run(COMPANIES[:1], settings, store)
    JobManager(store).finish_run(run_id)
    before = store.manifest_path(run_id).read_text()
    with pytest.raises(NotResumable, match="already completed"):
        await _resume(run_id, settings, store)
    assert store.manifest_path(run_id).read_text() == before


@pytest.mark.parametrize("run_type", ["voting", "calibration", "emerging_themes"])
async def test_resume_refuses_non_resumable_types(tmp_path, run_type):
    settings = _settings(tmp_path)
    store = RunStore(settings.runs_dir)
    run_id = JobManager(store).create_run(run_type, {}, 1, companies=COMPANIES[:1]).run_id
    with pytest.raises(NotResumable, match="not resumable"):
        await _resume(run_id, settings, store)


async def test_resume_refuses_unknown_run(tmp_path):
    settings = _settings(tmp_path)
    with pytest.raises(NotResumable, match="Unknown run_id"):
        await _resume("nope", settings, RunStore(settings.runs_dir))


async def test_resume_refuses_run_without_inputs(tmp_path):
    settings = _settings(tmp_path)
    store = RunStore(settings.runs_dir)
    run_id = create_financials_extraction_run(COMPANIES[:1], settings, store)
    store.companies_path(run_id).unlink()  # a run from before stored inputs
    with pytest.raises(NotResumable, match="run has no stored inputs"):
        await _resume(run_id, settings, store)


async def test_resume_theme_falls_back_to_companies_json(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    store = RunStore(settings.runs_dir)
    activity = ActivityDefinition(name="EV", in_scope_description="EVs.", out_of_scope_description="ICE.")
    theme = ThemeDefinition(name="Electrification", description="", activities=[activity])
    run_id = create_theme_run(theme, COMPANIES[:2], settings, store)  # universe_path=None
    seen = []

    async def _capture(run_id, theme, companies, **_kwargs):
        seen.extend(c.company_id for c in companies)
        return run_id

    monkeypatch.setattr(research_pipeline, "execute_theme_run", _capture)
    await _resume(run_id, settings, store)
    assert seen == ["c1", "c2"]


async def test_resume_theme_prefers_companies_json(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    store = RunStore(settings.runs_dir)
    activity = ActivityDefinition(name="EV", in_scope_description="EVs.", out_of_scope_description="ICE.")
    theme = ThemeDefinition(name="Electrification", description="", activities=[activity])
    universe = tmp_path / "universe.json"  # edited since the run started
    universe.write_text(json.dumps([{"company_id": "c9", "name": "Co 9"}]))
    run_id = create_theme_run(theme, COMPANIES[:2], settings, store, universe_path=str(universe))
    seen = []

    async def _capture(run_id, theme, companies, **_kwargs):
        seen.extend(c.company_id for c in companies)
        return run_id

    monkeypatch.setattr(research_pipeline, "execute_theme_run", _capture)
    await _resume(run_id, settings, store)
    assert seen == ["c1", "c2"]


async def test_resume_theme_run_busy_keeps_cancel_request(tmp_path):
    settings = _settings(tmp_path)
    store = RunStore(settings.runs_dir)
    activity = ActivityDefinition(name="EV", in_scope_description="EVs.", out_of_scope_description="ICE.")
    theme = ThemeDefinition(name="Electrification", description="", activities=[activity])
    run_id = create_theme_run(theme, COMPANIES[:2], settings, store)
    JobManager(store).request_cancel(run_id)
    with run_lease(store, run_id), pytest.raises(RunBusy):  # a live worker
        await _resume(run_id, settings, store)
    assert store.load_manifest(run_id).cancel_requested is True


async def test_resume_resets_failed_and_retries(tmp_path, fake):
    settings = _settings(tmp_path)
    store = RunStore(settings.runs_dir)
    run_id = create_transition_plan_run(COMPANIES[:2], settings, store)
    store.append_jsonl(store.errors_path(run_id), {"key": "c1", "error": "boom"})
    # review_delta with no review_queue row, as discovery records it: resume keeps it.
    JobManager(store).record_progress(run_id, failed_delta=1, review_delta=1, usage=LLMUsage(input_tokens=7), cost_delta_usd=0.5)
    JobManager(store).finish_run(run_id)
    assert store.load_manifest(run_id).status == JobStatus.PARTIALLY_COMPLETED

    await _resume(run_id, settings, store)
    manifest = store.load_manifest(run_id)
    assert manifest.failed_count == 0 and manifest.completed_count == 2
    assert manifest.review_count == 3  # the kept 1 plus the 2 new review items
    assert manifest.status == JobStatus.COMPLETED
    assert manifest.input_tokens == 7 and manifest.estimated_cost_usd == 0.5  # spent money is kept


def _execute(run_id, settings, store):
    return tp_pipeline.execute_transition_plan_run(
        run_id, COMPANIES, llm=LLM, verifier_llm=LLM, registry=DocumentSourceRegistry([]), settings=settings, run_store=store
    )


async def test_plain_execute_holds_the_run(tmp_path, fake):
    """A run started without a launcher (CLI, old theme resume, scheduler)
    still holds the lease: a second execute or a resume is refused."""
    settings = _settings(tmp_path)
    store = RunStore(settings.runs_dir)
    run_id = create_transition_plan_run(COMPANIES, settings, store)
    fake.block_after = 1
    task = asyncio.create_task(_execute(run_id, settings, store))
    while not fake.calls:
        await asyncio.sleep(0.01)
    with pytest.raises(RunBusy):
        await _execute(run_id, settings, store)
    with pytest.raises(RunBusy):
        await _resume(run_id, settings, store)
    fake.release.set()
    assert await task == run_id
    assert all(fake.calls.count(c.company_id) == 1 for c in COMPANIES)
    assert store.load_manifest(run_id).status == JobStatus.COMPLETED


@pytest.fixture
def api(tmp_path):
    settings = _settings(tmp_path)
    store = RunStore(settings.runs_dir)
    app.dependency_overrides[get_run_store] = lambda: store
    app.dependency_overrides[settings_dep] = lambda: settings
    yield settings, store
    for dep in (get_run_store, settings_dep):
        app.dependency_overrides.pop(dep, None)


async def test_resume_busy_run_refused(tmp_path, fake, api):
    settings, store = api
    run_id = create_transition_plan_run(COMPANIES[:1], settings, store)
    with run_lease(store, run_id):
        with pytest.raises(RunBusy):
            await _resume(run_id, settings, store)
        res = TestClient(app).post(f"/api/runs/{run_id}/resume")
        assert res.status_code == 409
    assert TestClient(app).post("/api/runs/nope/resume").status_code == 404
    JobManager(store).finish_run(run_id)
    assert TestClient(app).post(f"/api/runs/{run_id}/resume").status_code == 400


def test_resume_endpoint_requires_analyst(tmp_path, api):
    settings, store = api
    users = tmp_path / "users.json"
    users.write_text(json.dumps({"users": [{"token": "tv", "user_id": "u_v", "name": "V", "role": "viewer"}]}))
    app.dependency_overrides[settings_dep] = lambda: settings.model_copy(update={"auth_mode": "local", "users_file": users})
    # Real sign-in; the router-level authorize stays overridden, so the 403
    # can only come from the endpoint's own require_role("analyst").
    app.dependency_overrides.pop(current_user, None)
    run_id = create_transition_plan_run(COMPANIES[:1], settings, store)
    res = TestClient(app).post(f"/api/runs/{run_id}/resume", headers={"Authorization": "Bearer tv"})
    assert res.status_code == 403


def test_cli_extract_run_resumes(tmp_path, fake, monkeypatch):
    import arp.cli.extraction as cli
    import arp.orchestration.jobs as jobs

    settings = _settings(tmp_path)
    store = RunStore(settings.runs_dir)
    run_id = create_transition_plan_run(COMPANIES[:2], settings, store)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "_run_store", lambda: store)
    monkeypatch.setattr(cli, "_registry", lambda: DocumentSourceRegistry([]))
    monkeypatch.setattr(jobs, "build_llm_client", lambda s: LLM)
    monkeypatch.setattr(jobs, "build_verifier_llm_client", lambda s: LLM)

    res = CliRunner().invoke(extract_app, ["run", "--run-id", run_id])
    assert res.exit_code == 0, res.output
    assert store.load_manifest(run_id).status == JobStatus.COMPLETED

    res = CliRunner().invoke(extract_app, ["run", "--run-id", run_id])
    assert res.exit_code == 1 and "already completed" in res.output


def test_resume_endpoint_launches_and_finishes(tmp_path, fake, api):
    import time

    settings, store = api
    run_id = create_transition_plan_run(COMPANIES[:2], settings, store)
    with TestClient(app) as client:  # keeps the app's loop alive for the launched job
        res = client.post(f"/api/runs/{run_id}/resume")
        assert res.json() == {"run_id": run_id, "status": "resumed"}
        for _ in range(200):
            if store.load_manifest(run_id).status == JobStatus.COMPLETED:
                break
            time.sleep(0.02)
    assert store.load_manifest(run_id).status == JobStatus.COMPLETED  # lease=False: no RunBusy under the launcher's lease


async def test_resume_keeps_batch_mode(tmp_path, monkeypatch):
    from arp.llm.batching_client import BatchingLLMClient

    settings = _settings(tmp_path)
    store = RunStore(settings.runs_dir)
    run_id = create_transition_plan_run(COMPANIES[:1], settings, store)
    JobManager(store)._update(run_id, lambda m: m.params.__setitem__("batch", True))
    seen = {}

    async def _execute(run_id, companies, *, llm, verifier_llm, settings, **_kwargs):
        seen.update(llm=llm, verifier_llm=verifier_llm, settings=settings)
        return run_id

    monkeypatch.setattr(tp_pipeline, "execute_transition_plan_run", _execute)
    await resume_run(run_id, settings=settings, run_store=store, registry=DocumentSourceRegistry([]))
    assert isinstance(seen["llm"], BatchingLLMClient) and isinstance(seen["verifier_llm"], BatchingLLMClient)
    assert seen["settings"].llm_batch is True


def test_cli_theme_resume_keeps_batch_mode(tmp_path, monkeypatch):
    """`theme resume` hands resume_run pre-built real-time clients; a batch run must still resume in batch mode."""
    import arp.cli.theme as cli_theme
    from arp.llm.batching_client import BatchingLLMClient

    settings = _settings(tmp_path)
    store = RunStore(settings.runs_dir)
    activity = ActivityDefinition(name="EV", in_scope_description="EVs.", out_of_scope_description="ICE.")
    run_id = create_theme_run(ThemeDefinition(name="E", description="", activities=[activity]), COMPANIES[:1], settings, store)
    JobManager(store)._update(run_id, lambda m: m.params.__setitem__("batch", True))
    seen = {}

    async def _capture(run_id, theme, companies, *, llm, verifier_llm, settings, **_kwargs):
        seen.update(llm=llm, verifier_llm=verifier_llm, settings=settings)
        return run_id

    monkeypatch.setattr(research_pipeline, "execute_theme_run", _capture)
    monkeypatch.setattr(cli_theme, "get_settings", lambda: settings)
    monkeypatch.setattr(cli_theme, "_run_store", lambda: store)
    monkeypatch.setattr(cli_theme, "_registry", lambda: DocumentSourceRegistry([]))
    res = CliRunner().invoke(cli_theme.theme_app, ["resume", run_id])
    assert res.exit_code == 0, res.output
    assert isinstance(seen["llm"], BatchingLLMClient) and isinstance(seen["verifier_llm"], BatchingLLMClient)
    assert seen["settings"].llm_batch is True


def _batch_cli(tmp_path, monkeypatch, module, attr, app, args, create, theme_args=()):
    """Runs a CLI run command with `run_*` faked; returns (the llm it was given, the run's manifest params)."""
    settings = Settings(anthropic_api_key="unused", runs_dir=tmp_path / "runs", cache_dir=tmp_path / "cache")
    store = RunStore(settings.runs_dir)
    seen = {}

    async def _fake(*a, llm, settings, **_k):
        seen["llm"] = llm
        return create(*a, settings, store)  # the real creator, as the pipeline calls it

    monkeypatch.setattr(module, attr, _fake)
    monkeypatch.setattr(module, "get_settings", lambda: settings)
    monkeypatch.setattr(module, "_run_store", lambda: store)
    monkeypatch.setattr(module, "_registry", lambda: DocumentSourceRegistry([]))
    monkeypatch.setattr(module, "_engagement_store", lambda: None, raising=False)
    universe = tmp_path / "u.csv"
    universe.write_text("company_id,name\nAAA,Alpha Inc\n")
    theme = tmp_path / "theme.json"
    theme.write_text(ThemeDefinition(name="T", description="").model_dump_json())
    out = []
    for extra in ([], ["--batch"]):
        res = CliRunner().invoke(app, [*args, *theme_args, "--universe", str(universe), *extra])
        assert res.exit_code == 0, res.output
        out.append(seen["llm"])
    params = [m.params.get("batch") for m in sorted(store.list_runs(), key=lambda m: m.created_at)]
    return out, params


def test_theme_cli_batch_flag(tmp_path, monkeypatch):
    import arp.cli.theme as cli_theme

    (plain, batched), params = _batch_cli(tmp_path, monkeypatch, cli_theme, "run_thematic_universe", cli_theme.theme_app, ["run"], create_theme_run, ["--theme", str(tmp_path / "theme.json")])
    assert not isinstance(plain, BatchingLLMClient) and isinstance(batched, BatchingLLMClient)
    assert params == [None, True]


def test_voting_cli_batch_flag(tmp_path, monkeypatch):
    import arp.cli.voting as cli_voting

    (plain, batched), params = _batch_cli(tmp_path, monkeypatch, cli_voting, "run_voting", cli_voting.voting_app, ["run"], create_voting_run)
    assert not isinstance(plain, BatchingLLMClient) and isinstance(batched, BatchingLLMClient)
    assert params == [None, True]
