from __future__ import annotations

from enum import StrEnum


class ReasonCode(StrEnum):
    NOT_GROUNDED = "not_grounded"
    VERIFIER_DISAGREES = "verifier_disagrees"
    CONFLICT = "conflict"
    LOW_CONFIDENCE = "low_confidence"
    CHECK_FAILED = "check_failed"
    MATCH_AMBIGUOUS = "match_ambiguous"
    NOT_APPLICABLE_BY_RULE = "not_applicable_by_rule"


def field_item_key(issuer_key: str, field_id: str, period: str = "unspecified") -> str:
    return f"{issuer_key}:{field_id}:{period}"


def period_key(f) -> str:
    """`period_end` of an ExtractedField (model or dict), else "unspecified"."""
    end = f.get("period_end") if isinstance(f, dict) else f.period_end
    return end or "unspecified"
