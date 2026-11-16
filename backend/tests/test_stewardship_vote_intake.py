import pytest
from sqlalchemy import func, select

from arp.db.companies import ensure_universe_company
from arp.db.session import transaction
from arp.schemas.vote_ledger import against_management
from arp.stewardship.intake import intake_votes, meeting_key
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


def test_unknown_company_id_only_row_rejected(pg):
    # owner decision 14 Nov 2026: a company_id that is the only issuer id must be known
    report = intake_votes([_row(company_id="NOPE", isin=None)], pg, "api")
    assert [(r.field, r.reason) for r in report.rejected] == [("company_id", "unknown company")]
    assert _count(pg, VoteMeetingModel) == 0


def test_unknown_company_id_with_isin_stored_null(pg):
    report = intake_votes([_row(company_id="NOPE")], pg, "api")
    assert (report.created, report.rejected) == (3, [])
    with transaction(pg) as s:
        m = s.scalars(select(VoteMeetingModel)).one()
        assert (m.company_id, m.isin) == (None, "US0378331005")


def test_registry_company_id_without_stw_row_stored_null(pg):
    with transaction(pg) as s:
        ensure_universe_company(s, "C9", name="Nine")
    report = intake_votes([_row(company_id="C9", isin=None)], pg, "api")
    assert (report.created, report.rejected) == (3, [])  # known to the registry: not unknown, but no stw_companies row to link
    with transaction(pg) as s:
        m = s.scalars(select(VoteMeetingModel)).one()
        assert (m.company_id, m.external_id) == (None, "cid:C9:2026-05-01")


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
    report = intake_votes([{**row, "company_id": None}], pg, "api")  # same meeting key (cusip:), company_id now empty
    assert (report.updated, report.unchanged) == (0, 3)
    with transaction(pg) as s:
        assert s.scalars(select(VoteMeetingModel)).one().company_id == "acme"
    # stewardship-decisions-round-2: a company-only row names its own cid: meeting beside the cusip: one
    intake_votes([{**row, "external_id": "d2", "cusip": None}], pg, "api")
    with transaction(pg) as s:
        assert {(m.external_id, m.cusip) for m in s.scalars(select(VoteMeetingModel))} == {
            ("cusip:037833100:2026-05-01", "037833100"), ("cid:acme:2026-05-01", None)}


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
        # issuer_name equal to the company id: the stored company_id must win (#450 round-2 B2)
        {"external_id": "d1", "company_id": "acme", "issuer_name": "acme", "meeting_date": "2026-05-01", "item_number": "1", "vote": "for"},
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


def test_unknown_company_id_cannot_take_over_another_company_meeting(pg):
    # #450 round-2 B1: an unknown company_id beside an ISIN named the meeting, so a second company's row took it over
    for isin in ("US0378331005", "US5949181045"):
        PostgresEngagementStore(pg).get_or_create(f"isin_{isin}", isin)
    intake_votes([{**_row(), "external_id": "a1", "company_id": "X1", "isin": "US0378331005"}], pg, "api")
    intake_votes([{**_row(2), "external_id": "m1", "company_id": "X1", "isin": "US5949181045"}], pg, "api")
    with transaction(pg) as s:
        meetings = {(m.external_id, m.company_id, m.isin) for m in s.scalars(select(VoteMeetingModel))}
    assert meetings == {
        ("isin:US0378331005:2026-05-01", "isin_US0378331005", "US0378331005"),
        ("isin:US5949181045:2026-05-01", "isin_US5949181045", "US5949181045"),
    }


def test_meeting_company_never_pinned_by_another_id(pg):
    # #450 round-3 security B1: C9 (registry only) keys cid:C9, but its first row carried another company's ISIN,
    # which pinned that company onto C9's meeting; C9's own later row was then accepted under the wrong company
    with transaction(pg) as s:
        ensure_universe_company(s, "C9", name="Nine")
    PostgresEngagementStore(pg).get_or_create("isin_US5949181045", "Other")
    first = intake_votes([{**_row(), "company_id": "C9", "isin": "US5949181045"}], pg, "api")
    assert first.rejected == []
    # stewardship-decisions-round-2: each listing is its own meeting, so C9's second ISIN no longer conflicts
    report = intake_votes([{**_row(2), "company_id": "C9", "isin": "US0378331005"}], pg, "api")
    assert report.rejected == []
    with transaction(pg) as s:
        meetings = {(m.external_id, m.company_id) for m in s.scalars(select(VoteMeetingModel))}
    # C9 has no stw_companies row, so it is never a meeting's company; a listing's company is its isin_ row or none
    assert meetings == {("isin:US5949181045:2026-05-01", "isin_US5949181045"), ("isin:US0378331005:2026-05-01", None)}
    assert _count(pg, VoteDecisionModel) == 2


def test_conflicting_ids_in_one_batch_rejected(pg):
    PostgresEngagementStore(pg).get_or_create("acme", "Acme")
    rows = [{**_row(), "company_id": "acme", "cusip": "037833100"}, {**_row(2), "company_id": "acme", "cusip": "999999999"}]
    report = intake_votes(rows, pg, "api")
    assert [(r.row, r.field) for r in report.rejected] == [(2, "cusip")]
    assert _count(pg, VoteMeetingModel) == 0


def test_item_number_with_colon_rejected(pg):
    report = intake_votes([_row(item_number="2026-05-01:1")], pg, "api")
    assert [(r.field, r.reason) for r in report.rejected] == [("item_number", "must not contain ':'")]


def test_isin_company_id_suffix_upper_cased():
    assert meeting_key("isin_us0378331005", None, None) == meeting_key(None, "US0378331005", None) == "isin:US0378331005"


def test_isin_company_id_with_cusip_stays_on_its_isin_listing(pg):  # #552 code review B1
    PostgresEngagementStore(pg).get_or_create("isin_US0378331005", "Apple")
    assert meeting_key("isin_US0378331005", None, "037833100") == "isin:US0378331005"
    day = {"company_id": "isin_US0378331005", "isin": None, "item_number": "1"}
    report = intake_votes([_row(1, external_id="a", **day), _row(1, external_id="b", cusip="037833100", **day)], pg, "api")
    assert report.rejected == []
    with transaction(pg) as s:
        m = s.scalars(select(VoteMeetingModel)).one()
        assert (m.external_id, m.company_id, m.cusip) == ("isin:US0378331005:2026-05-01", "isin_US0378331005", "037833100")


def _set_meeting_key(pg, new):
    with transaction(pg) as s:
        m = s.scalars(select(VoteMeetingModel)).one()
        old, m.external_id = m.external_id, new
        for i in s.scalars(select(VoteItemModel)):
            i.external_id = new + i.external_id[len(old):]


def _run_steps(pg, *steps):
    with transaction(pg) as s:
        for step in steps:
            step(s.connection())


def test_unknown_company_id_with_isin_rekeyed_by_repair_step(pg):
    # #450 round-3 code review B1: #440 keyed this row `NOPE:<date>`; the first step made it cid:NOPE, intake keys isin:
    from arp.storage.postgres_schema import _vote_meeting_key_namespaces, _vote_meeting_key_repair

    row = {**_row(), "company_id": "NOPE"}
    intake_votes([row], pg, "api")
    _set_meeting_key(pg, "NOPE:2026-05-01")
    _run_steps(pg, _vote_meeting_key_namespaces, _vote_meeting_key_repair, _vote_meeting_key_repair)  # repair is idempotent
    report = intake_votes([row], pg, "api")
    assert (report.created, report.updated, report.unchanged, report.rejected) == (0, 0, 3, [])
    with transaction(pg) as s:
        assert [m.external_id for m in s.scalars(select(VoteMeetingModel))] == ["isin:US0378331005:2026-05-01"]


def test_repair_step_keeps_resolved_cid_and_skips_taken_key(pg, caplog):
    from arp.storage.postgres_schema import _vote_meeting_key_repair

    with transaction(pg) as s:
        ensure_universe_company(s, "C9", name="Nine")
    intake_votes([{**_row(), "company_id": "C9"}], pg, "api")
    _set_meeting_key(pg, "cid:C9:2026-05-01")  # a registry id, keyed cid:C9 as main wrote it before listing keys
    intake_votes([{**_row(2), "meeting_date": "2026-06-01"}], pg, "api")  # isin:US0378331005:2026-06-01
    intake_votes([{**_row(3), "isin": "US5949181045", "meeting_date": "2026-06-01"}], pg, "api")
    with transaction(pg) as s:  # turn the second meeting into a mis-keyed cid:NOPE one whose isin target is taken
        m = s.scalars(select(VoteMeetingModel).where(VoteMeetingModel.isin == "US5949181045")).one()
        m.external_id, m.isin = "cid:NOPE:2026-06-01", "US0378331005"
    _run_steps(pg, _vote_meeting_key_repair)
    with transaction(pg) as s:
        keys = sorted(m.external_id for m in s.scalars(select(VoteMeetingModel)))
    assert keys == ["cid:C9:2026-05-01", "cid:NOPE:2026-06-01", "isin:US0378331005:2026-06-01"]
    assert "1 meeting(s) left under their old key" in caplog.text


def test_ids_filled_in_by_a_later_row_are_written(pg):
    # #470 post-merge code review B1: the check accepted x2's ISIN for the meeting but the write used only x1's values,
    # so [x1, x2] then [x3] stored no ISIN and accepted x3's conflicting one; one batch rejected x3
    # stewardship-decisions-round-2: rows meet on their listing (ISIN), so the later row fills in the CUSIP
    PostgresEngagementStore(pg).get_or_create("acme", "Acme")
    x1 = {**_row(1), "company_id": "acme"}
    x2 = {**_row(2), "company_id": "acme", "cusip": "037833100"}
    x3 = {**_row(3), "company_id": "acme", "cusip": "999999999"}
    assert intake_votes([x1, x2], pg, "api").rejected == []
    with transaction(pg) as s:
        assert s.scalars(select(VoteMeetingModel)).one().cusip == "037833100"
    report = intake_votes([x3], pg, "api")
    assert [(r.field, r.reason) for r in report.rejected] == [("cusip", "cusip differs from the meeting's 037833100")]


# stewardship-decisions-round-2, area 5: one meeting per listing


def _syn(pg):
    PostgresEngagementStore(pg).get_or_create("SYN01", "Synthetic One")


def _keys(pg):
    with transaction(pg) as s:
        return {(m.external_id, m.company_id) for m in s.scalars(select(VoteMeetingModel))}


def test_two_listings_of_one_company_are_two_meetings(pg):  # AC-24
    _syn(pg)
    rows = [{**_row(1, external_id="a", isin="US0000000001"), "company_id": "SYN01", "item_number": "1"},
            {**_row(1, external_id="b", isin="US0000000002"), "company_id": "SYN01", "item_number": "1"}]
    report = intake_votes(rows, pg, "api")
    assert (report.rejected, report.created) == ([], 6)
    assert _keys(pg) == {("isin:US0000000001:2026-05-01", "SYN01"), ("isin:US0000000002:2026-05-01", "SYN01")}


def test_listing_key_step_rekeys_cid_meeting_so_resend_updates(pg, caplog):  # AC-25
    from arp.storage.postgres_schema import _vote_meeting_listing_key

    _syn(pg)
    row = {**_row(1, isin="US0000000001"), "company_id": "SYN01"}
    intake_votes([row], pg, "api")
    _set_meeting_key(pg, "cid:SYN01:2026-05-01")  # as main keyed it before this change
    _run_steps(pg, _vote_meeting_listing_key, _vote_meeting_listing_key)  # idempotent
    report = intake_votes([row], pg, "api")
    assert (report.created, report.unchanged, report.rejected) == (0, 3, [])
    with transaction(pg) as s:
        assert [i.external_id for i in s.scalars(select(VoteItemModel))] == ["isin:US0000000001:2026-05-01:1"]
    assert _keys(pg) == {("isin:US0000000001:2026-05-01", "SYN01")}
    intake_votes([{**row, "external_id": "d9", "isin": "US0000000009", "item_number": "9"}], pg, "api")
    _set_meeting_key_of(pg, "US0000000009", "cid:SYN01:2026-05-01", isin="US0000000001")  # its target key is taken
    _run_steps(pg, _vote_meeting_listing_key)
    assert ("cid:SYN01:2026-05-01", "SYN01") in _keys(pg)
    assert "vote_meeting_listing_key: 1 meeting(s) left under their old key; their new key is taken: api/cid:SYN01:2026-05-01" in caplog.text


def _set_meeting_key_of(pg, stored_isin, new, **values):
    with transaction(pg) as s:
        m = s.scalars(select(VoteMeetingModel).where(VoteMeetingModel.isin == stored_isin)).one()
        m.external_id = new
        for k, v in values.items():
            setattr(m, k, v)


def test_conflicting_cusip_on_one_listing_still_rejected(pg):  # AC-26
    _syn(pg)
    rows = [{**_row(1, external_id="a", isin="US0000000001", cusip="000000001"), "company_id": "SYN01"},
            {**_row(2, external_id="b", isin="US0000000001", cusip="000000002"), "company_id": "SYN01"}]
    report = intake_votes(rows, pg, "api")
    assert [(r.row, r.field) for r in report.rejected] == [(2, "cusip")]


def test_company_only_row_keeps_cid_key(pg):  # AC-27
    _syn(pg)
    row = {**_row(1, isin=None, meeting_date="2026-06-01"), "company_id": "SYN01"}
    intake_votes([row], pg, "api")
    again = intake_votes([row], pg, "api")
    assert (again.created, again.unchanged) == (0, 3)
    assert _keys(pg) == {("cid:SYN01:2026-06-01", "SYN01")}


def test_company_only_and_listing_row_are_two_meetings(pg):  # AC-28
    _syn(pg)
    day = {"meeting_date": "2026-07-01", "company_id": "SYN01", "item_number": "1"}
    report = intake_votes([{**_row(1, external_id="a", isin=None), **day},
                           {**_row(1, external_id="b", isin="US0000000001"), **day}], pg, "api")
    assert report.rejected == []
    assert _keys(pg) == {("cid:SYN01:2026-07-01", "SYN01"), ("isin:US0000000001:2026-07-01", "SYN01")}
