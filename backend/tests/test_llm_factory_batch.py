from arp.api import run_scheduling
from arp.config import Settings
from arp.llm.batching_client import BatchingLLMClient
from arp.llm.factory import batch_settings, build_llm_client, build_verifier_llm_client
from arp.orchestration.job_manager import JobManager
from arp.storage.run_store import RunStore


def _settings(tmp_path) -> Settings:
    return Settings(anthropic_api_key="unused", runs_dir=tmp_path / "runs", cache_dir=tmp_path / "cache")


def test_batch_settings_off_is_identity(tmp_path):
    s = _settings(tmp_path)
    assert batch_settings(s, False) is s
    assert not isinstance(build_llm_client(s), BatchingLLMClient)


def test_batch_settings_on(tmp_path):
    s = _settings(tmp_path)
    b = batch_settings(s, True)
    assert b.llm_batch is True
    assert b.max_concurrent_llm_calls == s.batch_concurrency == 1000
    assert s.llm_batch is False


def test_factory_returns_batching_client(tmp_path):
    s = batch_settings(_settings(tmp_path), True)
    llm, verifier = build_llm_client(s), build_verifier_llm_client(s)
    assert isinstance(llm, BatchingLLMClient) and isinstance(verifier, BatchingLLMClient)
    assert llm._batch_log == s.cache_dir / "llm_batches.jsonl"
    assert llm is not build_llm_client(s)  # one client per run, never shared


class _Launcher:
    def launch(self, run_id, job):
        pass


def _schedule(settings) -> dict:
    store = RunStore(settings.runs_dir)
    run_id = run_scheduling.schedule_llm_run(
        create_fn=lambda: JobManager(store).create_run("financials", {}, 1).run_id,
        run=None,
        settings=settings,
    )
    return store.load_manifest(run_id).params


def test_schedule_llm_run_marks_batch_run(tmp_path, monkeypatch):
    monkeypatch.setattr(run_scheduling, "get_job_launcher", _Launcher)
    s = _settings(tmp_path)
    assert _schedule(batch_settings(s, True))["batch"] is True
    assert "batch" not in _schedule(s)


async def test_emerging_themes_run_marked_batch(tmp_path, monkeypatch):
    from arp.emerging_themes import pipeline

    async def _execute(run_id, *_args, **_kwargs):
        return run_id

    monkeypatch.setattr(pipeline, "execute_emerging_themes_run", _execute)
    s = _settings(tmp_path)
    store = RunStore(s.runs_dir)

    async def _run(settings):
        run_id = await pipeline.run_emerging_themes(
            [], llm=None, sources=[], settings=settings, run_store=store, topic_store=None, triggered_by="schedule"
        )
        return store.load_manifest(run_id).params

    assert (await _run(batch_settings(s, "emerging_themes" in s.batch_scheduled_run_types)))["batch"] is True
    assert "batch" not in await _run(s)
