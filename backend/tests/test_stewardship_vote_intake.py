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
     ("abstain", "for", None), ("one_year", "for", None), ("against", None, None)],
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
    assert {(r.row, r.field) for r in report.rejected} >= {(7, "vote"), (8, "company_id")}


def test_changed_value_updates(pg):
    intake_votes([_row()], pg, "api")
    report = intake_votes([_row(vote="against", rationale="why")], pg, "api")
    assert (report.created, report.updated, report.unchanged) == (0, 1, 2)
    with transaction(pg) as s:
        assert s.scalars(select(VoteDecisionModel)).one().against_management is True
