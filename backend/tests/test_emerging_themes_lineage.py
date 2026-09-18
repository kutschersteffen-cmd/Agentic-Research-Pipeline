from arp.emerging_themes.lineage import classify_lineage
from arp.schemas.emerging_themes import LineageTransition, TopicCluster


def _cluster(cluster_id: str, company_ids: list[str], centroid: list[float] | None = None) -> TopicCluster:
    return TopicCluster(
        cluster_id=cluster_id, period="2026-W01", representative_label=cluster_id,
        company_ids=company_ids, centroid=centroid or [],
    )


def test_no_prior_clusters_everything_is_birth():
    current = [_cluster("c1", ["acme"]), _cluster("c2", ["globex"])]

    events = classify_lineage(current, None, "2026-W01")

    assert {e.cluster_id: e.transition for e in events} == {"c1": LineageTransition.BIRTH, "c2": LineageTransition.BIRTH}


def test_matching_prior_cluster_is_growth_not_birth():
    prior = [_cluster("p1", ["acme", "globex"])]
    current = [_cluster("c1", ["acme", "globex", "initech"])]  # strong company overlap with p1

    events = classify_lineage(current, prior, "2026-W02")

    current_event = next(e for e in events if e.cluster_id == "c1")
    assert current_event.transition == LineageTransition.GROWTH
    assert current_event.prior_cluster_ids == ["p1"]


def test_unrelated_current_cluster_with_prior_clusters_present_is_birth():
    prior = [_cluster("p1", ["acme"])]
    current = [_cluster("c1", ["totally", "different", "companies"])]

    events = classify_lineage(current, prior, "2026-W02")

    current_event = next(e for e in events if e.cluster_id == "c1")
    assert current_event.transition == LineageTransition.BIRTH


def test_one_prior_splitting_into_two_current_clusters_is_split():
    prior = [_cluster("p1", ["acme", "globex", "initech"])]
    current = [_cluster("c1", ["acme", "globex"]), _cluster("c2", ["globex", "initech"])]

    events = classify_lineage(current, prior, "2026-W02")

    by_id = {e.cluster_id: e for e in events}
    assert by_id["c1"].transition == LineageTransition.SPLIT
    assert by_id["c2"].transition == LineageTransition.SPLIT


def test_two_priors_converging_into_one_current_cluster_is_merge():
    prior = [_cluster("p1", ["acme", "globex"]), _cluster("p2", ["acme", "initech"])]
    current = [_cluster("c1", ["acme", "globex", "initech"])]

    events = classify_lineage(current, prior, "2026-W02")

    current_event = next(e for e in events if e.cluster_id == "c1")
    assert current_event.transition == LineageTransition.MERGE
    assert set(current_event.prior_cluster_ids) == {"p1", "p2"}


def test_prior_cluster_with_no_successor_is_death():
    prior = [_cluster("p1", ["acme"]), _cluster("p2", ["globex"])]
    current = [_cluster("c1", ["acme"])]  # only p1 continues

    events = classify_lineage(current, prior, "2026-W02")

    death_events = [e for e in events if e.transition == LineageTransition.DEATH]
    assert len(death_events) == 1
    assert death_events[0].cluster_id == "p2"
