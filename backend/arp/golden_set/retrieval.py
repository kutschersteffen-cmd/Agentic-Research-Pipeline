"""Retrieval recall against reviewer-approved citations (run mode) or a committed cases file (cases mode):
does the evidence a field's extraction sees contain the gold span? No LLM calls, so retrieval settings can
be compared cheaply."""

from __future__ import annotations

import asyncio
import hashlib
import json
import statistics
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from arp.config import Settings
from arp.extraction.field_graph import field_evidence
from arp.extraction.pipeline import load_run_schema
from arp.golden_set.export import final_decisions
from arp.grounding import _normalize, _normalize_with_offsets
from arp.ingestion.indexing_config import IndexingConfig
from arp.ingestion.local_files import LocalFileDocumentSource, parse_file_to_text_with_pages
from arp.ingestion.registry import DocumentSourceRegistry
from arp.normalise.locale import decimal_for, detect_language
from arp.presets.registry import PRESETS
from arp.retrieval.content_store_factory import content_store_for
from arp.schemas.common import CompanyRef, DocType, DocumentChunk, SourceDocument
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
    return _report(run_id, settings, ranks, stale, seconds, misses)


def _report(run_id: str | None, settings: Settings, ranks: list[int | None], stale: int, seconds: list[float],
            misses: list[dict]) -> dict:
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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ensure_documents(cases: list[dict], documents_file: Path, documents_dir: Path) -> None:
    """Downloads each case document missing from `<documents_dir>/<company_id>/<document>` from its
    `documents.json` url, and checks every listed file against its recorded SHA-256."""
    listed = json.loads(documents_file.read_text()) if documents_file.exists() else []
    entries = {(d["company_id"], d["document"]): d for d in listed}
    for company_id, document in dict.fromkeys((c["company_id"], c["document"]) for c in cases):
        path = documents_dir / company_id / document
        entry = entries.get((company_id, document))
        if entry is None:
            continue  # not listed: used as it is on disk; a missing file shows up as stale spans
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".part")
            with urllib.request.urlopen(entry["url"], timeout=300) as response:  # noqa: S310 -- urls come from the committed documents.json
                tmp.write_bytes(response.read())
            if _sha256(tmp) != entry["sha256"]:
                tmp.unlink()
                raise ValueError(f"Document {document} does not match its recorded hash.")
            tmp.rename(path)
        elif _sha256(path) != entry["sha256"]:
            raise ValueError(f"Document {document} does not match its recorded hash.")


def _parse(path: Path, company_id: str) -> SourceDocument | None:
    """The parser the labels were made with. Cases name files directly under `<company_id>/`, not under a
    doc-type folder as the app's local source reads them, so the file is parsed here."""
    if not path.exists():
        return None
    text, page_breaks, table_spans = parse_file_to_text_with_pages(path)
    language = detect_language(text)
    return SourceDocument(
        company_id=company_id, doc_type=DocType.SUSTAINABILITY_REPORT, title=path.name, local_path=str(path),
        full_text=text, page_breaks=page_breaks, table_spans=table_spans, language=language, decimal=decimal_for(language),
    )


def _contains(chunk_text: str, span_text: str) -> bool:
    return _normalize(span_text) in _normalize(chunk_text)


async def run_cases_retrieval_eval(cases_file: Path, *, documents_dir: Path, settings: Settings) -> dict:
    """Cases mode: gold spans are text in a committed cases file, so CI can run it without Postgres.
    A span is hit at the first evidence chunk of its document that contains it after grounding's
    normalisation; a span not found in its parsed document is stale (left out and counted)."""
    cases = json.loads(cases_file.read_text())
    ensure_documents(cases, cases_file.parent / "documents.json", documents_dir)
    schemas = {sid: {f.field_id: f for f in PRESETS[sid]().fields} for sid in {c["schema_id"] for c in cases}}
    ranks: list[int | None] = []
    seconds: list[float] = []
    misses: list[dict] = []
    stale = 0
    by_company: dict[str, list[dict]] = {}
    for c in cases:
        by_company.setdefault(c["company_id"], []).append(c)
    for company_id, company_cases in by_company.items():
        names = dict.fromkeys(c["document"] for c in company_cases)
        parsed = [await asyncio.to_thread(_parse, documents_dir / company_id / name, company_id) for name in names]
        documents = [d for d in parsed if d is not None]
        by_title = {d.title: d for d in documents}
        for c in company_cases:
            field = schemas[c["schema_id"]][c["field_id"]]
            doc = by_title.get(c["document"])
            normalised = _normalize_with_offsets(doc.full_text)[0] if doc is not None else ""  # cached per text
            spans = [g["span_text"] for g in c["gold"]]
            live = [s for s in spans if doc is not None and _normalize(s) in normalised]
            stale += len(spans) - len(live)
            if not live:
                continue
            started = time.perf_counter()
            evidence = field_evidence(field, documents, settings)
            seconds.append(time.perf_counter() - started)
            for span in live:
                rank = next((i for i, e in enumerate(evidence) if e.doc_id == doc.doc_id and _contains(e.text, span)), None)
                ranks.append(rank)
                if rank is None:
                    misses.append({"case_id": c["case_id"], "company_id": company_id, "field_id": field.field_id,
                                   "document": c["document"], "span_text": span})
    return _report(None, settings, ranks, stale, seconds, misses)
