from arp.config import Settings
from arp.discovery.identity_pipeline import (
    create_identity_run,
    enriched_universe,
    execute_identity_run,
    run_identity_resolution,
)
from arp.discovery.match_rules import needs_recheck
from arp.orchestration.review_queue import append_decision, record_review_decision
from arp.schemas.common import CompanyRef
from arp.schemas.discovery import EdgarNameMatch, IdentityAdjudication, IdentityResolutionResult, IdentityVerdict
from arp.schemas.issuer import IdentifierMap
from arp.schemas.review import ReviewDecision
from arp.storage.identifier_map import IdentifierMapStore
from arp.storage.run_store import RunStore


def _settings(tmp_path) -> Settings:
    return Settings(
        anthropic_api_key="unused",
        runs_dir=tmp_path / "runs",
        identifier_map_path=tmp_path / "idmap.jsonl",
        documents_dir=tmp_path / "docs",
        cache_dir=tmp_path / "cache",
        discovery_state_dir=tmp_path / "disc",
    )


class _FakeEdgar:
    def __init__(self, matches_by_query: dict[str, list[EdgarNameMatch]] | None = None):
        self._matches = matches_by_query or {}
        self.calls = 0

    async def search_by_name(self, name, limit=5):
        self.calls += 1
        return self._matches.get(name, [])[:limit]


class _NullSearch:
    def __init__(self):
        self.calls = 0

    async def search(self, query, max_results=5):
        self.calls += 1
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
    edgar = _FakeEdgar({"Acme": [EdgarNameMatch(ticker="ACME", cik="42", title="Acme")]})
    company = CompanyRef(company_id="acme", name="Acme")

    run_id = await run_identity_resolution(
        [company], llm=llm, settings=settings, run_store=run_store, edgar=edgar, search_client=_NullSearch()
    )

    assert enriched_universe(run_store, run_id) == []  # name-only: excluded until a reviewer approves
    record_review_decision(run_store, run_id, "acme", "approve", "reviewer1", None)
    universe = enriched_universe(run_store, run_id)
    assert len(universe) == 1
    assert universe[0].company_id == "acme"
    assert universe[0].cik == "42"


async def test_supplied_website_and_cik_still_resolve_unflagged(tmp_path, fake_llm):
    settings = _settings(tmp_path)
    run_store = RunStore(settings.runs_dir)
    company = CompanyRef(company_id="acme", name="Acme", website="https://acme.example.com", cik="42")

    run_id = await run_identity_resolution(
        [company], llm=fake_llm({}), settings=settings, run_store=run_store, edgar=_FakeEdgar(), search_client=_NullSearch()
    )

    universe = enriched_universe(run_store, run_id)
    assert [(c.website, c.cik) for c in universe] == [("https://acme.example.com", "42")]


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


async def test_enriched_universe_reads_generic_override_value(tmp_path, fake_llm):
    """The review controls send one free-text override as {"value": ...}: digits are a CIK, anything else a website."""
    settings = _settings(tmp_path)
    run_store = RunStore(settings.runs_dir)

    async def edited(value: str) -> CompanyRef:
        run_id = await run_identity_resolution(
            [CompanyRef(company_id="acme", name="Acme")], llm=_uncertain_llm_script(fake_llm), settings=settings,
            run_store=run_store, edgar=_FakeEdgar(), search_client=_NullSearch(),
        )
        record_review_decision(run_store, run_id, "acme", "edit", "reviewer1", {"value": value})
        [company] = enriched_universe(run_store, run_id)
        return company

    assert (await edited(" https://real-acme.example.com ")).website == "https://real-acme.example.com"
    assert (await edited("0000320193")).cik == "0000320193"


LEI_X = "5493001KJTIIGC8Y1R12"
LEI_Y = "529900T8BM49AURSDO55"


async def _run(tmp_path, fake_llm, company, *, edgar=None, search=None, previous=None, rows=()):
    settings = _settings(tmp_path)
    store = IdentifierMapStore(settings.identifier_map_path)
    for r in rows:
        store.add(r)
    run_store = RunStore(settings.runs_dir)
    llm = fake_llm({})
    run_id = create_identity_run([company], run_store)
    await execute_identity_run(
        run_id, [company], llm=llm, settings=settings, run_store=run_store,
        edgar=edgar or _FakeEdgar(), search_client=search or _NullSearch(), previous_run_id=previous,
    )
    result = IdentityResolutionResult.model_validate(run_store.read_jsonl(run_store.results_path(run_id))[0])
    return run_store, run_id, result, llm


async def test_name_only_match_always_creates_review_item(tmp_path, fake_llm):
    edgar = _FakeEdgar({"Acme": [EdgarNameMatch(ticker="ACME", cik="42", title="Acme")]})
    run_store, run_id, result, llm = await _run(tmp_path, fake_llm, CompanyRef(company_id="acme", name="Acme"), edgar=edgar)

    assert result.flagged_for_review is True
    assert result.match_rule == "name_only"
    assert result.reason_codes == ["match_ambiguous"]
    assert len(run_store.read_jsonl(run_store.review_queue_path(run_id))) == 1
    assert llm.calls == []


async def test_exact_lei_resolves_without_lookup(tmp_path, fake_llm):
    edgar, search = _FakeEdgar(), _NullSearch()
    _, _, result, _ = await _run(
        tmp_path, fake_llm, CompanyRef(company_id="acme", name="Acme", lei=LEI_X, cik="42"), edgar=edgar, search=search
    )

    assert result.match_rule == "exact_lei"
    assert result.resolved_issuer_key == LEI_X
    assert result.flagged_for_review is False
    assert edgar.calls == 0 and search.calls == 0


async def test_cik_resolves_through_identifier_map(tmp_path, fake_llm):
    rows = [IdentifierMap(issuer_key=LEI_X, scheme="CIK", value="0000320193")]
    _, _, result, _ = await _run(tmp_path, fake_llm, CompanyRef(company_id="a", name="A", cik="320193"), rows=rows)

    assert result.match_rule == "identifier_map"
    assert result.resolved_issuer_key == LEI_X
    assert result.flagged_for_review is False


async def test_cik_mapping_to_two_issuers_is_ambiguous(tmp_path, fake_llm):
    rows = [IdentifierMap(issuer_key=k, scheme="CIK", value="320193") for k in (LEI_X, LEI_Y)]
    _, _, result, _ = await _run(tmp_path, fake_llm, CompanyRef(company_id="a", name="A", cik="320193"), rows=rows)

    assert result.match_rule == "ambiguous"
    assert result.flagged_for_review is True


async def test_changed_identifier_triggers_recheck(tmp_path, fake_llm):
    company = CompanyRef(company_id="a", name="A", cik="320193")
    rows = [IdentifierMap(issuer_key=LEI_X, scheme="CIK", value="320193")]
    run_store, run_id, result, _ = await _run(tmp_path, fake_llm, company, rows=rows)
    idmap = IdentifierMapStore(_settings(tmp_path).identifier_map_path)

    assert needs_recheck(result, company, idmap) is False
    assert needs_recheck(result, company.model_copy(update={"cik": "999"}), idmap) is True
    idmap.add(IdentifierMap(issuer_key=LEI_Y, scheme="CIK", value="320193", valid_from="2000-01-01"))
    idmap.add(IdentifierMap(issuer_key=LEI_X, scheme="CIK", value="320193", valid_to="2001-01-01"))
    assert needs_recheck(result, company, idmap) is True


async def test_unchanged_company_reused_from_previous_run(tmp_path, fake_llm):
    settings = _settings(tmp_path)
    run_store = RunStore(settings.runs_dir)
    edgar = _FakeEdgar({"Acme": [EdgarNameMatch(ticker="ACME", cik="42", title="Acme")]})
    company = CompanyRef(company_id="acme", name="Acme")
    first = await run_identity_resolution(
        [company], llm=fake_llm({}), settings=settings, run_store=run_store, edgar=edgar, search_client=_NullSearch()
    )
    assert edgar.calls == 1

    second = create_identity_run([company], run_store)
    llm = fake_llm({})
    await execute_identity_run(
        second, [company], llm=llm, settings=settings, run_store=run_store, edgar=edgar,
        search_client=_NullSearch(), previous_run_id=first,
    )

    assert edgar.calls == 1  # reused, no lookup
    assert llm.calls == []
    assert len(run_store.read_jsonl(run_store.review_queue_path(second))) == 1


async def test_exact_lei_without_cik_or_website_looks_up_and_flags(tmp_path, fake_llm):
    edgar = _FakeEdgar({"Acme": [EdgarNameMatch(ticker="ACME", cik="42", title="Acme")]})
    run_store, run_id, result, llm = await _run(
        tmp_path, fake_llm, CompanyRef(company_id="acme", name="Acme", lei=LEI_X), edgar=edgar
    )

    assert llm.calls == [] and edgar.calls == 1
    assert result.match_rule == "exact_lei" and result.resolved_issuer_key == LEI_X
    assert result.flagged_for_review is True
    assert result.reason_codes == ["match_ambiguous"]
    assert result.resolved_cik == "42"
    record_review_decision(run_store, run_id, "acme", "approve", "reviewer1", None)
    universe = enriched_universe(run_store, run_id)
    assert [(c.cik, c.lei) for c in universe] == [("42", LEI_X)]


async def test_exact_lei_without_any_lookup_hit_is_flagged_not_dropped(tmp_path, fake_llm):
    _, _, result, llm = await _run(tmp_path, fake_llm, CompanyRef(company_id="acme", name="Acme", lei=LEI_X))

    assert llm.calls == []
    assert result.flagged_for_review is True and result.resolved_cik is None
    assert result.match_rule == "exact_lei"


async def test_ambiguous_map_outcome_keeps_supplied_cik_for_approval(tmp_path, fake_llm):
    rows = [IdentifierMap(issuer_key=k, scheme="CIK", value="320193") for k in (LEI_X, LEI_Y)]
    run_store, run_id, result, _ = await _run(
        tmp_path, fake_llm, CompanyRef(company_id="a", name="A", cik="320193"), rows=rows
    )

    assert result.resolved_cik == "320193"
    record_review_decision(run_store, run_id, "a", "approve", "reviewer1", None)
    assert [c.cik for c in enriched_universe(run_store, run_id)] == ["320193"]


def _correct(run_store, run_id, step, cik):
    append_decision(run_store, run_id, ReviewDecision(
        item_key="acme", decision="correct", reason_code="wrong_entity", reviewer="R", user_id=f"u_{step}", role="approver",
        corrected_value={"resolved_cik": cik}, snapshot_id="s", step=step, second_required=step == "first"))


async def test_identity_correct_needs_second_review_before_enriched(tmp_path, fake_llm):
    settings = _settings(tmp_path)
    run_store = RunStore(settings.runs_dir)
    run_id = await run_identity_resolution(
        [CompanyRef(company_id="acme", name="Acme")], llm=_uncertain_llm_script(fake_llm), settings=settings,
        run_store=run_store, edgar=_FakeEdgar(), search_client=_NullSearch(),
    )
    _correct(run_store, run_id, "first", "999")
    assert enriched_universe(run_store, run_id) == []
    _correct(run_store, run_id, "second", "999")
    assert [c.cik for c in enriched_universe(run_store, run_id)] == ["999"]


async def test_legacy_identity_edit_still_included(tmp_path, fake_llm):
    settings = _settings(tmp_path)
    run_store = RunStore(settings.runs_dir)
    run_id = await run_identity_resolution(
        [CompanyRef(company_id="acme", name="Acme")], llm=_uncertain_llm_script(fake_llm), settings=settings,
        run_store=run_store, edgar=_FakeEdgar(), search_client=_NullSearch(),
    )
    record_review_decision(run_store, run_id, "acme", "edit", "r", {"resolved_cik": "7"})
    assert [c.cik for c in enriched_universe(run_store, run_id)] == ["7"]
