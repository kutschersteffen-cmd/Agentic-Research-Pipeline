from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from arp.api.auth import Principal, require_role
from arp.api.deps import blob_store_dep, get_document_content_store, get_run_store, publish_store_dep
from arp.publish.facts import ConcurrentPublish, PublishStore, public_release, ts_now
from arp.publish.reader import as_of_bound, facts_as_of, read_events
from arp.publish.release import AlreadyWithdrawn, WithdrawalError, publish_run, withdraw
from arp.storage.run_store import RunStore

router = APIRouter(prefix="/api/publish", tags=["publish"])
_approver = require_role("approver")
CONCURRENT = "another publish changed these facts first; retry. Earlier documents of this run may already be published."


class WithdrawRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    reason: str = Field(min_length=1, max_length=2000)


@router.post("/runs/{run_id}")
def publish(
    run_id: str,
    principal: Principal = Depends(_approver),
    store: PublishStore = Depends(publish_store_dep),
    run_store: RunStore = Depends(get_run_store),
    blob_store=Depends(blob_store_dep),
    content_store=Depends(get_document_content_store),
) -> dict:
    if run_store.load_manifest(run_id) is None:
        raise HTTPException(404, f"unknown run {run_id}")
    try:
        result = publish_run(
            store, run_store, run_id, principal=principal, blob_store=blob_store, content_store=content_store
        )
    except ConcurrentPublish:
        raise HTTPException(409, CONCURRENT) from None
    return {
        "releases": [public_release(r) for r in result.releases],
        "reconfirmed": result.reconfirmed,
        "blocked": result.blocked,
        "skipped": [asdict(s) for s in result.skipped],
    }


@router.get("/releases")
def releases(
    doc_id: str | None = None, run_id: str | None = None, store: PublishStore = Depends(publish_store_dep)
) -> dict:
    return {"releases": [public_release(r) for r in store.list_releases(doc_id=doc_id, run_id=run_id)]}


@router.post("/releases/{release_id}/withdraw")
def withdraw_release(
    release_id: str,
    req: WithdrawRequest,
    principal: Principal = Depends(_approver),
    store: PublishStore = Depends(publish_store_dep),
) -> dict:
    try:
        restored = withdraw(store, release_id, reason=req.reason, principal=principal)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None
    except (AlreadyWithdrawn, ConcurrentPublish) as exc:
        raise HTTPException(409, str(exc) if isinstance(exc, AlreadyWithdrawn) else CONCURRENT) from None
    except WithdrawalError as exc:
        raise HTTPException(422, str(exc)) from None
    return {"restored": [f.model_dump(mode="json") for f in restored]}


@router.get("/facts")
def facts(
    as_of: str | None = None,
    issuer_key: str | None = None,
    field_id: str | None = None,
    store: PublishStore = Depends(publish_store_dep),
) -> dict:
    try:
        bound = as_of_bound(as_of or ts_now())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    rows = facts_as_of(store, bound, issuer_key=issuer_key, field_id=field_id)
    return {"as_of": bound, "facts": [f.model_dump(mode="json") for f in rows]}


@router.get("/facts/{fact_id}/lineage")
def lineage(fact_id: str, store: PublishStore = Depends(publish_store_dep)) -> dict:
    found = store.lineage(fact_id)
    if found is None:
        raise HTTPException(404, f"unknown fact {fact_id}")
    found.pop("storage_uri", None)  # a server path; clients use content_key / doc_id
    return found


@router.get("/versions")
def versions(
    issuer_key: str, field_id: str, period_end: str, basis: str = "", store: PublishStore = Depends(publish_store_dep)
) -> dict:
    return {"versions": [f.model_dump(mode="json") for f in store.versions((issuer_key, field_id, period_end, basis))]}


@router.get("/events")
def events(
    after_id: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=500),
    store: PublishStore = Depends(publish_store_dep),
) -> dict:
    return {"events": [e.model_dump(mode="json") for e in read_events(store, after_id=after_id, limit=limit)]}
