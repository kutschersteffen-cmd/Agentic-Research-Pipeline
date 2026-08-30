from __future__ import annotations

import numpy as np

from arp.schemas.emerging_themes import ExtractedTag, MentionSourceType, RawMention, TopicCluster

_MATCH_JACCARD_THRESHOLD = 0.5  # what counts as "the same rerun cluster" when scoring stability


def _tag_text(tag: ExtractedTag) -> str:
    return f"{tag.label}. {tag.claim}"


def _run_once(reduced: np.ndarray, min_cluster_size: int, seed: int) -> np.ndarray:
    """One UMAP+HDBSCAN pass. Both are lazily imported (same reasoning as
    `retrieval/embeddings.py::_get_model`'s lazy fastembed import) so a
    default install without the `emerging_themes` extra never pays their
    import cost, and importing this module doesn't require the extra
    unless clustering is actually invoked."""
    import hdbscan
    import umap

    n_neighbors = max(2, min(15, reduced.shape[0] - 1))
    embedding_2d = umap.UMAP(
        n_neighbors=n_neighbors, min_dist=0.0, metric="cosine", random_state=seed
    ).fit_transform(reduced)
    clusterer = hdbscan.HDBSCAN(min_cluster_size=min_cluster_size, metric="euclidean")
    return clusterer.fit_predict(embedding_2d)


def _label_member_sets(labels: np.ndarray) -> dict[int, set[int]]:
    members: dict[int, set[int]] = {}
    for idx, label in enumerate(labels):
        if label == -1:
            continue
        members.setdefault(int(label), set()).add(idx)
    return members


def _jaccard(a: set[int], b: set[int]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def _stability_scores(base_members: dict[int, set[int]], reduced: np.ndarray, min_cluster_size: int, n_reruns: int) -> dict[int, float]:
    """Re-runs clustering with different random seeds and scores each base
    cluster by how often some rerun cluster matches it well (best Jaccard
    over the rerun's clusters >= _MATCH_JACCARD_THRESHOLD). This is the
    pre-LLM stability gate the source plan calls for: only a cluster whose
    membership holds together across reseeded reruns should ever reach the
    synthesis agent.
    """
    if n_reruns <= 0 or not base_members:
        return {label: 1.0 for label in base_members}

    hits = {label: 0 for label in base_members}
    for seed in range(1, n_reruns + 1):
        rerun_labels = _run_once(reduced, min_cluster_size, seed=seed)
        rerun_members = _label_member_sets(rerun_labels)
        for label, members in base_members.items():
            best = max((_jaccard(members, other) for other in rerun_members.values()), default=0.0)
            if best >= _MATCH_JACCARD_THRESHOLD:
                hits[label] += 1
    return {label: hits[label] / n_reruns for label in base_members}


def _top_terms(cluster_docs: list[str], top_n: int = 3) -> list[str]:
    """c-TF-IDF-style labeling: each cluster's concatenated member text is
    treated as one 'document' and TF-IDF is computed across clusters, so a
    term is favored when it's frequent in this cluster but not common
    across the others -- lexical labeling, kept deliberately independent
    of the embedding model per the source plan ('keep lexical methods
    (c-TF-IDF) for labeling regardless of which embedding wins')."""
    from sklearn.feature_extraction.text import TfidfVectorizer

    if not cluster_docs:
        return []
    vectorizer = TfidfVectorizer(max_features=2000, ngram_range=(1, 2), stop_words="english")
    matrix = vectorizer.fit_transform(cluster_docs)
    terms = vectorizer.get_feature_names_out()
    results: list[list[str]] = []
    for row in matrix.toarray():
        top_idx = row.argsort()[::-1][:top_n]
        results.append([terms[i] for i in top_idx if row[i] > 0])
    return results  # type: ignore[return-value]


def cluster_tags(
    tags: list[ExtractedTag],
    mentions_by_id: dict[str, RawMention],
    company_ids_by_mention: dict[str, list[str]],
    period: str,
    *,
    min_cluster_size: int = 3,
    stability_reruns: int = 3,
) -> list[TopicCluster]:
    """The Detect layer's core clustering step: embed each tag's
    label+claim, reduce with UMAP, cluster with HDBSCAN (no pre-set
    cluster count; HDBSCAN's own noise label -1 is dropped here rather
    than forced into a cluster or surfaced as a watchlist -- a Phase 1.5
    addition, not silently discarded data loss, since noise-labeled tags
    are simply not yet part of any candidate).

    Requires the `emerging_themes` extra (umap-learn, hdbscan,
    scikit-learn) -- raises ImportError with a clear message if missing.
    """
    from arp.retrieval.embeddings import embed_texts

    if len(tags) < min_cluster_size:
        return []

    texts = [_tag_text(t) for t in tags]
    embeddings = embed_texts(texts)
    labels = _run_once(embeddings, min_cluster_size, seed=0)
    base_members = _label_member_sets(labels)
    if not base_members:
        return []

    stability = _stability_scores(base_members, embeddings, min_cluster_size, stability_reruns)
    cluster_docs = [" ".join(texts[i] for i in sorted(members)) for members in base_members.values()]
    top_terms_per_cluster = _top_terms(cluster_docs)

    clusters: list[TopicCluster] = []
    for cluster_idx, (label, members) in enumerate(base_members.items()):
        member_tags = [tags[i] for i in sorted(members)]
        member_mention_ids = {t.mention_id for t in member_tags}
        company_ids: set[str] = set()
        source_types: set[MentionSourceType] = set()
        for mention_id in member_mention_ids:
            company_ids.update(company_ids_by_mention.get(mention_id, []))
            mention = mentions_by_id.get(mention_id)
            if mention is not None:
                source_types.add(mention.source_type)
        centroid = embeddings[sorted(members)].mean(axis=0).tolist()
        terms = top_terms_per_cluster[cluster_idx] if cluster_idx < len(top_terms_per_cluster) else []
        representative_label = ", ".join(terms) if terms else member_tags[0].label

        clusters.append(
            TopicCluster(
                period=period,
                representative_label=representative_label,
                member_tag_ids=[t.tag_id for t in member_tags],
                member_labels=[t.label for t in member_tags],
                company_ids=sorted(company_ids),
                mention_count=len(member_mention_ids),
                source_types=sorted(source_types, key=lambda s: s.value),
                centroid=centroid,
                stability_score=stability.get(label, 0.0),
            )
        )
    return clusters
