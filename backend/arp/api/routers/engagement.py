from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from arp.api.auth import Principal, current_user
from arp.api.deps import get_engagement_store, get_llm_client, get_registry, settings_dep
from arp.config import Settings
from arp.db.session import require_dsn
from arp.engagement.drafting_agent import draft_meeting_summary, draft_outreach_letter, draft_talking_points
from arp.engagement.orchestrator import decide_next_action
from arp.engagement.reporting_agent import compile_report
from arp.engagement.research_agent import NoDocuments, research_company_issue
from arp.engagement.tracking_agent import (
    MissingEvidence,
    log_commitment_verified,
    log_meeting_summary_validated,
    log_outreach_sent,
)
from arp.engagement.triggers import ControversySignal, StaticControversySource, run_trigger_screen, scan_for_stalled_issues
from arp.ingestion.registry import DocumentSourceRegistry
from arp.schemas.common import CompanyRef
from arp.schemas.engagement import Contact, EscalationStage, IssueSeverity, IssueStatus, TriggerSource
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


def _valid_email(email: str) -> bool:
    """No spaces, one `@` with text before it, and a dotted domain after it (spec B14). No dependency."""
    local, at, domain = email.partition("@")
    return (
        bool(at) and bool(local) and "@" not in domain and not any(ch.isspace() for ch in email)
        and "." in domain and not domain.startswith(".") and not domain.endswith(".")
    )


@router.post("/records/{company_id}/contacts")
def add_contact(company_id: str, contact: Contact, store: EngagementStore = Depends(get_engagement_store)) -> dict:
    # Checked here, not on the stored model, so records already holding a bad address still load.
    if contact.email and not _valid_email(contact.email):
        raise HTTPException(422, "Enter a valid email address, or leave it empty.")
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
    reason: str = ""


@router.post("/records/{company_id}/issues/{issue_id}/escalate")
def escalate_issue(
    company_id: str,
    issue_id: str,
    req: EscalateRequest,
    store: EngagementStore = Depends(get_engagement_store),
    principal: Principal = Depends(current_user),
) -> dict:
    """The non-negotiable escalation-lever human checkpoint -- this is the
    only code path that can move an issue's escalation_stage."""
    issue = _get_issue_or_404(_get_record_or_404(store, company_id), issue_id)
    if issue.status in (IssueStatus.RESOLVED, IssueStatus.CLOSED):
        raise HTTPException(409, "A resolved or closed issue cannot be escalated.")
    return store.set_escalation_stage(company_id, issue_id, req.stage, principal.name, req.reason).model_dump(mode="json")


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
    listed = {c.company_id for c in req.companies}
    unlisted = [s.company_id for s in req.signals if s.company_id not in listed]
    return {
        "events": [e.model_dump(mode="json") for e in events],
        "unlisted_signals": {"count": len(unlisted), "company_ids": sorted(set(unlisted))},
    }


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
    documents = await registry.fetch_all(company)
    if not documents:  # before the model client: no documents means no model call (spec B, AC-112)
        raise HTTPException(422, str(NoDocuments(company)))
    llm = get_llm_client()
    dossier, needs_review, _usage = await research_company_issue(
        company, issue, record, registry=registry, llm=llm,
        fuzzy_threshold=settings.grounding_fuzzy_threshold, confidence_review_threshold=settings.confidence_review_threshold,
        documents=documents,
    )
    return {"dossier": dossier.model_dump(mode="json"), "needs_review": needs_review}


class OutreachLetterRequest(BaseModel):
    company_name: str
    recipient: str
    dossier: dict
    house_style_notes: str = ""


_PLACEHOLDER = re.compile(r"\[[^\[\]\n]{1,40}\]")


def letter_placeholders(subject: str, body: str, cited_doc_ids: set[str]) -> list[str]:
    """Every distinct `[...]` token in the subject, then the body, in order of first appearance; a token that is
    a cited document's `[<doc id>]` is a citation, not a placeholder (spec B15)."""
    tokens = _PLACEHOLDER.findall(subject) + _PLACEHOLDER.findall(body)
    return list(dict.fromkeys(t for t in tokens if t[1:-1] not in cited_doc_ids))


@router.post("/records/{company_id}/issues/{issue_id}/outreach-letter")
async def outreach_letter_endpoint(
    company_id: str,
    issue_id: str,
    req: OutreachLetterRequest,
    store: EngagementStore = Depends(get_engagement_store),
    settings: Settings = Depends(settings_dep),
) -> dict:
    from arp.schemas.engagement import ResearchDossier

    record = _get_record_or_404(store, company_id)
    issue = _get_issue_or_404(record, issue_id)
    llm = get_llm_client()
    dossier = ResearchDossier.model_validate(req.dossier)
    draft, _usage = await draft_outreach_letter(req.company_name, issue, dossier, req.recipient, llm, req.house_style_notes)
    if settings.fund_name:
        draft = draft.model_copy(
            update={k: getattr(draft, k).replace("[Fund name]", settings.fund_name) for k in ("subject", "body")}
        )
    placeholders = letter_placeholders(draft.subject, draft.body, {c.doc_id for c in dossier.citations})
    return {**draft.model_dump(mode="json"), "placeholders": placeholders}


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
    doc_ref: str | None = None


@router.post("/records/{company_id}/issues/{issue_id}/log-outreach-sent")
def log_outreach_sent_endpoint(
    company_id: str,
    issue_id: str,
    req: LogOutreachSentRequest,
    store: EngagementStore = Depends(get_engagement_store),
    principal: Principal = Depends(current_user),
) -> dict:
    return log_outreach_sent(store, company_id, issue_id, req.summary, principal.name, req.doc_ref).model_dump(mode="json")


class ValidateMeetingSummaryRequest(BaseModel):
    summary: str
    commitments: list[str] = []


@router.post("/records/{company_id}/issues/{issue_id}/log-meeting-summary-validated")
def log_meeting_summary_validated_endpoint(
    company_id: str,
    issue_id: str,
    req: ValidateMeetingSummaryRequest,
    store: EngagementStore = Depends(get_engagement_store),
    principal: Principal = Depends(current_user),
) -> dict:
    """The non-negotiable meeting-notes-validation checkpoint: only after a
    human confirms the drafted summary is accurate does it get logged as
    correspondence and any stated commitments recorded."""
    return log_meeting_summary_validated(store, company_id, issue_id, req.summary, req.commitments, principal.name).model_dump(mode="json")


class VerifyCommitmentRequest(BaseModel):
    commitment_id: str
    evidence: str | None = None


@router.post("/records/{company_id}/issues/{issue_id}/verify-commitment")
def verify_commitment_endpoint(
    company_id: str,
    issue_id: str,
    req: VerifyCommitmentRequest,
    store: EngagementStore = Depends(get_engagement_store),
    principal: Principal = Depends(current_user),
) -> dict:
    try:
        record = log_commitment_verified(store, company_id, issue_id, req.commitment_id, principal.name, req.evidence)
    except MissingEvidence as exc:
        raise HTTPException(422, str(exc)) from exc
    return record.model_dump(mode="json")


@router.get("/report")
def report(period_label: str, run_id: str | None = None, store: EngagementStore = Depends(get_engagement_store)) -> dict:
    """Reporting Agent: compiles a stewardship report for `period_label`.
    Pass `run_id` to include a voting run's cast votes in the same report;
    omitted, the report covers engagement activity only."""
    from arp.storage.run_store import RunStore

    vote_records = []
    if run_id:
        run_store = RunStore(require_dsn(settings_dep()), settings_dep().runs_dir)
        for ballot in get_ballots(run_store, run_id):
            vote_records.extend(ballot.votes)
        from arp.voting.pipeline import get_cast_votes

        cast_by_id = {v.vote_record_id: v for v in get_cast_votes(run_store, run_id)}
        vote_records = [cast_by_id.get(v.vote_record_id, v) for v in vote_records]
    return compile_report(store.list_all(), vote_records, period_label).model_dump(mode="json")
