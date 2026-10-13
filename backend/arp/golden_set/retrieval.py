"""Retrieval recall against reviewer-approved citations: does the evidence a field's extraction sees
contain the span a reviewer accepted? No LLM calls, so retrieval settings can be compared cheaply."""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass
from pathlib import Path

from arp.config import Settings
from arp.extraction.field_graph import field_evidence
from arp.extraction.pipeline import load_run_schema
from arp.golden_set.export import final_decisions
from arp.ingestion.indexing_config import IndexingConfig
from arp.ingestion.local_files import LocalFileDocumentSource
from arp.ingestion.registry import DocumentSourceRegistry
from arp.retrieval.content_store_factory import content_store_for
from arp.schemas.common import CompanyRef, DocumentChunk
from arp.schemas.review import DecisionKind, ReviewDecision, field_item_key, period_key
from arp.storage.run_store import RunStore


@dataclass(frozen=True)
class GoldSpan:
    company_id: str
    field_id: str
    doc_id: str
    char_start: int
    char_end: int
    span_text: str | None  # what grounding matched; None on citations from before it was recorded


def _spans(company_id: str, field_id: str, citations: list[dict]) -> list[GoldSpan]:
    return [
        GoldSpan(company_id, field_id, c["doc_id"], c["char_start"], c["char_end"], c.get("span_text"))
        for c in citations
        if c and c.get("grounded") and c.get("char_start") is not None and c.get("char_end") is not None
    ]


def gold_spans(run_store: RunStore, run_id: str, decisions: list[ReviewDecision]) -> list[GoldSpan]:
    """Grounded citations of final approvals, and grounded correction citations of final corrections."""
    final = final_decisions(decisions)
    out: list[GoldSpan] = []
    for row in run_store.read_results(run_id):
        for f in row.get("fields", []):
            d = final.get(field_item_key(row.get("issuer_key", ""), f["field_id"], period_key(f)))
            if d is None:
                continue
            if d["decision"] == DecisionKind.APPROVE:
                out += _spans(row["company_id"], f["field_id"], f.get("citations", []))
            elif d["decision"] == DecisionKind.CORRECT:
                out += _spans(row["company_id"], f["field_id"], [d.get("correction_citation")])
    return list(dict.fromkeys(out))  # one field's periods often cite the same span


def hit_rank(evidence: list[DocumentChunk], span: GoldSpan) -> int | None:
    """Position of the first evidence chunk overlapping the span, or None."""
    for i, c in enumerate(evidence):
        if c.doc_id == span.doc_id and c.char_start < span.char_end and span.char_start < c.char_end:
            return i
    return None


def recall_at(ranks: list[int | None], k: int) -> float | None:
    return sum(r is not None and r < k for r in ranks) / len(ranks) if ranks else None


def _registry(documents_dir: Path, settings: Settings) -> DocumentSourceRegistry:
    """The same local source `golden-set precision` reads, so doc_ids match the run's citations."""
    return DocumentSourceRegistry([LocalFileDocumentSource(
        documents_dir,
        content_store=content_store_for(settings),
        max_concurrent_parses=settings.max_concurrent_parses,
        indexing_config=IndexingConfig.from_settings(settings),
    )])


async def run_retrieval_eval(
    run_store: RunStore, run_id: str, decisions: list[ReviewDecision], *, documents_dir: Path, settings: Settings
) -> dict:
    schema = load_run_schema(run_store, run_id)
    if schema is None:
        raise ValueError(f"Run {run_id} has no schema.json; only extraction runs can be evaluated.")
    fields = {f.field_id: f for f in schema.fields}
    gold = [g for g in gold_spans(run_store, run_id, decisions) if g.field_id in fields]
    companies = {c.company_id: c for c in run_store.load_companies(run_id) or []}
    registry = _registry(documents_dir, settings)
    ranks: list[int | None] = []
    seconds: list[float] = []
    misses: list[dict] = []
    stale = 0
    by_company: dict[str, list[GoldSpan]] = {}
    for g in gold:
        by_company.setdefault(g.company_id, []).append(g)
    for company_id, spans in by_company.items():
        documents = await registry.fetch_all(companies.get(company_id) or CompanyRef(company_id=company_id, name=company_id))
        texts = {d.doc_id: d.full_text for d in documents}
        by_field: dict[str, list[GoldSpan]] = {}
        for g in spans:
            # Results keep their offsets after a parser upgrade (see reground.py), and a document can be gone:
            # a span whose text no longer sits there is not a retrieval miss, so it is left out and counted.
            text = texts.get(g.doc_id)
            if g.span_text is None or text is None or text[g.char_start:g.char_end] != g.span_text:
                stale += 1
                continue
            by_field.setdefault(g.field_id, []).append(g)
        for field_id, field_spans in by_field.items():
            started = time.perf_counter()
            evidence = field_evidence(fields[field_id], documents, settings)
            seconds.append(time.perf_counter() - started)
            for g in field_spans:
                rank = hit_rank(evidence, g)
                ranks.append(rank)
                if rank is None:
                    misses.append({"company_id": company_id, "field_id": field_id, "doc_id": g.doc_id,
                                   "char_start": g.char_start, "char_end": g.char_end})
    k = settings.evidence_max_chunks
    return {
        "run_id": run_id,
        "settings": {"hybrid_retrieval_enabled": settings.hybrid_retrieval_enabled, "rerank_enabled": settings.rerank_enabled,
                     "rerank_candidates": settings.rerank_candidates, "evidence_max_chunks": k,
                     "retrieval_backend": settings.retrieval_backend},
        "gold_spans": len(ranks),
        "stale_spans": stale,
        "fields_ranked": len(seconds),
        "recall_at_5": recall_at(ranks, 5),
        f"recall_at_{k}": recall_at(ranks, k),
        "median_seconds_per_field": statistics.median(seconds) if seconds else None,
        "max_seconds_per_field": max(seconds) if seconds else None,
        "misses": misses,
    }
