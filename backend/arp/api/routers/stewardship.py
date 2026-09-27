from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from arp.api.deps import get_engagement_store, get_stream_store, settings_dep
from arp.config import Settings
from arp.schemas.engagement import IssueSeverity, TriggerSource
from arp.stewardship import monitoring
from arp.stewardship.policies import POLICIES, PolicyStore, coverage_preview, voting_preview
from arp.stewardship.policy_review import DATA, load
from arp.stewardship.process import (
    HOUSE,
    SAMPLE_PATH,
    StreamStore,
    build_stream_policy,
    confirm_tiers,
    flow,
    record_decision,
    tier_review,
)
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


def _policy_or_404(policy_id: str) -> str:
    if policy_id not in POLICIES:
        raise HTTPException(404, "Unknown policy")
    return policy_id


@router.get("/policies/{policy_id}")
def get_policy(policy_id: str, streams: StreamStore = Depends(get_stream_store)) -> dict:
    store = PolicyStore(streams.root)
    _policy_or_404(policy_id)
    active = store.active_version(policy_id)
    return {
        "policy_id": policy_id,
        "active_version": active,
        "active": store.content(policy_id, active),
        "versions": store.versions(policy_id),
        "activations": store.activations(policy_id),
    }


@router.get("/policies/{policy_id}/versions/{version}")
def get_policy_version(policy_id: str, version: int, streams: StreamStore = Depends(get_stream_store)) -> dict:
    try:
        return PolicyStore(streams.root).content(_policy_or_404(policy_id), version)
    except KeyError as exc:
        raise HTTPException(404, "Unknown version") from exc


class SavePolicyRequest(BaseModel):
    content: dict
    note: str = ""
    created_by: str


@router.post("/policies/{policy_id}/versions")
def save_policy_version(policy_id: str, body: SavePolicyRequest, streams: StreamStore = Depends(get_stream_store)) -> dict:
    try:
        version = PolicyStore(streams.root).save(
            _policy_or_404(policy_id), body.content, body.note, body.created_by, json.loads(SAMPLE_PATH.read_text())
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"version": version}


class ActivateRequest(BaseModel):
    version: int
    approved_by: str


@router.post("/policies/{policy_id}/activate")
def activate_policy_version(policy_id: str, body: ActivateRequest, streams: StreamStore = Depends(get_stream_store)) -> dict:
    try:
        return PolicyStore(streams.root).activate(_policy_or_404(policy_id), body.version, body.approved_by)
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
