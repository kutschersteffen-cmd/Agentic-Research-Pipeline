from __future__ import annotations

import json

import pytest

pytest.importorskip("zen")
pptx = pytest.importorskip("pptx")

from pydantic import ValidationError  # noqa: E402

from arp.api.routers.stewardship import CreateStreamRequest, create_stream  # noqa: E402
from arp.stewardship.escalation import load_client_example  # noqa: E402
from arp.stewardship.process import SAMPLE_PATH, StreamStore, client_store  # noqa: E402
from arp.stewardship.program import ProgramParams, build_proposal, simulate  # noqa: E402

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
