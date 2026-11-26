"""Theme Radar slice 1 (spec theme-radar-screen): theme ids, burst flag, growing themes, GET /radar."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from arp.api.deps import get_run_store, get_topic_store
from arp.api.main import app
from arp.emerging_themes import radar
from arp.emerging_themes.clustering import cluster_tags
from arp.schemas.emerging_themes import (
    EmergingThemeCandidate,
    ExtractedTag,
    LineageEvent,
    LineageTransition,
    MentionSourceType,
    RawMention,
    TopicCluster,
)
from arp.storage.run_store import RunStore
from arp.storage.topic_store import TopicStateStore

WEEKS = [f"2026-W{w}" for w in range(40, 46)]
COUNTS = {
    "a": [5, 5, 5, 5, 6, 20], "b": [0, 4, 4, 4, 4, 6], "c": [10] * 6,
    "d": [12] * 5 + [6], "e": [0] * 5 + [5], "z": [73, 69, 69, 69, 68, 53],
}
LABELS = {"a": "alpha", "b": "bravo", "c": "charlie", "d": "delta", "e": "echo", "z": "zulu"}


def _fixture_h(store: TopicStateStore) -> None:
    for i, week in enumerate(WEEKS):
        clusters, events = [], []
        for t, counts in COUNTS.items():
            if not counts[i]:
                continue
            cid = f"{t}{week[-2:]}"
            extra: dict = {"source_counts": {"news": counts[i]}}
            if cid == "a45":
                extra = {"source_counts": {"news": 10, "filings": 6, "regulators": 4}, "company_ids": ["acme", "beta", "gamma"],
                         "member_labels": ["cell plant", "grid storage", "cell plant", "sodium cells", "pilot line", "supply deal", "offtake"]}
            if cid == "d45":
                extra["source_counts"] = {"news": 3, "filings": 3}
            clusters.append(TopicCluster(cluster_id=cid, period=week, representative_label=LABELS[t], mention_count=counts[i], **extra))
            if i and counts[i - 1]:
                events.append(LineageEvent(cluster_id=cid, period=week, transition=LineageTransition.GROWTH,
                                           prior_cluster_ids=[f"{t}{WEEKS[i - 1][-2:]}"], overlap_score=0.9))
            else:
                events.append(LineageEvent(cluster_id=cid, period=week, transition=LineageTransition.BIRTH))
        store.save_period(week, clusters)
        store.save_lineage_events(week, events)


def _candidate(store, theme_id, name, cluster_id, run_id, created_at) -> None:
    store.append_candidate(EmergingThemeCandidate(theme_id=theme_id, theme_name=name, cluster_id=cluster_id, run_id=run_id,
                                                  created_at=created_at, first_detected_date="2026-11-01", signal_velocity=1.0))


def _decide(run_store, run_id, theme_id, action) -> None:
    run_store.append_decision_row(run_id, {"theme_id": theme_id, "action": action, "reason": "r", "decided_at": "2026-11-04T00:00:00Z"})


def _fixture_s(store: TopicStateStore) -> None:
    w40 = [TopicCluster(cluster_id=c, period="2026-W40", representative_label=c, mention_count=n, source_counts={"news": n})
           for c, n in (("p1", 10), ("p2", 4), ("q", 5))]
    store.save_period("2026-W40", w40)
    store.save_lineage_events("2026-W40", [LineageEvent(cluster_id=c.cluster_id, period="2026-W40", transition=LineageTransition.BIRTH) for c in w40])
    store.save_period("2026-W41", [
        TopicCluster(cluster_id="s1", period="2026-W41", representative_label="s1", mention_count=6, source_counts={"news": 6}),
        TopicCluster(cluster_id="s2", period="2026-W41", representative_label="s2", mention_count=5, source_counts={"news": 5}),
        TopicCluster(cluster_id="m", period="2026-W41", representative_label="m", mention_count=9,
                     source_types=[MentionSourceType.EDGAR_FTS, MentionSourceType.GDELT]),
    ])
    store.save_lineage_events("2026-W41", [
        LineageEvent(cluster_id="s1", period="2026-W41", transition=LineageTransition.SPLIT, prior_cluster_ids=["p1"], overlap_score=0.8),
        LineageEvent(cluster_id="s2", period="2026-W41", transition=LineageTransition.SPLIT, prior_cluster_ids=["p1"], overlap_score=0.5),
        LineageEvent(cluster_id="m", period="2026-W41", transition=LineageTransition.MERGE, prior_cluster_ids=["p2", "q"], overlap_score=0.6),
    ])


@pytest.fixture
def env(tmp_path, pg):
    store = TopicStateStore(tmp_path / "topics")
    run_store = RunStore(pg, tmp_path / "runs")
    app.dependency_overrides[get_topic_store] = lambda: store
    app.dependency_overrides[get_run_store] = lambda: run_store
    yield TestClient(app), store, run_store
    for dep in (get_topic_store, get_run_store):
        app.dependency_overrides.pop(dep, None)


def _themes(client) -> dict:
    r = client.get("/api/emerging-themes/radar")
    assert r.status_code == 200
    return {t["radar_id"]: t for t in r.json()["themes"]}


def test_empty_store(env):
    client, _, _ = env
    assert client.get("/api/emerging-themes/radar").json() == {"periods": [], "themes": [], "companies": []}


def test_fixture_h_plus(env):
    client, store, run_store = env
    _fixture_h(store)
    _candidate(store, "et_b1", "Bravo theme", "b42", "rh1", "2026-10-14T00:00:00Z")
    _candidate(store, "et_b2", "Bravo again", "b45", "rh2", "2026-11-03T00:00:00Z")
    _candidate(store, "et_c", "Charlie theme", "c41", "rh0", "2026-10-07T00:00:00Z")
    _candidate(store, "et_e", "Echo theme", "e45", "rh2", "2026-11-03T00:00:01Z")
    _candidate(store, "et_d", "Delta theme", "d43", "rh1", "2026-10-21T00:00:00Z")
    _decide(run_store, "rh1", "et_b1", "reject")
    _decide(run_store, "rh0", "et_c", "promote")
    _decide(run_store, "rh1", "et_d", "disconfirm")

    body = client.get("/api/emerging-themes/radar").json()
    assert body["periods"] == WEEKS
    assert [t["radar_id"] for t in body["themes"]] == ["a40", "b41", "e45", "c40", "d40", "z40"]
    t = {x["radar_id"]: x for x in body["themes"]}
    a = t["a40"]
    assert (a["flag"], a["burst"], a["share"], a["baseline_share"]) == ("accelerating", 73.6362, 0.2, 0.0525)
    assert (t["b41"]["flag"], t["b41"]["burst"], t["b41"]["share"], t["b41"]["baseline_share"]) == ("rising", 3.8918, 0.06, 0.04)
    assert (t["e45"]["flag"], t["e45"]["burst"], t["e45"]["first_period"]) == ("new", 8.9588, "2026-W45")
    assert (t["c40"]["flag"], t["c40"]["burst"]) == ("steady", 0.0)
    assert (t["d40"]["flag"], t["z40"]["flag"], t["d40"]["burst"], t["d40"]["baseline_share"]) == ("cooling", "cooling", 0.0, 0.12)
    assert [h["mention_count"] for h in a["history"]] == [5, 5, 5, 5, 6, 20]
    assert [h["share"] for h in a["history"]] == [0.05, 0.05, 0.05, 0.05, 0.06, 0.2]
    assert [h["burst"] for h in a["history"]] == [0.0, 0.0, 0.0, 0.0, 1.9459, 73.6362]
    assert [h["share"] for h in t["e45"]["history"]] == [0.0] * 5 + [0.05]
    assert a["source_mix"] == {"news": 10, "filings": 6, "regulators": 4, "research": 0, "jobs": 0}
    assert (a["company_count"], a["labels"], a["label"]) == (3, ["cell plant", "grid storage", "sodium cells", "pilot line", "supply deal"], "alpha")
    assert [(t[r]["status"], t[r]["candidate"], t[r]["label"]) for r in ("a40", "b41", "c40", "d40", "z40")] == [
        ("none", None, "alpha"), ("candidate", {"run_id": "rh2", "theme_id": "et_b2"}, "Bravo again"),
        ("promoted", {"run_id": "rh0", "theme_id": "et_c"}, "Charlie theme"),
        ("disconfirmed", {"run_id": "rh1", "theme_id": "et_d"}, "Delta theme"), ("none", None, "zulu"),
    ]


def test_missing_lineage_file_starts_a_new_theme(env):
    client, store, _ = env
    _fixture_h(store)
    (store.lineage_dir / "2026-W43.jsonl").unlink()
    t = _themes(client)
    assert t["a40"]["last_period"] == "2026-W42"
    assert (t["a43"]["first_period"], t["a43"]["last_period"]) == ("2026-W43", "2026-W45")


def test_older_scans_listed_only_with_an_open_candidate(env):
    client, store, _ = env
    _fixture_h(store)
    for w in ("38", "39"):
        store.save_period(f"2026-W{w}", [TopicCluster(cluster_id=f"old{w}", period=f"2026-W{w}", representative_label="o", mention_count=1)])
        store.save_lineage_events(f"2026-W{w}", [LineageEvent(cluster_id=f"old{w}", period=f"2026-W{w}", transition=LineageTransition.BIRTH)])
    body = client.get("/api/emerging-themes/radar").json()
    assert body["periods"] == WEEKS and not {"old38", "old39"} & {x["radar_id"] for x in body["themes"]}
    _candidate(store, "et_o", "Old", "old38", "rh9", "2026-10-01T00:00:00Z")
    old = _themes(client)["old38"]
    assert old["status"] == "candidate" and [h["mention_count"] for h in old["history"]] == [0] * 6


def test_split_and_merge(env):
    client, store, _ = env
    _fixture_s(store)
    _candidate(store, "et_p2", "P2", "p2", "rh8", "2026-10-01T00:00:00Z")
    t = _themes(client)
    assert set(t) == {"p1", "q", "s2"}
    assert (t["s2"]["flag"], t["s2"]["first_period"]) == ("new", "2026-W41")
    assert (t["q"]["first_period"], t["q"]["last_period"], t["p1"]["last_period"]) == ("2026-W40", "2026-W41", "2026-W41")
    assert t["q"]["source_mix"] == {"news": 1, "filings": 1, "regulators": 0, "research": 0, "jobs": 0}


def test_source_counts_default():
    assert TopicCluster.model_validate({"period": "p", "representative_label": "x"}).source_counts == {}


def test_eligible_cluster_ids(tmp_path):
    store = TopicStateStore(tmp_path / "h")
    _fixture_h(store)
    _candidate(store, "et_b1", "Bravo theme", "b42", "rh1", "2026-10-14T00:00:00Z")
    assert radar.eligible_cluster_ids(store, "2026-W45") == {"a45", "e45"}
    _candidate(store, "et_a", "A", "a43", "rh3", "2026-10-21T00:00:00Z")
    assert radar.eligible_cluster_ids(store, "2026-W45") == {"e45"}
    s = TopicStateStore(tmp_path / "s")
    _fixture_s(s)
    assert radar.eligible_cluster_ids(s, "2026-W41") == {"m"}


def test_cluster_tags_fills_source_counts(monkeypatch):
    """AC-24."""
    import numpy as np

    vectors = np.vstack([np.full((3, 8), 5.0) + np.eye(3, 8) * 0.01])
    monkeypatch.setattr("arp.retrieval.embeddings.embed_texts", lambda texts: vectors)
    monkeypatch.setattr("arp.emerging_themes.clustering._run_once", lambda reduced, size, seed: np.array([0, 0, 0]))
    types = [MentionSourceType.GDELT, MentionSourceType.GDELT, MentionSourceType.EDGAR_FTS]
    mentions = {f"m{i}": RawMention(mention_id=f"m{i}", source_type=st, title="t", text="x", url=f"https://e.com/{i}") for i, st in enumerate(types)}
    tags = [ExtractedTag(tag_id=f"t{i}", mention_id=f"m{i}", label="battery", claim="c", quote="q") for i in range(3)]
    clusters = cluster_tags(tags, mentions, {}, "2026-W01", min_cluster_size=3, stability_reruns=0)
    assert clusters[0].source_counts == {"news": 2, "filings": 1}


def test_existing_routes_unchanged():
    """AC-25: the candidates, decision and schedule routes keep their paths and methods."""
    paths = app.openapi()["paths"]
    base = "/api/emerging-themes"
    for path, method in [
        (f"{base}/runs", "POST"), (f"{base}/runs/{{run_id}}/candidates", "GET"),
        (f"{base}/runs/{{run_id}}/candidates/{{theme_id}}/promote", "POST"),
        (f"{base}/runs/{{run_id}}/candidates/{{theme_id}}/reject", "POST"),
        (f"{base}/runs/{{run_id}}/candidates/{{theme_id}}/disconfirm", "POST"),
        (f"{base}/schedule", "GET"), (f"{base}/schedule", "PUT"),
    ]:
        assert method.lower() in paths[path]


def test_radar_imports_no_model_client():
    """AC-26."""
    source = (Path(radar.__file__)).read_text()
    assert "arp.llm" not in source
