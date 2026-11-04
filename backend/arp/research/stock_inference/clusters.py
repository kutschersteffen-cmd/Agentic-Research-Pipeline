from __future__ import annotations

from collections.abc import Callable

import numpy as np

from arp.emerging_themes.clustering import _run_once, _top_terms
from arp.research.stock_inference.schemas import Cluster
from arp.retrieval.embeddings import embed_texts
from arp.schemas.common import DocumentChunk

_MIN_CLUSTER_SIZE = 3


def cluster_points(embeddings: np.ndarray) -> np.ndarray:
    """UMAP+HDBSCAN labels (-1 = noise); too few points to cluster are all noise."""
    n = len(embeddings)
    if n < _MIN_CLUSTER_SIZE:
        return np.full(n, -1)
    return _run_once(embeddings, _MIN_CLUSTER_SIZE, seed=0)


def build_clusters(
    chunks_by_stock: dict[str, list[DocumentChunk]],
    weights: dict[str, float | None],
    benchmark_chunks: list[DocumentChunk],
    *,
    cluster: Callable[[np.ndarray], np.ndarray] = cluster_points,
    embed: Callable[[list[str]], np.ndarray] = embed_texts,
) -> list[Cluster]:
    fund = [(sid, c) for sid in sorted(chunks_by_stock) for c in chunks_by_stock[sid]]
    texts = [c.text for _, c in fund] + [c.text for c in benchmark_chunks]
    if not texts:
        return []
    labels = cluster(np.asarray(embed(texts)))

    by_label: dict[int, list[tuple[str, str]]] = {}
    for (sid, c), label in zip(fund, labels[: len(fund)], strict=True):
        if label != -1:  # benchmark points (the tail of labels) never reach members
            by_label.setdefault(int(label), []).append((sid, c.text))
    if not by_label:
        return []

    # Renumber by smallest member so ids don't depend on HDBSCAN's label order.
    ids = sorted(by_label, key=lambda i: sorted({s for s, _ in by_label[i]}))
    docs = [" ".join(t for _, t in by_label[i]) for i in ids]
    bench_doc = " ".join(c.text for c in benchmark_chunks)
    terms = _top_terms(docs + [bench_doc] if bench_doc else docs, top_n=10)[: len(ids)]

    total = sum(weights.get(s) or 0.0 for s in chunks_by_stock)
    out = []
    for new_id, (i, t) in enumerate(zip(ids, terms, strict=True)):
        members = sorted({s for s, _ in by_label[i]})
        share = None
        if total and any(weights.get(s) is not None for s in members):
            share = sum(weights.get(s) or 0.0 for s in members) / total
        out.append(Cluster(cluster_id=new_id, terms=t, members=members, weight_share=share))
    return out
