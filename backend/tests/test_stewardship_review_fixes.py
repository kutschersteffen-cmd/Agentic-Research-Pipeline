"""Regressions from the PR #41 review: client streams must survive a new house
voting policy, and misspelt client parameters must be rejected."""

from __future__ import annotations

import copy
import json

import pytest

pytest.importorskip("zen")

from arp.stewardship.policies import PolicyStore  # noqa: E402
from arp.stewardship.policy_review import DATA, review  # noqa: E402
from arp.stewardship.process import HOUSE, SAMPLE_PATH, StreamStore, build_stream_policy, flow, record_decision  # noqa: E402

SAMPLE = json.loads(SAMPLE_PATH.read_text())
CLIENT = json.loads((DATA / "examples" / "client_policy_example.json").read_text())
DECISIONS = json.loads((DATA / "examples" / "client_policy_example_decisions.json").read_text())


def _house_matching_client_on(issue_id: str, store: PolicyStore) -> dict:
    """A house version that takes over the client's position on one issue."""
    house = copy.deepcopy(store.active("house_voting"))
    row = next(r for r in review(CLIENT, house)["register"] if r["issue_id"] == issue_id)
    for p in house["positions"]:
        if p["issue_id"] == issue_id:
            p.update({k: row["client_position"][k] for k in ("action", "vote_target", "parameters", "scope")})
    return house


def test_a_new_house_version_sets_stale_decisions_aside_instead_of_breaking_the_stream(tmp_path):
    streams = StreamStore(tmp_path)
    stream = streams.create("Example Pension Fund", CLIENT, "SMA")
    stream = streams.save({**stream, "decisions": DECISIONS})
    adopted = next(d["issue_id"] for d in DECISIONS if d["decision"] == "adopt")

    store = PolicyStore(tmp_path)
    store.activate(
        "house_voting", store.save("house_voting", _house_matching_client_on(adopted, store), "", "Designer", SAMPLE), "Approver"
    )

    stages = {s["id"]: s for s in flow(stream["stream_id"], streams, [], sla_days=45)["stages"]}  # used to raise
    metrics = {m["label"]: m["value"] for m in stages["client_policy"]["metrics"]}
    assert metrics["Decisions set aside"] == 1
    assert {m["label"]: m["value"] for m in flow(HOUSE, streams, [], 45)["stages"][6]["metrics"]}["Decisions open"] == metrics[
        "To decide"
    ]

    other = next(d for d in DECISIONS if d["issue_id"] != adopted)
    record_decision(stream, {**other, "note": "re-decided"}, store.active("house_voting"))  # used to raise
    built = build_stream_policy(stream, store.active("house_voting"))  # the stale row is identical now: nothing to decide
    assert built["built_policy"]["positions"]


def test_misspelt_client_parameters_are_rejected():
    client = copy.deepcopy(CLIENT)
    position = next(p for p in client["positions"] if p.get("parameters"))
    position["parameters"] = {**position["parameters"], "min_independant_pct": 75}
    with pytest.raises(ValueError, match="min_independant_pct"):
        review(client)


def test_a_stance_issue_votes_the_position_action_when_it_is_not_for():
    from arp.stewardship.backtest import backtest
    from arp.stewardship.policy_review import load

    house = load("house_voting_policy_draft.json")
    against = copy.deepcopy(house)
    for p in against["positions"]:
        if p["issue_id"] == "climate.shareholder_proposals":
            p["action"] = "against"
    bt = backtest(house, against, SAMPLE)
    assert bt["changed"] > 0 and bt["affected_by_issue"].get("climate.shareholder_proposals", 0) == bt["changed"]
    from arp.stewardship.policy_graph import generate

    assert "default_action" in generate(against)["unused_parameters"]["climate.shareholder_proposals"]  # said, not silent
