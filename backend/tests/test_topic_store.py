from arp.schemas.emerging_themes import CandidateStatus, EmergingThemeCandidate, LineageEvent, LineageTransition, TopicCluster
from arp.storage.topic_store import TopicStateStore


def test_save_and_load_period_round_trips(tmp_path):
    store = TopicStateStore(tmp_path / "topics")
    clusters = [TopicCluster(cluster_id="c1", period="2026-W01", representative_label="battery", company_ids=["acme"])]

    store.save_period("2026-W01", clusters)

    assert store.list_periods() == ["2026-W01"]
    loaded = store.load_period("2026-W01")
    assert loaded is not None
    assert loaded[0].cluster_id == "c1"


def test_load_missing_period_returns_none(tmp_path):
    store = TopicStateStore(tmp_path / "topics")
    assert store.load_period("2026-W99") is None


def test_latest_period_before_picks_most_recent_earlier_period(tmp_path):
    store = TopicStateStore(tmp_path / "topics")
    for period in ["2026-W01", "2026-W02", "2026-W04"]:
        store.save_period(period, [])

    assert store.latest_period_before("2026-W05") == "2026-W04"
    assert store.latest_period_before("2026-W02") == "2026-W01"
    assert store.latest_period_before("2026-W01") is None


def test_lineage_events_round_trip(tmp_path):
    store = TopicStateStore(tmp_path / "topics")
    events = [LineageEvent(cluster_id="c1", period="2026-W01", transition=LineageTransition.BIRTH)]
    store.save_lineage_events("2026-W01", events)
    # No reader exists yet beyond the raw file -- just confirm it's valid JSONL.
    rows = (store.lineage_dir / "2026-W01.jsonl").read_text().strip().splitlines()
    assert len(rows) == 1


def test_candidate_append_and_list_round_trips(tmp_path):
    store = TopicStateStore(tmp_path / "topics")
    candidate = EmergingThemeCandidate(
        theme_name="Test theme", description="", first_detected_date="2026-01-01", signal_velocity=1.0,
        economic_rationale="", cluster_id="c1", run_id="run1", status=CandidateStatus.CANDIDATE,
    )

    store.append_candidate(candidate)

    loaded = store.list_candidates()
    assert len(loaded) == 1
    assert loaded[0].theme_id == candidate.theme_id
