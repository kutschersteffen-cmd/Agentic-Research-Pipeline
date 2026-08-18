from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from arp.api.deps import get_engagement_store, get_llm_client, get_registry, settings_dep
from arp.config import Settings
from arp.engagement.drafting_agent import draft_meeting_summary, draft_outreach_letter, draft_talking_points
from arp.engagement.orchestrator import decide_next_action
from arp.engagement.reporting_agent import compile_report
from arp.engagement.research_agent import research_company_issue
from arp.engagement.tracking_agent import log_commitment_verified, log_meeting_summary_validated, log_outreach_sent
from arp.engagement.triggers import ControversySignal, StaticControversySource, run_trigger_screen, scan_for_stalled_issues
from arp.ingestion.registry import DocumentSourceRegistry
from arp.schemas.common import CompanyRef
from arp.schemas.engagement import Contact, EscalationStage, IssueSeverity, TriggerSource
from arp.storage.engagement_store import EngagementStore
from arp.voting.pipeline import get_ballots

router = APIRouter(prefix="/api/engagement", tags=["engagement"])


def _get_record_or_404(store: EngagementStore, company_id: str):
    record = store.get(company_id)
    if record is None:
        raise HTTPException(404, "Engagement record not found")
    return record


def _get_issue_or_404(record, issue_id: str):
    for issue in record.issues:
        if issue.issue_id == issue_id:
            return issue
    raise HTTPException(404, "Issue not found")


@router.get("/records")
def list_records(store: EngagementStore = Depends(get_engagement_store)) -> dict:
    return {"records": [r.model_dump(mode="json") for r in store.list_all()]}


class CreateRecordRequest(BaseModel):
    company_id: str
    name: str
    sector: str | None = None


@router.post("/records")
def create_record(req: CreateRecordRequest, store: EngagementStore = Depends(get_engagement_store)) -> dict:
    return store.get_or_create(req.company_id, req.name, req.sector).model_dump(mode="json")


@router.get("/records/{company_id}")
def get_record(company_id: str, store: EngagementStore = Depends(get_engagement_store)) -> dict:
    return _get_record_or_404(store, company_id).model_dump(mode="json")


@router.get("/records/{company_id}/events")
def get_record_events(company_id: str, store: EngagementStore = Depends(get_engagement_store)) -> dict:
    return {"events": store.events(company_id)}


@router.post("/records/{company_id}/contacts")
def add_contact(company_id: str, contact: Contact, store: EngagementStore = Depends(get_engagement_store)) -> dict:
    return store.add_contact(company_id, contact).model_dump(mode="json")


class OpenIssueRequest(BaseModel):
    theme: str
    severity: IssueSeverity = IssueSeverity.MEDIUM
    source_detail: str = ""
    sector: str | None = None


@router.post("/records/{company_id}/issues")
def open_issue(company_id: str, req: OpenIssueRequest, name: str, store: EngagementStore = Depends(get_engagement_store)) -> dict:
    record, issue = store.open_issue(
        company_id, name, theme=req.theme, severity=req.severity, source=TriggerSource.ANALYST_RAISED, source_detail=req.source_detail, sector=req.sector
    )
    return {"record": record.model_dump(mode="json"), "issue_id": issue.issue_id}


@router.get("/records/{company_id}/issues/{issue_id}/next-action")
def next_action(company_id: str, issue_id: str, settings: Settings = Depends(settings_dep), store: EngagementStore = Depends(get_engagement_store)) -> dict:
    record = _get_record_or_404(store, company_id)
    issue = _get_issue_or_404(record, issue_id)
    return decide_next_action(issue, settings.engagement_sla_days).model_dump(mode="json")


class EscalateRequest(BaseModel):
    stage: EscalationStage
    decided_by: str
    reason: str = ""


@router.post("/records/{company_id}/issues/{issue_id}/escalate")
def escalate_issue(company_id: str, issue_id: str, req: EscalateRequest, store: EngagementStore = Depends(get_engagement_store)) -> dict:
    """The non-negotiable escalation-lever human checkpoint -- this is the
    only code path that can move an issue's escalation_stage."""
    return store.set_escalation_stage(company_id, issue_id, req.stage, req.decided_by, req.reason).model_dump(mode="json")


class TriggerScanRequest(BaseModel):
    companies: list[CompanyRef]
    signals: list[ControversySignal]


@router.post("/trigger-scan")
async def trigger_scan(req: TriggerScanRequest, store: EngagementStore = Depends(get_engagement_store)) -> dict:
    """Runs the trigger & detection layer against a caller-supplied
    controversy signal set (no real data-provider integration is wired up
    yet -- see docs/ENGAGEMENT_VOTING_ARCHITECTURE.md #8) plus an SLA sweep
    over existing issues."""
    source = StaticControversySource(req.signals)
    events = await run_trigger_screen(req.companies, source, store)
    settings = settings_dep()
    events += scan_for_stalled_issues(store, settings.engagement_sla_days)
    return {"events": [e.model_dump(mode="json") for e in events]}


@router.post("/records/{company_id}/issues/{issue_id}/dossier")
async def draft_dossier_endpoint(
    company_id: str,
    issue_id: str,
    company: CompanyRef,
    settings: Settings = Depends(settings_dep),
    store: EngagementStore = Depends(get_engagement_store),
    registry: DocumentSourceRegistry = Depends(get_registry),
) -> dict:
    record = _get_record_or_404(store, company_id)
    issue = _get_issue_or_404(record, issue_id)
    llm = get_llm_client()
    dossier, needs_review, _usage = await research_company_issue(
        company, issue, record, registry=registry, llm=llm,
        fuzzy_threshold=settings.grounding_fuzzy_threshold, confidence_review_threshold=settings.confidence_review_threshold,
    )
    return {"dossier": dossier.model_dump(mode="json"), "needs_review": needs_review}


class OutreachLetterRequest(BaseModel):
    company_name: str
    recipient: str
    dossier: dict
    house_style_notes: str = ""


@router.post("/records/{company_id}/issues/{issue_id}/outreach-letter")
async def outreach_letter_endpoint(company_id: str, issue_id: str, req: OutreachLetterRequest, store: EngagementStore = Depends(get_engagement_store)) -> dict:
    from arp.schemas.engagement import ResearchDossier

    record = _get_record_or_404(store, company_id)
    issue = _get_issue_or_404(record, issue_id)
    llm = get_llm_client()
    draft, _usage = await draft_outreach_letter(
        req.company_name, issue, ResearchDossier.model_validate(req.dossier), req.recipient, llm, req.house_style_notes
    )
    return draft.model_dump(mode="json")


class TalkingPointsRequest(BaseModel):
    company_name: str
    dossier: dict


@router.post("/records/{company_id}/issues/{issue_id}/talking-points")
async def talking_points_endpoint(company_id: str, issue_id: str, req: TalkingPointsRequest, store: EngagementStore = Depends(get_engagement_store)) -> dict:
    from arp.schemas.engagement import ResearchDossier

    record = _get_record_or_404(store, company_id)
    issue = _get_issue_or_404(record, issue_id)
    llm = get_llm_client()
    draft, _usage = await draft_talking_points(req.company_name, issue, ResearchDossier.model_validate(req.dossier), llm)
    return draft.model_dump(mode="json")


class MeetingSummaryRequest(BaseModel):
    company_name: str
    notes_or_transcript: str


@router.post("/records/{company_id}/issues/{issue_id}/meeting-summary")
async def meeting_summary_endpoint(company_id: str, issue_id: str, req: MeetingSummaryRequest, store: EngagementStore = Depends(get_engagement_store)) -> dict:
    record = _get_record_or_404(store, company_id)
    issue = _get_issue_or_404(record, issue_id)
    llm = get_llm_client()
    draft, _usage = await draft_meeting_summary(req.company_name, issue, req.notes_or_transcript, llm)
    return draft.model_dump(mode="json")


class LogOutreachSentRequest(BaseModel):
    summary: str
    sent_by: str
    doc_ref: str | None = None


@router.post("/records/{company_id}/issues/{issue_id}/log-outreach-sent")
def log_outreach_sent_endpoint(company_id: str, issue_id: str, req: LogOutreachSentRequest, store: EngagementStore = Depends(get_engagement_store)) -> dict:
    return log_outreach_sent(store, company_id, issue_id, req.summary, req.sent_by, req.doc_ref).model_dump(mode="json")


class ValidateMeetingSummaryRequest(BaseModel):
    summary: str
    commitments: list[str] = []
    validated_by: str


@router.post("/records/{company_id}/issues/{issue_id}/log-meeting-summary-validated")
def log_meeting_summary_validated_endpoint(company_id: str, issue_id: str, req: ValidateMeetingSummaryRequest, store: EngagementStore = Depends(get_engagement_store)) -> dict:
    """The non-negotiable meeting-notes-validation checkpoint: only after a
    human confirms the drafted summary is accurate does it get logged as
    correspondence and any stated commitments recorded."""
    return log_meeting_summary_validated(store, company_id, issue_id, req.summary, req.commitments, req.validated_by).model_dump(mode="json")


class VerifyCommitmentRequest(BaseModel):
    commitment_id: str
    verified_by: str


@router.post("/records/{company_id}/issues/{issue_id}/verify-commitment")
def verify_commitment_endpoint(company_id: str, issue_id: str, req: VerifyCommitmentRequest, store: EngagementStore = Depends(get_engagement_store)) -> dict:
    return log_commitment_verified(store, company_id, issue_id, req.commitment_id, req.verified_by).model_dump(mode="json")


@router.get("/report")
def report(period_label: str, run_id: str | None = None, store: EngagementStore = Depends(get_engagement_store)) -> dict:
    """Reporting Agent: compiles a stewardship report for `period_label`.
    Pass `run_id` to include a voting run's cast votes in the same report;
    omitted, the report covers engagement activity only."""
    from arp.storage.run_store import RunStore

    vote_records = []
    if run_id:
        run_store = RunStore(settings_dep().runs_dir)
        for ballot in get_ballots(run_store, run_id):
            vote_records.extend(ballot.votes)
        from arp.voting.pipeline import get_cast_votes

        cast_by_id = {v.vote_record_id: v for v in get_cast_votes(run_store, run_id)}
        vote_records = [cast_by_id.get(v.vote_record_id, v) for v in vote_records]
    return compile_report(store.list_all(), vote_records, period_label).model_dump(mode="json")
