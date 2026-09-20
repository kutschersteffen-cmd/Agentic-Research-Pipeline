from __future__ import annotations

from arp.schemas.results_diff import MatchDiffEntry, ResultsDiff
from arp.schemas.thematic import CompanyMatch

_DEFAULT_CONFIDENCE_DELTA_THRESHOLD = 0.1


def _key(match: CompanyMatch) -> str:
    return f"{match.company_id}:{match.activity_id}"


def diff_theme_results(
    run_id_a: str,
    run_id_b: str,
    matches_a: list[CompanyMatch],
    matches_b: list[CompanyMatch],
    *,
    confidence_delta_threshold: float = _DEFAULT_CONFIDENCE_DELTA_THRESHOLD,
) -> ResultsDiff:
    """Deterministic diff of two theme runs' results, keyed by
    '{company_id}:{activity_id}' -- an exact key, unlike
    taxonomy_sources/compare.py's fuzzy LLM-matched activity pairs, so no
    LLM call is needed here at all.
    """
    by_key_a = {_key(m): m for m in matches_a}
    by_key_b = {_key(m): m for m in matches_b}
    keys_a, keys_b = set(by_key_a), set(by_key_b)

    added = sorted(keys_b - keys_a)
    dropped = sorted(keys_a - keys_b)
    common = keys_a & keys_b

    verdict_changed: list[MatchDiffEntry] = []
    confidence_changed: list[MatchDiffEntry] = []
    unchanged_count = 0

    for key in sorted(common):
        a, b = by_key_a[key], by_key_b[key]
        if a.verdict != b.verdict:
            verdict_changed.append(
                MatchDiffEntry(
                    key=key, company_id=a.company_id, activity_id=a.activity_id, change="verdict_changed",
                    old_verdict=a.verdict, new_verdict=b.verdict, old_confidence=a.confidence, new_confidence=b.confidence,
                )
            )
        elif abs(a.confidence - b.confidence) > confidence_delta_threshold:
            confidence_changed.append(
                MatchDiffEntry(
                    key=key, company_id=a.company_id, activity_id=a.activity_id, change="confidence_changed",
                    old_verdict=a.verdict, new_verdict=b.verdict, old_confidence=a.confidence, new_confidence=b.confidence,
                )
            )
        else:
            unchanged_count += 1

    return ResultsDiff(
        run_id_a=run_id_a,
        run_id_b=run_id_b,
        added=added,
        dropped=dropped,
        verdict_changed=verdict_changed,
        confidence_changed=confidence_changed,
        unchanged_count=unchanged_count,
    )
