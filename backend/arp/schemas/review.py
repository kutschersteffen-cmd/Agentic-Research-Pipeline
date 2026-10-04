from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from arp.schemas.common import Citation, now_iso


class ReasonCode(StrEnum):
    NOT_GROUNDED = "not_grounded"
    VERIFIER_DISAGREES = "verifier_disagrees"
    CONFLICT = "conflict"
    LOW_CONFIDENCE = "low_confidence"
    CHECK_FAILED = "check_failed"
    MATCH_AMBIGUOUS = "match_ambiguous"
    NOT_APPLICABLE_BY_RULE = "not_applicable_by_rule"


class DecisionKind(StrEnum):
    APPROVE = "approve"
    CORRECT = "correct"
    REJECT = "reject"
    ESCALATE = "escalate"


class DecisionReason(StrEnum):
    CONFIRMED = "confirmed"
    WRONG_VALUE = "wrong_value"
    WRONG_UNIT_OR_SCALE = "wrong_unit_or_scale"
    WRONG_PERIOD = "wrong_period"
    WRONG_ENTITY = "wrong_entity"
    NOT_DISCLOSED = "not_disclosed"
    BAD_SOURCE = "bad_source"
    NEEDS_EXPERT = "needs_expert"
    OTHER = "other"


class ReviewDecision(BaseModel):
    """A stored review_decisions.jsonl row. `reviewer` (name) and `user_id` are internal."""

    item_key: str
    decision: DecisionKind
    reason_code: DecisionReason
    reviewer: str
    user_id: str
    role: str
    corrected_value: dict | None = None
    correction_citation: Citation | None = None
    snapshot_id: str
    comment: str | None = None
    step: Literal["first", "second", "resolution"]
    second_required: bool = False
    second_reasons: list[str] = []
    decided_at: str = Field(default_factory=now_iso)


def field_item_key(issuer_key: str, field_id: str, period: str = "unspecified") -> str:
    return f"{issuer_key}:{field_id}:{period}"


def period_key(f) -> str:
    """`period_end` of an ExtractedField (model or dict), else "unspecified"."""
    end = f.get("period_end") if isinstance(f, dict) else f.period_end
    return end or "unspecified"


def held_item_key(company_id: str, doc_id: str) -> str:
    return f"held:{company_id}:{doc_id}"


def sector_item_key(company_id: str) -> str:
    return f"isic:{company_id}"


class ReviewItemKind(StrEnum):
    VALUE = "value"
    SECTOR_CODE = "sector_code"
    IDENTITY = "identity"
    QUARANTINED_DOCUMENT = "quarantined_document"
    RESTATEMENT_CANDIDATE = "restatement_candidate"
    OTHER = "other"


class ReviewItem(BaseModel):
    item_key: str
    kind: ReviewItemKind
    run_id: str
    run_type: str
    payload: dict
    state: str = "pending"
    escalated: bool = False
    high_risk: bool = False
    decision: dict | None = None  # a public_decision; None when blind or undecided
