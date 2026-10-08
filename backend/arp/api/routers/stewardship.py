from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from arp.api.auth import Principal, current_user
from arp.api.deps import get_decision_store, get_engagement_store, get_stream_store, settings_dep
from arp.config import Settings
from arp.schemas.common import now_iso
from arp.schemas.engagement import (
    Commitment,
    CommitmentStatus,
    CorrespondenceType,
    EscalationStage,
    InteractionType,
    IssueSeverity,
    IssueStatus,
    TriggerSource,
)
from arp.stewardship import drafting, escalation, monitoring, tracking
from arp.stewardship.benchmark import BenchmarkStore, parse_ishares_holdings
from arp.stewardship.client_report import build_pptx, client_report
from arp.stewardship.policies import PolicyStore, coverage_preview, voting_preview
from arp.stewardship.policy_review import DATA, load
from arp.stewardship.process import (
    HOUSE,
    StreamStore,
    build_stream_policy,
    client_escalations,
    client_store,
    confirm_tiers,
    escalation_contexts,
    flow,
    load_sample,
    open_exceptions,
    record_decision,
    tier_review,
)
from arp.stewardship.program import ProgramParams, approve, build_proposal, monitor, record_run, simulate
from arp.stewardship.style import check as style_check
from arp.stewardship.tiers import TierStore, tier_contexts
from arp.stewardship.trigger_store import TriggerStore, trigger_id
from arp.stewardship.universe import HouseUniverseSetting
from arp.storage.decision_store import DecisionStore
from arp.storage.engagement_store import EngagementStore

router = APIRouter(prefix="/api/stewardship", tags=["stewardship"])


def _stream_or_404(streams: StreamStore, stream_id: str) -> dict:
    try:
        stream = streams.get(stream_id)
    except ValueError as exc:
        raise HTTPException(404, "Stream not found") from exc
    if stream is None:
        raise HTTPException(404, "Stream not found")
    return stream


@router.get("/streams")
def list_streams(streams: StreamStore = Depends(get_stream_store)) -> dict:
    return {
        "streams": [{"stream_id": HOUSE, "name": "House program", "kind": "house"}]
        + [{"stream_id": s["stream_id"], "name": s["name"], "kind": "client"} for s in streams.list()]
    }


class CreateStreamRequest(BaseModel):
    name: str
    vehicle_type: Literal["SMA", "CCF", "ETF"] = "SMA"
    client_policy: dict | None = None  # None: start from the example envisioned policy


@router.post("/streams")
def create_stream(body: CreateStreamRequest, streams: StreamStore = Depends(get_stream_store)) -> dict:
    if not body.name.strip():
        raise HTTPException(422, "A client stream needs a name")
    policy = body.client_policy or json.loads((DATA / "examples" / "client_policy_example.json").read_text())
    try:
        stream = streams.create(body.name.strip(), policy, body.vehicle_type)
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, f"Invalid client policy: {exc}") from exc
    return {"stream_id": stream["stream_id"]}


@router.get("/streams/{stream_id}/flow")
def get_flow(
    stream_id: str,
    streams: StreamStore = Depends(get_stream_store),
    engagements: EngagementStore = Depends(get_engagement_store),
    settings: Settings = Depends(settings_dep),
) -> dict:
    if stream_id != HOUSE:
        _stream_or_404(streams, stream_id)
    return flow(stream_id, streams, engagements.list_all(), settings.engagement_sla_days)


class PolicyDecisionRequest(BaseModel):
    issue_id: str
    decision: Literal["adopt", "adopt_with_modification", "decline", "defer", "clarify"]
    note: str | None = None
    modification: dict | None = None


@router.post("/streams/{stream_id}/decisions")
def post_decision(
    body: PolicyDecisionRequest,
    stream_id: str,
    streams: StreamStore = Depends(get_stream_store),
    principal: Principal = Depends(current_user),
) -> dict:
    stream = _stream_or_404(streams, stream_id)
    try:
        updated = record_decision(stream, {**body.model_dump(exclude_none=True), "decided_by": principal.name}, PolicyStore(streams.root).active("house_voting"))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    streams.save(updated)
    return {"ok": True}


@router.post("/streams/{stream_id}/build")
def post_build(stream_id: str, streams: StreamStore = Depends(get_stream_store)) -> dict:
    stream = _stream_or_404(streams, stream_id)
    try:
        updated = build_stream_policy(stream, PolicyStore(streams.root).active("house_voting"))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    streams.save(updated)
    return {"ok": True, "positions_from_client": sum(p["origin"] == "client" for p in updated["built_policy"]["positions"])}


class ConfirmTiersRequest(BaseModel):
    issuer_ids: list[str] | None = None  # None: confirm every proposed change


@router.post("/tiers/confirm")
def post_confirm_tiers(
    body: ConfirmTiersRequest,
    streams: StreamStore = Depends(get_stream_store),
    engagements: EngagementStore = Depends(get_engagement_store),
    principal: Principal = Depends(current_user),
) -> dict:
    try:
        confirmed = confirm_tiers(streams.root, engagements.list_all(), principal.name, body.issuer_ids)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"confirmed": confirmed}


@router.get("/tiers")
def get_tiers(
    streams: StreamStore = Depends(get_stream_store), engagements: EngagementStore = Depends(get_engagement_store)
) -> dict:
    """The tier report (E1): distribution of confirmed tiers, the latest assignment
    per issuer with the rule that decided it, and the changes awaiting confirmation."""
    review = tier_review(streams.root, load_sample(), engagements.list_all())
    return {**review, "assignments": list(TierStore(streams.root).latest().values())}


# --- Stage studios: versioned house policies, design and calibration ---------


def _store(streams: StreamStore, stream: str, policy_id: str) -> PolicyStore:
    """The house store, or a client stream's store (`?stream=<id>`) for the
    policies that have a client form."""
    if stream == HOUSE:
        store = PolicyStore(streams.root)
    else:
        _stream_or_404(streams, stream)
        store = client_store(streams.root, stream)
    try:
        store.versions(policy_id)
    except KeyError as exc:
        raise HTTPException(404, "Unknown policy") from exc
    return store


@router.get("/policies/{policy_id}")
def get_policy(policy_id: str, stream: str = HOUSE, streams: StreamStore = Depends(get_stream_store)) -> dict:
    store = _store(streams, stream, policy_id)
    active = store.active_version(policy_id)
    return {
        "policy_id": policy_id,
        "active_version": active,
        "active": store.content(policy_id, active),
        "versions": store.versions(policy_id),
        "activations": store.activations(policy_id),
    }


@router.get("/policies/{policy_id}/versions/{version}")
def get_policy_version(
    policy_id: str, version: int, stream: str = HOUSE, streams: StreamStore = Depends(get_stream_store)
) -> dict:
    try:
        return _store(streams, stream, policy_id).content(policy_id, version)
    except KeyError as exc:
        raise HTTPException(404, "Unknown version") from exc


class SavePolicyRequest(BaseModel):
    content: dict
    note: str = ""


@router.post("/policies/{policy_id}/versions")
def save_policy_version(
    policy_id: str,
    body: SavePolicyRequest,
    stream: str = HOUSE,
    streams: StreamStore = Depends(get_stream_store),
    principal: Principal = Depends(current_user),
) -> dict:
    store = _store(streams, stream, policy_id)
    try:
        version = store.save(policy_id, body.content, body.note, principal.user_id, load_sample())
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"version": version}


class ActivateRequest(BaseModel):
    version: int


@router.post("/policies/{policy_id}/activate")
def activate_policy_version(
    policy_id: str,
    body: ActivateRequest,
    stream: str = HOUSE,
    streams: StreamStore = Depends(get_stream_store),
    principal: Principal = Depends(current_user),
) -> dict:
    store = _store(streams, stream, policy_id)
    try:
        return store.activate(policy_id, body.version, principal.user_id)
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/catalogue")
def get_catalogue() -> dict:
    return load("policy_issue_catalogue.json")


class UniverseRequest(BaseModel):
    source: Literal["sample", "portfolio"]


@router.get("/universe")
def get_universe(streams: StreamStore = Depends(get_stream_store)) -> dict:
    """Which companies the house program covers, and how many each source has."""
    sample = load_sample(votes=[], alerts=[])
    return {**HouseUniverseSetting(streams.root).get(), "issuers": len(sample["issuers"]), "note": sample.get("note")}


@router.put("/universe")
def put_universe(
    body: UniverseRequest, streams: StreamStore = Depends(get_stream_store), principal: Principal = Depends(current_user)
) -> dict:
    try:
        HouseUniverseSetting(streams.root).set(body.source, principal.name)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return get_universe(streams)


@router.get("/decision-inputs")
def decision_inputs(decisions: DecisionStore = Depends(get_decision_store)) -> dict:
    """Decision Studio publications the coverage rules can read, and how many
    issuers in scope each one matched. Unmatched issuers simply lack the field."""
    issuer_ids = {i["issuer_id"] for i in load_sample()["issuers"]}
    return {
        "in_scope": len(issuer_ids),
        "published": [
            {
                "snapshot_id": s.snapshot_id,
                "framework_name": s.framework_name,
                "framework_version": s.framework_version,
                "dataset_name": s.dataset_name,
                "as_of": s.as_of,
                "published_by": s.published_by,
                "published_at": s.published_at,
                "field": f"issuer.decision.{s.framework_id}",
                "rows": len(s.rows),
                "matched": sum(1 for r in s.rows if r.entity_id in issuer_ids),
            }
            for s in decisions.latest_published()
        ],
    }


@router.get("/studio/coverage/inputs")
def coverage_inputs(engagements: EngagementStore = Depends(get_engagement_store)) -> dict:
    """The per-company inputs the coverage rules see (for the rule editor's live preview)."""
    return {"contexts": tier_contexts(load_sample(), engagements.list_all())}


class CoveragePreviewRequest(BaseModel):
    graph: dict


@router.post("/studio/coverage/preview")
def post_coverage_preview(
    body: CoveragePreviewRequest,
    streams: StreamStore = Depends(get_stream_store),
    engagements: EngagementStore = Depends(get_engagement_store),
) -> dict:
    try:
        return coverage_preview(
            body.graph,
            PolicyStore(streams.root).active("coverage_rules"),
            load_sample(),
            engagements.list_all(),
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(422, f"The coverage rules do not run: {exc}") from exc


class VotingPreviewRequest(BaseModel):
    policy: dict


@router.post("/studio/voting/preview")
def post_voting_preview(body: VotingPreviewRequest, streams: StreamStore = Depends(get_stream_store)) -> dict:
    try:
        return voting_preview(body.policy, PolicyStore(streams.root).active("house_voting"), load_sample())
    except (ValueError, KeyError, RuntimeError) as exc:
        raise HTTPException(422, f"The voting policy does not run: {exc}") from exc


@router.get("/studio/monitoring/triggers")
def monitoring_triggers(
    settings: Settings = Depends(settings_dep),
    streams: StreamStore = Depends(get_stream_store),
    engagements: EngagementStore = Depends(get_engagement_store),
) -> dict:
    """The triggers the active monitoring rules raise on company data, matched to
    open engagements, followed by the tracking triggers from the engagements themselves."""
    sample, records = load_sample(), engagements.list_all()
    rules = monitoring.evaluate(PolicyStore(streams.root).active("monitoring_rules"), sample, records)
    return {"triggers": rules + tracking.triggers(records, settings.engagement_sla_days)}


@router.get("/triggers")
def list_stored_triggers(status: Literal["open", "acknowledged", "resolved"] | None = None, streams: StreamStore = Depends(get_stream_store)) -> dict:
    return {"triggers": [t.model_dump() for t in TriggerStore(streams.root).list_triggers(status)]}


class TriggerTransitionRequest(BaseModel):
    status: Literal["open", "acknowledged", "resolved"]
    decided_by: str
    reason: str = ""


@router.post("/triggers/{trigger_id}/transition")
def post_trigger_transition(trigger_id: str, body: TriggerTransitionRequest, streams: StreamStore = Depends(get_stream_store)) -> dict:
    try:
        return TriggerStore(streams.root).transition(trigger_id, body.status, body.decided_by, body.reason).model_dump()
    except KeyError as exc:
        raise HTTPException(404, "Unknown trigger") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


class MonitoringPreviewRequest(BaseModel):
    graph: dict


@router.post("/studio/monitoring/preview")
def post_monitoring_preview(
    body: MonitoringPreviewRequest,
    streams: StreamStore = Depends(get_stream_store),
    engagements: EngagementStore = Depends(get_engagement_store),
) -> dict:
    try:
        return monitoring.preview(
            body.graph,
            PolicyStore(streams.root).active("monitoring_rules"),
            load_sample(),
            engagements.list_all(),
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(422, f"The monitoring rules do not run: {exc}") from exc


class OpenFromTriggerRequest(BaseModel):
    issuer_id: str
    rule: str


@router.post("/monitoring/open-engagement")
def open_engagement_from_trigger(
    body: OpenFromTriggerRequest,
    streams: StreamStore = Depends(get_stream_store),
    engagements: EngagementStore = Depends(get_engagement_store),
    principal: Principal = Depends(current_user),
) -> dict:
    """Opens an engagement for a trigger the active rules raise, or one a monthly run stored. The theme and
    severity come from the rule, not the request."""
    sample = load_sample()
    records = engagements.list_all()
    triggers = monitoring.evaluate(PolicyStore(streams.root).active("monitoring_rules"), sample, records)
    trigger = next((t for t in triggers if t["issuer_id"] == body.issuer_id and t["rule"] == body.rule), None)
    if trigger is None and (stored := TriggerStore(streams.root).stored_trigger(trigger_id(body.issuer_id, body.rule))):
        # the stored engagement_id is as of the run: match open engagements now, as evaluate does
        open_ids = [i.issue_id for r in records if r.company_id == stored["issuer_id"] for i in r.issues
                    if i.theme == stored["theme"] and i.status in (IssueStatus.OPEN, IssueStatus.STALLED)]
        trigger = {**stored, "engagement_id": open_ids[0] if open_ids else None}
    if trigger is None:
        raise HTTPException(404, "No active monitoring rule or monthly run raised such a trigger")
    if trigger["engagement_id"] is not None:
        raise HTTPException(409, f"Already attached to engagement {trigger['engagement_id']}")
    _, issue = engagements.open_issue(
        trigger["issuer_id"],
        trigger["company"],
        theme=trigger["theme"],
        severity=IssueSeverity(trigger["severity"]),
        source=TriggerSource.MONITORING_RULE,
        source_detail=f"{trigger['rule']}: {trigger['reason']} (opened by {principal.name})",
        sector=trigger["sector"],
    )
    return {"issue_id": issue.issue_id, "trigger": {**trigger, "engagement_id": issue.issue_id}}


def _escalation_contexts(settings: Settings, streams: StreamStore, engagements: EngagementStore) -> list[dict]:
    return escalation_contexts(
        streams.root, load_sample(), engagements.list_all(), settings.engagement_sla_days
    )


@router.get("/studio/escalation/recommendations")
def escalation_recommendations(
    settings: Settings = Depends(settings_dep),
    streams: StreamStore = Depends(get_stream_store),
    engagements: EngagementStore = Depends(get_engagement_store),
) -> dict:
    """What the active escalation rules recommend for every open engagement (sample and live)."""
    ctxs = _escalation_contexts(settings, streams, engagements)
    return {"recommendations": escalation.evaluate(PolicyStore(streams.root).active("escalation_rules"), ctxs)}


class EscalationPreviewRequest(BaseModel):
    graph: dict


@router.post("/studio/escalation/preview")
def post_escalation_preview(
    body: EscalationPreviewRequest,
    settings: Settings = Depends(settings_dep),
    streams: StreamStore = Depends(get_stream_store),
    engagements: EngagementStore = Depends(get_engagement_store),
) -> dict:
    try:
        ctxs = _escalation_contexts(settings, streams, engagements)
        return escalation.preview(body.graph, PolicyStore(streams.root).active("escalation_rules"), ctxs)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(422, f"The escalation rules do not run: {exc}") from exc


@router.get("/studio/escalation/client-example")
def client_escalation_example() -> dict:
    """An example client escalation graph (stricter on climate for CLTI laggards)."""
    return escalation.load_client_example()


@router.post("/streams/{stream_id}/studio/escalation/preview")
def post_client_escalation_preview(
    stream_id: str,
    body: EscalationPreviewRequest,
    settings: Settings = Depends(settings_dep),
    streams: StreamStore = Depends(get_stream_store),
    engagements: EngagementStore = Depends(get_engagement_store),
) -> dict:
    _stream_or_404(streams, stream_id)
    ctxs = _escalation_contexts(settings, streams, engagements)
    house = escalation.evaluate(PolicyStore(streams.root).active("escalation_rules"), ctxs)
    try:
        return escalation.client_preview(
            body.graph, client_store(streams.root, stream_id).active("escalation_rules"), ctxs, house
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(422, f"The escalation rules do not run: {exc}") from exc


class ExceptionDecisionRequest(BaseModel):
    issue_id: str
    client_step: str  # the step the decider saw: a stale or repeated request finds no open exception
    decision: Literal["adopt", "decline"]
    note: str = ""


@router.post("/streams/{stream_id}/exceptions")
def decide_client_exception(
    stream_id: str,
    body: ExceptionDecisionRequest,
    settings: Settings = Depends(settings_dep),
    streams: StreamStore = Depends(get_stream_store),
    engagements: EngagementStore = Depends(get_engagement_store),
    principal: Principal = Depends(current_user),
) -> dict:
    """The house decides a client's escalation above its own step: adopt moves the
    engagement to the client's step; decline keeps the house step. Both are logged
    on the stream, so the client report can show them."""
    stream = _stream_or_404(streams, stream_id)
    ctxs = _escalation_contexts(settings, streams, engagements)
    house = escalation.evaluate(PolicyStore(streams.root).active("escalation_rules"), ctxs)
    item = next(
        (
            r
            for r in open_exceptions(stream, client_escalations(streams.root, stream_id, ctxs, house))
            if (r["issue_id"], r["recommended"]) == (body.issue_id, body.client_step)
        ),
        None,
    )
    if item is None:
        raise HTTPException(404, "No open exception for this engagement at this step")
    if body.decision == "adopt":
        engagements.set_escalation_stage(
            item["company_id"],
            item["issue_id"],
            EscalationStage(item["recommended"]),
            principal.name,
            f"Adopted from {stream['name']}: {item['reason']} ({item['rule']})",
        )
    row = {
        "issue_id": item["issue_id"],
        "company_id": item["company_id"],
        "theme": item["theme"],
        "house_step": item["house_recommended"],
        "client_step": item["recommended"],
        "decision": body.decision,
        "decided_by": principal.name,
        "note": body.note,
        "decided_at": now_iso(),
    }
    streams.save({**stream, "exception_decisions": [*stream.get("exception_decisions", []), row]})
    return row


@router.get("/streams/{stream_id}/report")
def get_client_report(
    stream_id: str,
    settings: Settings = Depends(settings_dep),
    streams: StreamStore = Depends(get_stream_store),
    engagements: EngagementStore = Depends(get_engagement_store),
) -> dict:
    stream = _stream_or_404(streams, stream_id)
    return client_report(streams.root, stream, engagements.list_all(), settings.engagement_sla_days)


@router.get("/streams/{stream_id}/report.pptx")
def get_client_report_pptx(
    stream_id: str,
    background: BackgroundTasks,
    settings: Settings = Depends(settings_dep),
    streams: StreamStore = Depends(get_stream_store),
    engagements: EngagementStore = Depends(get_engagement_store),
) -> FileResponse:
    """The same report as a PowerPoint deck, rendered on request and not stored."""
    stream = _stream_or_404(streams, stream_id)
    report = client_report(streams.root, stream, engagements.list_all(), settings.engagement_sla_days)
    tmp = Path(tempfile.mkdtemp(prefix="arp_client_report_"))
    path = build_pptx(report, tmp / f"{stream_id}-stewardship-report.pptx", pdf=False)  # tmp is deleted: no PDF
    background.add_task(shutil.rmtree, tmp, ignore_errors=True)
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )


# --- Client program (Part 5): calibrate, compare with the house, propose -----


@router.get("/streams/{stream_id}/program")
def get_program(
    stream_id: str,
    settings: Settings = Depends(settings_dep),
    streams: StreamStore = Depends(get_stream_store),
    engagements: EngagementStore = Depends(get_engagement_store),
) -> dict:
    """The simulation for the saved calibration (the defaults until one is saved)."""
    stream = _stream_or_404(streams, stream_id)
    return {
        "saved": stream.get("program"),
        "versions": stream.get("program_versions", []),
        "runs": stream.get("program_runs", []),
        "simulation": simulate(streams.root, stream, engagements.list_all(), settings.engagement_sla_days),
    }


class ProgramRequest(BaseModel):
    params: ProgramParams


@router.post("/streams/{stream_id}/program/simulate")
def post_program_simulate(
    stream_id: str,
    body: ProgramRequest,
    settings: Settings = Depends(settings_dep),
    streams: StreamStore = Depends(get_stream_store),
    engagements: EngagementStore = Depends(get_engagement_store),
) -> dict:
    """Runs a calibration without saving it."""
    stream = _stream_or_404(streams, stream_id)
    try:
        return simulate(streams.root, stream, engagements.list_all(), settings.engagement_sla_days, body.params.model_dump())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.put("/streams/{stream_id}/program")
def put_program(
    stream_id: str, body: ProgramRequest, streams: StreamStore = Depends(get_stream_store), principal: Principal = Depends(current_user)
) -> dict:
    stream = _stream_or_404(streams, stream_id)
    if body.params.benchmark != "sample":
        try:
            BenchmarkStore(streams.root).get(body.params.benchmark)
        except KeyError as exc:
            raise HTTPException(422, f"Unknown benchmark: {body.params.benchmark}") from exc
    program = {"params": body.params.model_dump(), "updated_by": principal.user_id, "updated_at": now_iso()}
    streams.save({**stream, "program": program})
    return program


@router.get("/streams/{stream_id}/program/proposal.pptx")
def get_program_proposal(
    stream_id: str,
    background: BackgroundTasks,
    settings: Settings = Depends(settings_dep),
    streams: StreamStore = Depends(get_stream_store),
    engagements: EngagementStore = Depends(get_engagement_store),
) -> FileResponse:
    """The proposal deck for the saved calibration, rendered on request."""
    stream = _stream_or_404(streams, stream_id)
    sim = simulate(streams.root, stream, engagements.list_all(), settings.engagement_sla_days)
    tmp = Path(tempfile.mkdtemp(prefix="arp_program_"))
    path = build_proposal(sim, tmp / f"{stream_id}-program-proposal.pptx", pdf=False)  # tmp is deleted: no PDF
    background.add_task(shutil.rmtree, tmp, ignore_errors=True)
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )


class ApproveProgramRequest(BaseModel):
    pass  # approver comes from the signed-in principal


@router.post("/streams/{stream_id}/program/approve")
def post_program_approve(
    stream_id: str,
    body: ApproveProgramRequest,
    settings: Settings = Depends(settings_dep),
    streams: StreamStore = Depends(get_stream_store),
    engagements: EngagementStore = Depends(get_engagement_store),
    principal: Principal = Depends(current_user),
) -> dict:
    """Freezes the saved calibration as a new program version (four-eyes)."""
    stream = _stream_or_404(streams, stream_id)
    try:
        stream = approve(streams.root, stream, engagements.list_all(), settings.engagement_sla_days, principal.user_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    streams.save(stream)
    return stream["program_versions"][-1]


@router.get("/streams/{stream_id}/program/monitor")
def get_program_monitor(
    stream_id: str,
    settings: Settings = Depends(settings_dep),
    streams: StreamStore = Depends(get_stream_store),
    engagements: EngagementStore = Depends(get_engagement_store),
) -> dict:
    stream = _stream_or_404(streams, stream_id)
    return monitor(streams.root, stream, engagements.list_all(), settings.engagement_sla_days)


@router.post("/streams/{stream_id}/program/runs")
def post_program_run(
    stream_id: str,
    principal: Principal = Depends(current_user),
    settings: Settings = Depends(settings_dep),
    streams: StreamStore = Depends(get_stream_store),
    engagements: EngagementStore = Depends(get_engagement_store),
) -> dict:
    """Records one monitoring run (a KPI snapshot) against the approved version."""
    stream = _stream_or_404(streams, stream_id)
    try:
        stream = record_run(
            stream, monitor(streams.root, stream, engagements.list_all(), settings.engagement_sla_days), principal.name
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    streams.save(stream)
    return stream["program_runs"][-1]


# --- Stage 3: outreach drafts (E6 tags, E8 style check), approved at stage 5 ---


def _drafts(streams: StreamStore) -> drafting.DraftStore:
    return drafting.DraftStore(streams.root)


def _blocklist(streams: StreamStore) -> dict:
    return PolicyStore(streams.root).active("phrase_blocklist")


class StyleCheckRequest(BaseModel):
    text: str


@router.post("/style/check")
def post_style_check(body: StyleCheckRequest, streams: StreamStore = Depends(get_stream_store)) -> dict:
    """E8: blocklisted phrases in a text, with where they are. Flags only."""
    return {"flags": style_check(body.text, _blocklist(streams))}


@router.get("/drafts")
def list_drafts(streams: StreamStore = Depends(get_stream_store)) -> dict:
    return {"drafts": _drafts(streams).list()}


class CreateDraftRequest(BaseModel):
    company_id: str
    issue_id: str
    type: CorrespondenceType = CorrespondenceType.LETTER
    text: str
    interaction_type: InteractionType | None = None  # None: take the proposed tag


@router.post("/drafts")
def create_draft(
    body: CreateDraftRequest,
    streams: StreamStore = Depends(get_stream_store),
    engagements: EngagementStore = Depends(get_engagement_store),
    principal: Principal = Depends(current_user),
) -> dict:
    try:
        return drafting.create(_drafts(streams), engagements, _blocklist(streams), **body.model_dump(), created_by=principal.user_id)
    except KeyError as exc:
        raise HTTPException(404, "Unknown engagement") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


class UpdateDraftRequest(BaseModel):
    text: str | None = None
    interaction_type: InteractionType | None = None


@router.put("/drafts/{draft_id}")
def update_draft(
    draft_id: str,
    body: UpdateDraftRequest,
    streams: StreamStore = Depends(get_stream_store),
    engagements: EngagementStore = Depends(get_engagement_store),
    principal: Principal = Depends(current_user),
) -> dict:
    try:
        return drafting.update(_drafts(streams), engagements, _blocklist(streams), draft_id, **body.model_dump(), updated_by=principal.user_id)
    except KeyError as exc:
        raise HTTPException(404, "Unknown draft or engagement") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


class ApproveDraftRequest(BaseModel):
    note: str = ""


@router.post("/drafts/{draft_id}/approve")
def approve_draft(
    draft_id: str, body: ApproveDraftRequest, streams: StreamStore = Depends(get_stream_store), principal: Principal = Depends(current_user)
) -> dict:
    """The stage 5 checkpoint for outreach: nothing is sent before a second person approves it."""
    try:
        return drafting.approve(_drafts(streams), draft_id, principal.user_id, body.note)
    except KeyError as exc:
        raise HTTPException(404, "Unknown draft") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


class SentRequest(BaseModel):
    pass  # the sender is the signed-in principal


@router.post("/drafts/{draft_id}/sent")
def mark_draft_sent(
    draft_id: str,
    body: SentRequest,
    streams: StreamStore = Depends(get_stream_store),
    engagements: EngagementStore = Depends(get_engagement_store),
    principal: Principal = Depends(current_user),
) -> dict:
    """Records that an approved draft went out: it is logged as correspondence with its interaction type."""
    try:
        return drafting.mark_sent(_drafts(streams), engagements, draft_id, principal.user_id)
    except KeyError as exc:
        raise HTTPException(404, "Unknown draft or engagement") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


# --- Stage 6: tracking ---------------------------------------------------------


@router.get("/tracking")
def get_tracking(engagements: EngagementStore = Depends(get_engagement_store)) -> dict:
    """Every commitment with its target date and status, and the engagements, open and closed."""
    records = engagements.list_all()
    return {
        "commitments": tracking.commitments(records),
        "engagements": [
            {
                "company_id": r.company_id,
                "company": r.name,
                "issue_id": i.issue_id,
                "theme": i.theme,
                "status": i.status.value,
                "step": i.escalation_stage.value,
                "milestone": i.milestone_stage.value,
            }
            for r in records
            for i in r.issues
        ],
    }


class CommitmentRequest(BaseModel):
    company_id: str
    issue_id: str
    text: str
    target_date: str | None = None


@router.post("/tracking/commitments")
def add_commitment(
    body: CommitmentRequest,
    engagements: EngagementStore = Depends(get_engagement_store),
    principal: Principal = Depends(current_user),
) -> dict:
    """Logs a commitment the company made, as validated by the person recording it."""
    if not body.text.strip():
        raise HTTPException(422, "A commitment needs text")
    if body.target_date:
        try:
            datetime.fromisoformat(body.target_date)
        except ValueError as exc:
            raise HTTPException(422, "target_date must be an ISO date") from exc
    commitment = Commitment(text=body.text, target_date=body.target_date, recorded_by=principal.name)
    try:
        engagements.add_commitment(body.company_id, body.issue_id, commitment)
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, "Unknown engagement") from exc
    return commitment.model_dump(mode="json")


class CommitmentStatusRequest(BaseModel):
    company_id: str
    issue_id: str
    status: Literal["verified", "missed"]


@router.post("/tracking/commitments/{commitment_id}")
def set_commitment_status(
    commitment_id: str,
    body: CommitmentStatusRequest,
    engagements: EngagementStore = Depends(get_engagement_store),
    principal: Principal = Depends(current_user),
) -> dict:
    try:
        engagements.update_commitment_status(
            body.company_id, body.issue_id, commitment_id, CommitmentStatus(body.status), principal.name
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"commitment_id": commitment_id, "status": body.status}


class CloseRequest(BaseModel):
    company_id: str
    issue_id: str
    status: Literal["resolved", "closed"]
    outcome: str


@router.post("/tracking/close")
def close_engagement(
    body: CloseRequest, engagements: EngagementStore = Depends(get_engagement_store), principal: Principal = Depends(current_user)
) -> dict:
    try:
        tracking.close(engagements, body.company_id, body.issue_id, IssueStatus(body.status), body.outcome, principal.name)
    except KeyError as exc:
        raise HTTPException(404, "Unknown engagement") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"issue_id": body.issue_id, "status": body.status}


@router.get("/tracking/case-study/{company_id}/{issue_id}")
def get_case_study(
    company_id: str,
    issue_id: str,
    streams: StreamStore = Depends(get_stream_store),
    engagements: EngagementStore = Depends(get_engagement_store),
) -> dict:
    """E7: a case study compiled from a closed engagement's records, with its E8 style flags."""
    record = engagements.get(company_id)
    if record is None:
        raise HTTPException(404, "Unknown engagement")
    try:
        return tracking.case_study(record, issue_id, _blocklist(streams))
    except KeyError as exc:
        raise HTTPException(404, "Unknown engagement") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


# --- Benchmarks for client programs ----------------------------------------------


@router.get("/benchmarks")
def list_benchmarks(streams: StreamStore = Depends(get_stream_store)) -> dict:
    return {"benchmarks": BenchmarkStore(streams.root).list()}


class BenchmarkUpload(BaseModel):
    text: str


@router.post("/benchmarks")
def upload_benchmark(
    body: BenchmarkUpload, streams: StreamStore = Depends(get_stream_store), principal: Principal = Depends(current_user)
) -> dict:
    """An iShares holdings export (e.g. URTH for MSCI World): equities and weights.
    Uploading the same fund and date again replaces it."""
    if len(body.text) > 5_000_000:
        raise HTTPException(413, "File too large for a holdings export")
    try:
        record = BenchmarkStore(streams.root).save(parse_ishares_holdings(body.text), principal.name)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {k: v for k, v in record.items() if k != "constituents"} | {"constituents": len(record["constituents"])}
