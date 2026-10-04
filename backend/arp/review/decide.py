"""One reviewer decision on one workbench item (E53, E54): kind rules, a server-grounded
correction citation, the second-reviewer rules, under the run lock and the context etag."""

from __future__ import annotations

import math
from hashlib import sha256
from typing import TYPE_CHECKING

from arp.api.auth import ROLE_RANK
from arp.checks.numeric import NUMERIC_TYPES, candidates, parse_number
from arp.config import Settings
from arp.extraction.history import PriorValue, RunHistory
from arp.grounding import ground_citations
from arp.orchestration.review_queue import FINAL_STATES, agrees, append_decision, same_value
from arp.review.context import _state, _text, build_context, write_snapshot
from arp.review.items import get_item
from arp.schemas.common import Citation, SourceDocument
from arp.schemas.review import ItemDecisionRequest, ReviewDecision
from arp.storage.document_store import DocumentContentStore
from arp.storage.run_store import RunStore

if TYPE_CHECKING:
    from arp.api.auth import Principal

_ALL = {"approve", "correct", "reject", "escalate"}
ALLOWED = {
    "value": _ALL, "restatement_candidate": _ALL, "identity": _ALL, "sector_code": _ALL,
    "quarantined_document": {"approve", "reject", "escalate"},
}
CORRECTED_KEYS = {
    "value": {"value", "unit", "period_end"},
    "restatement_candidate": {"value", "unit", "period_end"},
    "identity": {"value", "resolved_website", "resolved_cik"},
    "sector_code": {"isic_code"},
}
_REQUIRED_KEY = {"value": "value", "restatement_candidate": "value", "sector_code": "isic_code"}


class DecisionError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status, self.message = status, message


def sampled(item_key: str, rate: float) -> bool:
    return int(sha256(item_key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF < rate


def second_review_reasons(
    decision: str, *, kind: str, item_key: str, high_risk: bool, first_audit_passed: bool | None,
    current_value, corrected_value, prior: PriorValue | None, sample_rate: float, changes_final: bool = False,
) -> list[str]:
    """`changes_final`: the decision would overturn this item's own final outcome in this run."""
    if decision == "escalate":
        return []
    changes_prior = prior is not None and (
        decision == "reject"
        or (decision == "approve" and not same_value(prior.value, current_value))
        or (decision == "correct" and not same_value(prior.value, corrected_value["value"]))
    )
    rules = [
        ("correction", decision == "correct"),
        ("high_risk", high_risk),
        ("published_change", kind == "restatement_candidate" or changes_prior or changes_final),
        ("first_audit_pending", first_audit_passed is False),
        ("sample", decision == "approve" and sampled(item_key, sample_rate)),
    ]
    return [name for name, hit in rules if hit]


def ground_correction(
    citation: Citation, bundle: dict, *, content_store: DocumentContentStore | None, data_type: str | None, corrected_value,
    fuzzy_threshold: float = 0.92,
) -> Citation:
    """Grounds the reviewer's citation against the stored text of one of the item's documents.
    Whatever offsets or span the client sent are discarded by `ground_citations`."""
    doc = next((d for d in bundle["documents"] if d["doc_id"] == citation.doc_id), None)
    if doc is None:
        raise DecisionError(422, "correction citation must cite one of this item's documents")
    text = _text(content_store, doc)
    if text is None:
        raise DecisionError(422, "source text unavailable")
    source = SourceDocument(
        doc_id=doc["doc_id"], company_id=doc.get("company_id") or "", doc_type=doc.get("doc_type") or citation.doc_type,
        title=doc.get("title") or "", full_text=text.full_text, page_breaks=text.page_breaks,
        content_key=doc["content_key"], parser_version=doc["parser_version"],
    )
    [grounded] = ground_citations([citation], {source.doc_id: source}, fuzzy_threshold)
    if not grounded.grounded:
        raise DecisionError(422, "correction citation is not in the source text")
    if data_type in NUMERIC_TYPES:
        want = parse_number(str(corrected_value["value"]))
        if want is None or not any(math.isclose(abs(want), abs(n), rel_tol=1e-9) for n in candidates(grounded.span_text)):
            raise DecisionError(422, "corrected number not in the cited text")
    return grounded


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _check_kind(kind: str, req: ItemDecisionRequest, principal: Principal) -> None:
    if req.decision not in ALLOWED[kind]:
        raise DecisionError(422, f"{req.decision} is not a decision for a {kind} item")
    if kind == "quarantined_document" and req.decision == "approve" and ROLE_RANK[principal.role] < ROLE_RANK["approver"]:
        raise DecisionError(403, "releasing a held document needs an approver")
    if req.decision != "correct":
        return
    keys = set(req.corrected_value)
    if keys - CORRECTED_KEYS[kind]:
        raise DecisionError(422, f"corrected_value may only hold {sorted(CORRECTED_KEYS[kind])}")
    if kind in _REQUIRED_KEY and _REQUIRED_KEY[kind] not in keys:
        raise DecisionError(422, f"corrected_value needs {_REQUIRED_KEY[kind]!r}")
    if kind in ("value", "restatement_candidate") and req.correction_citation is None:
        raise DecisionError(422, "a correction needs a citation")
    if kind == "identity" and not (req.corrected_value.get("resolved_website") or req.corrected_value.get("resolved_cik")):
        raise DecisionError(422, "an identity correction needs resolved_website or resolved_cik")
    if kind in ("identity", "sector_code") and not (req.comment or "").strip():
        raise DecisionError(422, "a correction needs a comment naming its source")


def _step(s, req: ItemDecisionRequest, principal: Principal) -> str:
    approver = ROLE_RANK[principal.role] >= ROLE_RANK["approver"]
    if s.state == "first_done":
        if principal.user_id == s.first.get("user_id"):
            raise DecisionError(409, "second review must be a different person")
        return "second"
    if s.state == "disagreed":
        if not approver:
            raise DecisionError(403, "a disagreement is resolved by an approver")
        if principal.user_id in {s.first.get("user_id"), s.second.get("user_id")}:
            raise DecisionError(409, "the resolver must not be a reviewer of this item")
        if req.decision == "escalate":
            raise DecisionError(422, "a disagreement is resolved, not escalated")
        return "resolution"
    if s.state == "pending" and s.escalated and not approver:
        raise DecisionError(403, "an escalated item is decided by an approver")
    if s.state in FINAL_STATES and s.effective.get("step") == "resolution" and not approver:
        raise DecisionError(403, "an item resolved by an approver is decided again by an approver")
    return "first"  # pending, second_done or final: a new round


def decide(
    run_store: RunStore, run_id: str, item_key: str, req: ItemDecisionRequest, principal: Principal, *,
    settings: Settings, content_store: DocumentContentStore | None,
) -> dict:
    with run_store.lock(run_id):
        item = get_item(run_store, run_id, item_key, principal)
        if item is None:
            raise DecisionError(404, "Review item not found")
        kind = item.kind.value
        if kind == "other":
            raise DecisionError(400, "decide this item through its run's review endpoint")
        _check_kind(kind, req, principal)
        s = _state(run_store, run_id, item_key)
        step = _step(s, req, principal)
        bundle = build_context(run_store, run_id, item_key, principal, settings=settings, content_store=content_store)
        if bundle["etag"] != req.context_etag:
            raise DecisionError(409, "this item changed since you loaded it; reload")
        field = bundle["field_definition"] or {}
        current = (bundle["value"] or {}).get("value")
        citation = None
        if req.decision == "correct" and req.correction_citation is not None:
            data_type = field.get("data_type")
            if data_type is None and any(_is_number(v) for v in (current, req.corrected_value.get("value"))):
                data_type = "number"  # no field definition (an old run): judge by the value itself
            citation = ground_correction(
                req.correction_citation, bundle, content_store=content_store, data_type=data_type,
                corrected_value=req.corrected_value, fuzzy_threshold=settings.grounding_fuzzy_threshold,
            )
        reasons: list[str] = []
        if step == "first":
            prior = None
            if kind in ("value", "restatement_candidate"):
                key = item.payload["item_key"] if kind == "restatement_candidate" else item_key
                prior = RunHistory.load(run_store, exclude_run_id=run_id).last_decided(key)
            reasons = second_review_reasons(
                req.decision, kind=kind, item_key=item_key, high_risk=item.high_risk,
                first_audit_passed=field.get("first_audit_passed"), current_value=current,
                corrected_value=req.corrected_value, prior=prior, sample_rate=settings.second_review_sample_rate,
                changes_final=s.state in FINAL_STATES and not agrees(s.effective, req.model_dump()),
            )
        snapshot_id = write_snapshot(run_store, run_id, bundle)
        append_decision(run_store, run_id, ReviewDecision(
            item_key=item_key, decision=req.decision, reason_code=req.reason_code, reviewer=principal.name,
            user_id=principal.user_id, role=principal.role, corrected_value=req.corrected_value,
            correction_citation=citation, snapshot_id=snapshot_id, comment=req.comment, step=step,
            second_required=bool(reasons), second_reasons=reasons,
        ))
        return {"state": _state(run_store, run_id, item_key).state, "snapshot_id": snapshot_id, "second_reasons": reasons}
