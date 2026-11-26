"""Theme Radar (spec theme-radar-screen): one id per theme across saved scans, a burst-score flag, and the
cross-scan radar view. Pure code: no model call decides an id, a flag or a status."""
from __future__ import annotations

import math
from statistics import mean, pstdev

from arp.schemas.emerging_themes import EmergingThemeCandidate, LineageTransition, MentionSourceType, TopicCluster
from arp.storage.run_store import RunStore
from arp.storage.topic_store import TopicStateStore

BASELINE_SCANS = 4
SD_FLOOR = 0.01
ACCELERATING_AT = 8.0
RISING_AT = 3.0
COOLING_Z = -1.0
HISTORY_SCANS = 6

SOURCE_CATEGORIES = ["news", "filings", "regulators", "research", "jobs"]
SOURCE_CATEGORY = {
    MentionSourceType.GDELT: "news",
    MentionSourceType.EDGAR_FTS: "filings",
    MentionSourceType.REGULATORY_RSS: "regulators",
}
_FLAG_ORDER = ["accelerating", "rising", "new", "steady", "cooling"]
_DECISION_STATUS = {"promote": "promoted", "reject": "rejected", "disconfirm": "disconfirmed"}


def _source_counts(cluster: TopicCluster) -> dict[str, int]:
    """A cluster saved before source_counts existed counts 1 for the category of each of its source_types."""
    return cluster.source_counts or {SOURCE_CATEGORY[s]: 1 for s in cluster.source_types}


def _walk(topic_store: TopicStateStore, periods: list[str]):
    """Per scan, radar_id -> cluster and total mentions; plus cluster_id -> radar_id and the absorbed radar_ids."""
    by_scan: dict[str, dict[str, TopicCluster]] = {}
    totals: dict[str, int] = {}
    radar_of: dict[str, str] = {}
    clusters: dict[str, TopicCluster] = {}
    absorbed: set[str] = set()
    for period in periods:
        scan = topic_store.load_period(period) or []
        totals[period] = sum(c.mention_count for c in scan)
        clusters.update((c.cluster_id, c) for c in scan)
        events = {e.cluster_id: e for e in topic_store.load_lineage_events(period) if e.transition != LineageTransition.DEATH}
        splits: dict[str, list[TopicCluster]] = {}
        for c in scan:
            e = events.get(c.cluster_id)
            if e and e.transition == LineageTransition.SPLIT and e.prior_cluster_ids:
                splits.setdefault(e.prior_cluster_ids[0], []).append(c)
        split_winners = {
            prior: min(group, key=lambda c: (-events[c.cluster_id].overlap_score, -c.mention_count, c.cluster_id)).cluster_id
            for prior, group in splits.items()
        }
        for c in scan:
            e = events.get(c.cluster_id)
            rid = c.cluster_id
            if e and e.transition == LineageTransition.GROWTH and e.prior_cluster_ids:
                rid = radar_of.get(e.prior_cluster_ids[0], rid)
            elif e and e.transition == LineageTransition.SPLIT and e.prior_cluster_ids:
                if split_winners[e.prior_cluster_ids[0]] == c.cluster_id:
                    rid = radar_of.get(e.prior_cluster_ids[0], rid)
            elif e and e.transition == LineageTransition.MERGE:
                priors = [(clusters[p].mention_count, radar_of[p]) for p in e.prior_cluster_ids if p in radar_of]
                if priors:
                    rid = min(priors, key=lambda x: (-x[0], x[1]))[1]
                    absorbed.update(r for _, r in priors if r != rid)
            radar_of[c.cluster_id] = rid
            by_scan.setdefault(period, {})[rid] = c
    return by_scan, totals, radar_of, absorbed


def _themes(topic_store: TopicStateStore, periods: list[str]) -> tuple[dict, dict[str, str], set[str]]:
    """radar_id -> {flag, burst, share, baseline_share, first_period, last_period, last, history}."""
    by_scan, totals, radar_of, absorbed = _walk(topic_store, periods)

    def share(rid: str, p: str) -> float:
        c = by_scan.get(p, {}).get(rid)
        return c.mention_count / totals[p] if c and totals[p] else 0.0

    def score(rid: str, i: int) -> tuple[float, float, float]:
        """(burst, z, baseline mean) of theme rid at periods[i]."""
        p = periods[i]
        baseline = [share(rid, q) for q in periods[max(0, i - BASELINE_SCANS):i]]
        if not baseline:
            return 0.0, 0.0, 0.0
        mu = mean(baseline)
        z = (share(rid, p) - mu) / max(pstdev(baseline), SD_FLOOR)
        c = by_scan.get(p, {}).get(rid)
        n = c.mention_count if c else 0
        h = 0.0
        if c:
            counts = [v for v in _source_counts(c).values() if v > 0]
            total = sum(counts)
            h = -sum(v / total * math.log(v / total) for v in counts) / math.log(5) if total else 0.0
        return max(0.0, z) * (1 + h) * math.log(1 + n), z, mu

    themes: dict[str, dict] = {}
    for rid in set(radar_of.values()) - absorbed:
        seen = [p for p in periods if rid in by_scan.get(p, {})]
        last_i = len(periods) - 1
        burst, z, mu = score(rid, last_i)
        if seen[0] == periods[-1]:
            flag = "new"
        elif burst >= ACCELERATING_AT:
            flag = "accelerating"
        elif burst >= RISING_AT:
            flag = "rising"
        elif z <= COOLING_Z:
            flag = "cooling"
        else:
            flag = "steady"
        history = []
        for i in range(max(0, len(periods) - HISTORY_SCANS), len(periods)):
            c = by_scan.get(periods[i], {}).get(rid)
            history.append({
                "period": periods[i], "mention_count": c.mention_count if c else 0,
                "share": round(share(rid, periods[i]), 4), "burst": round(score(rid, i)[0], 4),
            })
        themes[rid] = {
            "flag": flag, "burst": round(burst, 4), "share": round(share(rid, periods[-1]), 4),
            "baseline_share": round(mu, 4), "first_period": seen[0], "last_period": seen[-1],
            "last": by_scan[seen[-1]][rid], "history": history,
        }
    return themes, radar_of, absorbed


def eligible_cluster_ids(topic_store: TopicStateStore, period: str) -> set[str]:
    """Clusters of `period` to synthesize: every BIRTH, plus each accelerating or rising theme's cluster when the
    theme has no candidate yet."""
    periods = [p for p in topic_store.list_periods() if p <= period]
    themes, radar_of, _ = _themes(topic_store, periods)
    with_candidate = {radar_of[c.cluster_id] for c in topic_store.list_candidates() if c.cluster_id in radar_of}
    births = {e.cluster_id for e in topic_store.load_lineage_events(period) if e.transition == LineageTransition.BIRTH}
    eligible = set()
    for c in topic_store.load_period(period) or []:
        rid = radar_of[c.cluster_id]
        growing = rid in themes and themes[rid]["flag"] in ("accelerating", "rising") and rid not in with_candidate
        if c.cluster_id in births or growing:
            eligible.add(c.cluster_id)
    return eligible


def build_radar(topic_store: TopicStateStore, run_store: RunStore) -> dict:
    periods = topic_store.list_periods()
    if not periods:
        return {"periods": [], "themes": [], "companies": []}
    themes, radar_of, _ = _themes(topic_store, periods)
    shown = periods[-HISTORY_SCANS:]

    latest: dict[str, EmergingThemeCandidate] = {}
    for cand in topic_store.list_candidates():
        rid = radar_of.get(cand.cluster_id)
        if rid is not None and (rid not in latest or cand.created_at >= latest[rid].created_at):
            latest[rid] = cand

    rows = []
    for rid, t in themes.items():
        cand = latest.get(rid)
        status = "none"
        if cand is not None:
            decisions = {d["theme_id"]: d for d in run_store.read_decisions(cand.run_id)}
            decision = decisions.get(cand.theme_id)
            status = _DECISION_STATUS.get(decision["action"], cand.status.value) if decision else cand.status.value
        if t["last_period"] < shown[0] and status not in ("candidate", "under_review"):
            continue
        last: TopicCluster = t["last"]
        counts = _source_counts(last)
        rows.append({
            "radar_id": rid,
            "label": cand.theme_name if cand else last.representative_label,
            "flag": t["flag"], "burst": t["burst"], "share": t["share"], "baseline_share": t["baseline_share"],
            "first_period": t["first_period"], "last_period": t["last_period"],
            "status": status,
            "candidate": {"run_id": cand.run_id, "theme_id": cand.theme_id} if cand else None,
            "source_mix": {k: counts.get(k, 0) for k in SOURCE_CATEGORIES},
            "company_count": len(last.company_ids),
            "labels": list(dict.fromkeys(last.member_labels))[:5],
            "history": t["history"],
        })
    rows.sort(key=lambda r: (_FLAG_ORDER.index(r["flag"]), -r["burst"], r["radar_id"]))
    return {"periods": shown, "themes": rows, "companies": []}
