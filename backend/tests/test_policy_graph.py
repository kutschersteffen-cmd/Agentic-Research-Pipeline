from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("zen")

from arp.stewardship.policy_graph import evaluate, generate, issuer_fields  # noqa: E402
from arp.stewardship.policy_review import load  # noqa: E402

EXAMPLES = Path(__file__).resolve().parents[1] / "arp" / "stewardship" / "data" / "examples"


@pytest.fixture(scope="module")
def house():
    return generate(load("house_voting_policy_draft.json"))["graph"]


def _vote(graph: dict, resolution: dict, issuer: dict | None = None, engagement: dict | None = None) -> dict:
    return evaluate(graph, [{"issuer": issuer or {}, "resolution": resolution, "engagement": engagement or {}}])[0]


NOM_CHAIR = {"category": "director_election", "roles": ["nomination_committee_chair"], "management_recommendation": "for"}


def test_red_flag_fires_on_the_target_and_names_the_issue(house):
    result = _vote(house, NOM_CHAIR, {"governance": {"board_independence_pct": 45}})
    assert result["expected_vote"] == "against"
    assert result["decided_by"] == ["board.independence"]


def test_red_flag_does_not_hit_a_director_who_is_not_the_target(house):
    ordinary = {**NOM_CHAIR, "roles": []}
    assert _vote(house, ordinary, {"governance": {"board_independence_pct": 45}})["expected_vote"] == "for"


def test_missing_data_never_fires_and_never_fails(house):
    for category in load("policy_issue_catalogue.json")["resolution_categories"]:
        result = _vote(house, {"category": category, "roles": ["board_chair"], "director": {}})
        assert result["expected_vote"] in ("for", "case_by_case"), category


def test_no_hit_follows_management(house):
    shp = {"category": "shareholder_proposal_social", "management_recommendation": "against"}
    # social proposals are case_by_case in the house draft; an unrelated category follows management
    assert _vote(house, shp)["expected_vote"] == "case_by_case"
    assert _vote(house, {"category": "dividend_allocation", "management_recommendation": "against"})["expected_vote"] == "against"


def test_market_specific_threshold(house):
    board = {"governance": {"board_female_pct": 35}}
    assert _vote(house, NOM_CHAIR, {**board, "region": "EU"})["expected_vote"] == "against"  # EU needs 40
    assert _vote(house, NOM_CHAIR, {**board, "region": "US"})["expected_vote"] == "for"  # elsewhere 30


def test_overboarding_counts_chair_roles_double(house):
    director = {"category": "director_election", "roles": [], "director": {"is_executive": False, "chair_mandates": 1}}
    assert _vote(house, {**director, "director": {**director["director"], "mandates": 4}})["expected_vote"] == "for"  # 4 + 1 = 5
    assert _vote(house, {**director, "director": {**director["director"], "mandates": 5}})["expected_vote"] == "against"  # 6


def test_stance_with_override(house):
    climate_shp = {"category": "shareholder_proposal_environmental", "management_recommendation": "against"}
    assert _vote(house, climate_shp)["expected_vote"] == "for"
    assert _vote(house, {**climate_shp, "prescriptive": True})["expected_vote"] == "against"


def test_engagement_at_vote_step_targets_the_theme_director(house):
    chair = {"category": "director_election", "roles": ["board_chair"], "management_recommendation": "for"}
    engagement = {"climate_transition": {"at_vote_step": True}}
    result = _vote(house, chair, engagement=engagement)
    assert result["expected_vote"] == "against"
    assert result["decided_by"] == ["stewardship.engagement_escalation"]
    assert _vote(house, {**chair, "roles": ["audit_committee_chair"]}, engagement=engagement)["expected_vote"] == "for"


def test_escalate_positions_have_no_vote_rule_and_unused_parameters_are_reported():
    result = generate(load("house_voting_policy_draft.json"))
    assert result["no_vote_effect"] == ["nature.laggard_accountability", "nature.disclosure"]
    assert "require_prior_notice" in result["unused_parameters"]["stewardship.engagement_escalation"]


def test_client_policy_graph_applies_client_values(house):
    client = generate(json.loads((EXAMPLES / "client_policy_example_built.json").read_text()))["graph"]
    board = {"governance": {"board_independence_pct": 60}}
    assert _vote(house, NOM_CHAIR, board)["expected_vote"] == "for"  # house: 50%
    assert _vote(client, NOM_CHAIR, board)["expected_vote"] == "against"  # client: 66%


def test_catalogue_data_fields_match_what_the_rules_read():
    for issue in load("policy_issue_catalogue.json")["issues"]:
        read = set(issuer_fields(issue["issue_id"]))
        assert read <= set(issue["data_fields"]), issue["issue_id"]
