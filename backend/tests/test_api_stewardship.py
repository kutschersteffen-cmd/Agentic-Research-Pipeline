from __future__ import annotations

import pytest
from fastapi import HTTPException

pytest.importorskip("zen")

from arp.api.routers.stewardship import (  # noqa: E402
    CreateStreamRequest,
    PolicyDecisionRequest,
    create_stream,
    list_streams,
    post_build,
    post_decision,
)
from arp.stewardship.process import HOUSE, StreamStore, flow  # noqa: E402
from arp.storage.engagement_store import EngagementStore  # noqa: E402
from tests.conftest import PRINCIPAL

pytestmark = pytest.mark.usefixtures("sample_house_universe", "pg")


@pytest.fixture
def streams(tmp_path):
    return StreamStore(tmp_path / "streams")


def _stage(result: dict, stage_id: str) -> dict:
    return next(s for s in result["stages"] if s["id"] == stage_id)


def test_house_flow_has_all_stages_with_sourced_metrics(streams, tmp_path):
    engagements = EngagementStore(tmp_path / "engagements")
    engagements.open_issue("ACME", "Acme", theme="climate_transition")
    result = flow(HOUSE, streams, engagements.list_all(), sla_days=-1)  # every open issue is stalled
    assert [s["number"] for s in result["stages"]] == list(range(1, 9))
    assert all(m["source"] in ("live", "sample", "not_built") for s in result["stages"] for m in s["metrics"])
    decisions = [d for d in _stage(result, "checkpoint")["decisions"] if d["kind"] == "escalation"]
    assert [(d["company_id"], d["current"], d["next"]) for d in decisions] == [("ACME", "private_engagement", "written_escalation_to_board")]


def test_client_stream_decide_every_difference_then_build(streams, tmp_path):
    created = create_stream(CreateStreamRequest(name="Example Pension Fund", vehicle_type="SMA"), streams)
    assert [s["kind"] for s in list_streams(streams)["streams"]] == ["house", "client"]
    stream_id = created["stream_id"]

    result = flow(stream_id, streams, [], sla_days=45)
    open_items = [d for d in _stage(result, "client_policy")["decisions"] if d["decision"] is None]
    assert open_items and not _stage(result, "client_policy")["can_build"]
    with pytest.raises(HTTPException):
        post_build(stream_id, streams)  # undecided differences

    for item in open_items:
        decision = "clarify" if item["difference"] in ("unclear", "unmapped") else "adopt"
        post_decision(
            PolicyDecisionRequest(issue_id=item["issue_id"], decision=decision), stream_id, streams, PRINCIPAL
        )
    assert _stage(flow(stream_id, streams, [], sla_days=45), "client_policy")["can_build"]
    assert post_build(stream_id, streams)["positions_from_client"] > 0
    assert _stage(flow(stream_id, streams, [], sla_days=45), "reporting")["metrics"][0]["value"] == "built"


def test_invalid_decision_is_rejected(streams):
    stream_id = create_stream(CreateStreamRequest(name="X"), streams)["stream_id"]
    with pytest.raises(HTTPException) as exc:
        post_decision(PolicyDecisionRequest(issue_id="board.attendance", decision="adopt"), stream_id, streams, PRINCIPAL)
    assert exc.value.status_code == 422


def test_stream_ids_cannot_escape_the_directory(streams):
    with pytest.raises(ValueError):
        streams.get("../../etc")


def test_approved_program_versions_read_old_tier_keys_as_the_new_ones(streams, tmp_path):
    # AC-19: mapped on read, the stored stream is not rewritten
    from arp.api.routers.stewardship import get_program
    from arp.config import Settings

    stream = streams.get(create_stream(CreateStreamRequest(name="client-s"), streams)["stream_id"])
    target = {"issuer_id": "SYN01", "company": "Synthetic Company 01", "theme": "climate_transition", "tier": "scaled_baseline"}
    streams.save({**stream, "program_versions": [{"version": 1, "params": {}, "targets": [target], "kpis": {}}]})
    got = get_program(stream["stream_id"], Settings(), streams, EngagementStore(tmp_path / "e"))
    assert [t["tier"] for t in got["versions"][0]["targets"]] == ["letter"]
    assert streams.get(stream["stream_id"])["program_versions"][0]["targets"][0]["tier"] == "scaled_baseline"
