import pytest
from sqlalchemy import func, select

from arp.db.session import transaction
from arp.schemas.vote_ledger import against_management
from arp.stewardship.intake import intake_votes
from arp.storage.postgres_engagement_store import PostgresEngagementStore
from arp.storage.postgres_models import StwCompanyModel, VoteDecisionModel, VoteItemModel, VoteMeetingModel


@pytest.mark.parametrize(
    ("vote", "rec", "expected"),
    [("against", "for", True), ("withhold", "for", True), ("for", "against", True), ("for", "for", False),
     ("abstain", "for", None), ("one_year", "for", None), ("against", None, None), ("against", "", None), ("against", "withhold", None), ("for", "abstain", None),
     ("against", "against", False), ("withhold", "withhold", False)],
)  # fmt: skip
def test_against_management_rule(vote, rec, expected):
    assert against_management(vote, rec) is expected


def _row(n=1, **kw):
    return {"external_id": f"d{n}", "isin": "US0378331005", "meeting_date": "2026-05-01", "item_number": str(n),
            "description": f"item {n}", "management_recommendation": "for", "vote": "for", **kw}  # fmt: skip


def _count(dsn, model):
    with transaction(dsn) as s:
        return s.scalar(select(func.count()).select_from(model))


def test_rationale_required(pg):
    report = intake_votes([_row(vote="against", rationale="")], pg, "api")
    assert [r.model_dump() for r in report.rejected] == [
        {"sheet": "votes", "row": 1, "field": "rationale", "reason": "rationale required when voting against management"}
    ]
    assert _count(pg, VoteMeetingModel) == 0
    assert intake_votes([_row(vote="against")], pg, "npx_urth_demo").rejected == []


def test_three_items_counts_and_rerun(pg):
    rows = [_row(n) for n in (1, 2, 3)]
    first = intake_votes(rows, pg, "excel")
    assert (first.created, first.updated, first.unchanged, first.rejected) == (7, 0, 0, [])
    again = intake_votes(rows, pg, "excel")
    assert (again.created, again.updated, again.unchanged) == (0, 0, 7)
    assert [_count(pg, m) for m in (VoteMeetingModel, VoteItemModel, VoteDecisionModel)] == [1, 3, 3]


def test_unmatched_company_stored_null(pg):
    intake_votes([_row()], pg, "api")
    with transaction(pg) as s:
        m = s.scalars(select(VoteMeetingModel)).one()
        assert (m.company_id, m.isin) == (None, "US0378331005")
        assert s.scalar(select(func.count()).select_from(StwCompanyModel)) == 0


def test_known_company_matched_and_excel_rows(pg):
    PostgresEngagementStore(pg).get_or_create("isin_US0378331005", "Acme")
    intake_votes([_row()], pg, "api")
    with transaction(pg) as s:
        assert s.scalars(select(VoteMeetingModel)).one().company_id == "isin_US0378331005"
    report = intake_votes([{**_row(), "_row": 7, "vote": "maybe"}, {"_row": 8, "external_id": "x", "vote": "for"}], pg, "excel", excel_rows=True)
    assert {(r.row, r.field) for r in report.rejected} == {(7, "vote"), (8, "meeting_date"), (8, "item_number"), (8, "company_id")}


def test_changed_value_updates(pg):
    intake_votes([_row()], pg, "api")
    report = intake_votes([_row(vote="against", rationale="why")], pg, "api")
    assert (report.created, report.updated, report.unchanged) == (0, 1, 2)
    with transaction(pg) as s:
        assert s.scalars(select(VoteDecisionModel)).one().against_management is True


def test_list_values_rejected_not_crash(pg):
    report = intake_votes([_row(vote=["for"], isin=["x"], external_id=["d"])], pg, "api")
    assert {r.field for r in report.rejected} >= {"vote", "isin", "external_id"}
    assert all(r.sheet == "votes" for r in report.rejected)


def test_company_id_only_row_stored_null(pg):
    report = intake_votes([_row(company_id="NOPE", isin=None)], pg, "api")
    assert (report.created, report.rejected) == (3, [])
    with transaction(pg) as s:
        assert s.scalars(select(VoteMeetingModel)).one().company_id is None


def test_meeting_key_stable_when_company_appears_later(pg):
    rows = [_row()]
    intake_votes(rows, pg, "api")
    PostgresEngagementStore(pg).get_or_create("isin_US0378331005", "Acme")
    again = intake_votes(rows, pg, "api")
    assert (again.created, again.updated, again.unchanged) == (0, 1, 2)  # only the meeting's company_id changes
    assert _count(pg, VoteMeetingModel) == 1


def test_short_cusip_padded_and_vote_label_set(pg):
    a = {"company_id": None, "isin": None}
    intake_votes([_row(1, **a, cusip="37833100")], pg, "api")
    again = intake_votes([_row(1, **a, cusip="037833100")], pg, "api")
    assert (again.created, again.unchanged, _count(pg, VoteMeetingModel)) == (0, 3, 1)
    with transaction(pg) as s:
        assert s.scalars(select(VoteDecisionModel)).one().vote_label == "for"


def test_issuer_name_cannot_take_over_a_company_meeting(pg):
    PostgresEngagementStore(pg).get_or_create("acme", "Acme")
    acme = {"external_id": "d1", "company_id": "acme", "isin": "US0378331005", "cusip": "037833100", "issuer_name": "Acme Inc", "meeting_date": "2026-05-01", "item_number": "1", "vote": "for"}
    intake_votes([acme], pg, "api")
    report = intake_votes([{"external_id": "d2", "issuer_name": "acme", "meeting_date": "2026-05-01", "item_number": "1", "vote": "for"}], pg, "api")
    assert [r.field for r in report.rejected] == ["company_id"]  # an issuer name alone is no issuer id
    with transaction(pg) as s:
        rows = {(m.company_id, m.isin, m.cusip, m.issuer_name) for m in s.scalars(select(VoteMeetingModel))}
    assert rows == {("acme", "US0378331005", "037833100", "Acme Inc")}


def test_upsert_never_clears_meeting_ids(pg):
    PostgresEngagementStore(pg).get_or_create("acme", "Acme")
    row = {"external_id": "d1", "company_id": "acme", "cusip": "037833100", "meeting_date": "2026-05-01", "item_number": "1", "vote": "for"}
    intake_votes([row], pg, "api")
    report = intake_votes([{**row, "cusip": None}], pg, "api")  # same meeting key (cid:acme), cusip now empty
    assert (report.updated, report.unchanged) == (0, 3)
    with transaction(pg) as s:
        assert s.scalars(select(VoteMeetingModel)).one().cusip == "037833100"


def test_isin_company_id_and_isin_only_row_share_a_meeting(pg):
    PostgresEngagementStore(pg).get_or_create("isin_US0378331005", "Apple")
    day = {"meeting_date": "2026-05-01", "vote": "for"}
    intake_votes([{"external_id": "d1", "company_id": "isin_US0378331005", "item_number": "1", **day}], pg, "api")
    intake_votes([{"external_id": "d2", "isin": "US0378331005", "item_number": "2", **day}], pg, "api")
    with transaction(pg) as s:
        assert s.scalar(select(func.count()).select_from(VoteMeetingModel)) == 1


def test_old_format_keys_rewritten_so_resend_finds_them(pg):
    from arp.storage.postgres_schema import _vote_meeting_key_namespaces

    PostgresEngagementStore(pg).get_or_create("acme", "Acme")
    rows = [
        {"external_id": "d1", "company_id": "acme", "meeting_date": "2026-05-01", "item_number": "1", "vote": "for"},
        {"external_id": "d2", "isin": "US0378331005", "meeting_date": "2026-05-01", "item_number": "1", "vote": "for"},
        {"external_id": "d3", "cusip": "037833100", "meeting_date": "2026-05-01", "item_number": "1", "vote": "for"},
    ]
    intake_votes(rows, pg, "api")
    old = {"cid:acme": "acme", "isin:US0378331005": "isin_US0378331005", "cusip:037833100": "037833100"}
    with transaction(pg) as s:  # put the rows back into #440's key format
        for m in s.scalars(select(VoteMeetingModel)):
            new_key, _, date = m.external_id.rpartition(":")
            m.external_id = f"{old[new_key]}:{date}"
        for i in s.scalars(select(VoteItemModel)):
            new_key, _, rest = i.external_id.partition(":20")
            i.external_id = f"{old[new_key]}:20{rest}"
    with transaction(pg) as s:
        _vote_meeting_key_namespaces(s.connection())
        _vote_meeting_key_namespaces(s.connection())  # idempotent
    report = intake_votes(rows, pg, "api")
    assert (report.created, report.updated, report.unchanged) == (0, 0, 9)
    with transaction(pg) as s:
        assert s.scalar(select(func.count()).select_from(VoteMeetingModel)) == 3


def test_keyless_rows_rejected_not_merged(pg):
    # #440 code review B1: rows without the spec's meeting/item key merged into one meeting and item
    a = {"external_id": "a", "vote": "for", "management_recommendation": "for", "issuer_name": "Acme", "meeting_type": "annual"}
    b = {"external_id": "b", "vote": "against", "management_recommendation": "against", "issuer_name": "Acme", "meeting_type": "special"}
    for row in (a, b):
        assert {r.field for r in intake_votes([row], pg, "api").rejected} == {"meeting_date", "item_number", "company_id"}
    x = {"cusip": "037833100", "meeting_date": "2026-05-01", "vote": "for", "management_recommendation": "for"}
    report = intake_votes([{**x, "external_id": "x1"}, {**x, "external_id": "x2", "vote": "against", "management_recommendation": "against"}], pg, "api")
    assert {(r.row, r.field) for r in report.rejected} == {(1, "item_number"), (2, "item_number")}
    assert _count(pg, VoteMeetingModel) == _count(pg, VoteItemModel) == 0


def test_row_without_external_id_rejected_not_duplicated(pg):
    # #440 code review B2: a row without external_id was inserted again on every re-send
    row = {k: v for k, v in _row().items() if k != "external_id"}
    for _ in range(2):
        assert [(r.field, r.reason) for r in intake_votes([row], pg, "api").rejected] == [("external_id", "required")]
    assert _count(pg, VoteDecisionModel) == 0


def test_blank_or_whitespace_key_counts_as_missing(pg):
    row = {**_row(), "external_id": "  ", "item_number": "", "meeting_date": None, "isin": " "}
    report = intake_votes([row], pg, "api")
    assert sorted((r.field, r.reason) for r in report.rejected) == [
        ("company_id", "one of company_id, isin, cusip required"), ("external_id", "required"),
        ("item_number", "required"), ("meeting_date", "required"),
    ]
