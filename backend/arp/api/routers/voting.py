from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from arp.api.deps import get_ballot_platform, get_engagement_store, get_registry, get_run_store, settings_dep
from arp.api.review_endpoints import get_review_history, get_review_queue, submit_review
from arp.api.run_scheduling import schedule_llm_run
from arp.config import Settings
from arp.ingestion.registry import DocumentSourceRegistry
from arp.schemas.common import CompanyRef
from arp.storage.engagement_store import EngagementStore
from arp.storage.run_store import RunStore
from arp.universe import load_company_universe
from arp.voting.ballot_casting import BallotPlatform
from arp.voting.pipeline import cast_approved_votes, create_voting_run, execute_voting_run, get_ballots, get_cast_votes

router = APIRouter(prefix="/api/voting", tags=["voting"])


class RunRequest(BaseModel):
    companies: list[CompanyRef] | None = None
    universe_path: str | None = None
    meeting_dates: dict[str, str] = {}


@router.post("/runs")
async def start_voting_run(
    req: RunRequest,
    settings: Settings = Depends(settings_dep),
    run_store: RunStore = Depends(get_run_store),
    registry: DocumentSourceRegistry = Depends(get_registry),
    engagement_store: EngagementStore = Depends(get_engagement_store),
) -> dict:
    companies = req.companies or (load_company_universe(req.universe_path) if req.universe_path else None)
    if not companies:
        raise HTTPException(400, "Provide either `companies` or `universe_path`.")

    def _create() -> str:
        return create_voting_run(companies, settings, run_store)

    async def _run(run_id: str, llm) -> None:
        await execute_voting_run(
            run_id, companies, llm=llm, registry=registry, engagement_store=engagement_store,
            settings=settings, run_store=run_store, meeting_dates=req.meeting_dates, fund_name=settings.fund_name,
        )

    run_id = schedule_llm_run(create_fn=_create, run=_run)
    return {"run_id": run_id, "company_count": len(companies)}


@router.get("/runs/{run_id}")
def get_voting_run(run_id: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    manifest = run_store.load_manifest(run_id)
    if manifest is None:
        raise HTTPException(404, "Run not found")
    return manifest.model_dump(mode="json")


@router.get("/runs/{run_id}/ballots")
def get_voting_ballots(run_id: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    return {"ballots": [b.model_dump(mode="json") for b in get_ballots(run_store, run_id)]}


@router.get("/runs/{run_id}/review-queue")
def get_voting_review_queue(run_id: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    return get_review_queue(run_store, run_id)


@router.get("/runs/{run_id}/review-history")
def get_voting_review_history(run_id: str, item_key: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    return get_review_history(run_store, run_id, item_key)


class VoteReviewDecisionRequest(BaseModel):
    """Voting's review decision carries extra fields (vote, co_signed_by)
    and its own validation beyond the generic shape shared by the other
    routers -- see arp/api/review_endpoints.py's module docstring for why
    that isn't generalized -- but still calls the same submit_review()
    persistence helper everyone else uses."""

    item_key: str
    decision: str  # 'approve' | 'edit' | 'reject'
    reviewer: str
    vote: str | None = Field(None, description="Required if decision == 'edit': the human-decided vote ('for'/'against'/'abstain'/'withhold').")
    co_signed_by: str | None = Field(None, description="Required before casting when the item carries an engagement_alignment_flag.")
    comment: str | None = None


@router.post("/runs/{run_id}/review")
def submit_voting_review(run_id: str, req: VoteReviewDecisionRequest, run_store: RunStore = Depends(get_run_store)) -> dict:
    """Every ballot item requires an explicit decision here before it can be
    cast (see cast_approved_votes) -- there is no confidence-based
    auto-approve path for voting, unlike the extraction review queue."""
    if req.decision not in ("approve", "edit", "reject"):
        raise HTTPException(400, "decision must be 'approve', 'edit', or 'reject'")
    if req.decision == "edit" and not req.vote:
        raise HTTPException(400, "vote is required when decision == 'edit'")
    edited_value = {"vote": req.vote, "co_signed_by": req.co_signed_by} if req.decision == "edit" else (
        {"co_signed_by": req.co_signed_by} if req.co_signed_by else None
    )
    return submit_review(
        run_store, run_id, item_key=req.item_key, decision=req.decision, reviewer=req.reviewer,
        edited_value=edited_value, comment=req.comment,
    )


@router.post("/runs/{run_id}/cast")
async def cast_votes_endpoint(
    run_id: str, run_store: RunStore = Depends(get_run_store), platform: BallotPlatform = Depends(get_ballot_platform)
) -> dict:
    cast = await cast_approved_votes(run_id, run_store, platform)
    return {"cast_count": len(cast), "votes": [v.model_dump(mode="json") for v in cast]}


@router.get("/runs/{run_id}/cast")
def get_cast_votes_endpoint(run_id: str, run_store: RunStore = Depends(get_run_store)) -> dict:
    return {"votes": [v.model_dump(mode="json") for v in get_cast_votes(run_store, run_id)]}
