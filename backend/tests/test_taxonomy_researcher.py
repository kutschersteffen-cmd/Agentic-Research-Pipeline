from arp.agents import taxonomy_researcher as taxonomy_researcher_module
from arp.agents.taxonomy_researcher import (
    create_taxonomy_research_run,
    execute_taxonomy_research_run,
    research_taxonomy,
)
from arp.config import Settings
from arp.discovery.site_finder import SearchResult
from arp.research.taxonomy_sources import authority as authority_module
from arp.research.taxonomy_sources.activity_merge import _MergedActivityDraft, _MergedActivityDraftList
from arp.research.taxonomy_sources.authority_extraction import _AuthorityActivityDraft, _AuthorityActivityDraftList
from arp.research.taxonomy_sources.discovery import _AssessmentList, _CandidateAssessment
from arp.schemas.taxonomy import DerivationMethod, Taxonomy, TaxonomyStatus
from arp.schemas.taxonomy_sources import SourceCandidate, SourceCandidateType
from arp.schemas.thematic import ActivityDefinition, ThemeDefinition
from arp.storage.run_store import RunStore
from arp.storage.taxonomy_store import TaxonomyStore


def _settings(tmp_path, **overrides) -> Settings:
    return Settings(anthropic_api_key="unused", cache_dir=tmp_path / "cache", **overrides)


def _ratified_taxonomy(name="Electrification", activity_names=("EV manufacturing",)) -> Taxonomy:
    theme = ThemeDefinition(
        name=name, description="Electrification of transport and industry.",
        activities=[ActivityDefinition(name=n, in_scope_description="x", out_of_scope_description="y") for n in activity_names],
    )
    return Taxonomy(
        name=name, theme=theme, derivation_method=DerivationMethod.LLM_DRAFT,
        status=TaxonomyStatus.RATIFIED, ratified_by="jane.analyst",
    )


async def test_research_taxonomy_no_candidates_found(fake_llm, fake_search, tmp_path):
    taxonomy = _ratified_taxonomy()
    llm = fake_llm({})
    search = fake_search({})  # no query substring matches -> zero candidates

    finding, merged_theme = await research_taxonomy(taxonomy, llm, search, _settings(tmp_path))
    assert finding.proposed is False
    assert "No candidate authority sources found" in finding.reason
    assert merged_theme is None
    assert llm.calls == []


async def test_research_taxonomy_no_authoritative_sources(fake_llm, fake_search, tmp_path):
    taxonomy = _ratified_taxonomy()
    search = fake_search({"official taxonomy classification": [SearchResult(title="Some blog", url="https://blog.example.com/x")]})
    # empty assessments -> the candidate comes back unranked (authority_score=None), failing the threshold
    llm = fake_llm({_AssessmentList.__name__: [_AssessmentList(assessments=[])]})

    finding, merged_theme = await research_taxonomy(taxonomy, llm, search, _settings(tmp_path))
    assert finding.proposed is False
    assert "No sufficiently authoritative sources found" in finding.reason
    assert merged_theme is None


async def test_research_taxonomy_proposes_new_version_when_activity_added(fake_llm, fake_search, tmp_path, monkeypatch):
    taxonomy = _ratified_taxonomy(activity_names=["EV manufacturing"])

    candidate = SourceCandidate(source_type=SourceCandidateType.AUTHORITY, name="IEA report", url="https://iea.org/x", snippet="")

    async def fake_discover(theme_name, search_client, max_candidates=10):
        return [candidate]

    monkeypatch.setattr(taxonomy_researcher_module, "discover_authority_sources", fake_discover)

    async def fake_fetch(url, user_agent, timeout=20.0):
        return "The IEA defines grid modernization as upgrading electricity transmission infrastructure."

    monkeypatch.setattr(authority_module, "fetch_source_text", fake_fetch)

    assessment = _AssessmentList(
        assessments=[_CandidateAssessment(candidate_id=candidate.candidate_id, authority_score=0.9, authority_reasoning="IEA is authoritative.")]
    )
    extracted = _AuthorityActivityDraftList(
        activities=[
            _AuthorityActivityDraft(
                name="Grid modernization", in_scope_description="x", out_of_scope_description="y",
                seed_keywords=["grid"], source_quote="upgrading electricity transmission infrastructure",
            )
        ]
    )
    merged = _MergedActivityDraftList(
        activities=[
            _MergedActivityDraft(name="EV manufacturing", in_scope_description="x", out_of_scope_description="y"),
            _MergedActivityDraft(name="Grid modernization", in_scope_description="x", out_of_scope_description="y"),
        ],
        merge_notes="Kept both as distinct activities.",
    )
    llm = fake_llm({
        _AssessmentList.__name__: [assessment],
        _AuthorityActivityDraftList.__name__: [extracted],
        _MergedActivityDraftList.__name__: [merged],
    })

    finding, merged_theme = await research_taxonomy(taxonomy, llm, fake_search({}), _settings(tmp_path))
    assert finding.proposed is True
    assert finding.added_activity_names == ["Grid modernization"]
    assert merged_theme is not None
    assert {a.name for a in merged_theme.activities} == {"EV manufacturing", "Grid modernization"}


async def test_execute_taxonomy_research_run_writes_draft_version_never_ratifies(fake_llm, fake_search, tmp_path, monkeypatch):
    store = TaxonomyStore(tmp_path / "taxonomies")
    theme = ThemeDefinition(
        name="Electrification", description="", activities=[ActivityDefinition(name="EV manufacturing", in_scope_description="x", out_of_scope_description="y")]
    )
    created = store.create("Electrification", theme, DerivationMethod.LLM_DRAFT)
    ratified = store.ratify(created.taxonomy_id, created.version, "jane.analyst")

    candidate = SourceCandidate(source_type=SourceCandidateType.AUTHORITY, name="IEA report", url="https://iea.org/x", snippet="")

    async def fake_discover(theme_name, search_client, max_candidates=10):
        return [candidate]

    monkeypatch.setattr(taxonomy_researcher_module, "discover_authority_sources", fake_discover)

    async def fake_fetch(url, user_agent, timeout=20.0):
        return "The IEA defines grid modernization as upgrading electricity transmission infrastructure."

    monkeypatch.setattr(authority_module, "fetch_source_text", fake_fetch)

    assessment = _AssessmentList(assessments=[_CandidateAssessment(candidate_id=candidate.candidate_id, authority_score=0.9, authority_reasoning="x")])
    extracted = _AuthorityActivityDraftList(
        activities=[_AuthorityActivityDraft(name="Grid modernization", in_scope_description="x", out_of_scope_description="y", seed_keywords=[], source_quote="upgrading electricity transmission infrastructure")]
    )
    merged = _MergedActivityDraftList(
        activities=[
            _MergedActivityDraft(name="EV manufacturing", in_scope_description="x", out_of_scope_description="y"),
            _MergedActivityDraft(name="Grid modernization", in_scope_description="x", out_of_scope_description="y"),
        ],
        merge_notes="x",
    )
    llm = fake_llm({
        _AssessmentList.__name__: [assessment],
        _AuthorityActivityDraftList.__name__: [extracted],
        _MergedActivityDraftList.__name__: [merged],
    })

    run_store = RunStore(tmp_path / "runs")
    run_id = create_taxonomy_research_run(store, run_store, None, "manual")
    await execute_taxonomy_research_run(
        run_id, llm=llm, search_client=fake_search({}), settings=_settings(tmp_path),
        taxonomy_store=store, run_store=run_store, taxonomy_ids=None,
    )

    rows = run_store.read_jsonl(run_store.results_path(run_id))
    assert len(rows) == 1
    assert rows[0]["proposed"] is True
    assert rows[0]["new_version"] == 2

    new_version = store.get(ratified.taxonomy_id, 2)
    assert new_version is not None
    assert new_version.status == TaxonomyStatus.DRAFT  # never auto-ratified
    assert {a.name for a in new_version.theme.activities} == {"EV manufacturing", "Grid modernization"}
    # the original ratified version is untouched
    assert store.get(ratified.taxonomy_id, 1).status == TaxonomyStatus.RATIFIED


async def test_execute_taxonomy_research_run_skips_unratified_taxonomies(fake_llm, fake_search, tmp_path):
    store = TaxonomyStore(tmp_path / "taxonomies")
    theme = ThemeDefinition(name="Draft Theme", description="", activities=[ActivityDefinition(name="x", in_scope_description="x", out_of_scope_description="y")])
    store.create("Draft Theme", theme, DerivationMethod.LLM_DRAFT)  # never ratified

    run_store = RunStore(tmp_path / "runs")
    llm = fake_llm({})
    run_id = create_taxonomy_research_run(store, run_store, None, "manual")
    await execute_taxonomy_research_run(
        run_id, llm=llm, search_client=fake_search({}), settings=_settings(tmp_path),
        taxonomy_store=store, run_store=run_store, taxonomy_ids=None,
    )
    rows = run_store.read_jsonl(run_store.results_path(run_id))
    assert rows == []
    assert llm.calls == []
    manifest = run_store.load_manifest(run_id)
    assert manifest.company_count == 0
