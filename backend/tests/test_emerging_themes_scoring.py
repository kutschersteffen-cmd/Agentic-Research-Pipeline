from arp.emerging_themes.scoring import compute_breadth, compute_novelty, compute_persistence, compute_velocity, score_clusters
from arp.schemas.emerging_themes import LineageEvent, LineageTransition, TopicCluster
from arp.storage.topic_store import TopicStateStore


def _cluster(cluster_id: str, period: str, mention_count: int = 5, company_ids=None, centroid=None) -> TopicCluster:
    return TopicCluster(
        cluster_id=cluster_id, period=period, representative_label=cluster_id,
        mention_count=mention_count, company_ids=company_ids or [], centroid=centroid or [],
    )


# --- compute_novelty ---

def test_novelty_is_maximal_with_no_prior_clusters():
    assert compute_novelty(_cluster("c1", "p1"), None) == 1.0


def test_novelty_is_low_when_a_prior_cluster_is_nearly_identical():
    current = _cluster("c1", "p2", centroid=[1.0, 0.0])
    prior = _cluster("p1", "p1", centroid=[1.0, 0.0])
    assert compute_novelty(current, [prior]) == 0.0


def test_novelty_is_high_when_no_prior_cluster_is_similar():
    current = _cluster("c1", "p2", centroid=[1.0, 0.0])
    prior = _cluster("p1", "p1", centroid=[0.0, 1.0])
    assert compute_novelty(current, [prior]) == 1.0


# --- compute_breadth ---

def test_breadth_is_share_of_universe():
    cluster = _cluster("c1", "p1", company_ids=["a", "b"])
    assert compute_breadth(cluster, universe_size=4) == 0.5


def test_breadth_is_capped_at_one():
    cluster = _cluster("c1", "p1", company_ids=["a", "b", "c"])
    assert compute_breadth(cluster, universe_size=2) == 1.0


def test_breadth_is_zero_for_empty_universe():
    cluster = _cluster("c1", "p1", company_ids=["a"])
    assert compute_breadth(cluster, universe_size=0) == 0.0


# --- compute_persistence ---

def test_persistence_is_zero_with_no_matching_event(tmp_path):
    store = TopicStateStore(tmp_path / "topics")
    assert compute_persistence("c1", "2026-W02", [], store) == 0


def test_persistence_is_zero_for_a_birth(tmp_path):
    store = TopicStateStore(tmp_path / "topics")
    events = [LineageEvent(cluster_id="c1", period="2026-W02", transition=LineageTransition.BIRTH)]
    assert compute_persistence("c1", "2026-W02", events, store) == 0


def test_persistence_walks_an_unbroken_growth_chain_across_periods(tmp_path):
    store = TopicStateStore(tmp_path / "topics")
    # Two saved historical periods, each a GROWTH link back one further.
    store.save_lineage_events("2026-W01", [LineageEvent(cluster_id="c_w1", period="2026-W01", transition=LineageTransition.BIRTH)])
    store.save_period("2026-W01", [_cluster("c_w1", "2026-W01")])
    store.save_lineage_events(
        "2026-W02", [LineageEvent(cluster_id="c_w2", period="2026-W02", transition=LineageTransition.GROWTH, prior_cluster_ids=["c_w1"])]
    )
    store.save_period("2026-W02", [_cluster("c_w2", "2026-W02")])

    # Current period (W03) event, passed in directly (not yet saved).
    current_events = [
        LineageEvent(cluster_id="c_w3", period="2026-W03", transition=LineageTransition.GROWTH, prior_cluster_ids=["c_w2"])
    ]

    persistence = compute_persistence("c_w3", "2026-W03", current_events, store)

    assert persistence == 2  # c_w3 <- c_w2 (growth), c_w2 <- c_w1 (growth), c_w1 is a BIRTH (chain stops)


def test_persistence_stops_at_a_split_or_merge(tmp_path):
    store = TopicStateStore(tmp_path / "topics")
    store.save_lineage_events(
        "2026-W01", [LineageEvent(cluster_id="c_w1", period="2026-W01", transition=LineageTransition.MERGE, prior_cluster_ids=["x", "y"])]
    )
    current_events = [
        LineageEvent(cluster_id="c_w2", period="2026-W02", transition=LineageTransition.GROWTH, prior_cluster_ids=["c_w1"])
    ]

    persistence = compute_persistence("c_w2", "2026-W02", current_events, store)

    assert persistence == 1  # c_w2 <- c_w1 counts once, but c_w1 is a MERGE so the chain stops there


# --- compute_velocity ---

def test_velocity_is_a_real_ratio_for_growth():
    cluster = _cluster("c1", "p2", mention_count=10)
    prior = _cluster("p1", "p1", mention_count=5)
    event = LineageEvent(cluster_id="c1", period="p2", transition=LineageTransition.GROWTH, prior_cluster_ids=["p1"])

    assert compute_velocity(cluster, event, [prior], []) == 2.0


def test_velocity_falls_back_to_baseline_average_for_a_birth():
    cluster = _cluster("c1", "p1", mention_count=10)
    event = LineageEvent(cluster_id="c1", period="p1", transition=LineageTransition.BIRTH)
    baseline = [[_cluster("b1", "p_earlier", mention_count=4), _cluster("b2", "p_earlier", mention_count=6)]]

    # average baseline cluster size is (4+6)/2 = 5 -> 10/5 = 2.0
    assert compute_velocity(cluster, event, None, baseline) == 2.0


def test_velocity_defaults_to_one_with_no_baseline_and_no_prior():
    cluster = _cluster("c1", "p1", mention_count=10)
    event = LineageEvent(cluster_id="c1", period="p1", transition=LineageTransition.BIRTH)

    assert compute_velocity(cluster, event, None, []) == 1.0


# --- score_clusters (integration) ---

def test_score_clusters_populates_all_four_fields_on_a_first_ever_scan(tmp_path):
    store = TopicStateStore(tmp_path / "topics")
    clusters = [_cluster("c1", "2026-W01", mention_count=5, company_ids=["acme"], centroid=[1.0, 0.0])]
    lineage_events = [LineageEvent(cluster_id="c1", period="2026-W01", transition=LineageTransition.BIRTH)]

    scored = score_clusters(clusters, lineage_events, None, "2026-W01", store, universe_size=2)

    assert len(scored) == 1
    result = scored[0]
    assert result.novelty == 1.0  # no prior period at all
    assert result.breadth == 0.5  # 1 of 2 companies
    assert result.persistence == 0  # a birth
    assert result.velocity == 1.0  # no baseline, no prior self
