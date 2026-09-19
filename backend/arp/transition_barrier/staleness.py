from __future__ import annotations

from datetime import date, datetime

from arp.schemas.transition_barrier import BarrierScore, StalenessReport
from arp.transition_barrier.dataset import load_scores

# 18 months. A rating that has not been re-checked in this long is stale
# regardless of how confident the analyst was when they set it.
DEFAULT_STALENESS_DAYS = 548


def _parse(last_verified: str) -> date:
    return datetime.strptime(last_verified[:10], "%Y-%m-%d").date()


def staleness_days(score: BarrierScore, *, now: date | None = None) -> int:
    """Days since this cell was last checked against its sources.

    Deliberately independent of `confidence`: confidence is how sure the analyst
    was about the rating when they set it, staleness is how long ago that was. A
    high-confidence rating from three years ago is stale, not low-confidence,
    and collapsing the two would hide exactly the case this module exists to
    catch -- the 2025 US policy reversals behind MIN-R2 and OGU-R1.
    """
    return ((now or date.today()) - _parse(score.last_verified)).days


def is_stale(score: BarrierScore, *, threshold_days: int = DEFAULT_STALENESS_DAYS, now: date | None = None) -> bool:
    return staleness_days(score, now=now) >= threshold_days


def stale_scores(
    *,
    threshold_days: int = DEFAULT_STALENESS_DAYS,
    now: date | None = None,
    scores: list[BarrierScore] | None = None,
) -> list[BarrierScore]:
    rows = scores if scores is not None else load_scores()
    return [s for s in rows if is_stale(s, threshold_days=threshold_days, now=now)]


def build_staleness_report(
    *,
    threshold_days: int = DEFAULT_STALENESS_DAYS,
    now: date | None = None,
    scores: list[BarrierScore] | None = None,
) -> StalenessReport:
    rows = scores if scores is not None else load_scores()
    stale = stale_scores(threshold_days=threshold_days, now=now, scores=rows)
    return StalenessReport(
        threshold_days=threshold_days,
        total=len(rows),
        stale=len(stale),
        fresh=len(rows) - len(stale),
        stale_codes=sorted({s.code for s in stale}),
    )
