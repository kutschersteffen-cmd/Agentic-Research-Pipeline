from __future__ import annotations

import json

import pytest

pytest.importorskip("zen")
pptx = pytest.importorskip("pptx")

from pydantic import ValidationError  # noqa: E402

from arp.api.routers.stewardship import CreateStreamRequest, create_stream  # noqa: E402
from arp.stewardship.escalation import load_client_example  # noqa: E402
from arp.stewardship.process import SAMPLE_PATH, StreamStore, client_store  # noqa: E402
from arp.stewardship.program import ProgramParams, approve, build_proposal, monitor, record_run, simulate  # noqa: E402
from arp.storage.engagement_store import EngagementStore  # noqa: E402

SAMPLE = json.loads(SAMPLE_PATH.read_text())


@pytest.fixture
def stream(tmp_path):
    streams = StreamStore(tmp_path)
    return streams, streams.get(create_stream(CreateStreamRequest(name="Example Pension Fund"), streams)["stream_id"])


def test_tilt_moves_weight_to_clti_leaders_and_keeps_weights_whole(stream):
    streams, s = stream
    sim = simulate(streams.root, s, [], 45)
    assert sum(h["portfolio_pct"] for h in sim["holdings"]) == pytest.approx(100, abs=0.01)
    assert sim["kpis"]["clti_uplift"] > 0
    flat = simulate(streams.root, s, [], 45, {"tilt_floor": 1, "tilt_ceiling": 1})
    assert flat["kpis"]["clti_uplift"] == 0 and flat["kpis"]["active_share_pct"] == 0


def test_targets_are_ranked_by_leverage_and_capped(stream):
    streams, s = stream
    sim = simulate(streams.root, s, [], 45, {"max_targets": 3})
    assert len(sim["targets"]) == 3 and sim["candidates"] > 3
    assert [t["leverage"] for t in sim["targets"]] == sorted((t["leverage"] for t in sim["targets"]), reverse=True)
    no_triggers = simulate(streams.root, s, [], 45, {"include_triggers": False, "max_targets": 50})
    assert {t["theme"] for t in no_triggers["targets"]} == {"climate_transition"}


def test_client_escalation_to_the_vote_step_becomes_an_expected_sanction(stream):
    streams, s = stream
    store = client_store(streams.root, s["stream_id"])
    store.activate("escalation_rules", store.save("escalation_rules", load_client_example(), "", "Designer", SAMPLE), "Approver")
    sim = simulate(streams.root, s, [], 45, {"max_targets": 50})
    [syn10] = [t for t in sim["targets"] if (t["issuer_id"], t["theme"]) == ("SYN10", "climate_transition")]
    assert syn10["client_step"] == "vote_against_management" and syn10["at_vote_step"] and syn10["above_house"]
    assert any(v["sanction"] == "yes" and v["company"] == "Synthetic Company 10" for v in sim["votes"])
    assert sim["kpis"]["sanctions"] >= 1


def test_house_checks_flag_capacity_and_pooled_vehicles(tmp_path):
    streams = StreamStore(tmp_path)
    pooled = streams.get(create_stream(CreateStreamRequest(name="Pooled Fund", vehicle_type="CCF"), streams)["stream_id"])
    checks = {c["check"]: c["status"] for c in simulate(streams.root, pooled, [], 45, {"free_capacity_days": 0})["checks"]}
    assert checks["Marginal workload"] == "red"
    assert checks["Vote conflicts"] == "red"  # the example policy differs from the house, and a CCF votes one way


def test_invalid_calibration_is_rejected():
    with pytest.raises(ValidationError):
        ProgramParams(tilt_floor=2, tilt_ceiling=1)


def test_proposal_deck_has_every_section(stream, tmp_path):
    streams, s = stream
    deck = pptx.Presentation(build_proposal(simulate(streams.root, s, [], 45), tmp_path / "p.pptx"))
    titles = [x.shapes.title.text for x in deck.slides]
    for heading in ("Engagement targets", "Escalation: house and client steps", "Feasibility against the house program"):
        assert heading in titles


def _save(streams, s, params, by="Designer"):
    return streams.save({**s, "program": {"params": ProgramParams(**params).model_dump(), "updated_by": by, "updated_at": "x"}})


def test_approval_needs_a_saved_calibration_and_a_second_person(stream):
    streams, s = stream
    with pytest.raises(ValueError, match="Save a calibration"):
        approve(streams.root, s, [], 45, "Approver")
    s = _save(streams, s, {"max_targets": 3})
    with pytest.raises(ValueError, match="Four-eyes"):
        approve(streams.root, s, [], 45, "designer")
    s = approve(streams.root, s, [], 45, "Approver")
    [v] = s["program_versions"]
    assert v["version"] == 1 and len(v["targets"]) == 3 and v["proposed_by"] == "Designer"


def test_monitoring_flags_new_targets_and_engagement_state_against_the_frozen_list(stream):
    streams, s = stream
    assert monitor(streams.root, s, [], 45) == {"approved": None}
    s = approve(streams.root, _save(streams, s, {"max_targets": 3}), [], 45, "Approver")
    calm = {a["kpi"]: a["status"] for a in monitor(streams.root, s, [], 45)["alerts"]}
    assert calm["Target membership"] == "green" and calm["Sanction conformance"] == "not_built"
    assert calm["Engagements not started"] == "amber"  # client-only targets nobody has opened yet

    engagements = EngagementStore(streams.root / "e")
    first = s["program_versions"][0]["targets"][0]
    engagements.open_issue(first["issuer_id"], first["company"], theme=first["theme"])
    result = monitor(streams.root, s, engagements.list_all(), sla_days=-1)  # every open engagement is stalled
    row = next(
        r for r in result["targets"] if r["company"] == first["company"] and r["theme"] == first["theme"].replace("_", " ")
    )
    assert row["engagement"] == "stalled"
    assert {a["kpi"]: a["status"] for a in result["alerts"]}["Engagement progress"] == "amber"

    # the approved list stays frozen: a wider calibration saved later does not change what is monitored
    s = streams.save({**s, "program": {**s["program"], "params": {**s["program"]["params"], "max_targets": 10}}})
    later = monitor(streams.root, s, [], 45)
    assert later["calibration_changed"] and len(later["targets"]) == 3


def test_recorded_runs_build_the_kpi_series(stream):
    streams, s = stream
    with pytest.raises(ValueError):
        record_run(s, monitor(streams.root, s, [], 45), "Analyst")
    s = approve(streams.root, _save(streams, s, {}), [], 45, "Approver")
    s = record_run(record_run(s, monitor(streams.root, s, [], 45), "Analyst"), monitor(streams.root, s, [], 45), "Analyst")
    assert [r["version"] for r in s["program_runs"]] == [1, 1] and "clti_uplift" in s["program_runs"][0]["kpis"]
