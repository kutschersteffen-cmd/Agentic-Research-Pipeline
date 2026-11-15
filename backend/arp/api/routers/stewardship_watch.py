"""Watch list routes (spec stewardship-commitment-loop, "API"): proof statements, watch topics, objective
results and evidence suggestions. Postgres engagement store only; the file store answers 409."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal, TypeVar

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from arp.api.auth import Principal, current_user
from arp.api.deps import get_engagement_store, get_llm_client, get_registry, settings_dep
from arp.config import Settings
from arp.ingestion.registry import DocumentSourceRegistry
from arp.schemas.common import CompanyRef
from arp.schemas.engagement import (
    Commitment,
    EvidenceSuggestion,
    InfluenceLevel,
    Objective,
    ObjectiveResult,
    WatchTopic,
)
from arp.stewardship.watch_check import ArgusFailed, check_documents, find_commitments, newest
from arp.storage.postgres_engagement_store import PostgresEngagementStore, WatchError, is_iso_date

router = APIRouter(prefix="/api/stewardship", tags=["stewardship"])
ItemKind = Literal["objective", "commitment", "topic"]
T = TypeVar("T")


def watch_store(store=Depends(get_engagement_store)) -> PostgresEngagementStore:
    if not isinstance(store, PostgresEngagementStore):
        raise HTTPException(409, "Watch items need the Postgres engagement store.")
    return store


def _call(fn: Callable[..., T], *args) -> T:
    try:
        return fn(*args)
    except WatchError as exc:
        raise HTTPException(exc.status, exc.detail) from exc


def _required(value: str | None, message: str) -> str:
    if value is None or not value.strip():
        raise HTTPException(422, message)
    return value.strip()


def _date(value: str | None) -> str | None:
    if value and not is_iso_date(value):
        raise HTTPException(422, "target_date must be an ISO date")
    return value or None


class ProofStatementRequest(BaseModel):
    company_id: str
    issue_id: str
    proof_statement: str


@router.post("/watch-items/{item_kind}/{item_id}/proof-statement", response_model=Objective | Commitment | WatchTopic)
def set_proof_statement(
    item_kind: ItemKind, item_id: str, body: ProofStatementRequest, store: PostgresEngagementStore = Depends(watch_store)
):
    text = _required(body.proof_statement, "A proof statement cannot be blank.")
    return _call(store.set_proof_statement, body.company_id, body.issue_id, item_kind, item_id, text)


class WatchCheckRequest(BaseModel):
    company_id: str


class WatchCheckResult(BaseModel):
    documents: int
    suggestions: int
    unclear: int
    skipped: int


@router.post("/watch-items/{item_kind}/{item_id}/check", response_model=WatchCheckResult)
async def check_watch_item(
    item_kind: ItemKind,
    item_id: str,
    body: WatchCheckRequest,
    store: PostgresEngagementStore = Depends(watch_store),
    registry: DocumentSourceRegistry = Depends(get_registry),
    settings: Settings = Depends(settings_dep),
) -> dict:
    item = _call(store.watch_item, body.company_id, item_kind, item_id)
    # name only: no ticker, CIK or LEI, so only local and uploaded documents are read
    company = CompanyRef(company_id=body.company_id, name=store.get(body.company_id).name)
    docs = newest(await registry.fetch_all(company))
    if not docs:
        return {"documents": 0, "suggestions": 0, "unclear": 0, "skipped": 0}
    try:
        return await check_documents(store, get_llm_client(), body.company_id, [item], docs, settings.grounding_fuzzy_threshold)
    except ArgusFailed as exc:
        raise HTTPException(502, "Argus could not check the documents.") from exc


class FindCommitmentsResult(BaseModel):
    suggestions: int
    ungrounded: int
    skipped: int


@router.post("/activities/{activity_id}/find-commitments", response_model=FindCommitmentsResult)
async def find_commitments_in_note(
    activity_id: str, store: PostgresEngagementStore = Depends(watch_store), settings: Settings = Depends(settings_dep)
) -> dict:
    try:
        return await find_commitments(store, get_llm_client(), activity_id, settings.grounding_fuzzy_threshold)
    except WatchError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    except ArgusFailed as exc:
        raise HTTPException(502, "Argus could not read the note.") from exc


class WatchTopicRequest(BaseModel):
    company_id: str
    issue_id: str
    question: str
    proof_statement: str | None = None
    target_date: str | None = None


@router.post("/watch-topics", response_model=WatchTopic)
def add_watch_topic(
    body: WatchTopicRequest,
    store: PostgresEngagementStore = Depends(watch_store),
    principal: Principal = Depends(current_user),
) -> WatchTopic:
    topic = WatchTopic(
        engagement_id=body.issue_id,
        question=_required(body.question, "A question is required."),
        proof_statement=(body.proof_statement or "").strip() or None,
        target_date=_date(body.target_date),
        created_by=principal.name,
    )
    return _call(store.add_watch_topic, body.company_id, body.issue_id, topic)


@router.get("/watch-topics")
def list_watch_topics(company_id: str, store: PostgresEngagementStore = Depends(watch_store)) -> dict[str, list[WatchTopic]]:
    return {"topics": store.list_watch_topics(company_id)}


@router.post("/watch-topics/{topic_id}/close", response_model=WatchTopic)
def close_watch_topic(
    topic_id: str, store: PostgresEngagementStore = Depends(watch_store), principal: Principal = Depends(current_user)
) -> WatchTopic:
    return _call(store.close_watch_topic, topic_id, principal.name)


class ObjectiveResultRequest(BaseModel):
    company_id: str
    issue_id: str
    result: ObjectiveResult
    influence_level: InfluenceLevel | None = None
    outcome: str


@router.post("/objectives/{objective_id}/result", response_model=Objective)
def record_objective_result(
    objective_id: str, body: ObjectiveResultRequest, store: PostgresEngagementStore = Depends(watch_store)
) -> Objective:
    outcome = _required(body.outcome, "An outcome is required.")
    if body.influence_level is None and body.result != ObjectiveResult.ABANDONED:
        raise HTTPException(422, "An influence level is required to close an objective.")
    level = body.influence_level.value if body.influence_level else None
    return _call(store.record_objective_result, body.company_id, body.issue_id, objective_id, body.result.value, level, outcome)


@router.get("/evidence-suggestions")
def list_suggestions(
    company_id: str,
    status: Literal["pending", "confirmed", "rejected"] = "pending",
    store: PostgresEngagementStore = Depends(watch_store),
) -> dict[str, list[EvidenceSuggestion]]:
    return {"suggestions": store.list_suggestions(company_id, status)}


class ConfirmRequest(BaseModel):
    """Only read for a `new_commitment` suggestion: each field overrides what Argus worded."""

    text: str | None = None
    proof_statement: str | None = None
    target_date: str | None = None


@router.post("/evidence-suggestions/{suggestion_id}/confirm", response_model=EvidenceSuggestion)
def confirm_suggestion(
    suggestion_id: str,
    body: ConfirmRequest | None = None,
    store: PostgresEngagementStore = Depends(watch_store),
    principal: Principal = Depends(current_user),
) -> EvidenceSuggestion:
    overrides = {k: v for k, v in (body.model_dump() if body else {}).items() if v is not None and v.strip()}
    return _call(store.confirm_suggestion, suggestion_id, principal.name, overrides)


class RejectRequest(BaseModel):
    reason: str


@router.post("/evidence-suggestions/{suggestion_id}/reject", response_model=EvidenceSuggestion)
def reject_suggestion(
    suggestion_id: str,
    body: RejectRequest,
    store: PostgresEngagementStore = Depends(watch_store),
    principal: Principal = Depends(current_user),
) -> EvidenceSuggestion:
    reason = _required(body.reason, "A reason is required to reject a suggestion.")
    return _call(store.reject_suggestion, suggestion_id, principal.name, reason)
