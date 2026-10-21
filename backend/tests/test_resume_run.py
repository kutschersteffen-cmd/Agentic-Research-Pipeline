import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import arp.research.pipeline as research_pipeline
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
from arp.research.pipeline import CompanyMatchesResult, create_theme_run
from arp.schemas.common import CompanyRef, JobStatus
from arp.schemas.thematic import ActivityDefinition, ThemeDefinition
from arp.storage.run_store import RunStore
from arp.voting.pipeline import create_voting_run
from tests.postgres_helpers import forget_companies, pg_dsn

COMPANIES = [CompanyRef(company_id=f"c{i}", name=f"Co {i}") for i in range(1, 7)]
LLM = object()  # never called: the fake assessor stands in for every LLM step
THEME = ThemeDefinition(name="T", description="")


def _settings(tmp_path) -> Settings:
    return Settings(anthropic_api_key="unused", runs_dir=tmp_path / "runs", cache_dir=tmp_path / "cache")


def _theme_run(companies, settings, store) -> str:
    return create_theme_run(THEME, companies, settings, store)


class FakeAssessor:
    """Stands in for the theme pipeline's _match_company: records each call; once
    `block_after` companies have returned, every further call waits on `release`."""

    def __init__(self, block_after: int | None = None) -> None:
        self.calls: list[str] = []
        self.returned = 0
        self.block_after = block_after
        self.release = asyncio.Event()

    async def __call__(self, company, theme, *, registry, llm, verifier_llm=None, settings, **_kwargs):
        self.calls.append(company.company_id)
        if self.block_after is not None and self.returned >= self.block_after:
            await self.release.wait()
        self.returned += 1
        # A model-chosen sector code: one review item per company.
        return CompanyMatchesResult([], LLMUsage(), 0.0, isic_code="X", isic_from_model=True)


@pytest.fixture
def fake(monkeypatch):
    assessor = FakeAssessor()
    monkeypatch.setattr(research_pipeline, "_match_company", assessor)
    return assessor


def _resume(run_id, settings, store, **kwargs):
    return resume_run(
        run_id, settings=settings, run_store=store, registry=DocumentSourceRegistry([]), llm=LLM, verifier_llm=LLM, **kwargs
    )


async def test_killed_worker_resumes_without_repeats(tmp_path, fake, pg):
    settings = _settings(tmp_path)
    store = RunStore(pg, settings.runs_dir)
    run_id = _theme_run(COMPANIES, settings, store)
    fake.block_after = 3

    task = asyncio.create_task(
        research_pipeline.execute_theme_run(
            run_id, THEME, COMPANIES, llm=LLM, verifier_llm=LLM, registry=DocumentSourceRegistry([]), settings=settings, run_store=store
        )
    )
    while len(store.read_results(run_id)) < 3:
        await asyncio.sleep(0.01)
    task.cancel()  # the kill
    with pytest.raises(asyncio.CancelledError):
        await task
    done_before = {r["_key"] for r in store.read_results(run_id)}
    fake.release.set()

    assert await _resume(run_id, settings, store) == run_id

    ids = [r["_key"] for r in store.read_results(run_id)]
    assert sorted(ids) == sorted(c.company_id for c in COMPANIES)
    assert all(fake.calls.count(cid) == 1 for cid in done_before)
    manifest = store.load_manifest(run_id)
    assert manifest.completed_count == 6 and manifest.status == JobStatus.COMPLETED
    keys = [r["item_key"] for r in store.read_review_queue(run_id)]
    assert len(keys) == len(set(keys)) == 6
    assert manifest.review_count == 6


async def test_resume_refuses_completed_run(tmp_path, fake, pg):
    settings = _settings(tmp_path)
    store = RunStore(pg, settings.runs_dir)
    run_id = _theme_run(COMPANIES[:1], settings, store)
    store.append_result(run_id, {"_key": "c1"})  # every company reached
    JobManager(store).finish_run(run_id)
    before = store.load_manifest(run_id)
    with pytest.raises(NotResumable, match="already completed"):
        await _resume(run_id, settings, store)
    assert store.load_manifest(run_id) == before


@pytest.mark.parametrize("run_type", ["voting", "calibration", "emerging_themes"])
async def test_resume_refuses_non_resumable_types(tmp_path, run_type, pg):
    settings = _settings(tmp_path)
    store = RunStore(pg, settings.runs_dir)
    run_id = JobManager(store).create_run(run_type, {}, 1, companies=COMPANIES[:1]).run_id
    with pytest.raises(NotResumable, match="not resumable"):
        await _resume(run_id, settings, store)


async def test_resume_refuses_unknown_run(tmp_path, pg):
    settings = _settings(tmp_path)
    with pytest.raises(NotResumable, match="Unknown run_id"):
        await _resume("nope", settings, RunStore(pg, settings.runs_dir))


async def test_resume_refuses_run_without_inputs(tmp_path, pg):
    settings = _settings(tmp_path)
    store = RunStore(pg, settings.runs_dir)
    run_id = create_financials_extraction_run(COMPANIES[:1], settings, store)
    forget_companies(store, run_id)  # a run from before stored inputs
    with pytest.raises(NotResumable, match="run has no stored inputs"):
        await _resume(run_id, settings, store)


async def test_resume_theme_falls_back_to_companies_json(tmp_path, monkeypatch, pg):
    settings = _settings(tmp_path)
    store = RunStore(pg, settings.runs_dir)
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


async def test_resume_theme_prefers_companies_json(tmp_path, monkeypatch, pg):
    settings = _settings(tmp_path)
    store = RunStore(pg, settings.runs_dir)
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


async def test_resume_theme_run_busy_keeps_cancel_request(tmp_path, pg):
    settings = _settings(tmp_path)
    store = RunStore(pg, settings.runs_dir)
    activity = ActivityDefinition(name="EV", in_scope_description="EVs.", out_of_scope_description="ICE.")
    theme = ThemeDefinition(name="Electrification", description="", activities=[activity])
    run_id = create_theme_run(theme, COMPANIES[:2], settings, store)
    JobManager(store).request_cancel(run_id)
    with run_lease(store, run_id), pytest.raises(RunBusy):  # a live worker
        await _resume(run_id, settings, store)
    assert store.load_manifest(run_id).cancel_requested is True


async def test_resume_resets_failed_and_retries(tmp_path, fake, pg):
    settings = _settings(tmp_path)
    store = RunStore(pg, settings.runs_dir)
    run_id = _theme_run(COMPANIES[:2], settings, store)
    store.append_error(run_id, {"key": "c1", "error": "boom"})
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
    return research_pipeline.execute_theme_run(
        run_id, THEME, COMPANIES, llm=LLM, verifier_llm=LLM, registry=DocumentSourceRegistry([]), settings=settings, run_store=store
    )


async def test_plain_execute_holds_the_run(tmp_path, fake, pg):
    """A run started without a launcher (CLI, old theme resume, scheduler)
    still holds the lease: a second execute or a resume is refused."""
    settings = _settings(tmp_path)
    store = RunStore(pg, settings.runs_dir)
    run_id = _theme_run(COMPANIES, settings, store)
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
def api(tmp_path, pg):
    settings = _settings(tmp_path)
    store = RunStore(pg, settings.runs_dir)
    app.dependency_overrides[get_run_store] = lambda: store
    app.dependency_overrides[settings_dep] = lambda: settings
    yield settings, store
    for dep in (get_run_store, settings_dep):
        app.dependency_overrides.pop(dep, None)


async def test_resume_busy_run_refused(tmp_path, fake, api):
    settings, store = api
    run_id = _theme_run(COMPANIES[:1], settings, store)
    with run_lease(store, run_id):
        with pytest.raises(RunBusy):
            await _resume(run_id, settings, store)
        res = TestClient(app).post(f"/api/runs/{run_id}/resume")
        assert res.status_code == 409
    assert TestClient(app).post("/api/runs/nope/resume").status_code == 404
    store.append_result(run_id, {"_key": "c1"})  # every company reached
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
    run_id = _theme_run(COMPANIES[:1], settings, store)
    res = TestClient(app).post(f"/api/runs/{run_id}/resume", headers={"Authorization": "Bearer tv"})
    assert res.status_code == 403


def test_cli_extract_run_resumes(tmp_path, fake, monkeypatch, pg):
    import arp.cli.extraction as cli
    import arp.orchestration.jobs as jobs

    settings = _settings(tmp_path)
    store = RunStore(pg, settings.runs_dir)
    run_id = _theme_run(COMPANIES[:2], settings, store)
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
    run_id = _theme_run(COMPANIES[:2], settings, store)
    with TestClient(app) as client:  # keeps the app's loop alive for the launched job
        res = client.post(f"/api/runs/{run_id}/resume")
        assert res.json() == {"run_id": run_id, "status": "resumed"}
        for _ in range(200):
            if store.load_manifest(run_id).status == JobStatus.COMPLETED:
                break
            time.sleep(0.02)
    assert store.load_manifest(run_id).status == JobStatus.COMPLETED  # lease=False: no RunBusy under the launcher's lease


async def test_resume_keeps_batch_mode(tmp_path, monkeypatch, pg):
    from arp.llm.batching_client import BatchingLLMClient

    settings = _settings(tmp_path)
    store = RunStore(pg, settings.runs_dir)
    run_id = _theme_run(COMPANIES[:1], settings, store)
    JobManager(store)._update(run_id, lambda m: m.params.__setitem__("batch", True))
    seen = {}

    async def _execute(run_id, theme, companies, *, llm, verifier_llm, settings, **_kwargs):
        seen.update(llm=llm, verifier_llm=verifier_llm, settings=settings)
        return run_id

    monkeypatch.setattr(research_pipeline, "execute_theme_run", _execute)
    await resume_run(run_id, settings=settings, run_store=store, registry=DocumentSourceRegistry([]))
    assert isinstance(seen["llm"], BatchingLLMClient) and isinstance(seen["verifier_llm"], BatchingLLMClient)
    assert seen["settings"].llm_batch is True


def test_cli_theme_resume_keeps_batch_mode(tmp_path, monkeypatch, pg):
    """`theme resume` hands resume_run pre-built real-time clients; a batch run must still resume in batch mode."""
    import arp.cli.theme as cli_theme
    from arp.llm.batching_client import BatchingLLMClient

    settings = _settings(tmp_path)
    store = RunStore(pg, settings.runs_dir)
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
    store = RunStore(pg_dsn(), settings.runs_dir)
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


def test_theme_cli_batch_flag(tmp_path, monkeypatch, pg):
    import arp.cli.theme as cli_theme

    (plain, batched), params = _batch_cli(tmp_path, monkeypatch, cli_theme, "run_thematic_universe", cli_theme.theme_app, ["run"], create_theme_run, ["--theme", str(tmp_path / "theme.json")])
    assert not isinstance(plain, BatchingLLMClient) and isinstance(batched, BatchingLLMClient)
    assert params == [None, True]


def test_voting_cli_batch_flag(tmp_path, monkeypatch, pg):
    import arp.cli.voting as cli_voting

    (plain, batched), params = _batch_cli(tmp_path, monkeypatch, cli_voting, "run_voting", cli_voting.voting_app, ["run"], create_voting_run)
    assert not isinstance(plain, BatchingLLMClient) and isinstance(batched, BatchingLLMClient)
    assert params == [None, True]


def _run(tmp_path, pg, n=1):
    settings = _settings(tmp_path)
    store = RunStore(pg, settings.runs_dir)
    return store, _theme_run(COMPANIES[:n], settings, store)


def test_crash_inside_the_lease_marks_the_run_failed(tmp_path, pg):
    from arp.orchestration.jobs import hold_run

    store, run_id = _run(tmp_path, pg)
    with pytest.raises(RuntimeError), hold_run(store, run_id):
        raise RuntimeError("boom")
    manifest = store.load_manifest(run_id)
    assert (manifest.status, manifest.error) == (JobStatus.FAILED, "RuntimeError: boom")


def test_nested_holders_mark_failed_once(tmp_path, pg, monkeypatch):
    from arp.orchestration.jobs import hold_run

    store, run_id = _run(tmp_path, pg)
    calls = []
    finish = JobManager.finish_run
    monkeypatch.setattr(JobManager, "finish_run", lambda self, *a, **kw: calls.append(a) or finish(self, *a, **kw))
    with pytest.raises(RuntimeError), hold_run(store, run_id), hold_run(store, run_id):
        raise RuntimeError("boom")
    assert len(calls) == 1


def test_busy_run_and_cancellation_are_not_failures(tmp_path, pg):
    from arp.orchestration.jobs import hold_run

    store, run_id = _run(tmp_path, pg)
    before = store.load_manifest(run_id)
    with run_lease(store, run_id), pytest.raises(RunBusy), hold_run(store, run_id):
        pass
    with pytest.raises(asyncio.CancelledError), hold_run(store, run_id):
        raise asyncio.CancelledError
    assert store.load_manifest(run_id).status == before.status == JobStatus.RUNNING


def test_finish_run_failure_keeps_the_original_error(tmp_path, pg, monkeypatch):
    from arp.orchestration.jobs import hold_run

    store, run_id = _run(tmp_path, pg)

    def broken(self, *a, **kw):
        raise OSError("db down")

    monkeypatch.setattr(JobManager, "finish_run", broken)
    with pytest.raises(RuntimeError, match="boom"), hold_run(store, run_id):
        raise RuntimeError("boom")


def test_completed_run_that_missed_companies_is_resumable(tmp_path, pg):
    from arp.orchestration.jobs import check_resumable

    store, run_id = _run(tmp_path, pg, n=2)
    JobManager(store).record_progress(run_id, completed_delta=1)
    JobManager(store).finish_run(run_id)
    assert check_resumable(store, run_id).run_id == run_id


def test_completed_run_whose_rest_stopped_for_review_is_refused(tmp_path, pg):
    from arp.orchestration.jobs import check_resumable

    store, run_id = _run(tmp_path, pg, n=2)
    store.append_result(run_id, {"_key": "c1"})
    store.append_error(run_id, {"key": "c2", "review": True})  # stopped for a person
    JobManager(store).finish_run(run_id)
    with pytest.raises(NotResumable, match="already completed"):
        check_resumable(store, run_id)


def test_resume_endpoint_crash_marks_theme_run_failed(tmp_path, monkeypatch, api):
    import arp.api.routers.runs as runs_router

    settings, store = api
    activity = ActivityDefinition(name="EV", in_scope_description="EVs.", out_of_scope_description="ICE.")
    run_id = create_theme_run(ThemeDefinition(name="E", description="", activities=[activity]), COMPANIES[:1], settings, store)
    JobManager(store).finish_run(run_id, error="killed")

    async def boom(*_a, **_kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(runs_router, "resume_run", boom)
    with TestClient(app) as client:
        res = client.post(f"/api/runs/{run_id}/resume")
        assert res.json() == {"run_id": run_id, "status": "resumed"}
        client.portal.call(asyncio.sleep, 0.05)
    manifest = store.load_manifest(run_id)
    assert (manifest.status, manifest.error) == (JobStatus.FAILED, "RuntimeError: boom")


def test_completed_run_with_every_stored_company_done_is_refused_whatever_the_counts(tmp_path, pg):
    """company_count counts refs save_companies may drop (duplicates, identity conflicts); the stored companies decide."""
    from arp.orchestration.jobs import check_resumable

    store, run_id = _run(tmp_path, pg, n=2)
    for c in COMPANIES[:2]:
        store.append_result(run_id, {"_key": c.company_id, "company_id": c.company_id})
    JobManager(store).record_progress(run_id, completed_delta=1)  # counts under-report what was done
    JobManager(store).finish_run(run_id)
    with pytest.raises(NotResumable, match="already completed"):
        check_resumable(store, run_id)


def test_lease_leaves_no_worker_file(tmp_path, pg):
    store, run_id = _run(tmp_path, pg)
    with run_lease(store, run_id):
        pass
    assert not (store.runs_dir / run_id / ".worker").exists()


def test_lease_conflicts_per_run_and_is_released(tmp_path, pg):
    store = RunStore(pg, tmp_path / "runs")
    with run_lease(store, "r1"):
        with pytest.raises(RunBusy), run_lease(store, "r1"):
            pass
        with run_lease(store, "r2"):
            pass
    with run_lease(store, "r1"):
        pass
    with pytest.raises(RuntimeError), run_lease(store, "r1"):
        raise RuntimeError
    with run_lease(store, "r1"):
        pass


def test_lease_is_held_in_postgres(tmp_path, pg):
    from sqlalchemy import text

    from arp.db.session import transaction
    from arp.orchestration.jobs import _LEASE_NS

    store, run_id = _run(tmp_path, pg)
    held = text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND classid = :ns")
    with run_lease(store, run_id), transaction(pg) as s:
        assert s.scalar(held, {"ns": _LEASE_NS}) == 1


def test_lease_cycles_leak_no_connections(tmp_path, pg):
    from sqlalchemy import text

    from arp.db.session import transaction

    store, run_id = _run(tmp_path, pg)

    def connections():
        with transaction(pg) as s:
            return s.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"))

    before = connections()
    for _ in range(50):
        with run_lease(store, run_id):
            pass
    assert connections() <= before


def test_dead_lease_connection_keeps_the_runs_outcome(tmp_path, pg):
    """The lease connection dropped mid-run (failover, idle NAT): the run's own result or error stands."""
    from sqlalchemy import text

    from arp.db.session import transaction
    from arp.orchestration.jobs import _LEASE_NS

    store, run_id = _run(tmp_path, pg)

    def kill_lease():
        with transaction(pg) as s:
            s.execute(text("SELECT pg_terminate_backend(pid) FROM pg_locks WHERE locktype = 'advisory' AND classid = :ns"
                           " AND database = (SELECT oid FROM pg_database WHERE datname = current_database())"),
                      {"ns": _LEASE_NS})

    with run_lease(store, run_id):
        kill_lease()  # completes normally: no error
    with pytest.raises(ValueError, match="real"), run_lease(store, run_id):
        kill_lease()
        raise ValueError("real")
    with run_lease(store, run_id):  # and the lease is free again
        pass
