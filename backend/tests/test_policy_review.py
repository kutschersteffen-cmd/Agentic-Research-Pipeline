from __future__ import annotations

import pytest

from arp.stewardship.policy_review import build, decide, load, review


def _row(result: dict, issue_id: str) -> dict:
    return next(r for r in result["register"] if r["issue_id"] == issue_id)


def test_direction_comes_from_catalogue_parameter_direction():
    result = review(
        {
            "positions": [
                {"issue_id": "board.independence", "parameters": {"min_independent_pct": 66}},  # min_: higher is stricter
                {
                    "issue_id": "audit.non_audit_fees",
                    "parameters": {"max_non_audit_to_audit_ratio": 2.0},
                },  # max_: higher is looser
                {"issue_id": "social.human_rights", "parameters": {"min_controversy_severity": 4}},  # override: lower is stricter
            ]
        }
    )
    assert _row(result, "board.independence")["kind"] == "stricter"
    assert _row(result, "audit.non_audit_fees")["kind"] == "looser"
    assert _row(result, "social.human_rights")["kind"] == "stricter"


def test_unstated_parameters_inherit_house_and_silence_is_house_only():
    result = review({"positions": [{"issue_id": "board.overboarding", "parameters": {"max_mandates_non_executive": 4}}]})
    changes = _row(result, "board.overboarding")["changes"]
    assert [c["field"] for c in changes] == ["max_mandates_non_executive"]
    assert _row(result, "board.attendance")["kind"] == "house_only"


def test_shareholder_proposal_issues_invert_management_direction():
    # On a shareholder proposal, moving from "for" to "against" means siding with management.
    result = review({"positions": [{"issue_id": "gov.shareholder_proposals", "action": "against"}]})
    assert _row(result, "gov.shareholder_proposals")["assessment"]["direction"] == "fewer_against_management"


def test_pooled_vehicle_cannot_deliver_deviations():
    result = review(
        {
            "mandate": {"vehicle_type": "CCF"},
            "positions": [{"issue_id": "board.independence", "parameters": {"min_independent_pct": 66}}],
        }
    )
    assert _row(result, "board.independence")["assessment"]["recommendation"] == "decline_or_change_vehicle"
    assert result["summary"]["not_deliverable"] == 1


def test_process_only_change_needs_no_separate_vote():
    result = review(
        {"positions": [{"issue_id": "stewardship.engagement_escalation", "parameters": {"require_prior_notice": False}}]}
    )
    assessment = _row(result, "stewardship.engagement_escalation")["assessment"]
    assert assessment["split_vote"] == "none"
    assert assessment["recommendation"] == "review_with_house"


def test_unknown_issue_is_rejected():
    with pytest.raises(ValueError):
        review({"positions": [{"issue_id": "board.nonexistent"}]})


def _decided(decisions: list[dict], positions: list[dict]) -> dict:
    return decide(review({"policy_id": "c", "positions": positions}), decisions)


_STRICTER = [{"issue_id": "board.independence", "parameters": {"min_independent_pct": 66}, "source": "Two-thirds independent."}]


def test_build_applies_adopted_differences_and_keeps_house_elsewhere():
    policy = build(_decided([{"issue_id": "board.independence", "decision": "adopt", "decided_by": "x"}], _STRICTER))
    positions = {p["issue_id"]: p for p in policy["positions"]}
    assert positions["board.independence"]["parameters"]["min_independent_pct"] == 66
    assert positions["board.independence"]["origin"] == "client"
    assert positions["board.independence"]["rationale"] == "Two-thirds independent."
    assert positions["board.attendance"]["origin"] == "house"
    assert len(positions) == len(load("policy_issue_catalogue.json")["issues"])


def test_build_refuses_undecided_differences():
    with pytest.raises(ValueError, match="Undecided"):
        build(review({"policy_id": "c", "positions": _STRICTER}))


def test_decline_and_defer_keep_the_house_position():
    for decision in ("decline", "defer"):
        policy = build(_decided([{"issue_id": "board.independence", "decision": decision, "decided_by": "x"}], _STRICTER))
        independence = next(p for p in policy["positions"] if p["issue_id"] == "board.independence")
        assert independence["origin"] == "house"
        assert independence["parameters"]["min_independent_pct"] == 50
    assert [o["issue_id"] for o in policy["open_items"]] == ["board.independence"]  # defer stays open


def test_modification_is_applied_and_validated():
    ok = [
        {
            "issue_id": "board.independence",
            "decision": "adopt_with_modification",
            "decided_by": "x",
            "modification": {"parameters": {"min_independent_pct": 60}},
        }
    ]
    policy = build(_decided(ok, _STRICTER))
    assert (
        next(p for p in policy["positions"] if p["issue_id"] == "board.independence")["parameters"]["min_independent_pct"] == 60
    )
    bad = [{**ok[0], "modification": {"vote_target": "say_on_pay"}}]  # not a target of this issue
    with pytest.raises(ValueError, match="vote target"):
        build(_decided(bad, _STRICTER))


def test_decision_must_fit_the_kind_of_row():
    with pytest.raises(ValueError, match="not valid"):
        _decided([{"issue_id": "board.attendance", "decision": "adopt", "decided_by": "x"}], _STRICTER)  # house_only row
