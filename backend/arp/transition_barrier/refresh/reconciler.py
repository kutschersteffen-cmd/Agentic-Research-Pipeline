from __future__ import annotations

from dataclasses import dataclass, field

from arp.schemas.transition_barrier import (
    BarrierRefreshFinding,
    BarrierScore,
    Rating,
    RefreshOutcome,
)
from arp.transition_barrier.refresh.eli import EliRef


@dataclass(frozen=True)
class FetchedVersion:
    """What the retriever managed to establish about a legal source right now.

    Deliberately small: this slice answers "did the act change?", not "what
    does the act say". `in_force` is None when the fetch could not determine it
    rather than False, so "unknown" never reads as "repealed".
    """

    source_key: str
    eli: EliRef
    latest_point_in_time: str | None = None
    in_force: bool | None = None
    quote: str = ""
    error: str = ""
    conflicting_versions: list[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return bool(self.error)


def reconcile(
    score: BarrierScore,
    fetched: FetchedVersion,
    *,
    recorded_point_in_time: str | None = None,
) -> BarrierRefreshFinding:
    """Decide what re-checking one source says about one matrix cell.

    The rule this function exists to enforce: a change in the underlying law is
    evidence that a rating *may* need to move, never authority to move it. The
    strongest outcome available is RATING_CHANGE_CANDIDATE, which is advisory
    and carries `proposed_rating` for a human to accept or reject.

    Rating semantics matter for the proposal: H means transition is *more*
    feasible. An act falling out of force removes a regulatory driver, so the
    proposal is a downgrade; that is a suggestion for review, not a conclusion.
    """
    common = {
        "code": score.code,
        "region": score.region,
        "source_key": fetched.source_key,
        "current_rating": score.rating,
        "source_quote": fetched.quote,
    }

    if fetched.failed:
        return BarrierRefreshFinding(
            **common,
            outcome=RefreshOutcome.FETCH_FAILED,
            detail=f"Could not verify {fetched.source_key}: {fetched.error}",
        )

    # Never silently pick a side when sources disagree -- surface both.
    if fetched.conflicting_versions:
        return BarrierRefreshFinding(
            **common,
            outcome=RefreshOutcome.RATING_CHANGE_CANDIDATE,
            proposed_rating=None,
            detail=(
                "Conflicting versions reported for "
                f"{fetched.eli.celex_like}: {', '.join(fetched.conflicting_versions)}. "
                "Both surfaced for human adjudication; no rating proposed."
            ),
        )

    if fetched.in_force is False:
        proposed = Rating.MODERATE if score.rating is Rating.HIGH else Rating.LOW
        return BarrierRefreshFinding(
            **common,
            outcome=RefreshOutcome.RATING_CHANGE_CANDIDATE,
            proposed_rating=proposed,
            detail=(
                f"{fetched.eli.celex_like} is reported no longer in force. The regulatory driver behind "
                f"rating {score.rating.value} may have been removed. Requires human confirmation."
            ),
        )

    changed = (
        recorded_point_in_time is not None
        and fetched.latest_point_in_time is not None
        and fetched.latest_point_in_time != recorded_point_in_time
    )
    if changed:
        return BarrierRefreshFinding(
            **common,
            outcome=RefreshOutcome.EVIDENCE_DRIFT,
            detail=(
                f"{fetched.eli.celex_like} has a newer consolidated version "
                f"({recorded_point_in_time} -> {fetched.latest_point_in_time}). Rating unchanged; "
                "evidence text and last_verified may be refreshed."
            ),
        )

    return BarrierRefreshFinding(
        **common,
        outcome=RefreshOutcome.UNCHANGED,
        detail=f"{fetched.eli.celex_like} unchanged since last verification.",
    )


def is_auto_applicable(finding: BarrierRefreshFinding) -> bool:
    """Whether this finding may be written back without human approval.

    The exact inverse of BarrierRefreshFinding.needs_review, which owns the
    rule -- so the pipeline's "queue this" decision and the CLI's "how many
    need a human" count can never drift apart.
    """
    return not finding.needs_review


def partition_findings(
    findings: list[BarrierRefreshFinding],
) -> tuple[list[BarrierRefreshFinding], list[BarrierRefreshFinding]]:
    """Split into (auto-applicable, needs-human-review)."""
    auto = [f for f in findings if is_auto_applicable(f)]
    review = [f for f in findings if not is_auto_applicable(f)]
    return auto, review
