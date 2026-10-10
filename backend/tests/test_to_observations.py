from datetime import date
from uuid import uuid4

from arp.db.models import CitationRole, ValueState
from arp.db.to_observations import to_observations

CID = uuid4()


def _cite(doc_id, quote="q"):
    return {"doc_id": doc_id, "doc_type": "10-K", "quote": quote, "page": 3, "grounded": True, "content_key": "ck"}


def _field(period_end, value=100.0, **kw):
    return {"field_id": "revenue", "field_name": "Revenue", "value": value, "confidence": 0.9,
            "period_end": period_end, "route": "auto_accept", **kw}


def _record(*fields, **kw):
    return {"company_id": "acme", "name": "Acme", "schema_id": "s", "run_id": "r1", "fields": list(fields),
            "_key": "acme", **kw}


def test_extraction_one_observation_per_field_with_period():
    obs = to_observations("extraction", CID, "r1", _record(_field("2024-12-31"), _field("2023-12-31", 90.0)), trial=False)
    assert [(o.field_id, o.period_end, o.value) for o in obs] == [
        ("revenue", date(2024, 12, 31), 100.0), ("revenue", date(2023, 12, 31), 90.0),
    ]
    assert all(o.company_id == CID and o.run_id == "r1" and o.value_state == ValueState.FOUND for o in obs)


def test_extraction_citation_roles():
    f = _field("2024-12-31", citations=[_cite("d1"), _cite("d2")],
               alternatives=[{"value": 1.0, "source": "verifier", "citations": [_cite("d3")]}])
    (o,) = to_observations("extraction", CID, "r1", _record(f), trial=False)
    assert [(c.doc_id, c.role) for c in o.citations] == [
        ("d1", CitationRole.PRIMARY), ("d2", CitationRole.CORROBORATING), ("d3", CitationRole.ALTERNATIVE),
    ]
    assert o.citations[0].page == 3 and o.citations[0].content_key == "ck"


def test_theme_field_id():
    row = {"company_matches": [{"company_id": "acme", "name": "Acme", "activity_id": "A1", "activity_name": "a",
                                "verdict": "include", "exposure_estimate": "high", "confidence": 0.8,
                                "adjudicator_rationale": "x"}], "_key": "acme"}
    (o,) = to_observations("theme", CID, "r1", row, trial=False)
    assert o.field_id == "theme:A1"


def test_voting_field_id():
    row = {"company_id": "acme", "name": "Acme", "meeting_id": "M1", "votes": [{"proposal": {
        "company_id": "acme", "meeting_id": "M1", "proposal_number": "3", "type": "other", "sponsor": "Management",
        "resolution_text": "t"}, "policy_recommendation": {"vote": "for", "rationale": "r"}}]}
    (o,) = to_observations("proxy_voting", CID, "r1", row, trial=False)
    assert o.field_id == "vote:M1:3" and o.value == "for"


def test_unsafe_id_segment_is_sanitised():
    row = {"company_matches": [{"activity_id": "a b:c", "verdict": "include", "exposure_estimate": "high",
                                "confidence": 0.8}]}
    (o,) = to_observations("theme", CID, "r1", row, trial=False)
    assert o.field_id == "theme:a_b_c"


def test_trial_marks_every_observation():
    obs = to_observations("extraction", CID, "r1", _record(_field("2024-12-31"), _field("2023-12-31")), trial=True)
    assert obs and all(o.trial for o in obs)


def test_invalid_period_end_is_excluded_and_reported():
    errors = []
    obs = to_observations("extraction", CID, "r1", _record(_field("31/12/2024"), _field("2023-12-31")), trial=False,
                          errors=errors)
    assert [o.period_end for o in obs] == [date(2023, 12, 31)]
    assert errors == [{"kind": "invalid_value", "field_id": "revenue", "raw": "31/12/2024"}]


def test_unknown_run_type_has_no_observations():
    assert to_observations("discovery", CID, "r1", {"_key": "acme"}, trial=False) == []
