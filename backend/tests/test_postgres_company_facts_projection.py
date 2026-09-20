"""Pure-logic unit tests for fact_candidates/resolve_fact -- the two
functions that determine WHAT gets materialized and WHAT its status is,
verified against the actual results.jsonl row shapes and item_key
conventions each pipeline uses (arp/research/pipeline.py,
arp/voting/pipeline.py). No real Postgres instance required. The
DB-write half (materialize_run/materialize_all) needs a real instance
and is covered separately, gated on ARP_TEST_POSTGRES_DSN."""

from __future__ import annotations

from arp.storage.postgres_company_facts_projection import fact_candidates, resolve_fact


def test_fact_candidates_returns_empty_without_key():
    assert fact_candidates("extraction", {"foo": "bar"}) == []


def test_fact_candidates_extraction_is_whole_row_at_company_level():
    row = {"_key": "acme", "field_id": "scope_1_emissions", "needs_review": True}
    candidates = fact_candidates("extraction", row)
    assert candidates == [("acme", row)]


def test_fact_candidates_financials_is_whole_row_at_company_level():
    row = {"_key": "acme", "capex_total": 1_000_000}
    candidates = fact_candidates("financials", row)
    assert candidates == [("acme", row)]


def test_fact_candidates_theme_splits_by_activity_id():
    row = {
        "_key": "acme",
        "company_matches": [
            {"company_id": "acme", "activity_id": "act_1", "flagged_for_review": False},
            {"company_id": "acme", "activity_id": "act_2", "flagged_for_review": True},
        ],
    }
    candidates = fact_candidates("theme", row)
    assert [c[0] for c in candidates] == ["acme:act_1", "acme:act_2"]
    assert candidates[0][1]["activity_id"] == "act_1"


def test_fact_candidates_theme_row_has_no_top_level_company_id():
    """Regression guard: the theme results.jsonl row shape is
    {"company_matches": [...], "_key": company_id} -- NOT a top-level
    company_id field. A generic reader must use "_key", never
    row.get("company_id"), or it silently drops every theme fact."""
    row = {"_key": "acme", "company_matches": [{"activity_id": "act_1"}]}
    assert fact_candidates("theme", row) == [("acme:act_1", {"activity_id": "act_1"})]


def test_fact_candidates_voting_splits_by_proposal_number():
    row = {
        "_key": "acme",
        "votes": [
            {"proposal": {"proposal_number": "3", "company_id": "acme"}, "vote_record_id": "v1"},
            {"proposal": {"proposal_number": "4", "company_id": "acme"}, "vote_record_id": "v2"},
        ],
    }
    candidates = fact_candidates("proxy_voting", row)
    assert [c[0] for c in candidates] == ["acme:3", "acme:4"]
    assert candidates[0][1]["vote_record_id"] == "v1"


def test_fact_candidates_voting_skips_votes_without_proposal_number():
    row = {"_key": "acme", "votes": [{"proposal": {}, "vote_record_id": "v1"}]}
    assert fact_candidates("proxy_voting", row) == []


def test_fact_candidates_unknown_run_type_falls_back_to_whole_row():
    row = {"_key": "acme", "anything": True}
    assert fact_candidates("some_future_run_type", row) == [("acme", row)]


# --- resolve_fact ---------------------------------------------------------

_RAW_VALUE = {"value": "42"}


def test_resolve_fact_approve():
    decisions = {"acme": {"decision": "approve", "reviewer": "alice"}}
    value, status, reviewer = resolve_fact("acme", _RAW_VALUE, decisions, set())
    assert value == _RAW_VALUE
    assert status == "approved"
    assert reviewer == "alice"


def test_resolve_fact_edit_uses_edited_value():
    edited = {"value": "43"}
    decisions = {"acme": {"decision": "edit", "reviewer": "bob", "edited_value": edited}}
    value, status, reviewer = resolve_fact("acme", _RAW_VALUE, decisions, set())
    assert value == edited
    assert status == "edited"
    assert reviewer == "bob"


def test_resolve_fact_edit_without_edited_value_falls_back_to_raw():
    decisions = {"acme": {"decision": "edit", "reviewer": "bob", "edited_value": None}}
    value, status, _ = resolve_fact("acme", _RAW_VALUE, decisions, set())
    assert value == _RAW_VALUE
    assert status == "edited"


def test_resolve_fact_reject_is_still_returned():
    decisions = {"acme": {"decision": "reject", "reviewer": "carol"}}
    value, status, reviewer = resolve_fact("acme", _RAW_VALUE, decisions, set())
    assert value == _RAW_VALUE
    assert status == "rejected"
    assert reviewer == "carol"


def test_resolve_fact_queued_but_no_decision_is_pending_review():
    value, status, reviewer = resolve_fact("acme", _RAW_VALUE, decisions={}, queued_item_keys={"acme"})
    assert value == _RAW_VALUE
    assert status == "pending_review"
    assert reviewer is None


def test_resolve_fact_never_queued_is_auto_approved():
    value, status, reviewer = resolve_fact("acme", _RAW_VALUE, decisions={}, queued_item_keys=set())
    assert value == _RAW_VALUE
    assert status == "auto_approved"
    assert reviewer is None
