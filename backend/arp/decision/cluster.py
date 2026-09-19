from __future__ import annotations

import statistics

from arp.decision.normalise import spearman
from arp.decision.roles import pretty, tokens

_STOP = {
    "the", "of", "and", "per", "pct", "percent", "score", "flag", "eur", "meur", "usd",
    "total", "share", "rate", "index", "level", "co2e", "tco2e", "0", "1", "2", "3", "5", "100",
}


def correlation_matrix(normalised: dict[str, list[float | None]]) -> dict[tuple[str, str], float]:
    columns = list(normalised)
    out: dict[tuple[str, str], float] = {}
    for i, a in enumerate(columns):
        for b in columns[i + 1 :]:
            out[_key(a, b)] = spearman(normalised[a], normalised[b])
    return out


def _key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


def cluster_criteria(columns: list[str], correlations: dict[tuple[str, str], float], threshold: float) -> list[list[str]]:
    """Complete-linkage agglomerative clustering on rank correlation.

    Complete, not single, linkage: every pair inside a dimension must
    clear the threshold. Under single linkage a chain of moderately
    correlated indicators merges into one dimension whose members may be
    entirely unrelated to each other, which quietly collapses a framework
    into a single weight.
    """
    clusters = [[c] for c in columns]
    while len(clusters) > 1:
        best, bi, bj = -2.0, -1, -1
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                link = min(correlations.get(_key(a, b), 0.0) for a in clusters[i] for b in clusters[j])
                if link > best:
                    best, bi, bj = link, i, j
        if best < threshold:
            break
        clusters[bi] = clusters[bi] + clusters[bj]
        clusters.pop(bj)
    return clusters


def name_cluster(members: list[str], correlations: dict[tuple[str, str], float]) -> str:
    """The tokens every member shares, if any; otherwise the medoid -- the
    member most typical of the rest -- which beats naming a group after
    whichever column happened to sort first."""
    if len(members) == 1:
        return pretty(members[0])
    sets = [set(t for t in tokens(m) if t not in _STOP and not t.isdigit()) for m in members]
    common = set.intersection(*sets) if sets else set()
    if common:
        ordered = [t for t in tokens(members[0]) if t in common]
        return " ".join(t.capitalize() for t in ordered)
    best_member, best_mean = members[0], float("-inf")
    for m in members:
        others = [correlations.get(_key(m, o), 0.0) for o in members if o != m]
        avg = statistics.fmean(others) if others else 0.0
        if avg > best_mean:
            best_member, best_mean = m, avg
    return " ".join(pretty(best_member).split()[:2]) + " group"


def cluster_range(members: list[str], correlations: dict[tuple[str, str], float]) -> tuple[float, float]:
    values = [correlations.get(_key(a, b), 0.0) for i, a in enumerate(members) for b in members[i + 1 :]]
    return (min(values), max(values)) if values else (0.0, 0.0)
