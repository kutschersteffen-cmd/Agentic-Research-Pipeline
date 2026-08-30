from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from arp.config import Settings
from arp.emerging_themes.clustering import cluster_tags
from arp.emerging_themes.entity_resolution import resolve_mention_companies
from arp.emerging_themes.extraction import tag_mention
from arp.emerging_themes.ingestion.base import MentionSource
from arp.emerging_themes.lineage import classify_lineage
from arp.emerging_themes.synthesis import build_candidate
from arp.llm.base import LLMClient, LLMUsage
from arp.orchestration.batch_runner import run_batch
from arp.orchestration.job_manager import JobManager
from arp.research.taxonomy_sources.corpus_synthesis import synthesize_activities_from_corpus
from arp.schemas.common import CompanyRef, now_iso
from arp.schemas.emerging_themes import (
    CandidateStatus,
    EmergingThemeCandidate,
    ExtractedTag,
    LineageTransition,
    RawMention,
)
from arp.schemas.taxonomy import DerivationMethod
from arp.schemas.taxonomy_sources import CorpusSnippet, CorpusSourceType
from arp.schemas.thematic import ThemeDefinition
from arp.storage.run_store import RunStore
from arp.storage.taxonomy_store import TaxonomyStore
from arp.storage.topic_store import TopicStateStore

logger = logging.getLogger(__name__)


def current_period() -> str:
    """ISO week key (e.g. '2026-W35') -- the cadence lineage tracking
    links periods across; matches the schedule's weekly default."""
    iso = datetime.now(timezone.utc).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def create_emerging_themes_run(run_store: RunStore, companies: list[CompanyRef], triggered_by: str) -> str:
    job_manager = JobManager(run_store)
    manifest = job_manager.create_run(
        "emerging_themes", {"triggered_by": triggered_by, "universe_size": len(companies)}, len(companies)
    )
    return manifest.run_id


async def execute_emerging_themes_run(
    run_id: str,
    companies: list[CompanyRef],
    *,
    llm: LLMClient,
    sources: list[MentionSource],
    settings: Settings,
    run_store: RunStore,
    topic_store: TopicStateStore,
) -> str:
    """Runs the full Ingest -> Extract -> Detect -> Synthesize -> Validate
    -> Output pipeline against an already-created run (see
    create_emerging_themes_run). Shared by the manual API/CLI trigger and
    the periodic scheduler, same split as discovery/pipeline.py.
    """
    job_manager = JobManager(run_store)
    period = current_period()
    since = datetime.now(timezone.utc) - timedelta(days=settings.emerging_themes_lookback_days)

    # --- Ingest ---
    mentions: list[RawMention] = []
    for source in sources:
        try:
            mentions.extend(await source.fetch(since))
        except Exception:  # noqa: BLE001 - one source failing must not abort the run
            logger.exception("Ingestion failed for source %s", source.name)
    mentions_by_id = {m.mention_id: m for m in mentions}
    for mention in mentions:
        run_store.append_jsonl(run_store.run_dir(run_id) / "mentions.jsonl", mention.model_dump(mode="json"))

    if not mentions:
        job_manager.finish_run(run_id)
        return run_id

    # --- Extract ---
    extracted_path = run_store.run_dir(run_id) / "extracted_tags.jsonl"

    async def _extract_one(mention: RawMention) -> tuple[list[ExtractedTag], LLMUsage]:
        return await tag_mention(mention, llm)

    def _on_extract_success(_mention: RawMention, result: tuple[list[ExtractedTag], LLMUsage]) -> None:
        _tags, usage = result
        job_manager.record_progress(
            run_id, completed_delta=1, input_tokens_delta=usage.input_tokens, output_tokens_delta=usage.output_tokens
        )

    def _on_extract_error(_mention: RawMention, _exc: Exception) -> None:
        job_manager.record_progress(run_id, failed_delta=1)

    await run_batch(
        mentions,
        item_key=lambda m: m.mention_id,
        worker=_extract_one,
        results_path=extracted_path,
        errors_path=run_store.errors_path(run_id),
        concurrency=settings.max_concurrent_llm_calls,
        result_to_json=lambda result: {"tags": [t.model_dump(mode="json") for t in result[0]]},
        on_success=_on_extract_success,
        on_error=_on_extract_error,
    )

    all_tags = [ExtractedTag.model_validate(t) for row in run_store.read_jsonl(extracted_path) for t in row.get("tags", [])]
    if len(all_tags) < settings.emerging_themes_min_cluster_size:
        job_manager.finish_run(run_id)
        return run_id

    # --- entity resolution (feeds Detect's company_ids and Synthesize's candidate_sectors_companies) ---
    company_ids_by_mention: dict[str, list[str]] = {}
    for tag in all_tags:
        mention = mentions_by_id.get(tag.mention_id)
        names = list(tag.entity_names) + (mention.raw_entity_names if mention else [])
        if not names:
            continue
        resolved = resolve_mention_companies(names, companies)
        if resolved:
            existing = set(company_ids_by_mention.get(tag.mention_id, []))
            company_ids_by_mention[tag.mention_id] = sorted(existing | set(resolved))

    # --- Detect: cluster + lineage ---
    try:
        clusters = cluster_tags(
            all_tags,
            mentions_by_id,
            company_ids_by_mention,
            period,
            min_cluster_size=settings.emerging_themes_min_cluster_size,
            stability_reruns=settings.emerging_themes_cluster_stability_reruns,
        )
    except ImportError as exc:
        job_manager.finish_run(run_id, error=f"Clustering dependencies missing ({exc}). Install the `emerging_themes` extra: pip install -e '.[emerging_themes]'.")
        return run_id

    topic_store.save_period(period, clusters)
    prior_period = topic_store.latest_period_before(period)
    prior_clusters = topic_store.load_period(prior_period) if prior_period else None
    lineage_events = classify_lineage(clusters, prior_clusters, period)
    topic_store.save_lineage_events(period, lineage_events)

    # Only a BIRTH -- no lineage edge back to the prior period -- is
    # eligible to become a candidate; see lineage.py's module docstring.
    birth_cluster_ids = {e.cluster_id for e in lineage_events if e.transition == LineageTransition.BIRTH}
    clusters_by_id = {c.cluster_id: c for c in clusters}
    tags_by_id = {t.tag_id: t for t in all_tags}

    # --- Synthesize + Validate + Output ---
    for cluster_id in birth_cluster_ids:
        cluster = clusters_by_id[cluster_id]
        member_tags = [tags_by_id[tid] for tid in cluster.member_tag_ids if tid in tags_by_id]
        try:
            candidate, usage = await build_candidate(
                cluster, member_tags, mentions_by_id, llm, run_id,
                min_independent_sources=settings.emerging_themes_min_independent_sources,
            )
        except Exception:  # noqa: BLE001 - one cluster's synthesis failing must not abort the run
            logger.exception("Synthesis failed for cluster %s", cluster_id)
            job_manager.record_progress(run_id, failed_delta=1)
            continue

        job_manager.record_progress(run_id, input_tokens_delta=usage.input_tokens, output_tokens_delta=usage.output_tokens)
        if candidate is None:
            continue  # failed the independent-source-minimum check
        run_store.append_jsonl(run_store.results_path(run_id), candidate.model_dump(mode="json"))
        topic_store.append_candidate(candidate)
        job_manager.record_progress(run_id, review_delta=1)

    job_manager.finish_run(run_id)
    return run_id


async def run_emerging_themes(
    companies: list[CompanyRef],
    *,
    llm: LLMClient,
    sources: list[MentionSource],
    settings: Settings,
    run_store: RunStore,
    topic_store: TopicStateStore,
    triggered_by: str = "manual",
) -> str:
    """Convenience wrapper (create + execute in one call) for the CLI and
    the scheduler, where blocking until completion is expected."""
    run_id = create_emerging_themes_run(run_store, companies, triggered_by)
    return await execute_emerging_themes_run(
        run_id, companies, llm=llm, sources=sources, settings=settings, run_store=run_store, topic_store=topic_store,
    )


def load_candidates_with_status(run_store: RunStore, run_id: str) -> list[EmergingThemeCandidate]:
    """Folds the run's append-only promote/reject decisions over its base
    candidate rows -- same "never mutate history in place" discipline as
    the extraction review-decision log, applied here instead of rewriting
    results.jsonl on every promotion."""
    candidates = [EmergingThemeCandidate.model_validate(r) for r in run_store.read_jsonl(run_store.results_path(run_id))]
    decisions = {d["theme_id"]: d for d in run_store.read_jsonl(run_store.review_decisions_path(run_id))}

    resolved: list[EmergingThemeCandidate] = []
    for candidate in candidates:
        decision = decisions.get(candidate.theme_id)
        if decision is None:
            resolved.append(candidate)
        elif decision["action"] == "promote":
            resolved.append(candidate.model_copy(update={
                "status": CandidateStatus.PROMOTED,
                "promoted_to_taxonomy_id": decision.get("promoted_to_taxonomy_id"),
                "promoted_to_taxonomy_version": decision.get("promoted_to_taxonomy_version"),
            }))
        elif decision["action"] == "reject":
            resolved.append(candidate.model_copy(update={"status": CandidateStatus.REJECTED}))
        else:
            resolved.append(candidate)
    return resolved


async def promote_candidate(
    run_store: RunStore,
    taxonomy_store: TaxonomyStore,
    llm: LLMClient,
    run_id: str,
    theme_id: str,
    *,
    taxonomy_id: str | None = None,
) -> EmergingThemeCandidate:
    """The human review gate's action: promotes one surviving candidate
    into the taxonomy DRAFT/ratify workflow. Never automatic -- no
    candidate reaches Tool 1 without this explicit call.

    Re-synthesizes the ActivityDefinition list from the candidate's own
    corroborating-source quotes via `synthesize_activities_from_corpus`
    (the same function `news_mining.py` uses) rather than persisting
    activities on `EmergingThemeCandidate` itself, so that schema stays
    exactly the source plan's fixed handoff contract.

    Pass `taxonomy_id` to extend an existing ratified taxonomy with this
    as a new activity (`TaxonomyStore.new_version`); omit it to create a
    brand-new taxonomy (`TaxonomyStore.create`). Always writes a DRAFT --
    never auto-ratified.
    """
    candidates = load_candidates_with_status(run_store, run_id)
    candidate = next((c for c in candidates if c.theme_id == theme_id), None)
    if candidate is None:
        raise ValueError(f"Unknown theme_id {theme_id} in run {run_id}")
    if candidate.status == CandidateStatus.PROMOTED:
        raise ValueError(f"{theme_id} is already promoted (taxonomy {candidate.promoted_to_taxonomy_id})")

    corpus = [
        CorpusSnippet(text=citation.quote, source_type=CorpusSourceType.NEWS, source_ref=citation.url)
        for citation in candidate.corroborating_sources
    ]
    activities, _assessment, _usage = await synthesize_activities_from_corpus(candidate.theme_name, candidate.description, corpus, llm)
    theme = ThemeDefinition(name=candidate.theme_name, description=candidate.description, activities=activities)
    notes = f"Promoted from Emerging Themes Scanner candidate {candidate.theme_id} (run {run_id}). {candidate.economic_rationale}"

    if taxonomy_id:
        taxonomy = taxonomy_store.new_version(taxonomy_id, theme, DerivationMethod.EMERGING_SIGNAL_DISCOVERY, notes)
    else:
        taxonomy = taxonomy_store.create(candidate.theme_name, theme, DerivationMethod.EMERGING_SIGNAL_DISCOVERY, notes)

    run_store.append_jsonl(
        run_store.review_decisions_path(run_id),
        {
            "theme_id": candidate.theme_id,
            "action": "promote",
            "promoted_to_taxonomy_id": taxonomy.taxonomy_id,
            "promoted_to_taxonomy_version": taxonomy.version,
            "decided_at": now_iso(),
        },
    )
    return candidate.model_copy(update={
        "status": CandidateStatus.PROMOTED,
        "promoted_to_taxonomy_id": taxonomy.taxonomy_id,
        "promoted_to_taxonomy_version": taxonomy.version,
    })


def reject_candidate(run_store: RunStore, run_id: str, theme_id: str) -> None:
    run_store.append_jsonl(
        run_store.review_decisions_path(run_id),
        {"theme_id": theme_id, "action": "reject", "decided_at": now_iso()},
    )
