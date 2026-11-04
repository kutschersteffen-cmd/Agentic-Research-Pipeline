"""Theme funnel: embeddings -> cross-encoder -> NLI over one company x activity pair, so the LLM debate
only runs for pairs whose documents actually state the activity (spec 2026-11-01-theme-funnel-design)."""

from __future__ import annotations

import hashlib
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass

import numpy as np

from arp import models
from arp.ingestion.parsing import chunk_document
from arp.retrieval.embeddings import EMBED_MODEL_NAME
from arp.schemas.common import DocumentChunk, SourceDocument
from arp.schemas.thematic import ActivityDefinition, FunnelRecord, ThemeDefinition

# Stage words (spec amendment B): early-stage evidence must reach the funnel, not only revenue language.
STAGE_WORDS = [
    "research programme", "prototype", "lab-scale", "proof of concept",
    "pilot plant", "demonstrator", "first commercial", "pre-series", "order", "FID",
    "segment revenue", "capacity", "backlog", "market share",
]
POSITIVE_PREFIX = "The company researches, develops, pilots, manufactures or sells"


@dataclass(frozen=True)
class FunnelQuery:
    """What the funnel searches for, built from the whole taxonomy version and its generated schema fields."""

    keywords: list[str]
    query: str
    rerank_query: str
    positives: list[str]


def funnel_query(theme: ThemeDefinition | None, activity: ActivityDefinition) -> FunnelQuery:
    from arp.research.taxonomy_schema import activity_fields  # taxonomy_schema imports the storage layer

    fields = activity_fields(activity, theme.theme_id if theme else "", 0)  # names and keywords only; ids unused
    keywords: list[str] = []
    for kw in [*activity.seed_keywords, *(k for f in fields for k in f.seed_keywords), *STAGE_WORDS]:
        if kw.lower() not in {k.lower() for k in keywords}:
            keywords.append(kw)
    technologies = theme.technologies if theme else []
    definitions = theme.definitions if theme else []
    lines = [
        f"{activity.name}: {activity.in_scope_description}",
        theme.description if theme else "",
        f"Technologies: {', '.join(t.name for t in technologies)}" if technologies else "",
        f"Definitions: {'; '.join(f'{d.term}: {d.text}' for d in definitions)}" if definitions else "",
    ]
    query = "\n".join(line for line in lines if line)
    return FunnelQuery(
        keywords=keywords,
        query=query,
        rerank_query=f"{query}\nEvidence: {'; '.join(f.name for f in fields)}",
        positives=[f"{POSITIVE_PREFIX} {activity.name}.",
                   f"{POSITIVE_PREFIX} the following: {activity.in_scope_description}"],
    )


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_PASSAGE_SENTENCES = 3  # NLI entailment saturates on whole chunks; 3-sentence passages keep statements apart


def chunks_for(documents: list[SourceDocument]) -> list[DocumentChunk]:
    """The funnel's passages: every chunk of every document (no keyword filter), split into 3-sentence windows."""
    out: list[DocumentChunk] = []
    for chunk in (c for doc in documents for c in chunk_document(doc)):
        sentences = [x for x in _SENTENCE_END.split(chunk.text) if x.strip()]
        if len(sentences) <= _PASSAGE_SENTENCES:
            out.append(chunk)
            continue
        for n, i in enumerate(range(0, len(sentences), _PASSAGE_SENTENCES)):
            text = " ".join(sentences[i:i + _PASSAGE_SENTENCES])
            out.append(chunk.model_copy(update={"chunk_id": f"{chunk.chunk_id}#s{n}", "text": text}))
    return out


# Without Postgres, vectors are kept in-process so each document embeds once per company, not once per activity.
# shortcut: bounded LRU, lost on restart; run `documents warm --embed` with Postgres for anything larger.
_MEMO: OrderedDict[str, np.ndarray] = OrderedDict()
_MEMO_MAX = 50_000
_LOCK = threading.Lock()  # score_pair runs in worker threads; the local model is not thread-safe


def _memo_key(chunk: DocumentChunk) -> str:
    return f"{chunk.chunk_id}#{hashlib.sha256(chunk.text.encode('utf-8')).hexdigest()[:16]}"


def passage_vectors(chunks: list[DocumentChunk], content_store) -> dict[str, np.ndarray]:
    """One vector per chunk_id, read from the chunk-embeddings store where present (same keys and model as
    select_evidence's hybrid ranking); only missing chunks are embedded, then stored back."""
    with _LOCK:
        if content_store:
            cached = content_store.lookup_embeddings([c.chunk_id for c in chunks], EMBED_MODEL_NAME)
        else:
            cached = {c.chunk_id: _MEMO[_memo_key(c)] for c in chunks if _memo_key(c) in _MEMO}
        missing = [c for c in chunks if c.chunk_id not in cached]
        if missing:
            vectors, _ = models.embed([c.text for c in missing])
            new = {c.chunk_id: vectors[i] for i, c in enumerate(missing)}
            if content_store:
                content_store.store_embeddings(new, EMBED_MODEL_NAME)
            else:
                for c in missing:
                    _MEMO[_memo_key(c)] = new[c.chunk_id]
                while len(_MEMO) > _MEMO_MAX:
                    _MEMO.popitem(last=False)
            cached = {**cached, **new}
        return cached


def score_pair(
    documents: list[SourceDocument], activity: ActivityDefinition, thresholds: dict[str, float], content_store=None,
    query: FunnelQuery | None = None,
) -> FunnelRecord:
    q = query or funnel_query(None, activity)
    negatives = [activity.out_of_scope_description, *activity.contrast_statements]
    chunks = chunks_for(documents)
    base = {"thresholds": thresholds, "query": q.query, "rerank_query": q.rerank_query, "positives": q.positives}
    if not chunks:
        return FunnelRecord(passed=False, rerank_max=None, entail_positive=0.0, best_passage="", best_doc_id="",
                            passages_scored=0, positive=q.positives[0], **base)

    vectors = passage_vectors(chunks, content_store)
    with _LOCK:
        qv, embed_prov = models.embed([q.query])
    qn = qv[0] / (np.linalg.norm(qv[0]) or 1.0)
    sims = [float(np.dot(vectors[c.chunk_id], qn) / (np.linalg.norm(vectors[c.chunk_id]) or 1.0)) for c in chunks]
    top = [chunks[i] for i in sorted(range(len(chunks)), key=lambda i: -sims[i])[: int(thresholds["k1"])]]

    with _LOCK:
        scores, rerank_prov = models.rerank(q.rerank_query, [c.text for c in top])
    if scores is None:  # rerank service down: keep embedding order and let the debate decide
        rerank_max = None
        kept = top[: int(thresholds["k2"])]
    else:
        order = sorted(range(len(top)), key=lambda i: -scores[i])[: int(thresholds["k2"])]
        kept = [top[i] for i in order]
        rerank_max = float(max(scores))

    with _LOCK:
        entail, nli_prov = models.classify([c.text for c in kept], [*q.positives, *negatives], hypothesis="{}")
    winner = next(
        ((i, p) for i, s in enumerate(entail) for p in q.positives
         if s[p] >= thresholds["t_entail"] and all(s[p] > s[n] for n in negatives)),
        None,
    )
    best, positive = winner or max(((i, p) for i in range(len(kept)) for p in q.positives),
                                   key=lambda ip: entail[ip[0]][ip[1]])
    passed = rerank_max is None or (rerank_max >= thresholds["t_rerank"] and winner is not None)
    return FunnelRecord(
        passed=passed,
        rerank_max=rerank_max,
        entail_positive=entail[best][positive],
        entail_negatives={n: entail[best][n] for n in negatives},
        best_passage=kept[best].text,
        best_doc_id=kept[best].doc_id,
        passages_scored=len(kept),
        models=[embed_prov, rerank_prov, nli_prov],
        positive=positive,
        **base,
    )
