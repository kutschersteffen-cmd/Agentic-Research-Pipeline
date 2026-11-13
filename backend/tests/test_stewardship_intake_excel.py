import io
from datetime import date, datetime

import pytest
from openpyxl import Workbook, load_workbook
from sqlalchemy import func, select

from arp.db.session import transaction
from arp.schemas.engagement import FirTheme
from arp.stewardship.intake import ENGAGEMENT_COLUMNS, VOTE_COLUMNS, intake_engagements
from arp.stewardship.intake_excel import read_workbook, template
from arp.storage.postgres_engagement_store import PostgresEngagementStore
from arp.storage.postgres_models import StwEventModel


def _data(typed=False):
    """2 engagements, 3 objectives, 5 activities; `typed` stores cells the way Excel saves them."""
    eng = [{"external_id": f"e{i}", "company_id": f"C{i}", "theme": "climate", "esg_pillars": "E;S", "started_at": "2026-01-05"} for i in (1, 2)]
    obj = [{"external_id": f"o{i}", "engagement_external_id": f"e{1 + i % 2}", "description": "d", "objective_type": "strategic", "escalated": "true", "target_date": "2026-03-01"} for i in (1, 2, 3)]
    act = [{"external_id": f"a{i}", "engagement_external_id": "e1", "occurred_at": "2026-02-01", "summary": "s", "is_initiation": "true"} for i in range(1, 6)]
    if typed:
        for r in eng:
            r["started_at"] = datetime(2026, 1, 5)
            r["company_id"] = r["company_id"]
        for r in obj:
            r["escalated"], r["target_date"] = True, date(2026, 3, 1)
        for r in act:
            r["is_initiation"], r["occurred_at"] = 1, datetime(2026, 2, 1)
        for r in eng + obj + act:
            r["external_id"] = r["external_id"]
    return {"engagements": eng, "objectives": obj, "activities": act}


def _xlsx(sheets):
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        ws.append(ENGAGEMENT_COLUMNS[name])
        for r in rows:
            ws.append([r.get(c) for c in ENGAGEMENT_COLUMNS[name]])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _upload(pg, sheets):
    batch, bad = read_workbook(_xlsx(sheets), "engagements")
    assert bad == []
    return intake_engagements(batch, pg, "excel")


@pytest.fixture
def two_companies(pg):
    for c in ("C1", "C2"):
        PostgresEngagementStore(pg).get_or_create(c, c)


def test_upload_counts(pg, two_companies):
    r = _upload(pg, _data())
    assert (r.created, r.updated, r.unchanged, r.rejected) == (10, 0, 0, [])


def test_reupload_unchanged(pg, two_companies):
    _upload(pg, _data())
    r = _upload(pg, _data())
    assert (r.created, r.updated, r.unchanged) == (0, 0, 10)


def test_reupload_no_events(pg, two_companies):
    _upload(pg, _data())
    with transaction(pg) as s:
        before = s.scalar(select(func.count()).select_from(StwEventModel))
    _upload(pg, _data())
    with transaction(pg) as s:
        assert s.scalar(select(func.count()).select_from(StwEventModel)) == before


def test_changed_summary_updates_one(pg, two_companies):
    _upload(pg, _data())
    d = _data()
    d["activities"][0]["summary"] = "changed"
    r = _upload(pg, d)
    assert (r.updated, r.unchanged) == (1, 9)


def test_worksheet_row_number(pg, two_companies):
    d = _data()
    d["objectives"][1]["objective_type"] = "ambitious"
    d["objectives"].insert(0, {})  # a fully blank worksheet row is skipped but still counts
    batch, bad = read_workbook(_xlsx(d), "engagements")
    r = intake_engagements(batch, pg, "excel")
    assert [x.model_dump() for x in r.rejected if x.field == "objective_type"] == [
        {"sheet": "objectives", "row": 4, "field": "objective_type", "reason": "not one of transparency, operational, strategic"}
    ]
    d["objectives"].pop(0)
    r = intake_engagements(read_workbook(_xlsx(d), "engagements")[0], pg, "excel")
    assert (r.rejected[0].row, r.rejected[0].sheet) == (3, "objectives")


def test_excel_saved_types_unchanged(pg, two_companies):
    _upload(pg, _data())
    r = _upload(pg, _data(typed=True))
    assert (r.created, r.updated, r.unchanged, r.rejected) == (0, 0, 10, [])


def test_float_ids_become_strings():
    d = {"engagements": [{"external_id": 1.0, "company_id": 7.0, "theme": "t"}]}
    batch, _ = read_workbook(_xlsx(d), "engagements")
    assert (batch["engagements"][0]["external_id"], batch["engagements"][0]["company_id"]) == ("1", "7")


def test_wrong_workbook():
    d = _data()
    del d["objectives"]
    _, bad = read_workbook(_xlsx(d), "engagements")
    assert [b.model_dump() for b in bad] == [{"sheet": "objectives", "row": 0, "field": "", "reason": "missing sheet"}]
    wb = load_workbook(io.BytesIO(_xlsx(_data())))
    wb["activities"]["D1"] = "occured_at"
    buf = io.BytesIO()
    wb.save(buf)
    _, bad = read_workbook(buf.getvalue(), "engagements")
    assert [b.model_dump() for b in bad] == [{"sheet": "activities", "row": 1, "field": "occured_at", "reason": "unknown column occured_at"}]
    _, bad = read_workbook(b"not a workbook", "engagements")
    assert len(bad) == 1


def test_votes_kind():
    wb = Workbook()
    wb.active.title = "votes"
    wb.active.append(["external_id", "categories", "vote"])
    wb.active.append(["v1", "a;b", "for"])
    buf = io.BytesIO()
    wb.save(buf)
    batch, bad = read_workbook(buf.getvalue(), "votes")
    assert bad == [] and batch["votes"][0]["categories"] == ["a", "b"]


def test_template_engagements_headers():
    wb = load_workbook(io.BytesIO(template("engagements")))
    assert wb.sheetnames == ["engagements", "objectives", "activities", "lists"]
    for name, cols in ENGAGEMENT_COLUMNS.items():
        assert [c.value for c in wb[name][1]] == cols


def test_template_votes_headers():
    wb = load_workbook(io.BytesIO(template("votes")))
    assert wb.sheetnames == ["votes", "lists"]
    assert [c.value for c in wb["votes"][1]] == VOTE_COLUMNS


def test_lists_fir_theme():
    ws = load_workbook(io.BytesIO(template("engagements")))["lists"]
    header = [c.value for c in ws[1]]
    col = list(ws.iter_cols(min_col=header.index("fir_theme") + 1, max_col=header.index("fir_theme") + 1))[0]
    assert [c.value for c in col[1:] if c.value] == [e.value for e in FirTheme]
    assert ws.cell(2, header.index("fir_theme") + 2).value == "Climate Mitigation & Paris Alignment"
