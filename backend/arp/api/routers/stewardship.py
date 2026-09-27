from __future__ import annotations

import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from arp.api.deps import get_engagement_store, get_stream_store, settings_dep
from arp.config import Settings
from arp.schemas.engagement import EscalationStage, IssueSeverity, TriggerSource
from arp.stewardship import escalation, monitoring
from arp.stewardship.client_report import build_pptx, client_report
from arp.stewardship.policies import PolicyStore, coverage_preview, voting_preview
from arp.stewardship.policy_review import DATA, load
from arp.stewardship.process import (
    HOUSE,
    SAMPLE_PATH,
    StreamStore,
    build_stream_policy,
    client_escalations,
    client_store,
    confirm_tiers,
    escalation_contexts,
    flow,
    open_exceptions,
    record_decision,
    tier_review,
)
from arp.stewardship.program import ProgramParams, build_proposal, simulate
from arp.stewardship.tiers import TierStore, tier_contexts
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
    decided_by: str
    note: str | None = None
    modification: dict | None = None


@router.post("/streams/{stream_id}/decisions")
def post_decision(body: PolicyDecisionRequest, stream_id: str, streams: StreamStore = Depends(get_stream_store)) -> dict:
    stream = _stream_or_404(streams, stream_id)
    try:
        updated = record_decision(stream, body.model_dump(exclude_none=True), PolicyStore(streams.root).active("house_voting"))
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
    decided_by: str
    issuer_ids: list[str] | None = None  # None: confirm every proposed change


@router.post("/tiers/confirm")
def post_confirm_tiers(
    body: ConfirmTiersRequest,
    streams: StreamStore = Depends(get_stream_store),
    engagements: EngagementStore = Depends(get_engagement_store),
) -> dict:
    try:
        confirmed = confirm_tiers(streams.root, engagements.list_all(), body.decided_by, body.issuer_ids)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"confirmed": confirmed}


@router.get("/tiers")
def get_tiers(
    streams: StreamStore = Depends(get_stream_store), engagements: EngagementStore = Depends(get_engagement_store)
) -> dict:
    """The tier report (E1): distribution of confirmed tiers, the latest assignment
    per issuer with the rule that decided it, and the changes awaiting confirmation."""
    review = tier_review(streams.root, json.loads(SAMPLE_PATH.read_text()), engagements.list_all())
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
    created_by: str


@router.post("/policies/{policy_id}/versions")
def save_policy_version(
    policy_id: str, body: SavePolicyRequest, stream: str = HOUSE, streams: StreamStore = Depends(get_stream_store)
) -> dict:
    store = _store(streams, stream, policy_id)
    try:
        version = store.save(policy_id, body.content, body.note, body.created_by, json.loads(SAMPLE_PATH.read_text()))
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"version": version}


class ActivateRequest(BaseModel):
    version: int
    approved_by: str


@router.post("/policies/{policy_id}/activate")
def activate_policy_version(
    policy_id: str, body: ActivateRequest, stream: str = HOUSE, streams: StreamStore = Depends(get_stream_store)
) -> dict:
    store = _store(streams, stream, policy_id)
    try:
        return store.activate(policy_id, body.version, body.approved_by)
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/catalogue")
def get_catalogue() -> dict:
    return load("policy_issue_catalogue.json")


@router.get("/studio/coverage/inputs")
def coverage_inputs(engagements: EngagementStore = Depends(get_engagement_store)) -> dict:
    """The per-company inputs the coverage rules see (for the rule editor's live preview)."""
    return {"contexts": tier_contexts(json.loads(SAMPLE_PATH.read_text()), engagements.list_all())}


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
            json.loads(SAMPLE_PATH.read_text()),
            engagements.list_all(),
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(422, f"The coverage rules do not run: {exc}") from exc


class VotingPreviewRequest(BaseModel):
    policy: dict


@router.post("/studio/voting/preview")
def post_voting_preview(body: VotingPreviewRequest, streams: StreamStore = Depends(get_stream_store)) -> dict:
    try:
        return voting_preview(body.policy, PolicyStore(streams.root).active("house_voting"), json.loads(SAMPLE_PATH.read_text()))
    except (ValueError, KeyError, RuntimeError) as exc:
        raise HTTPException(422, f"The voting policy does not run: {exc}") from exc


@router.get("/studio/monitoring/triggers")
def monitoring_triggers(
    streams: StreamStore = Depends(get_stream_store), engagements: EngagementStore = Depends(get_engagement_store)
) -> dict:
    """The triggers the active monitoring rules raise, matched to open engagements."""
    sample = json.loads(SAMPLE_PATH.read_text())
    return {"triggers": monitoring.evaluate(PolicyStore(streams.root).active("monitoring_rules"), sample, engagements.list_all())}


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
            json.loads(SAMPLE_PATH.read_text()),
            engagements.list_all(),
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(422, f"The monitoring rules do not run: {exc}") from exc


class OpenFromTriggerRequest(BaseModel):
    issuer_id: str
    rule: str
    decided_by: str


@router.post("/monitoring/open-engagement")
def open_engagement_from_trigger(
    body: OpenFromTriggerRequest,
    streams: StreamStore = Depends(get_stream_store),
    engagements: EngagementStore = Depends(get_engagement_store),
) -> dict:
    """Opens an engagement for a trigger the active rules raise. The theme and
    severity come from the rule, not the request."""
    if not body.decided_by.strip():
        raise HTTPException(422, "Opening an engagement needs decided_by")
    sample = json.loads(SAMPLE_PATH.read_text())
    triggers = monitoring.evaluate(PolicyStore(streams.root).active("monitoring_rules"), sample, engagements.list_all())
    trigger = next((t for t in triggers if t["issuer_id"] == body.issuer_id and t["rule"] == body.rule), None)
    if trigger is None:
        raise HTTPException(404, "The active monitoring rules raise no such trigger")
    if trigger["engagement_id"] is not None:
        raise HTTPException(409, f"Already attached to engagement {trigger['engagement_id']}")
    _, issue = engagements.open_issue(
        trigger["issuer_id"],
        trigger["company"],
        theme=trigger["theme"],
        severity=IssueSeverity(trigger["severity"]),
        source=TriggerSource.MONITORING_RULE,
        source_detail=f"{trigger['rule']}: {trigger['reason']} (opened by {body.decided_by})",
        sector=trigger["sector"],
    )
    return {"issue_id": issue.issue_id, "trigger": {**trigger, "engagement_id": issue.issue_id}}


def _escalation_contexts(settings: Settings, streams: StreamStore, engagements: EngagementStore) -> list[dict]:
    return escalation_contexts(
        streams.root, json.loads(SAMPLE_PATH.read_text()), engagements.list_all(), settings.engagement_sla_days
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
    decided_by: str
    note: str = ""


@router.post("/streams/{stream_id}/exceptions")
def decide_client_exception(
    stream_id: str,
    body: ExceptionDecisionRequest,
    settings: Settings = Depends(settings_dep),
    streams: StreamStore = Depends(get_stream_store),
    engagements: EngagementStore = Depends(get_engagement_store),
) -> dict:
    """The house decides a client's escalation above its own step: adopt moves the
    engagement to the client's step; decline keeps the house step. Both are logged
    on the stream, so the client report can show them."""
    if not body.decided_by.strip():
        raise HTTPException(422, "A decision needs decided_by")
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
            body.decided_by,
            f"Adopted from {stream['name']}: {item['reason']} ({item['rule']})",
        )
    row = {
        "issue_id": item["issue_id"],
        "company_id": item["company_id"],
        "theme": item["theme"],
        "house_step": item["house_recommended"],
        "client_step": item["recommended"],
        "decision": body.decision,
        "decided_by": body.decided_by,
        "note": body.note,
        "decided_at": datetime.now(UTC).isoformat(),
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
    path = build_pptx(report, tmp / f"{stream_id}-stewardship-report.pptx")
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
    return simulate(streams.root, stream, engagements.list_all(), settings.engagement_sla_days, body.params.model_dump())


class SaveProgramRequest(ProgramRequest):
    updated_by: str


@router.put("/streams/{stream_id}/program")
def put_program(stream_id: str, body: SaveProgramRequest, streams: StreamStore = Depends(get_stream_store)) -> dict:
    if not body.updated_by.strip():
        raise HTTPException(422, "Saving a calibration needs updated_by")
    stream = _stream_or_404(streams, stream_id)
    program = {"params": body.params.model_dump(), "updated_by": body.updated_by, "updated_at": datetime.now(UTC).isoformat()}
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
    path = build_proposal(sim, tmp / f"{stream_id}-program-proposal.pptx")
    background.add_task(shutil.rmtree, tmp, ignore_errors=True)
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )
