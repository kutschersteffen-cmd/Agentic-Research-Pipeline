"""Step 5 (`pick`): activities, keywords, mapping and tiers for one theme, saved as a draft taxonomy."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from arp.config import Settings
from arp.extraction.schema_builder import draft_schema
from arp.grounding import ground_citations
from arp.ingestion.registry import DocumentSourceRegistry
from arp.orchestration.job_manager import JobManager
from arp.research.authority_taxonomy.consolidate import consolidate
from arp.research.authority_taxonomy.extract import extract_source
from arp.research.authority_taxonomy.matching import match_activities
from arp.research.indirect_exposure.factory import resolve_indirect_exposure_model
from arp.research.revenue_exposure.mapping import suggest_catalogue_mapping
from arp.research.stock_inference.profile import _ref, description_chunks
from arp.research.stock_inference.run import InferFailed, WrongStage, _save, load_run, read_methodology
from arp.research.stock_inference.schemas import ActivityOrigin, InferRun, InferStock, StockProfile, Theme
from arp.research.stock_inference.selection import load_stocks
from arp.research.stock_inference.stored import load_segments
from arp.schemas.authority_taxonomy import SourceCitation
from arp.schemas.common import Citation, DocumentChunk, SourceDocument
from arp.schemas.taxonomy import DerivationMethod
from arp.schemas.thematic import ActivityDefinition, ActivityTier, ThemeDefinition

NO_ACTIVITY = "No activity could be grounded in the supporting stocks."


async def _not_yet(*_args, **_kwargs):  # the step defaults until Tasks 3-6 implement them
    raise NotImplementedError("This pick step is not implemented yet.")


async def supporting_chunks(
    run: InferRun, theme: Theme, registry: DocumentSourceRegistry, *, stocks: dict[str, InferStock] | None = None,
    limit: int = 4,
) -> dict[str, list[DocumentChunk]]:
    """Description chunks of every described stock (supporting the theme or not), keyed by company_id.

    `stocks` (the run's stocks file) supplies ticker/lei/cik, which profiles do not keep and EDGAR needs."""
    described = [p for p in run.profiles if p.description]
    gate = asyncio.Semaphore(limit)

    async def fetch(p):
        stock = (stocks or {}).get(p.company_id) or InferStock(company_id=p.company_id, name=p.name, isin=p.isin,
                                                               sedol=p.sedol)
        async with gate:
            return await registry.fetch_all(_ref(stock))

    docs = await asyncio.gather(*(fetch(p) for p in described))
    return {p.company_id: description_chunks(d) for p, d in zip(described, docs, strict=True)}


class StockActivity(BaseModel):
    name: str
    in_scope_description: str
    out_of_scope_description: str = Field(
        description="The adjacent activities that do not count, one sentence per adjacent value-chain role.")
    tier: ActivityTier = ActivityTier.CORE
    value_chain_role: Literal["core", "upstream", "enabling"] = "core"
    seed_keywords: list[str] = Field(default_factory=list)
    quotes: list[str] = Field(default_factory=list, description="Verbatim sentences from the excerpts.")


class StockActivities(BaseModel):
    activities: list[StockActivity]


_SYNTH_SYSTEM = (
    "You define the economic activities through which a set of stocks take part in an investment theme. Return "
    "the distinct activities the excerpts show. For each: a short name, an in-scope description, an out-of-scope "
    "description naming the adjacent activities that do not count (one per adjacent value-chain role: upstream "
    "supplier, enabler, user of the product), its tier and value-chain role, seed keywords, and verbatim quotes "
    "from the excerpts that show a stock doing it."
)


async def synthesize(theme: Theme, profiles: list[StockProfile], chunks: dict[str, list[DocumentChunk]], llm, *,
                     fuzzy_threshold: float) -> list[ActivityDefinition]:
    """Bottom-up: one call over the supporting stocks' chunks; an activity keeps only quotes found in a chunk."""
    all_chunks = [ch for cs in chunks.values() for ch in cs]
    if not all_chunks:
        return []
    names = {p.company_id: p.name for p in profiles}
    payload = {"theme": {"name": theme.name, "description": theme.description},
               "stocks": [{"company_id": c, "name": names.get(c, c), "excerpts": [ch.text for ch in cs]}
                          for c, cs in chunks.items()]}
    reply, _ = await llm.complete_structured(system=_SYNTH_SYSTEM, prompt=json.dumps(payload, indent=1),
                                             output_model=StockActivities)
    docs = {ch.chunk_id: SourceDocument(doc_id=ch.chunk_id, company_id=ch.company_id, doc_type=ch.doc_type,
                                        title=ch.doc_id, full_text=ch.text) for ch in all_chunks}
    out = []
    for a in reply.activities:
        cites = []
        for q in dict.fromkeys(a.quotes):
            found = ground_citations([Citation(doc_id=ch.chunk_id, doc_type=ch.doc_type, quote=q) for ch in all_chunks],
                                     docs, fuzzy_threshold)
            hit = next((ch for ch, c in zip(all_chunks, found, strict=True) if q.strip() and c.grounded), None)
            if hit:
                cites.append(SourceCitation(quote=q, source_url=hit.doc_id, location=hit.company_id))
        if cites:
            out.append(ActivityDefinition(**a.model_dump(exclude={"quotes"}), citations=cites))
    return out


async def top_down(sources: list[str], theme_name: str, llm, settings: Settings, fetch, *,
                   scope: str) -> list[ActivityDefinition]:
    """Methodology activities: today's authority checklist per document, consolidated with the value chain.

    Activities keep their `out_of_scope_citations`: the boundary quotes exclusion keywords ground in."""
    docs = await fetch(sources, settings.discovery_user_agent)
    extractions = [await extract_source(d.source_url, d.full_text, theme_name=theme_name, scope=scope,
                                        value_chain=True, llm=llm) for d in docs]
    if not extractions:
        return []
    model = resolve_indirect_exposure_model(settings, use_sample=False)
    theme, _notes = await consolidate(extractions, theme_name=theme_name, scope=scope, value_chain=True,
                                      settings=settings, llm=llm, value_chain_model=model)
    return theme.activities


async def merge(stock_acts: list[ActivityDefinition], method_acts: list[ActivityDefinition], scope: str, llm,
                matcher) -> tuple[list[ActivityDefinition], list[ActivityOrigin]]:
    """Merge as equals: a matched pair keeps the stock activity's id and name and both sides' citations."""
    pairs = ({m.left: m.right for m in await matcher(stock_acts, method_acts, scope=scope, llm=llm)}
             if stock_acts and method_acts else {})
    out, origins = [], []
    for i, a in enumerate(stock_acts):
        if (j := pairs.get(i)) is not None:
            m = method_acts[j]
            a = a.model_copy(update={f: getattr(a, f) + [x for x in getattr(m, f) if x not in getattr(a, f)]
                                     for f in ("citations", "out_of_scope_citations", "sector_codes")})
        out.append(a)
        origins.append(ActivityOrigin(activity_id=a.activity_id, name=a.name, origin="both" if j is not None else "stocks"))
    for j, m in enumerate(method_acts):
        if j not in pairs.values():
            out.append(m)
            origins.append(ActivityOrigin(activity_id=m.activity_id, name=m.name, origin="methodology"))
    return out, origins


class ActivityKeywords(BaseModel):
    activity_id: str
    primary: list[str] = Field(default_factory=list, description="Phrases that alone mark the activity.")
    contextual: list[str] = Field(default_factory=list, description="Phrases that count only near a primary one.")
    exclusion: list[str] = Field(default_factory=list, description="Phrases that mark an adjacent, out-of-scope activity.")


class KeywordProposal(BaseModel):
    activities: list[ActivityKeywords]


_KEYWORD_SYSTEM = (
    "For each activity propose a keyword dictionary in three buckets: primary (phrases that alone show the "
    "activity), contextual (phrases that show it only near a primary phrase) and exclusion (phrases of adjacent "
    "activities that do not count). Use phrases as they appear in the texts. Return each activity's activity_id."
)


def _occurring(phrases: list[str], texts: list[str]) -> list[str]:
    """Phrases (deduplicated, in order) that occur as a case-insensitive whole-word phrase in some text."""
    out = []
    for ph in dict.fromkeys(p.strip() for p in phrases):
        # (?<!\w)..(?!\w) so "C++" and "(PEM)" match; \s+ so a line break inside a phrase still matches
        rx = re.compile(r"(?<!\w)" + r"\s+".join(map(re.escape, ph.split())) + r"(?!\w)", re.IGNORECASE)
        if ph and any(rx.search(t) for t in texts):
            out.append(ph)
    return out


async def keywords(activities: list[ActivityDefinition], chunks_supporting: dict[str, list[DocumentChunk]],
                   chunks_other: dict[str, list[DocumentChunk]], boundary_quotes: list[str], llm
                   ) -> list[ActivityDefinition]:
    """One call proposes three buckets per activity; code keeps only phrases found in the stock text.

    Primary and contextual must occur in a supporting stock's chunk; exclusion in another stock's chunk or a
    methodology boundary quote. Primary goes to `seed_keywords`."""
    if not activities:
        return activities
    support = [ch.text for cs in chunks_supporting.values() for ch in cs]
    others = [ch.text for cs in chunks_other.values() for ch in cs] + list(boundary_quotes)
    payload = {"activities": [{"activity_id": a.activity_id, "name": a.name,
                               "in_scope_description": a.in_scope_description,
                               "out_of_scope_description": a.out_of_scope_description} for a in activities],
               "supporting_excerpts": support, "other_excerpts": others}
    reply, _ = await llm.complete_structured(system=_KEYWORD_SYSTEM, prompt=json.dumps(payload, indent=1),
                                             output_model=KeywordProposal)
    by_id = {k.activity_id: k for k in reply.activities}
    out = []
    for a in activities:
        k = by_id.get(a.activity_id) or ActivityKeywords(activity_id=a.activity_id)
        # earlier seeds survive only where the activity's own citation quotes show them
        seeds = _occurring(a.seed_keywords, [c.quote for c in a.citations]) + _occurring(k.primary, support)
        out.append(a.model_copy(update={"seed_keywords": list(dict.fromkeys(seeds)),
                                        "contextual_keywords": _occurring(k.contextual, support),
                                        "exclusion_keywords": _occurring(k.exclusion, others)}))
    return out


async def pick(
    run_id: str, rank: int, *, run_store, taxonomy_store, settings: Settings, llm, registry: DocumentSourceRegistry,
    matcher=match_activities, draft=draft_schema, mapper=suggest_catalogue_mapping, fetch=read_methodology,
    synthesize=synthesize, top_down=top_down, merge=merge, keywords=keywords, map_stocks=_not_yet, tiers=_not_yet,
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
        stocks_path = Path(params["stocks"]) if params.get("stocks") else None
        stocks = load_stocks(stocks_path)[0] if stocks_path and stocks_path.exists() else []
        chunks = await supporting_chunks(run, theme, registry, stocks={s.company_id: s for s in stocks},
                                         limit=settings.max_concurrent_downloads)
        supporting = {c: ch for c, ch in chunks.items() if c in theme.supporting}
        other = {c: ch for c, ch in chunks.items() if c not in theme.supporting}

        stock_acts = await synthesize(theme, run.profiles, supporting, llm,
                                      fuzzy_threshold=settings.grounding_fuzzy_threshold)
        if not stock_acts:
            raise fail(NO_ACTIVITY)
        unread: list[str] = []

        async def fetch_or_skip(srcs, user_agent):  # per source: one that no longer answers is skipped alone
            docs = []
            for src in srcs:
                try:
                    got = await fetch([src], user_agent)
                except Exception:
                    got = []
                docs += got
                if not got:
                    unread.append(src)
            return docs

        method_acts = (await top_down(sources, theme.name, llm, settings, fetch_or_skip, scope=theme.description)
                       if sources else [])
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
        if unread:
            notes += f" Methodology not read, skipped in top-down: {', '.join(unread)}."
        taxonomy = taxonomy_store.create(run.name, definition, DerivationMethod.STOCK_INFERENCE, notes)
        return _save(run.model_copy(update={"stage": "drafted", "taxonomy_id": taxonomy.taxonomy_id,
                                            "activities": origins, "mapping": mapping}), run_store)
    except InferFailed:
        raise
    except Exception as e:  # never leave a run half-picked
        raise fail(f"{type(e).__name__}: {e}") from e
