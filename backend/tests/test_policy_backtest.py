from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("zen")

from arp.stewardship.backtest import _nest, attach_impact, backtest, build_contexts  # noqa: E402
from arp.stewardship.policy_review import load, review  # noqa: E402

EXAMPLES = Path(__file__).resolve().parents[1] / "arp" / "stewardship" / "data" / "examples"


@pytest.fixture(scope="module")
def sample():
    return json.loads((EXAMPLES / "sample_meetings.json").read_text())


def test_flat_field_ids_become_nested_context():
    assert _nest({"governance.board_independence_pct": 55, "region_x": 1}) == {
        "governance": {"board_independence_pct": 55},
        "region_x": 1,
    }


def test_every_resolution_gets_a_context(sample):
    contexts = build_contexts(sample)
    assert len(contexts) == sum(len(m["resolutions"]) for m in sample["meetings"])
    assert len({rid for rid, _ in contexts}) == len(contexts)


def test_same_policy_changes_nothing(sample):
    house = load("house_voting_policy_draft.json")
    result = backtest(house, house, sample)
    assert result["changed"] == 0 and not result["affected_by_issue"]


def test_changed_votes_are_attributed_to_the_differing_issue(sample):
    house = load("house_voting_policy_draft.json")
    stricter = {
        **house,
        "positions": [
            {**p, "parameters": {**p["parameters"], "min_independent_pct": 101}} if p["issue_id"] == "board.independence" else p
            for p in house["positions"]
        ],
    }
    result = backtest(house, stricter, sample)
    assert result["changed"] > 0
    assert set(result["affected_by_issue"]) == {"board.independence"}
    assert all(r["issues"] == ["board.independence"] for r in result["rows"] if r["changed"])


def test_review_register_gets_impact(sample):
    client = json.loads((EXAMPLES / "client_policy_example.json").read_text())
    result = attach_impact(review(client), load("house_voting_policy_draft.json"), sample, "synthetic")
    impacts = [r["assessment"]["impact"] for r in result["register"] if "changes" in r and "assessment" in r]
    assert impacts and all(i["resolutions"] == result["summary"]["backtest"]["resolutions"] for i in impacts)
    assert sum(i["votes_changed"] for i in impacts) >= result["summary"]["backtest"]["changed"]
