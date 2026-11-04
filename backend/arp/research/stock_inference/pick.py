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
from arp.research.stock_inference.schemas import (
    ActivityOrigin,
    Coverage,
    InferRun,
    InferStock,
    Mapping,
    StockProfile,
    Theme,
)
from arp.research.stock_inference.selection import load_stocks
from arp.research.stock_inference.stored import _segment_rows, load_segments
from arp.schemas.authority_taxonomy import SourceCitation
from arp.schemas.common import Citation, DocumentChunk, SourceDocument
from arp.schemas.datapoints import FieldDefinition
from arp.schemas.taxonomy import DerivationMethod
from arp.schemas.thematic import ActivityDefinition, ActivityTier, ThemeDefinition

NO_ACTIVITY = "No activity could be grounded in the supporting stocks."


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


class StockAssignment(BaseModel):
    company_id: str
    activity_id: str = Field(description="One of the activity_ids, or 'none' when the stock does none of them.")
    reason: str
    quote: str = Field(description="A verbatim sentence from this stock's own excerpts.")


class StockAssignments(BaseModel):
    assignments: list[StockAssignment]


_MAP_SYSTEM = (
    "Assign every stock to the one activity its excerpts show it doing most, or to 'none' when it does none of "
    "them. For each stock give its company_id, the activity_id (or 'none'), a one-sentence reason and a verbatim "
    "quote from that stock's own excerpts."
)


async def map_stocks(profiles: list[StockProfile], activities: list[ActivityDefinition],
                     chunks: dict[str, list[DocumentChunk]], llm, *, fuzzy_threshold: float
                     ) -> tuple[list[Mapping], list[str]]:
    """One call maps every described stock; a mapping is kept only when its quote grounds in that stock's own
    chunks (a grounded 'none' is kept with `activity_id` None). The rest are returned as unmapped."""
    described = [p for p in profiles if p.description]
    if not described:
        return [], []
    payload = {"activities": [{"activity_id": a.activity_id, "name": a.name,
                               "in_scope_description": a.in_scope_description} for a in activities],
               "stocks": [{"company_id": p.company_id, "name": p.name,
                           "excerpts": [ch.text for ch in chunks.get(p.company_id, [])]} for p in described]}
    reply, _ = await llm.complete_structured(system=_MAP_SYSTEM, prompt=json.dumps(payload, indent=1),
                                             output_model=StockAssignments)
    ids = {a.activity_id for a in activities}
    by_id = {a.company_id: a for a in reply.assignments}
    mapping, unmapped = [], []
    for p in described:
        a, own = by_id.get(p.company_id), chunks.get(p.company_id, [])
        docs = {ch.chunk_id: SourceDocument(doc_id=ch.chunk_id, company_id=ch.company_id, doc_type=ch.doc_type,
                                            title=ch.doc_id, full_text=ch.text) for ch in own}
        answered = a is not None and bool(a.quote.strip())
        known = answered and (a.activity_id in ids or a.activity_id == "none")
        quoted = known and any(c.grounded for c in ground_citations(
            [Citation(doc_id=ch.chunk_id, doc_type=ch.doc_type, quote=a.quote) for ch in own], docs, fuzzy_threshold))
        if quoted:
            mapping.append(Mapping(company_id=p.company_id, activity_id=None if a.activity_id == "none" else a.activity_id,
                                   reason=a.reason, quote=a.quote, tier="unknown"))
        else:
            unmapped.append(p.company_id)
    return mapping, unmapped


def coverage(run: InferRun, mapping: list[Mapping], unmapped: list[str]) -> Coverage:
    """Mapped weight over described weight and over `total_weight`; a missing weight counts as 0."""
    total = run.selection.total_weight
    weight = {p.company_id: p.weight or 0.0 for p in run.profiles}
    described = sum(weight[p.company_id] for p in run.profiles if p.description)
    mapped = sum(weight.get(m.company_id, 0.0) for m in mapping if m.activity_id is not None)
    return Coverage(profiled_weight_share=mapped / described if total is not None and described else None,
                    fund_weight_share=mapped / total if total else None, unmapped=sorted(unmapped))


def coverage_note(c: Coverage) -> str:
    def fmt(x):
        return "n/a" if x is None else f"{x:.2f}"

    return f"Coverage: {fmt(c.profiled_weight_share)} of profiled weight, {fmt(c.fund_weight_share)} of fund weight."


def _tier(share: float) -> str:
    return "core" if share >= 0.5 else "enabler" if share >= 0.2 else "adopter"


def _latest_period(rows: list) -> list:
    """Only the latest `period`'s rows (string max), so shares from several years are not added up."""
    latest = max((r.period for r in rows), default="")
    return [r for r in rows if r.period == latest]


async def tiers(theme_definition: ThemeDefinition, mapping: list[Mapping], segments: dict, llm, mapper
                ) -> list[Mapping]:
    """Company tier from the share of its revenue in segment labels the mapper links to its mapped activity."""
    if not segments:
        return mapping
    revenue = {cid: [r for r in _segment_rows(_latest_period(rows)) if r["metric"] == "revenue"]
               for cid, rows in segments.items()}
    labels = sorted({r["label"] for rows in revenue.values() for r in rows})
    links, _ = await mapper(theme_definition, {"revenue": labels}, llm) if labels else ([], None)
    linked = {x.activity_id: set(x.matched_labels) for x in links if x.metric == "revenue"}
    out = []
    for m in mapping:
        rows = [r for r in revenue.get(m.company_id, []) if r["share"] is not None]
        if m.activity_id is not None and rows:
            mine = linked.get(m.activity_id, set())
            m = m.model_copy(update={"tier": _tier(sum(r["share"] for r in rows if r["label"] in mine))})
        out.append(m)
    return out


async def draft_kpis(theme: Theme, activities: list[ActivityDefinition], methodology_text: str, llm, draft
                     ) -> list[FieldDefinition]:
    """Theme KPIs drafted by `draft_schema` from the theme, its activities and the methodology; at most 5 kept."""
    acts = "\n".join(f"- {a.name}: {a.in_scope_description}" for a in activities)
    criteria = (f"Theme-level KPIs (2 to 5 fields) for the investment theme '{theme.name}': {theme.description}\n"
                f"Activities of the theme:\n{acts}\n"
                "Do not propose per-activity revenue, CapEx, OpEx or R&D shares; those exist already.")
    if methodology_text:
        criteria += f"\nMethodology excerpts:\n{methodology_text}"
    schema, _ = await draft(criteria, llm)
    return schema.fields[:5]


async def pick(
    run_id: str, rank: int, *, run_store, taxonomy_store, settings: Settings, llm, registry: DocumentSourceRegistry,
    matcher=match_activities, draft=draft_schema, mapper=suggest_catalogue_mapping, fetch=read_methodology,
    synthesize=synthesize, top_down=top_down, merge=merge, keywords=keywords, map_stocks=map_stocks, tiers=tiers,
    draft_kpis=draft_kpis,
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
        mapping, unmapped = await map_stocks(run.profiles, activities, chunks, llm,
                                             fuzzy_threshold=settings.grounding_fuzzy_threshold)
        definition = ThemeDefinition(name=theme.name, description=theme.description, activities=activities,
                                     scope=theme.description)
        mapping = await tiers(definition, mapping, segments, llm, mapper)
        methodology_text = "\n".join(c.quote for a in method_acts for c in a.citations)
        definition.kpis = await draft_kpis(theme, activities, methodology_text, llm, draft)

        notes = f"Inferred by 'arp taxonomy infer pick' from run {run_id}, theme {rank} ({theme.name})."
        if unread:
            notes += f" Methodology not read, skipped in top-down: {', '.join(unread)}."
        cover = coverage(run, mapping, unmapped)
        notes += f" {coverage_note(cover)}"
        taxonomy = taxonomy_store.create(run.name, definition, DerivationMethod.STOCK_INFERENCE, notes)
        return _save(run.model_copy(update={"stage": "drafted", "taxonomy_id": taxonomy.taxonomy_id,
                                            "activities": sorted(origins, key=lambda a: a.activity_id), "coverage": cover,
                                            "mapping": sorted(mapping, key=lambda m: m.company_id)}), run_store)
    except InferFailed:
        raise
    except Exception as e:  # never leave a run half-picked
        raise fail(f"{type(e).__name__}: {e}") from e
