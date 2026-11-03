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
        return "text"

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
    assert (t.theme.activities[0].name, t.version, t.derivation_method) == ("N", 1, "authority_source")


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
