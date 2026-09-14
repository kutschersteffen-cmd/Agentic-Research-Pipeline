from __future__ import annotations

from arp.emerging_themes.lineage import centroid_cosine
from arp.schemas.emerging_themes import (
    ContradictionType,
    ExtractedTag,
    LineageEvent,
    LineageTransition,
    MaterialityCategory,
    TopicCluster,
)
from arp.storage.topic_store import TopicStateStore

_DEFAULT_BASELINE_PERIODS = 4


def compute_novelty(cluster: TopicCluster, prior_clusters: list[TopicCluster] | None) -> float:
    """1 minus the highest centroid similarity to any prior-period cluster
    -- the Discovery Blueprint's own definition (roadmap P2). A cluster
    with no prior period to compare against at all (the very first scan)
    is maximally novel by convention, not by an absence of evidence.
    """
    if not prior_clusters:
        return 1.0
    best = max((centroid_cosine(cluster, prior) for prior in prior_clusters), default=0.0)
    return max(0.0, 1.0 - best)


def compute_breadth(cluster: TopicCluster, universe_size: int) -> float:
    """Distinct companies in this cluster as a share of the universe
    scanned this run -- the Blueprint's breadth metric, stated in terms of
    the resolved company_ids already on the cluster rather than a new
    computation."""
    if universe_size <= 0:
        return 0.0
    return min(1.0, len(cluster.company_ids) / universe_size)


def compute_persistence(
    cluster_id: str, current_period: str, current_period_events: list[LineageEvent], topic_store: TopicStateStore
) -> int:
    """Length of the unbroken GROWTH chain ending at this cluster, walked
    back through saved lineage history. A SPLIT or MERGE breaks the chain
    by convention (which single predecessor would 'continue' is
    ambiguous) rather than picking one arbitrarily. The current period's
    own events are passed in directly since they are not saved to
    `topic_store` until after scoring runs (see pipeline.py); every
    earlier period's events are loaded from disk.
    """
    chain_length = 0
    events_by_id = {event.cluster_id: event for event in current_period_events}
    period = current_period
    current_id = cluster_id

    while True:
        event = events_by_id.get(current_id)
        if event is None or event.transition != LineageTransition.GROWTH or len(event.prior_cluster_ids) != 1:
            break
        chain_length += 1
        current_id = event.prior_cluster_ids[0]
        period = topic_store.latest_period_before(period)
        if period is None:
            break
        events_by_id = {event.cluster_id: event for event in topic_store.load_lineage_events(period)}

    return chain_length


def compute_velocity(
    cluster: TopicCluster,
    event: LineageEvent | None,
    prior_clusters: list[TopicCluster] | None,
    baseline_periods: list[list[TopicCluster]],
) -> float:
    """A real growth ratio (this period's mention_count divided by the
    linked prior cluster's) when lineage provides a same-entity
    comparison -- GROWTH, SPLIT, or MERGE all have at least one specific
    prior-period predecessor with its own mention_count. A BIRTH has no
    prior self to compare against, so this falls back to the cluster's
    mention_count relative to the average cluster size across recent
    baseline periods instead -- a 'how much of an outlier in scale is
    this' measure, not a literal growth rate of the same entity. Both
    numbers are genuinely comparable in that a value greater than 1.0
    always means 'bigger than the relevant baseline', so callers don't
    need to know which case produced the number to interpret its sign.
    """
    if event is not None and event.transition != LineageTransition.BIRTH and event.prior_cluster_ids and prior_clusters:
        priors_by_id = {prior.cluster_id: prior for prior in prior_clusters}
        linked = [priors_by_id[pid] for pid in event.prior_cluster_ids if pid in priors_by_id]
        prior_total = sum(prior.mention_count for prior in linked)
        if prior_total > 0:
            return cluster.mention_count / prior_total

    all_baseline_clusters = [c for period_clusters in baseline_periods for c in period_clusters]
    if not all_baseline_clusters:
        return 1.0
    avg_size = sum(c.mention_count for c in all_baseline_clusters) / len(all_baseline_clusters)
    return cluster.mention_count / avg_size if avg_size > 0 else 1.0


def compute_materiality(cluster_tags: list[ExtractedTag]) -> float:
    """Share of this cluster's member tags whose materiality_category is
    not NONE -- the Blueprint's materiality signal (Section 4.1: 'evidence
    linked to revenue, margin, cash flow, assets or risk'), same shape as
    synthesis.py::compute_action_score. Empty input scores 0.0."""
    if not cluster_tags:
        return 0.0
    material_count = sum(1 for tag in cluster_tags if tag.materiality_category != MaterialityCategory.NONE)
    return material_count / len(cluster_tags)


def compute_contradiction(cluster_tags: list[ExtractedTag]) -> float:
    """Share of this cluster's member tags whose contradiction_type is not
    NONE -- the Blueprint's contradiction signal (Section 4.1: 'delays,
    cancellations, impairments or target withdrawals'). Scored the same
    way as every other metric here, but per the Blueprint's governance
    rules this evidence is never used to silently drop a candidate -- see
    synthesis.py::select_contradiction_evidence and
    CandidateStatus.DISCONFIRMED. Empty input scores 0.0."""
    if not cluster_tags:
        return 0.0
    contradiction_count = sum(1 for tag in cluster_tags if tag.contradiction_type != ContradictionType.NONE)
    return contradiction_count / len(cluster_tags)


def score_clusters(
    clusters: list[TopicCluster],
    lineage_events: list[LineageEvent],
    prior_clusters: list[TopicCluster] | None,
    period: str,
    topic_store: TopicStateStore,
    universe_size: int,
    tags_by_id: dict[str, ExtractedTag],
    *,
    baseline_periods: int = _DEFAULT_BASELINE_PERIODS,
) -> list[TopicCluster]:
    """The Detect layer's scoring depth pass (roadmap P2, extended by the
    materiality/contradiction pass below): attaches velocity/breadth/
    persistence/novelty/materiality/contradiction to every cluster this
    period, not just the ones that will become candidates -- an analyst
    should be able to see why a cluster was or wasn't flagged, not just
    read a single opaque confidence percentage. Must run after
    `lineage.classify_lineage` (needs its events) and before
    `TopicStateStore.save_period` (the scores belong in what gets
    persisted as this period's history for the next run's baseline).
    """
    events_by_cluster_id = {event.cluster_id: event for event in lineage_events}
    baseline = topic_store.load_recent_periods(period, baseline_periods)

    scored: list[TopicCluster] = []
    for cluster in clusters:
        event = events_by_cluster_id.get(cluster.cluster_id)
        member_tags = [tags_by_id[tid] for tid in cluster.member_tag_ids if tid in tags_by_id]
        scored.append(
            cluster.model_copy(
                update={
                    "novelty": compute_novelty(cluster, prior_clusters),
                    "breadth": compute_breadth(cluster, universe_size),
                    "persistence": compute_persistence(cluster.cluster_id, period, lineage_events, topic_store),
                    "velocity": compute_velocity(cluster, event, prior_clusters, baseline),
                    "materiality": compute_materiality(member_tags),
                    "contradiction": compute_contradiction(member_tags),
                }
            )
        )
    return scored
