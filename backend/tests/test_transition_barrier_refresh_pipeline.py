from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from arp.config import Settings
from arp.orchestration.review_queue import latest_decisions
from arp.schemas.transition_barrier import RefreshOutcome
from arp.storage.run_store import RunStore
from arp.transition_barrier import dataset
from arp.transition_barrier.refresh import pipeline as refresh_pipeline
from arp.transition_barrier.refresh.pipeline import RefreshDisabledError, execute_refresh_run, run_refresh
from arp.transition_barrier.refresh.reconciler import FetchedVersion

SCORES_PATH = Path(dataset.__file__).parent / "data" / "assessment_scores.json"


def _settings(**overrides) -> Settings:
    return Settings(anthropic_api_key="unused", transition_barrier_refresh_enabled=True, **overrides)


@pytest.fixture
def run_store(tmp_path) -> RunStore:
    return RunStore(tmp_path / "runs")


@pytest.fixture
def no_network(monkeypatch):
    """Replace the retriever so no test touches the network. Each source comes
    back as an act that is no longer in force -- the worst case, which produces
    a rating-change candidate for every cell it touches.
    """

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    async def _fake_fetch(routed, *, client):
        return FetchedVersion(
            source_key=routed.source.key,
            eli=routed.eli,
            in_force=False,
            quote="no longer in force",
        )

    monkeypatch.setattr(refresh_pipeline, "build_client", lambda *a, **k: _FakeClient())
    monkeypatch.setattr(refresh_pipeline, "fetch_version", _fake_fetch)


async def test_refresh_never_mutates_the_bundled_scores(run_store, no_network):
    """The rule that matters: a refresh may propose, never apply. The bundled
    data file must be byte-identical after a run that found a rating change for
    every cell it checked.
    """
    before = hashlib.sha256(SCORES_PATH.read_bytes()).hexdigest()

    run_id, findings = await run_refresh(settings=_settings(), run_store=run_store)

    after = hashlib.sha256(SCORES_PATH.read_bytes()).hexdigest()
    assert after == before, "a refresh run must never write back to assessment_scores.json"
    assert findings
    assert all(f.outcome is RefreshOutcome.RATING_CHANGE_CANDIDATE for f in findings)
    assert run_store.load_manifest(run_id) is not None


async def test_rating_change_candidates_land_in_the_review_queue(run_store, no_network):
    run_id, findings = await run_refresh(settings=_settings(), run_store=run_store)

    queued = run_store.read_jsonl(run_store.review_queue_path(run_id))
    assert len(queued) == len(findings), "every candidate must be queued for a human"
    assert latest_decisions(run_store, run_id) == {}, "nothing may be pre-decided"

    item = queued[0]["payload"] if "payload" in queued[0] else queued[0]
    assert item["outcome"] == "rating_change_candidate"
    assert item["proposed_rating"] is not None
    assert item["source_quote"], "a queued change must carry the exact source quote it rests on"


async def test_results_are_written_and_progress_recorded(run_store, no_network):
    run_id, findings = await run_refresh(settings=_settings(), run_store=run_store)

    rows = run_store.read_jsonl(run_store.results_path(run_id))
    assert len(rows) == len(findings)

    manifest = run_store.load_manifest(run_id)
    assert manifest.completed_count == 15, "one unit of work per automatable legal source"
    assert manifest.review_count == len(findings)
    assert manifest.status.value in {"completed", "succeeded", "done"}


async def test_a_fetch_failure_does_not_abort_the_run(run_store, monkeypatch):
    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    calls = {"n": 0}

    async def _flaky_fetch(routed, *, client):
        calls["n"] += 1
        if calls["n"] == 1:
            return FetchedVersion(source_key=routed.source.key, eli=routed.eli, error="timeout")
        return FetchedVersion(source_key=routed.source.key, eli=routed.eli, in_force=True)

    monkeypatch.setattr(refresh_pipeline, "build_client", lambda *a, **k: _FakeClient())
    monkeypatch.setattr(refresh_pipeline, "fetch_version", _flaky_fetch)

    run_id, findings = await run_refresh(settings=_settings(), run_store=run_store)

    assert calls["n"] == 15, "one unreachable source must not stop the other fourteen"
    assert any(f.outcome is RefreshOutcome.FETCH_FAILED for f in findings)
    assert any(f.outcome is RefreshOutcome.UNCHANGED for f in findings)

    manifest = run_store.load_manifest(run_id)
    assert manifest.failed_count == 1
    # completed and failed must not double-count the same source.
    assert manifest.completed_count == 14
    assert manifest.completed_count + manifest.failed_count == 15

    # An unverifiable cell still reaches a human rather than being dropped.
    queued = run_store.read_jsonl(run_store.review_queue_path(run_id))
    assert len(queued) == sum(1 for f in findings if f.outcome is RefreshOutcome.FETCH_FAILED)


async def test_execute_refuses_when_disabled(run_store):
    with pytest.raises(RefreshDisabledError):
        await execute_refresh_run("whatever", settings=Settings(anthropic_api_key="unused"), run_store=run_store)
