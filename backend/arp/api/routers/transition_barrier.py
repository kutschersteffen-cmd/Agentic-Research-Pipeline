from __future__ import annotations

import asyncio
import hashlib
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel

from arp.api.auth import Principal, current_user
from arp.api.deps import blob_store_dep, get_run_store, settings_dep
from arp.api.review_endpoints import (
    ReviewDecisionRequest,
    get_review_decisions,
    get_review_history,
    get_review_queue,
    submit_review,
)
from arp.config import Settings
from arp.schemas.transition_barrier import (
    BarrierCriterion,
    BarrierScore,
    Pillar,
    Region,
    RegistrySource,
    StalenessReport,
)
from arp.storage.run_store import RunStore
from arp.transition_barrier import store
from arp.transition_barrier.dataset import (
    build_matrix,
    data_dir,
    filter_scores,
    load_criteria,
    load_source_registry,
    rating_distribution,
    sectors,
    sources_for_criterion,
)
from arp.transition_barrier.facts import FactRefused, UploadMeta, check_fact
from arp.transition_barrier.refresh.pipeline import (
    RefreshDisabledError,
    create_refresh_run,
    execute_refresh_run,
)
from arp.transition_barrier.refresh.router import coverage_summary
from arp.transition_barrier.rule_book import load_rule_book
from arp.transition_barrier.staleness import build_staleness_report, staleness_days

router = APIRouter(prefix="/api/transition-barrier", tags=["transition-barrier"])


@router.get("/criteria", response_model=list[BarrierCriterion])
def list_criteria() -> list[BarrierCriterion]:
    """The 35 criteria (9 sectors x 3 constraint pillars) with their metrics,
    H/M/L rubrics and primary sources. Static reference data, not per-run state.
    """
    return load_criteria()


@router.get("/criteria/{code}")
def get_criterion(code: str) -> dict:
    """One criterion, joined with its three regional ratings and its
    deduplicated source records -- what the UI detail drawer needs in one call.
    """
    criterion = next((c for c in load_criteria() if c.code == code), None)
    if criterion is None:
        raise HTTPException(404, f"Unknown criterion code: {code}")
    return {
        "criterion": criterion.model_dump(mode="json"),
        "scores": [s.model_dump(mode="json") for s in filter_scores(code=code)],
        "sources": [s.model_dump(mode="json") for s in sources_for_criterion(code)],
    }


@router.get("/scores", response_model=list[BarrierScore])
def list_scores(
    sector: str | None = None,
    region: Region | None = None,
    pillar: Pillar | None = None,
    rating: str | None = None,
) -> list[BarrierScore]:
    """The 105 matrix cells, optionally filtered. All filters are ANDed."""
    return filter_scores(sector=sector, region=region, pillar=pillar, rating=rating)


@router.get("/matrix")
def get_matrix(settings: Settings = Depends(settings_dep)) -> dict:
    """The full 35x3 grid plus the summary counts the heatmap header shows."""
    grid = build_matrix()
    threshold = settings.transition_barrier_staleness_days
    return {
        "sectors": sectors(),
        "regions": [r.value for r in Region],
        "pillars": [p.value for p in Pillar],
        "criteria": [c.model_dump(mode="json") for c in load_criteria()],
        "cells": {
            code: {
                region: {
                    **score.model_dump(mode="json"),
                    "staleness_days": staleness_days(score),
                    "stale": staleness_days(score) >= threshold,
                }
                for region, score in by_region.items()
            }
            for code, by_region in grid.items()
        },
        "distribution": {
            "overall": rating_distribution(),
            **{r.value: rating_distribution(r) for r in Region},
        },
    }


@router.get("/sources", response_model=list[RegistrySource])
def list_sources() -> list[RegistrySource]:
    """The 94 deduplicated sources behind the matrix."""
    return load_source_registry()


@router.get("/staleness", response_model=StalenessReport)
def get_staleness(settings: Settings = Depends(settings_dep)) -> StalenessReport:
    """Which cells are overdue for re-verification. Independent of confidence."""
    return build_staleness_report(threshold_days=settings.transition_barrier_staleness_days)


@router.get("/refresh/coverage")
def get_refresh_coverage() -> dict:
    """How much of the registry the refresh pipeline can actually automate --
    an honest inventory, including the sources that remain manual.
    """
    return {**coverage_summary(), "enabled_patterns": ["legal_regulatory_text"]}


@router.post("/refresh/runs")
async def start_refresh_run(
    settings: Settings = Depends(settings_dep),
    run_store: RunStore = Depends(get_run_store),
) -> dict:
    """Re-check the EUR-Lex legal sources against the recorded ratings.

    Rating changes are never applied here -- they land in the run's review
    queue for a human to accept or reject.
    """
    try:
        run_id = create_refresh_run(settings, run_store)
    except RefreshDisabledError as exc:
        raise HTTPException(409, str(exc)) from exc

    asyncio.create_task(execute_refresh_run(run_id, settings=settings, run_store=run_store))
    return {"run_id": run_id, "source_count": coverage_summary()["automatable"]}


@router.get("/refresh/runs/{run_id}")
def get_refresh_run(run_id: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    manifest = run_store.load_manifest(run_id)
    if manifest is None:
        raise HTTPException(404, "Run not found")
    return manifest.model_dump(mode="json")


@router.get("/refresh/runs/{run_id}/results")
def get_refresh_results(
    run_id: str, offset: int = 0, limit: int = 500, run_store: RunStore = Depends(get_run_store)
) -> dict:
    rows = run_store.read_results(run_id)
    return {"total": len(rows), "results": rows[offset : offset + limit]}


@router.get("/refresh/runs/{run_id}/review-queue")
def get_refresh_review_queue(run_id: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    return get_review_queue(run_store, run_id)


@router.get("/refresh/runs/{run_id}/review-decisions")
def get_refresh_review_decisions(run_id: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    return get_review_decisions(run_store, run_id)


@router.get("/refresh/runs/{run_id}/review-history")
def get_refresh_review_history(run_id: str, item_key: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    return get_review_history(run_store, run_id, item_key)


@router.post("/refresh/runs/{run_id}/review")
def submit_refresh_review(
    run_id: str, req: ReviewDecisionRequest, run_store: RunStore = Depends(get_run_store),
    principal: Principal = Depends(current_user),
) -> dict:
    return submit_review(
        run_store,
        run_id,
        item_key=req.item_key,
        decision=req.decision,
        principal=principal,
        edited_value=req.edited_value,
        comment=req.comment,
    )


def _cell(code: str, region: str):
    """The criterion's rules and registered sources, or 404 for a cell that doesn't exist."""
    criterion = next((c for c in load_criteria() if c.code == code), None)
    if criterion is None or region not in {r.value for r in Region}:
        raise HTTPException(404, f"Unknown cell {code} / {region}")
    return load_rule_book(data_dir())[0].criteria[code], criterion.primary_sources


def _iso(text: str) -> date | None:
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        raise HTTPException(422, "As-of date must be YYYY-MM-DD.") from None


@router.post("/cells/{code}/{region}/facts", status_code=201)
def add_fact(
    code: str,
    region: str,
    fact: str = Form(...),
    value: str = Form(...),
    unit: str = Form(""),
    quote: str = Form(""),
    page: int | None = Form(None),
    locator: str = Form(""),
    source_key: str = Form(""),
    file: UploadFile | None = File(None),
    title: str = Form(""),
    publisher: str = Form(""),
    as_of: str = Form(""),
    tier: str = Form(""),
    user: Principal = Depends(current_user),
    settings: Settings = Depends(settings_dep),
    blobs=Depends(blob_store_dep),
) -> dict:
    """An analyst enters a fact for sources code cannot read: from a registered source, or with an uploaded PDF."""
    rules, registry = _cell(code, region)
    fact_def = next((f for f in rules.facts if f.id == fact), None)
    if fact_def is None:
        raise HTTPException(422, f"Unknown fact {fact}")
    if fact_def.type is None:
        raise HTTPException(422, f"{fact} is computed and can't be entered")
    data = file.file.read(settings.max_upload_bytes + 1) if file and file.filename else None
    if data is not None and len(data) > settings.max_upload_bytes:
        raise HTTPException(413, f"File is larger than the {settings.max_upload_bytes // 1_000_000} MB upload limit.")
    if data is not None and not data.startswith(b"%PDF-"):
        raise HTTPException(422, "Upload a PDF document.")
    upload = None if data is None else UploadMeta(title.strip(), publisher.strip(), _iso(as_of.strip()), tier.strip())
    try:
        checked = check_fact(fact_def, value=value, unit=unit.strip() or None, quote=quote, page=page, upload=upload, pdf=data)
        if upload is None and source_key not in {s.key for s in registry}:
            raise FactRefused(422, f"Unknown source {source_key}" if source_key else "Name a registered source or upload a document.")
        document_id = None
        if upload is not None:
            content_key = hashlib.sha256(data).hexdigest()
            blobs.put(content_key, data)
            document_id = store.add_document(
                title=upload.title, publisher=upload.publisher, as_of=upload.as_of, tier=upload.tier, filename=file.filename,
                content_key=content_key, page_texts=checked.pages, uploaded_by=user.user_id,
            )
        stored = checked.value.isoformat() if isinstance(checked.value, date) else checked.value
        fact_id = store.add_fact(
            code=code, region=region, fact=fact, value=stored, unit=fact_def.unit if fact_def.type == "number" else None,
            quote=quote, page=checked.page, locator=locator or None, source_key=None if upload else source_key,
            document_id=document_id, entered_by=user.user_id, machine_checked=checked.machine_checked,
        )
    except FactRefused as exc:
        raise HTTPException(exc.status, exc.message) from None
    return {"id": fact_id, "page": checked.page, "machine_checked": checked.machine_checked}


class ChoiceRequest(BaseModel):
    fact: str
    value_id: str | int
    reason: str = ""


@router.post("/cells/{code}/{region}/choices", status_code=201)
def add_choice(code: str, region: str, req: ChoiceRequest, user: Principal = Depends(current_user)) -> dict:
    """For a conflict, the analyst picks which value counts, with a written reason."""
    rules, _ = _cell(code, region)
    if req.fact not in {f.id for f in rules.facts if f.type}:
        raise HTTPException(422, f"Unknown fact {req.fact}")
    try:
        choice_id = store.add_choice(
            code=code, region=region, fact=req.fact, value_id=str(req.value_id), reason=req.reason, chosen_by=user.user_id
        )
    except FactRefused as exc:
        raise HTTPException(exc.status, exc.message) from None
    return {"id": choice_id}


@router.get("/documents/{doc_id}")
def get_document(doc_id: int, blobs=Depends(blob_store_dep)) -> Response:
    found = store.document(doc_id, blobs)
    if found is None:
        raise HTTPException(404, "Document not found")
    _, data = found  # the uploaded name is client-supplied: it stays in the database, never in a header
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="document-{doc_id}.pdf"'})
