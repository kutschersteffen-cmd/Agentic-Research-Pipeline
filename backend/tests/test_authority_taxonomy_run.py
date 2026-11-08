import asyncio

import pytest

from arp.research.authority_taxonomy import run
from arp.research.authority_taxonomy.discovery import Candidate
from arp.research.authority_taxonomy.extract import SourceExtraction
from arp.storage.run_store import LegacyRunStore
from arp.storage.taxonomy_store import TaxonomyStore
from tests.test_authority_taxonomy_consolidate import _act, _fake, _settings


@pytest.fixture
def env(monkeypatch, tmp_path):
    async def fake_discover(theme_name, theme_key, guidance, **kw):
        return [Candidate(url="https://a.org", title="A", source_type="agency_report", summary="s", reason="r",
                          fetchable=True, covers=[], from_library=False)]

    async def fake_fetch(url, user_agent, timeout=20.0, max_chars=0):
        assert max_chars == 400_000
        return None if "bad" in url else "text"

    async def fake_extract(url, text, **kw):
        return SourceExtraction(url=url, activities=[_act("Stacks", url)])

    monkeypatch.setattr(run, "discover_candidates", fake_discover)
    monkeypatch.setattr(run, "fetch_source_text", fake_fetch)
    monkeypatch.setattr(run, "extract_source", fake_extract)
    store = LegacyRunStore(tmp_path / "runs")
    deps = dict(llm=_fake(10), settings=_settings(tmp_path), user_agent="t", value_chain_model=None)
    return store, TaxonomyStore(tmp_path / "tax"), deps, tmp_path


def _start(store):
    return asyncio.run(run.start_run("Hydrogen", None, "", "", False, run_store=store, search_client=None,
                                     llm=None, user_agent="t"))


def _review(env, files=()):
    store, _, deps, _ = env
    state = _start(store)
    return asyncio.run(run.select_sources(state.run_id, ["https://a.org"], list(files), run_store=store, **deps))


def test_put_and_accept(env):
    store, tax, _, _ = env
    state = _review(env)
    assert state.stage == "awaiting_review"
    draft = state.draft.model_copy(deep=True)
    draft.activities[0].name = "N"
    run.put_draft(state.run_id, draft, store)
    assert run.load_state(state.run_id, store).draft.activities[0].name == "N"
    done = run.accept(state.run_id, store, tax)
    assert done.stage == "accepted"
    t = tax.get(done.taxonomy_id)
    assert (t.theme.activities[0].name, t.version, t.derivation_method, t.status) == ("N", 1, "authority_source", "draft")


def test_nothing_saved_before_accept(env):
    _, tax, _, _ = env
    before = len(tax.list_all())
    _review(env)
    assert len(tax.list_all()) == before


def test_local_file_source(env):
    f = env[3] / "f.txt"
    f.write_text("local text")
    state = _review(env, [f])
    assert str(f) in {c.source_url for a in state.draft.activities for c in a.citations}


def test_accept_wrong_stage(env):
    store, tax, _, _ = env
    state = _start(store)
    with pytest.raises(run.WrongStage) as e:
        run.accept(state.run_id, store, tax)
    assert e.value.stage == "awaiting_sources"


def test_cancel_both_stages(env):
    store = env[0]
    for state in (_start(store), _review(env)):
        run.cancel(state.run_id, store)
        assert run.load_state(state.run_id, store).stage == "cancelled"


def test_draft_without_citation_rejected(env):
    store = env[0]
    state = _review(env)
    draft = state.draft.model_copy(deep=True)
    draft.activities[0].citations = []
    with pytest.raises(ValueError, match="activity Stacks has no citation"):
        run.put_draft(state.run_id, draft, store)


def test_unreadable_source_in_notes(env):
    store, _, deps, _ = env
    state = _start(store)
    state = asyncio.run(run.select_sources(state.run_id, ["https://a.org", "https://bad.org"], [], run_store=store, **deps))
    assert "Could not read: https://bad.org" in state.notes


def test_all_unreadable_keeps_stage(env):
    store, _, deps, _ = env
    state = _start(store)
    with pytest.raises(ValueError, match="no selected source could be read"):
        asyncio.run(run.select_sources(state.run_id, ["https://bad.org"], [], run_store=store, **deps))
    # the run goes back to the same stage, now carrying the error and the kept selection
    assert run.load_state(state.run_id, store) == state.model_copy(update={
        "error": "no selected source could be read", "selection": run.SourceSelection(urls=["https://bad.org"]),
    })


# --- background steps -------------------------------------------------------

def _create(store):
    return run.create_run("Hydrogen", None, "", "", False, run_store=store)


def _discover(store, run_id):
    return asyncio.run(run.discover(run_id, run_store=store, search_client=None, llm=None, user_agent="t"))


def _extract(env, run_id):
    store, _, deps, _ = env
    return asyncio.run(run.extract(run_id, run_store=store, **deps))


def test_create_run_is_discovering(env):
    state = _create(env[0])
    assert state.stage == "discovering" and state.step_started_at


def test_discover_success(env, monkeypatch):
    async def two(*a, **kw):
        return [Candidate(url=f"https://{c}.org", title=c, source_type="agency_report", summary="s", reason="r",
                          fetchable=True, covers=[], from_library=False) for c in "ab"]

    monkeypatch.setattr(run, "discover_candidates", two)
    store = env[0]
    state = _discover(store, _create(store).run_id)
    assert (state.stage, len(state.candidates), state.error) == ("awaiting_sources", 2, None)


def test_discover_failure(env, monkeypatch):
    async def boom(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(run, "discover_candidates", boom)
    store = env[0]
    state = _discover(store, _create(store).run_id)
    assert state.stage == "failed" and "boom" in state.error


def _awaiting(env):
    store = env[0]
    return _discover(store, _create(store).run_id)


def test_extract_unreadable_keeps_selection(env):
    store = env[0]
    state = _awaiting(env)
    run.begin_extraction(state.run_id, ["https://bad.org"], [], run_store=store)
    state = _extract(env, state.run_id)
    assert state.stage == "awaiting_sources"
    assert "no selected source could be read" in state.error
    assert state.selection.urls == ["https://bad.org"]


def test_extract_after_failure_clears_error(env):
    store = env[0]
    rid = _awaiting(env).run_id
    run.begin_extraction(rid, ["https://bad.org"], [], run_store=store)
    _extract(env, rid)
    run.begin_extraction(rid, ["https://a.org"], [], run_store=store)
    state = _extract(env, rid)
    assert (state.stage, state.error) == ("awaiting_review", None)


def test_cancel_during_extract(env):
    store = env[0]
    rid = _awaiting(env).run_id
    run.begin_extraction(rid, ["https://a.org"], [], run_store=store)
    run.cancel(rid, store)
    state = _extract(env, rid)
    assert (state.stage, state.draft, state.error) == ("cancelled", None, None)


def test_cancel_during_discover(env):
    store = env[0]
    rid = _create(store).run_id
    run.cancel(rid, store)
    state = _discover(store, rid)
    assert (state.stage, state.candidates, state.error) == ("cancelled", [], None)


def test_cancel_then_step_raises_keeps_cancelled(env, monkeypatch):
    async def boom(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(run, "discover_candidates", boom)
    store = env[0]
    rid = _create(store).run_id
    run.cancel(rid, store)
    state = _discover(store, rid)
    assert (state.stage, state.error) == ("cancelled", None)


def _aged(env, stage, minutes_ago):
    from datetime import UTC, datetime, timedelta

    store = env[0]
    state = _create(store)
    old = (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat()
    return run._save(state.model_copy(update={"stage": stage, "step_started_at": old}), store)


def test_refresh_interrupted_discovering(env, monkeypatch):
    monkeypatch.setattr(run.jobs, "run_alive", lambda *a: False)
    state = run.refresh(_aged(env, "discovering", 2), env[0])
    assert (state.stage, state.error) == ("failed", run.INTERRUPTED)


def test_refresh_interrupted_extracting(env, monkeypatch):
    monkeypatch.setattr(run.jobs, "run_alive", lambda *a: False)
    state = run.refresh(_aged(env, "extracting", 2), env[0])
    assert (state.stage, state.error) == ("awaiting_sources", run.INTERRUPTED)


def test_refresh_fresh_step_alive(env, monkeypatch):
    monkeypatch.setattr(run.jobs, "run_alive", lambda *a: False)
    state = _aged(env, "discovering", 0)
    assert run.refresh(state, env[0]) == state


def test_put_draft_empty_activities(env):
    store = env[0]
    state = _review(env)
    draft = state.draft.model_copy(deep=True)
    draft.activities = []
    assert run.put_draft(state.run_id, draft, store).draft.activities == []
