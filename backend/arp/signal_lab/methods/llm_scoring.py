from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations
from statistics import fmean

from arp.llm.base import LLMUsage
from arp.replication.sentiment_scoring import build_sentiment_panel
from arp.schemas.common import DocType, SourceDocument
from arp.signal_lab.methods.base import MethodInput, MethodResult, register_method, text_buckets
from arp.signal_lab.stats import spearman
from arp.signal_lab.text_store import TextRecord


def to_source_document(rec: TextRecord) -> SourceDocument:
    return SourceDocument(
        doc_id=rec.item_id,
        company_id=rec.company_id or "",
        doc_type=DocType.OTHER,
        title=rec.title,
        full_text=rec.title + "\n\n" + rec.body,
        published_at=rec.event_time,
        source_url=rec.source_url,
    )


def _documents(inp: MethodInput) -> dict[str, dict[str, list[SourceDocument]]]:
    period_ends = inp.prices.period_ends
    return {
        issuer: {period_ends[i]: [to_source_document(r) for r in bucket] for i, bucket in enumerate(buckets) if bucket}
        for issuer, buckets in text_buckets(inp.texts, period_ends).items()
    }


def _run(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # shortcut: one thread per call, fine for a research session
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def estimate_llm_calls(inp: MethodInput) -> dict:
    """An upper bound: the client cache may serve some of these calls."""
    docs = [d for cells in _documents(inp).values() for cell in cells.values() for d in cell]
    return {"calls": len(docs), "approx_input_tokens": sum(len(d.full_text) for d in docs) // 4}


def rerun_stability(score_once: Callable[[], tuple[list[float], list[LLMUsage]]], runs: int) -> float | None:
    """Mean pairwise Spearman correlation of the score vectors across `runs` runs; None if no pair is defined."""
    if isinstance(runs, bool) or not isinstance(runs, int) or runs < 2:
        raise ValueError(f"runs must be an integer >= 2, got {runs!r}")
    vectors: list[list[float]] = []
    for _ in range(runs):
        scores, usages = score_once()
        if any(u.cached for u in usages):
            raise ValueError("cached answers make stability meaningless; pass a client with the cache off")
        if vectors and len(scores) != len(vectors[0]):
            raise ValueError(f"score vectors differ in length ({len(vectors[0])} vs {len(scores)})")
        vectors.append(scores)
    # A constant vector has no rank correlation: skip that pair rather than count it as 0.
    pairs = [c for a, b in combinations(vectors, 2) if (c := spearman(a, b)) is not None]
    return fmean(pairs) if pairs else None


@register_method("grounded_llm")
def _grounded_llm(params: dict, inp: MethodInput) -> MethodResult:
    runs = params.get("stability_runs", 0)
    if isinstance(runs, bool) or not isinstance(runs, int) or runs < 0 or runs == 1:
        raise ValueError(f"grounded_llm 'stability_runs' must be 0 or an integer >= 2, got {runs!r}")
    llm = inp.resources.get("llm")
    if llm is None:
        raise ValueError("grounded_llm needs an LLM client in resources['llm']")
    docs = _documents(inp)

    def score():
        return _run(build_sentiment_panel(docs, inp.prices.period_ends, llm))

    panel, records, usages = score()
    models = {u.model for u in usages if u.model}  # "" means the client did not report one
    if len(models) > 1:
        raise ValueError(f"grounded_llm calls used more than one model: {sorted(models)}")
    if usages and not models:
        raise ValueError("the LLM client reported no model name; a model that is unnamed cannot be split at a cutoff")
    notes: dict = {"calls": len(usages), "ungrounded": sum(not r.grounded for r in records)}
    if runs:
        def score_vector():
            _, recs, used = score()
            return [r.score for r in recs], used

        notes["rerun_stability"] = rerun_stability(score_vector, runs)
    return MethodResult(panel, model=next(iter(models), None), notes=notes)
