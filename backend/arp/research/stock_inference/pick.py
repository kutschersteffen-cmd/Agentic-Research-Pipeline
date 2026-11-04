"""Step 5 (`pick`): activities, keywords, mapping and tiers for one theme, saved as a draft taxonomy."""

from __future__ import annotations

import asyncio
from pathlib import Path

from arp.config import Settings
from arp.extraction.schema_builder import draft_schema
from arp.ingestion.registry import DocumentSourceRegistry
from arp.orchestration.job_manager import JobManager
from arp.research.authority_taxonomy.matching import match_activities
from arp.research.revenue_exposure.mapping import suggest_catalogue_mapping
from arp.research.stock_inference.profile import _ref, description_chunks
from arp.research.stock_inference.run import InferFailed, WrongStage, _save, load_run, read_methodology
from arp.research.stock_inference.schemas import InferRun, InferStock, Theme
from arp.research.stock_inference.stored import load_segments
from arp.schemas.common import DocumentChunk
from arp.schemas.taxonomy import DerivationMethod
from arp.schemas.thematic import ThemeDefinition


async def _not_yet(*_args, **_kwargs):  # the step defaults until Tasks 3-6 implement them
    raise NotImplementedError("This pick step is not implemented yet.")


async def supporting_chunks(run: InferRun, theme: Theme, registry: DocumentSourceRegistry) -> dict[str, list[DocumentChunk]]:
    """Description chunks of every described stock (supporting the theme or not), keyed by company_id."""
    described = [p for p in run.profiles if p.description]
    # shortcut: profiles keep no ticker/lei/cik, so sources keyed only by those miss; store them if that bites
    docs = await asyncio.gather(*(registry.fetch_all(_ref(InferStock(company_id=p.company_id, name=p.name,
                                                                     isin=p.isin, sedol=p.sedol)))
                                  for p in described))
    return {p.company_id: description_chunks(d) for p, d in zip(described, docs, strict=True)}


async def pick(
    run_id: str, rank: int, *, run_store, taxonomy_store, settings: Settings, llm, registry: DocumentSourceRegistry,
    matcher=match_activities, draft=draft_schema, mapper=suggest_catalogue_mapping, fetch=read_methodology,
    synthesize=_not_yet, top_down=_not_yet, merge=_not_yet, keywords=_not_yet, map_stocks=_not_yet, tiers=_not_yet,
    draft_kpis=_not_yet,
) -> InferRun:
    run = load_run(run_id, run_store)
    if run.stage != "themes_ready":
        raise WrongStage(run_id, run.stage, "pick", "themes_ready")
    theme = next((t for t in run.themes if t.rank == rank), None)
    if theme is None:
        raise ValueError(f"Run {run_id} has no theme {rank}.")
    jobs = JobManager(run_store)

    def fail(message: str) -> InferFailed:
        jobs.finish_run(run_id, error=message)
        return InferFailed(_save(run.model_copy(update={"stage": "failed"}), run_store), message)

    try:
        params = run_store.load_manifest(run_id).params
        sources, segments_path = params.get("methodology") or [], params.get("segments")
        segments = load_segments(Path(segments_path)) if segments_path else {}
        chunks = await supporting_chunks(run, theme, registry)
        supporting = {c: ch for c, ch in chunks.items() if c in theme.supporting}
        other = {c: ch for c, ch in chunks.items() if c not in theme.supporting}

        stock_acts = await synthesize(theme, run.profiles, supporting, llm,
                                      fuzzy_threshold=settings.grounding_fuzzy_threshold)
        method_acts = await top_down(sources, theme.name, llm, settings, fetch) if sources else []
        activities, origins = await merge(stock_acts, method_acts, theme.description, llm, matcher)
        boundary_quotes = [c.quote for a in method_acts for c in a.out_of_scope_citations]
        activities = await keywords(activities, supporting, other, boundary_quotes, llm)
        mapping, _unmapped = await map_stocks(run.profiles, activities, chunks, llm)
        definition = ThemeDefinition(name=theme.name, description=theme.description, activities=activities,
                                     scope=theme.description)
        mapping = await tiers(definition, mapping, segments, llm, mapper)
        methodology_text = "\n".join(c.quote for a in method_acts for c in a.citations)
        definition.kpis = await draft_kpis(theme, activities, methodology_text, llm, draft)

        notes = f"Inferred by 'arp taxonomy infer pick' from run {run_id}, theme {rank} ({theme.name})."
        taxonomy = taxonomy_store.create(run.name, definition, DerivationMethod.STOCK_INFERENCE, notes)
        return _save(run.model_copy(update={"stage": "drafted", "taxonomy_id": taxonomy.taxonomy_id,
                                            "activities": origins, "mapping": mapping}), run_store)
    except Exception as e:  # never leave a run half-picked
        raise fail(f"{type(e).__name__}: {e}") from e
