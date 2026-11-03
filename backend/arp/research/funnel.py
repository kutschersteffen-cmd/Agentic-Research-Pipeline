"""Theme funnel: embeddings -> cross-encoder -> NLI over one company x activity pair, so the LLM debate
only runs for pairs whose documents actually state the activity (spec 2026-11-01-theme-funnel-design)."""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict

import numpy as np

from arp import models
from arp.ingestion.parsing import chunk_document
from arp.retrieval.embeddings import EMBED_MODEL_NAME
from arp.schemas.common import DocumentChunk, SourceDocument
from arp.schemas.thematic import ActivityDefinition, FunnelRecord


def chunks_for(documents: list[SourceDocument]) -> list[DocumentChunk]:
    """Every chunk of every document, no keyword filter."""
    return [c for doc in documents for c in chunk_document(doc)]


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
    documents: list[SourceDocument], activity: ActivityDefinition, thresholds: dict[str, float], content_store=None
) -> FunnelRecord:
    positive = activity.in_scope_description
    negatives = [activity.out_of_scope_description, *activity.contrast_statements]
    chunks = chunks_for(documents)
    if not chunks:
        return FunnelRecord(passed=False, rerank_max=None, entail_positive=0.0, best_passage="", best_doc_id="",
                            passages_scored=0, thresholds=thresholds)

    vectors = passage_vectors(chunks, content_store)
    with _LOCK:
        query, embed_prov = models.embed([positive])
    q = query[0] / (np.linalg.norm(query[0]) or 1.0)
    sims = [float(np.dot(vectors[c.chunk_id], q) / (np.linalg.norm(vectors[c.chunk_id]) or 1.0)) for c in chunks]
    top = [chunks[i] for i in sorted(range(len(chunks)), key=lambda i: -sims[i])[: int(thresholds["k1"])]]

    with _LOCK:
        scores, rerank_prov = models.rerank(positive, [c.text for c in top])
    if scores is None:  # rerank service down: keep embedding order and let the debate decide
        rerank_max = None
        kept = top[: int(thresholds["k2"])]
    else:
        order = sorted(range(len(top)), key=lambda i: -scores[i])[: int(thresholds["k2"])]
        kept = [top[i] for i in order]
        rerank_max = float(max(scores))

    with _LOCK:
        entail, nli_prov = models.classify([c.text for c in kept], [positive, *negatives], hypothesis="{}")
    winner = next(
        (i for i, s in enumerate(entail)
         if s[positive] >= thresholds["t_entail"] and all(s[positive] > s[n] for n in negatives)),
        None,
    )
    best = winner if winner is not None else max(range(len(kept)), key=lambda i: entail[i][positive])
    passed = rerank_max is None or (rerank_max >= thresholds["t_rerank"] and winner is not None)
    return FunnelRecord(
        passed=passed,
        rerank_max=rerank_max,
        entail_positive=entail[best][positive],
        entail_negatives={n: entail[best][n] for n in negatives},
        best_passage=kept[best].text,
        best_doc_id=kept[best].doc_id,
        passages_scored=len(kept),
        thresholds=thresholds,
        models=[embed_prov, rerank_prov, nli_prov],
    )
