from datetime import datetime, timezone

from arp.config import Settings
from arp.emerging_themes import pipeline as pipeline_module
from arp.emerging_themes.ingestion.base import MentionSource
from arp.emerging_themes.pipeline import (
    create_emerging_themes_run,
    execute_emerging_themes_run,
    load_candidates_with_status,
    promote_candidate,
    reject_candidate,
)
from arp.emerging_themes.synthesis import _CandidateDraft
from arp.research.taxonomy_sources.corpus_synthesis import _SynthesizedActivityDraft, _SynthesizedActivityDraftList
from arp.schemas.common import CompanyRef
from arp.schemas.emerging_themes import CandidateStatus, MentionSourceType, RawMention, TopicCluster
from arp.schemas.taxonomy import TaxonomyStatus
from arp.storage.run_store import RunStore
from arp.storage.taxonomy_store import TaxonomyStore
from arp.storage.topic_store import TopicStateStore


class _FixedMentionSource(MentionSource):
    name = "fixed"

    def __init__(self, mentions: list[RawMention]) -> None:
        self._mentions = mentions

    async def fetch(self, since: datetime) -> list[RawMention]:
        return self._mentions


def _mentions() -> list[RawMention]:
    title = "Acme Battery Co unveils solid-state battery breakthrough"
    text = "The company says the new cell chemistry could cut charging times in half."
    return [
        RawMention(source_type=MentionSourceType.GDELT, title=title, text=text, url=f"https://news.example.com/{i}")
        for i in range(5)
    ]


def _settings(tmp_path) -> Settings:
    return Settings(
        runs_dir=tmp_path / "runs",
        taxonomies_dir=tmp_path / "taxonomies",
        emerging_themes_state_dir=tmp_path / "emerging_themes_state",
        emerging_themes_min_cluster_size=3,
        emerging_themes_min_independent_sources=2,
    )


def _fake_cluster_tags(tags, mentions_by_id, company_ids_by_mention, period, *, min_cluster_size, stability_reruns):
    """Stands in for the real UMAP+HDBSCAN clustering step -- this test is
    about the pipeline's orchestration (ingest bookkeeping, extraction
    checkpointing, entity resolution wiring, the independent-source
    filter, output writing, promote/reject decision folding), not about
    clustering internals, which have their own dedicated tests."""
    company_ids = sorted({cid for ids in company_ids_by_mention.values() for cid in ids})
    return [
        TopicCluster(
            cluster_id="cl_fixed", period=period, representative_label="solid-state battery",
            member_tag_ids=[t.tag_id for t in tags], member_labels=[t.label for t in tags],
            company_ids=company_ids, mention_count=len({t.mention_id for t in tags}),
            source_types=[MentionSourceType.GDELT], centroid=[], stability_score=0.9,
        )
    ]


async def test_execute_run_produces_one_candidate_from_five_corroborating_mentions(tmp_path, monkeypatch, fake_llm):
    from arp.emerging_themes.extraction import _TagDraft, _TagDraftList

    monkeypatch.setattr(pipeline_module, "cluster_tags", _fake_cluster_tags)

    settings = _settings(tmp_path)
    run_store = RunStore(settings.runs_dir)
    topic_store = TopicStateStore(settings.emerging_themes_state_dir / "topics")
    companies = [CompanyRef(company_id="acme", name="Acme Battery Co")]

    tag_draft = _TagDraftList(
        tags=[
            _TagDraft(
                label="solid-state battery breakthrough",
                claim="Acme Battery Co unveiled a new solid-state cell chemistry.",
                entity_names=["Acme Battery Co"],
                quote="Acme Battery Co unveils solid-state battery breakthrough",
            )
        ]
    )
    candidate_draft = _CandidateDraft(
        theme_name="Solid-state EV battery commercialization",
        description="Companies are commercializing solid-state battery cells for EVs.",
        economic_rationale="A step-change in energy density would reshape EV cost structures and charging infrastructure demand.",
        rationale="Five independent reports of Acme Battery Co's solid-state breakthrough.",
    )
    llm = fake_llm({
        "_TagDraftList": [tag_draft] * 5,  # one per mention
        "_CandidateDraft": [candidate_draft],
    })

    run_id = create_emerging_themes_run(run_store, companies, "manual")
    await execute_emerging_themes_run(
        run_id, companies, llm=llm, sources=[_FixedMentionSource(_mentions())], settings=settings,
        run_store=run_store, topic_store=topic_store,
    )

    manifest = run_store.load_manifest(run_id)
    assert manifest.status.value in ("completed", "partially_completed")

    candidates = load_candidates_with_status(run_store, run_id)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.theme_name == "Solid-state EV battery commercialization"
    assert candidate.status == CandidateStatus.CANDIDATE
    assert candidate.candidate_sectors_companies == ["acme"]
    assert len(candidate.corroborating_sources) == 5


async def test_promote_candidate_creates_draft_taxonomy_and_folds_status(tmp_path, fake_llm):
    settings = _settings(tmp_path)
    run_store = RunStore(settings.runs_dir)
    taxonomy_store = TaxonomyStore(settings.taxonomies_dir)
    run_id = create_emerging_themes_run(run_store, [CompanyRef(company_id="acme", name="Acme Battery Co")], "manual")

    from arp.schemas.emerging_themes import EmergingThemeCandidate, MentionCitation

    candidate = EmergingThemeCandidate(
        theme_name="Solid-state EV battery commercialization",
        description="desc",
        first_detected_date=datetime.now(timezone.utc).date().isoformat(),
        signal_velocity=5.0,
        corroborating_sources=[MentionCitation(mention_id="m0", source_type=MentionSourceType.GDELT, url="https://news.example.com/0", quote="q", grounded=True)],
        candidate_sectors_companies=["acme"],
        economic_rationale="x",
        cluster_id="cl_fixed",
        run_id=run_id,
    )
    run_store.append_jsonl(run_store.results_path(run_id), candidate.model_dump(mode="json"))

    activity_draft = _SynthesizedActivityDraftList(
        activities=[_SynthesizedActivityDraft(name="Solid-state cell manufacturing", in_scope_description="x", out_of_scope_description="y")],
        corpus_assessment="ok",
    )
    llm = fake_llm({"_SynthesizedActivityDraftList": [activity_draft]})

    promoted = await promote_candidate(run_store, taxonomy_store, llm, run_id, candidate.theme_id)

    assert promoted.status == CandidateStatus.PROMOTED
    assert promoted.promoted_to_taxonomy_id is not None
    taxonomy = taxonomy_store.get(promoted.promoted_to_taxonomy_id)
    assert taxonomy is not None
    assert taxonomy.status == TaxonomyStatus.DRAFT  # never auto-ratified
    assert taxonomy.theme.activities[0].name == "Solid-state cell manufacturing"

    # status folding: a fresh read of the run's candidates reflects the promotion
    reloaded = load_candidates_with_status(run_store, run_id)
    assert reloaded[0].status == CandidateStatus.PROMOTED
    assert reloaded[0].promoted_to_taxonomy_id == taxonomy.taxonomy_id


async def test_reject_candidate_folds_into_rejected_status(tmp_path):
    settings = _settings(tmp_path)
    run_store = RunStore(settings.runs_dir)
    run_id = create_emerging_themes_run(run_store, [], "manual")

    from arp.schemas.emerging_themes import EmergingThemeCandidate

    candidate = EmergingThemeCandidate(
        theme_name="Weak signal", description="", first_detected_date="2026-01-01", signal_velocity=1.0,
        economic_rationale="", cluster_id="cl1", run_id=run_id,
    )
    run_store.append_jsonl(run_store.results_path(run_id), candidate.model_dump(mode="json"))

    reject_candidate(run_store, run_id, candidate.theme_id)

    reloaded = load_candidates_with_status(run_store, run_id)
    assert reloaded[0].status == CandidateStatus.REJECTED
