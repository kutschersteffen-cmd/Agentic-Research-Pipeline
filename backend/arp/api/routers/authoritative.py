"""Authoritative values: publishing a ratified calculate-only framework and reading what it published, as of a time."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from arp.api.auth import Principal, require_role
from arp.api.deps import authoritative_store_dep, get_decision_store
from arp.authoritative.evaluate import check_outputs
from arp.authoritative.store import AuthoritativeStore, StalePublish
from arp.storage.decision_store import DecisionStore

router = APIRouter(prefix="/api/authoritative", tags=["authoritative"])


class PublishAuthoritativeRequest(BaseModel):
    framework_id: str
    version: int | None = None
    dataset_id: str


class PublishAuthoritativeResponse(BaseModel):
    snapshot_id: str


class AuthoritativeValueOut(BaseModel):
    id: int
    framework_id: str
    output: str
    company_id: str
    value: Any = None
    unit: str | None = None
    period_end: str | None = None
    status: str
    reason: str | None = None
    framework_version: int
    dataset_as_of: str | None = None
    snapshot_id: str
    published_by: str
    valid_from: str
    valid_to: str | None = None
    superseded_by: int | None = None
    reconfirmed_at: str | None = None
    derivation: dict | None = None


@router.post("/publish", response_model=PublishAuthoritativeResponse)
def publish(
    req: PublishAuthoritativeRequest,
    store: DecisionStore = Depends(get_decision_store),
    values: AuthoritativeStore = Depends(authoritative_store_dep),
    principal: Principal = Depends(require_role("approver")),
) -> PublishAuthoritativeResponse:
    config = store.get(req.framework_id, req.version) if req.version else (
        store.latest_ratified(req.framework_id) or store.get(req.framework_id)
    )
    if config is None or config.purpose != "authoritative":
        raise HTTPException(404, f"No authoritative framework {req.framework_id}" + (f" v{req.version}" if req.version else ""))
    if not config.ratified:
        raise HTTPException(422, f"{config.name} v{config.version} is not ratified; only a ratified version publishes.")
    dataset = store.get_dataset(req.dataset_id)
    if dataset is None or dataset.source != "source_values":
        raise HTTPException(404, f"No source-values dataset {req.dataset_id}")
    try:
        check_outputs(dataset, config)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    try:
        return PublishAuthoritativeResponse(snapshot_id=values.publish(dataset, config, published_by=principal.name))
    except StalePublish as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/values", response_model=list[AuthoritativeValueOut])
def list_values(
    framework_id: str,
    output: str | None = None,
    company_id: str | None = None,
    as_of: str | None = None,
    values: AuthoritativeStore = Depends(authoritative_store_dep),
) -> list[dict]:
    return values.values(framework_id=framework_id, output=output, company_id=company_id, as_of=as_of)


@router.get("/values/{value_id}", response_model=AuthoritativeValueOut)
def get_value(value_id: int, values: AuthoritativeStore = Depends(authoritative_store_dep)) -> dict:
    found = values.get(value_id)
    if found is None:
        raise HTTPException(404, f"No authoritative value {value_id}")
    return found
