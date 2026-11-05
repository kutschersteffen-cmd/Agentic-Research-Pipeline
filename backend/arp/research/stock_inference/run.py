"""Stock-inference run: select, profile, cluster and propose themes, stored in RunStore under snapshot "infer"."""

from __future__ import annotations

import asyncio
import importlib.util
import random
from pathlib import Path

from arp.config import Settings
from arp.extraction.pipeline import _extract_company
from arp.ingestion.local_files import parse_file_to_text
from arp.ingestion.registry import DocumentSourceRegistry
from arp.orchestration.job_manager import JobManager
from arp.research.stock_inference.clusters import build_clusters, cluster_points
from arp.research.stock_inference.index_rules import stated_index_rules
from arp.research.stock_inference.profile import description_chunks, discover_missing, profile_all
from arp.research.stock_inference.schemas import Cluster, InferRun
from arp.research.stock_inference.selection import load_stocks, select
from arp.research.stock_inference.stored import load_segments
from arp.research.stock_inference.themes import propose_themes
from arp.research.taxonomy_sources.fetch import fetch_source_text
from arp.retrieval.embeddings import embed_texts
from arp.schemas.common import DocType, DocumentChunk, SourceDocument
from arp.universe import load_company_universe

_SNAPSHOT = "infer"
_MAX_BENCHMARK = 200
_MAX_CHARS = 400_000


class WrongStage(Exception):
    def __init__(self, run_id: str, stage: str, command: str, needed: str) -> None:
        super().__init__(f"Run {run_id} is at stage '{stage}'; '{command}' needs '{needed}'.")
        self.run_id, self.stage, self.command, self.needed = run_id, stage, command, needed


class InferFailed(Exception):
    """The run was saved at stage `failed`; `args[0]` is the message for the user."""

    def __init__(self, run: InferRun, message: str) -> None:
        super().__init__(message)
        self.run = run


def load_run(run_id: str, run_store) -> InferRun:
    data = run_store.read_snapshot(run_id, _SNAPSHOT)
    if data is None:
        raise KeyError(f"Run {run_id} not found.")
    return InferRun.model_validate(data)


def _round(v):
    if isinstance(v, float):
        return round(v, 4)
    if isinstance(v, dict):  # construction_spec keeps full precision: rounding 1e-9 floors to 0 would not validate
        return {k: x if k == "construction_spec" else _round(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_round(x) for x in v]
    return v


def dump(run: InferRun) -> dict:
    """The run JSON: numbers rounded to 4 decimals; a profile's `error` is absent on success."""
    data = _round(run.model_dump(mode="json"))
    for p in data["profiles"]:
        if p["error"] is None:
            del p["error"]
    return data


def _save(run: InferRun, run_store) -> InferRun:
    run_store.save_snapshot(run.run_id, _SNAPSHOT, dump(run))
    return run


async def read_methodology(sources: list[str], user_agent: str) -> list[SourceDocument]:
    docs = []
    for i, src in enumerate(sources, 1):
        if src.startswith(("http://", "https://")):
            text = await fetch_source_text(src, user_agent, max_chars=_MAX_CHARS)
        else:
            text = parse_file_to_text(Path(src))[:_MAX_CHARS]
        if text:  # an unreachable URL is skipped, like the authority agent does
            docs.append(SourceDocument(doc_id=f"methodology_{i}", company_id="methodology", doc_type=DocType.OTHER,
                                       title=src, source_url=src, full_text=text))
    return docs


async def _benchmark_chunks(path: Path, registry: DocumentSourceRegistry, limit: int) -> list[DocumentChunk]:
    refs = sorted(load_company_universe(path), key=lambda c: c.company_id)
    if len(refs) > _MAX_BENCHMARK:
        refs = random.Random(0).sample(refs, _MAX_BENCHMARK)
    gate = asyncio.Semaphore(limit)

    async def fetch(ref):
        async with gate:
            return await registry.fetch_all(ref)

    docs = await asyncio.gather(*(fetch(r) for r in refs))  # documents on hand only: no discovery
    return [c for d in docs if d for c in description_chunks(d)]


def _samples(clusters: list[Cluster], chunks_by_stock: dict[str, list[DocumentChunk]]) -> dict[int, list[str]]:
    # shortcut: build_clusters does not return each cluster's chunks, so take the member chunks holding the most
    # cluster terms; return them from build_clusters if the samples prove off-topic
    out = {}
    for c in clusters:
        texts = [ch.text for m in c.members for ch in chunks_by_stock.get(m, [])]
        out[c.cluster_id] = sorted(texts, key=lambda t: -sum(term in t.lower() for term in c.terms))[:3]
    return out


async def start(
    stocks_path: Path, *, methodology: list[str] = (), segments_path: Path | None = None,
    benchmark_path: Path | None = None, name: str | None = None, run_store, settings: Settings, llm, verifier_llm,
    registry: DocumentSourceRegistry, discover=discover_missing, extract=_extract_company,
    cluster=cluster_points, embed=embed_texts,
) -> InferRun:
    if any(importlib.util.find_spec(m) is None for m in ("umap", "hdbscan", "sklearn")):
        raise ValueError('Clustering needs the emerging_themes extra: pip install -e ".[emerging_themes]"')
    stocks_path = Path(stocks_path)
    stocks, total_weight = load_stocks(stocks_path)
    if not stocks:
        raise ValueError(f"No stocks found in {stocks_path}.")
    selected, selection = select(stocks, total_weight)
    segments = load_segments(segments_path) if segments_path else {}
    methodology_docs = await read_methodology(list(methodology), settings.discovery_user_agent)
    name = name or stocks_path.stem
    params = {"stocks": str(stocks_path), "methodology": list(methodology), "name": name,
              "segments": str(segments_path) if segments_path else None,
              "benchmark": str(benchmark_path) if benchmark_path else None}
    jobs = JobManager(run_store)
    manifest = jobs.create_run("stock_inference", params, len(selected), model=settings.llm_model,
                                                verifier_model=settings.llm_verifier_model)
    run = _save(InferRun(run_id=manifest.run_id, stage="started", name=name, extractor_model=settings.llm_model,
                         verifier_model=settings.llm_verifier_model, selection=selection), run_store)

    def fail(message: str) -> InferFailed:
        jobs.finish_run(run.run_id, error=message)
        return InferFailed(_save(run.model_copy(update={"stage": "failed"}), run_store), message)

    try:
        profiles, chunks_by_stock = await profile_all(
            selected, registry=registry, llm=llm, verifier_llm=verifier_llm, settings=settings, discover=discover,
            extract=extract, segments=segments,
        )
        run = run.model_copy(update={"profiles": profiles})
        described = [p for p in profiles if p.description]
        if not described:
            no_doc = sum(p.error == "no_document" for p in profiles)
            raise fail(f"No stock could be profiled: {len(profiles) - no_doc} failed, {no_doc} had no document.")
        run = _save(run.model_copy(update={"stage": "profiled"}), run_store)

        bench = await _benchmark_chunks(Path(benchmark_path), registry, settings.max_concurrent_downloads) if benchmark_path else []
        chunks = {p.company_id: chunks_by_stock.get(p.company_id, []) for p in described}
        clusters = build_clusters(chunks, {p.company_id: p.weight for p in described}, bench,
                                  cluster=cluster, embed=embed)
        run = run.model_copy(update={"clusters": clusters})
        stated_theme = None
        if methodology_docs:
            index_rules, stated_theme = await stated_index_rules(methodology_docs, name, llm)
            run = run.model_copy(update={"index_rules": index_rules})
        themes, outliers = await propose_themes(profiles, clusters, stated_theme, methodology_docs, llm,
                                                samples=_samples(clusters, chunks),
                                                fuzzy_threshold=settings.grounding_fuzzy_threshold)
        if not themes:
            raise fail("No common theme is supported by the profiled stocks.")
        jobs.finish_run(run.run_id)
        return _save(run.model_copy(update={"stage": "themes_ready", "themes": themes, "outliers": outliers}),
                     run_store)
    except InferFailed:
        raise
    except Exception as e:  # never leave a run stuck at started/profiled
        raise fail(f"{type(e).__name__}: {e}") from e
