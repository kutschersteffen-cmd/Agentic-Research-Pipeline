from __future__ import annotations

import numpy as np

from arp.schemas.emerging_themes import LineageEvent, LineageTransition, TopicCluster

_LINK_THRESHOLD = 0.3  # combined jaccard/cosine score above which two clusters count as linked across periods


def _company_jaccard(a: TopicCluster, b: TopicCluster) -> float:
    sa, sb = set(a.company_ids), set(b.company_ids)
    if not sa and not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _centroid_cosine(a: TopicCluster, b: TopicCluster) -> float:
    if not a.centroid or not b.centroid:
        return 0.0
    va, vb = np.array(a.centroid), np.array(b.centroid)
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


def _link_score(current: TopicCluster, prior: TopicCluster) -> float:
    """The actual novelty signal: how similar is this period's cluster to
    a specific prior-period cluster, by company overlap and by meaning
    (centroid cosine similarity). Either signal alone can be misleading
    (two clusters can share companies without sharing a topic, or vice
    versa), so the stronger of the two decides the link."""
    return max(_company_jaccard(current, prior), _centroid_cosine(current, prior))


def classify_lineage(
    current_clusters: list[TopicCluster],
    prior_clusters: list[TopicCluster] | None,
    current_period: str,
    *,
    link_threshold: float = _LINK_THRESHOLD,
) -> list[LineageEvent]:
    """Links this period's clusters to the prior period's by member-overlap/
    centroid-similarity and classifies each transition as
    birth/growth/split/merge/death.

    This is the check that makes 'emerging' mean genuinely *new*, not just
    *large or active*: only a BIRTH (no lineage edge back to the prior
    period) is eligible to become a candidate theme downstream -- see
    `emerging_themes/pipeline.py`. GROWTH/SPLIT/MERGE clusters are a
    maturing or restructuring theme the taxonomy library (or a prior
    candidate) should already know about, and DEATH is recorded for the
    history only, never emitted as a candidate.
    """
    if not prior_clusters:
        return [
            LineageEvent(cluster_id=c.cluster_id, period=current_period, transition=LineageTransition.BIRTH)
            for c in current_clusters
        ]

    scores = {
        (c.cluster_id, p.cluster_id): _link_score(c, p) for c in current_clusters for p in prior_clusters
    }
    by_prior_id = {p.cluster_id: p for p in prior_clusters}

    events: list[LineageEvent] = []
    matched_prior_ids: set[str] = set()

    for current in current_clusters:
        matched_priors = [
            p for p in prior_clusters if scores[(current.cluster_id, p.cluster_id)] >= link_threshold
        ]
        if not matched_priors:
            events.append(LineageEvent(cluster_id=current.cluster_id, period=current_period, transition=LineageTransition.BIRTH))
            continue

        matched_prior_ids.update(p.cluster_id for p in matched_priors)
        best_score = max(scores[(current.cluster_id, p.cluster_id)] for p in matched_priors)

        if len(matched_priors) > 1:
            events.append(
                LineageEvent(
                    cluster_id=current.cluster_id, period=current_period, transition=LineageTransition.MERGE,
                    prior_cluster_ids=[p.cluster_id for p in matched_priors], overlap_score=best_score,
                )
            )
            continue

        prior = matched_priors[0]
        successors = [
            c for c in current_clusters if scores[(c.cluster_id, prior.cluster_id)] >= link_threshold
        ]
        transition = LineageTransition.SPLIT if len(successors) > 1 else LineageTransition.GROWTH
        events.append(
            LineageEvent(
                cluster_id=current.cluster_id, period=current_period, transition=transition,
                prior_cluster_ids=[prior.cluster_id], overlap_score=best_score,
            )
        )

    for prior_id in by_prior_id:
        if prior_id not in matched_prior_ids:
            events.append(LineageEvent(cluster_id=prior_id, period=current_period, transition=LineageTransition.DEATH))

    return events
