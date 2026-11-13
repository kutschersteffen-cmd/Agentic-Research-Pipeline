"""Vote ledger values (spec "Data model -> Votes")."""

from __future__ import annotations

from enum import StrEnum


class VoteValue(StrEnum):
    FOR = "for"
    AGAINST = "against"
    ABSTAIN = "abstain"
    WITHHOLD = "withhold"
    DO_NOT_VOTE = "do_not_vote"
    ONE_YEAR = "one_year"
    TWO_YEARS = "two_years"
    THREE_YEARS = "three_years"
    OTHER = "other"


def against_management(vote: VoteValue, recommendation: str | None) -> bool | None:
    """Spec "Intake -> Rules": against management, or None when it cannot be told."""
    if recommendation is None or vote in {"abstain", "do_not_vote", "other", "one_year", "two_years", "three_years"}:
        return None
    if vote in {"against", "withhold"}:
        return recommendation == "for"
    return recommendation == "against"  # vote is `for`
