from arp.config import Settings
from arp.discovery.identity_pipeline import (
    create_identity_run,
    enriched_universe,
    execute_identity_run,
    run_identity_resolution,
)
from arp.orchestration.review_queue import record_review_decision
from arp.schemas.common import CompanyRef
from arp.schemas.discovery import EdgarNameMatch, IdentityAdjudication, IdentityVerdict
from arp.storage.run_store import RunStore


def _settings(tmp_path) -> Settings:
    return Settings(
        anthropic_api_key="unused",
        runs_dir=tmp_path / "runs",
        documents_dir=tmp_path / "docs",
        cache_dir=tmp_path / "cache",
        discovery_state_dir=tmp_path / "disc",
    )


class _FakeEdgar:
    def __init__(self, matches_by_query: dict[str, list[EdgarNameMatch]] | None = None):
        self._matches = matches_by_query or {}

    async def search_by_name(self, name, limit=5):
        return self._matches.get(name, [])[:limit]


class _NullSearch:
    async def search(self, query, max_results=5):
        return []


def _uncertain_llm_script(fake_llm):
    return fake_llm(
        {
            IdentityAdjudication.__name__: [
                IdentityAdjudication(
                    verdict=IdentityVerdict.UNCERTAIN, confidence=0.3, resolved_website=None, resolved_cik=None,
                    rationale="Too ambiguous.",
                )
            ],
        }
    )


async def test_resolved_company_lands_in_results_but_not_review_queue(tmp_path, fake_llm):
    settings = _settings(tmp_path)
    run_store = RunStore(settings.runs_dir)
    llm = fake_llm({})  # no LLM calls expected -- website already known
    company = CompanyRef(company_id="acme", name="Acme", website="https://acme.example.com")

    run_id = await run_identity_resolution(
        [company], llm=llm, settings=settings, run_store=run_store, edgar=_FakeEdgar(), search_client=_NullSearch()
    )

    results = run_store.read_jsonl(run_store.results_path(run_id))
    review_queue = run_store.read_jsonl(run_store.review_queue_path(run_id))
    assert len(results) == 1
    assert results[0]["verdict"] == "resolved"
    assert review_queue == []

    manifest = run_store.load_manifest(run_id)
    assert manifest.completed_count == 1
    assert manifest.review_count == 0


async def test_uncertain_company_lands_in_both_results_and_review_queue(tmp_path, fake_llm):
    settings = _settings(tmp_path)
    run_store = RunStore(settings.runs_dir)
    llm = _uncertain_llm_script(fake_llm)
    company = CompanyRef(company_id="acme", name="Acme")

    run_id = await run_identity_resolution(
        [company], llm=llm, settings=settings, run_store=run_store, edgar=_FakeEdgar(), search_client=_NullSearch()
    )

    results = run_store.read_jsonl(run_store.results_path(run_id))
    review_queue = run_store.read_jsonl(run_store.review_queue_path(run_id))
    assert len(results) == 1
    assert results[0]["verdict"] == "uncertain"
    assert len(review_queue) == 1
    assert review_queue[0]["item_key"] == "acme"

    manifest = run_store.load_manifest(run_id)
    assert manifest.review_count == 1


async def test_create_then_execute_matches_the_convenience_wrapper(tmp_path, fake_llm):
    settings = _settings(tmp_path)
    run_store = RunStore(settings.runs_dir)
    llm = fake_llm({})
    company = CompanyRef(company_id="acme", name="Acme", cik="42")

    run_id = create_identity_run([company], run_store)
    await execute_identity_run(
        run_id, [company], llm=llm, settings=settings, run_store=run_store, edgar=_FakeEdgar(), search_client=_NullSearch()
    )

    manifest = run_store.load_manifest(run_id)
    assert manifest.run_type == "identity"
    assert manifest.status.value in ("completed", "partially_completed")


async def test_enriched_universe_includes_clean_resolved_companies(tmp_path, fake_llm):
    settings = _settings(tmp_path)
    run_store = RunStore(settings.runs_dir)
    llm = fake_llm({})
    company = CompanyRef(company_id="acme", name="Acme", website="https://acme.example.com", cik="42")

    run_id = await run_identity_resolution(
        [company], llm=llm, settings=settings, run_store=run_store, edgar=_FakeEdgar(), search_client=_NullSearch()
    )

    universe = enriched_universe(run_store, run_id)
    assert len(universe) == 1
    assert universe[0].company_id == "acme"
    assert universe[0].website == "https://acme.example.com"
    assert universe[0].cik == "42"


async def test_enriched_universe_excludes_flagged_company_with_no_decision(tmp_path, fake_llm):
    settings = _settings(tmp_path)
    run_store = RunStore(settings.runs_dir)
    llm = _uncertain_llm_script(fake_llm)
    company = CompanyRef(company_id="acme", name="Acme")

    run_id = await run_identity_resolution(
        [company], llm=llm, settings=settings, run_store=run_store, edgar=_FakeEdgar(), search_client=_NullSearch()
    )

    assert enriched_universe(run_store, run_id) == []


async def test_enriched_universe_includes_edited_flagged_company(tmp_path, fake_llm):
    settings = _settings(tmp_path)
    run_store = RunStore(settings.runs_dir)
    llm = _uncertain_llm_script(fake_llm)
    company = CompanyRef(company_id="acme", name="Acme")

    run_id = await run_identity_resolution(
        [company], llm=llm, settings=settings, run_store=run_store, edgar=_FakeEdgar(), search_client=_NullSearch()
    )
    record_review_decision(
        run_store, run_id, "acme", "edit", "reviewer1",
        {"resolved_website": "https://real-acme.example.com", "resolved_cik": "999"},
    )

    universe = enriched_universe(run_store, run_id)
    assert len(universe) == 1
    assert universe[0].website == "https://real-acme.example.com"
    assert universe[0].cik == "999"


async def test_enriched_universe_excludes_rejected_company(tmp_path, fake_llm):
    settings = _settings(tmp_path)
    run_store = RunStore(settings.runs_dir)
    llm = _uncertain_llm_script(fake_llm)
    company = CompanyRef(company_id="acme", name="Acme")

    run_id = await run_identity_resolution(
        [company], llm=llm, settings=settings, run_store=run_store, edgar=_FakeEdgar(), search_client=_NullSearch()
    )
    record_review_decision(run_store, run_id, "acme", "reject", "reviewer1", None)

    assert enriched_universe(run_store, run_id) == []


async def test_enriched_universe_approve_without_edit_uses_agents_own_resolved_fields(tmp_path, fake_llm):
    settings = _settings(tmp_path)
    run_store = RunStore(settings.runs_dir)
    llm = fake_llm(
        {
            IdentityAdjudication.__name__: [
                IdentityAdjudication(
                    verdict=IdentityVerdict.RESOLVED, confidence=0.5, resolved_website=None, resolved_cik=None,
                    rationale="Weak but resolved.",
                )
            ],
        }
    )
    company = CompanyRef(company_id="acme", name="Acme")

    run_id = await run_identity_resolution(
        [company], llm=llm, settings=settings, run_store=run_store, edgar=_FakeEdgar(), search_client=_NullSearch()
    )
    # low-confidence RESOLVED is still flagged_for_review (see identity_graph.py)
    review_queue = run_store.read_jsonl(run_store.review_queue_path(run_id))
    assert len(review_queue) == 1

    record_review_decision(run_store, run_id, "acme", "approve", "reviewer1", None)
    universe = enriched_universe(run_store, run_id)
    assert len(universe) == 0  # no website/cik was ever resolved -- approving doesn't invent one
