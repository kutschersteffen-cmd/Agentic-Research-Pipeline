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


def _extraction_row():
    return {"_key": "acme", "issuer_key": "ARP:x", "fields": [{"field_id": "a", "value": 1}, {"field_id": "b", "value": 2}]}


def test_extraction_fact_resolves_per_field_decisions():
    from arp.storage.postgres_company_facts_projection import resolve_extraction_fact

    row = _extraction_row()
    key_b = "ARP:x:b:unspecified"
    assert resolve_extraction_fact("acme", row, {}, set())[1] == "auto_approved"
    assert resolve_extraction_fact("acme", row, {}, {key_b})[1] == "pending_review"
    edit = {key_b: {"decision": "edit", "reviewer": "r", "edited_value": {"field_id": "b", "value": 5}}}
    value, status, reviewer = resolve_extraction_fact("acme", row, edit, {key_b})
    assert (status, reviewer, value["fields"][1]["value"], value["fields"][0]["value"]) == ("edited", "r", 5, 1)
    assert resolve_extraction_fact("acme", row, {key_b: {"decision": "reject"}}, {key_b})[1] == "rejected"


def test_extraction_fact_still_resolves_old_company_level_key():
    from arp.storage.postgres_company_facts_projection import resolve_extraction_fact

    assert resolve_extraction_fact("acme", _extraction_row(), {}, {"acme"})[1] == "pending_review"


def test_extraction_partial_edit_merges_into_field_and_refolds():
    from arp.storage.postgres_company_facts_projection import resolve_extraction_fact

    row = _extraction_row()
    row["fields"][1].update(field_name="Beta", citations=[{"quote": "q"}])
    key_b = "ARP:x:b:unspecified"
    edit = {key_b: {"decision": "edit", "reviewer": "r", "edited_value": {"value": 5}}}
    value, status, _ = resolve_extraction_fact("acme", row, edit, {key_b})
    f = value["fields"][1]
    assert (status, f["field_id"], f["field_name"], f["citations"], f["value"]) == ("edited", "b", "Beta", [{"quote": "q"}], 5)
    assert resolve_extraction_fact("acme", value, edit, {key_b})[1] == "edited"  # refold: no KeyError


def test_extraction_approve_plus_edit_is_edited_and_only_edited_field_changes():
    from arp.storage.postgres_company_facts_projection import resolve_extraction_fact

    row = _extraction_row()
    ka, kb = "ARP:x:a:unspecified", "ARP:x:b:unspecified"
    decisions = {ka: {"decision": "approve"}, kb: {"decision": "edit", "edited_value": {"value": 7}}}
    value, status, _ = resolve_extraction_fact("acme", row, decisions, {ka, kb})
    assert status == "edited"
    assert [f["value"] for f in value["fields"]] == [1, 7]


def _two_period_row():
    return {
        "issuer_key": "ARP:x",
        "fields": [
            {"field_id": "a", "value": 10, "period_end": "2024-12-31"},
            {"field_id": "a", "value": 7, "period_end": "2023-12-31"},
        ],
    }


def test_projection_two_periods_same_field():
    from arp.storage.postgres_company_facts_projection import resolve_extraction_fact

    k23 = "ARP:x:a:2023-12-31"
    decisions = {k23: {"decision": "edit", "reviewer": "r", "edited_value": {"value": 8}}}
    value, status, _ = resolve_extraction_fact("acme", _two_period_row(), decisions, {k23, "ARP:x:a:2024-12-31"})
    assert status == "pending_review"  # FY2024 row is flagged but undecided
    assert [f["value"] for f in value["fields"]] == [10, 8]
    value, status, _ = resolve_extraction_fact("acme", _two_period_row(), decisions, {k23})
    assert status == "edited" and [f["value"] for f in value["fields"]] == [10, 8]


def test_projection_old_rows_without_period_unchanged():
    from arp.storage.postgres_company_facts_projection import resolve_extraction_fact

    row = {"issuer_key": "ARP:x", "fields": [{"field_id": "a", "value": 1}]}
    key = "ARP:x:a:unspecified"
    value, status, _ = resolve_extraction_fact("acme", row, {key: {"decision": "edit", "edited_value": {"value": 3}}}, {key})
    assert status == "edited" and value["fields"][0]["value"] == 3


def test_edit_supplying_value_clears_not_found():
    from arp.storage.postgres_company_facts_projection import resolve_extraction_fact

    row = {"issuer_key": "ARP:x", "fields": [{"field_id": "a", "value": None, "value_state": "not_found"}]}
    key = "ARP:x:a:unspecified"
    for edit, state in (({"value": 5}, "found"), ({"value": 0}, "zero"), ({"value": 5, "value_state": "not_applicable"}, "not_applicable")):
        value, _, _ = resolve_extraction_fact("acme", row, {key: {"decision": "edit", "edited_value": edit}}, {key})
        assert value["fields"][0]["value_state"] == state


def test_edit_with_value_only_clears_stale_canonical():
    from arp.storage.postgres_company_facts_projection import resolve_extraction_fact

    row = _extraction_row()
    row["fields"][1].update(canonical_value=1000, canonical_unit="kg")
    key_b = "ARP:x:b:unspecified"
    edit = {key_b: {"decision": "edit", "edited_value": {"value": 5}}}
    f = resolve_extraction_fact("acme", row, edit, {key_b})[0]["fields"][1]
    assert (f["value"], f["canonical_value"], f["canonical_unit"]) == (5, None, None)
    edit = {key_b: {"decision": "edit", "edited_value": {"value": 5, "canonical_value": 5, "canonical_unit": "kg"}}}
    f = resolve_extraction_fact("acme", row, edit, {key_b})[0]["fields"][1]
    assert (f["canonical_value"], f["canonical_unit"]) == (5, "kg")
