from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select
from typer.testing import CliRunner

from arp.cli import app
from arp.db import models as m
from arp.db.companies import resolve_company
from arp.db.session import transaction
from arp.schemas.common import CompanyRef
from arp.storage.postgres_models import StwCompanyModel, VoteDecisionModel, VoteItemModel, VoteMeetingModel

FIXTURE = Path(__file__).parent / "fixtures" / "npx"
COMMITTED = Path(__file__).parents[2] / "data" / "voting" / "npx_urth"
TABLES = (VoteMeetingModel, VoteItemModel, VoteDecisionModel)


@pytest.fixture
def run(pg, monkeypatch):
    monkeypatch.setenv("ARP_SKIP_CUTOVER_CHECK", "1")
    return lambda *args: CliRunner().invoke(app, ["stewardship", "load-npx", *map(str, args)])


def _counts(dsn):
    with transaction(dsn) as s:
        return [s.scalar(select(func.count()).select_from(t).where(t.source == "npx_urth_demo")) for t in TABLES]


def _all(dsn, model):
    with transaction(dsn) as s:
        rows = s.scalars(select(model)).all()
        s.expunge_all()
        return rows


def test_ac33_fixture_counts(run, pg):
    res = run(FIXTURE)
    assert res.exit_code == 0, res.output
    assert res.output.strip() == "meetings 3, items 10, decisions 10 created"
    assert _counts(pg) == [3, 10, 10]


def test_ac34_against_and_empty_vote(run, pg):
    run(FIXTURE)
    decisions = _all(pg, VoteDecisionModel)
    assert sum(d.against_management is True for d in decisions) == 2
    empty = [i for i in _all(pg, VoteItemModel) if i.description == "Shareholder Proposal on Climate Transition Plan"]
    assert len(empty) == 1 and empty[0].proponent == "shareholder"
    assert not [d for d in decisions if d.item_id == empty[0].item_id]


def test_fixture_values(run, pg):
    run(FIXTURE)
    by_label = {d.vote_label: d for d in _all(pg, VoteDecisionModel)}
    freq = by_label["ONE YEAR"]
    assert (freq.vote, freq.against_management, freq.shares_voted, freq.rationale) == ("one_year", None, 20000, None)
    split = [d for d in _all(pg, VoteDecisionModel) if d.shares_voted in (600, 400)]
    assert len({d.item_id for d in split}) == 1 and {d.vote for d in split} == {"for"}
    assert {d.external_id for d in split} == {"fixture.csv:4", "fixture.csv:5"}  # header is line 1
    items = {i.description: i for i in _all(pg, VoteItemModel)}
    pay = items["Approve Remuneration Policy of CEO"]
    assert (pay.item_number, pay.categories, pay.proponent, pay.management_recommendation) == (
        "2",
        ["SECTION 14A SAY-ON-PAY VOTES", "COMPENSATION"],
        "issuer",
        "for",
    )
    assert items["Shareholder Proposal on Climate Transition Plan"].management_recommendation is None
    meeting = next(x for x in _all(pg, VoteMeetingModel) if x.isin == "JP3633400001")
    assert meeting.external_id == "0001021408-24-004974:J92676113:2024-06-18"
    assert meeting.meeting_date.date().isoformat() == "2024-06-18" and meeting.company_id is None


def test_cusip_leading_zero(run, pg):
    run(FIXTURE)
    apple = next(x for x in _all(pg, VoteMeetingModel) if x.isin == "US0378331005")
    assert apple.cusip == "037833100"
    assert apple.external_id == "0001021408-24-004974:037833100:2024-02-28"


def test_unicode_names_round_trip(run, pg):
    run(FIXTURE)
    names = {x.issuer_name for x in _all(pg, VoteMeetingModel)}
    assert "Société Générale".encode() in {n.encode() for n in names}
    assert "トヨタ自動車".encode() in {n.encode() for n in names}


def test_registry_match_isin_and_cusip(run, pg):
    with transaction(pg) as s:
        resolve_company(s, CompanyRef(company_id="isin_US0378331005", name="Apple", isin="US0378331005"))
        toyota = resolve_company(s, CompanyRef(company_id="toyota_jp", name="Toyota")).company_id
        s.add(m.CompanyIdentifier(company_id=toyota, scheme="CUSIP", value="J92676113"))
        resolve_company(s, CompanyRef(company_id="isin_FR0000130809", name="SocGen", isin="FR0000130809"))  # no stw row
        for key in ("isin_US0378331005", "toyota_jp"):
            s.add(StwCompanyModel(company_id=key, source="app", name=key))
    run(FIXTURE)
    by_isin = {x.isin: x.company_id for x in _all(pg, VoteMeetingModel)}
    assert by_isin == {"US0378331005": "isin_US0378331005", "JP3633400001": "toyota_jp", "FR0000130809": None}


def test_rerun_refreshes_company_only(run, pg):
    run(FIXTURE)
    with transaction(pg) as s:
        resolve_company(s, CompanyRef(company_id="isin_US0378331005", name="Apple", isin="US0378331005"))
        s.add(StwCompanyModel(company_id="isin_US0378331005", source="app", name="Apple"))
    res = run(FIXTURE)
    assert res.output.strip() == "meetings 0, items 0, decisions 0 created"
    assert _counts(pg) == [3, 10, 10]
    assert {x.company_id for x in _all(pg, VoteMeetingModel)} == {None, "isin_US0378331005"}


def test_no_csv_exits_1(run, tmp_path):
    res = run(tmp_path)
    assert res.exit_code == 1
    assert "no .csv files" in res.output


@pytest.mark.slow
def test_ac35_ac36_ac37_committed_csvs(run, pg):
    assert run(COMMITTED).exit_code == 0
    assert _counts(pg) == [4131, 61964, 59786]
    res = run(COMMITTED)  # AC-36
    assert res.output.strip() == "meetings 0, items 0, decisions 0 created"
    assert _counts(pg) == [4131, 61964, 59786]
    with transaction(pg) as s:  # AC-37
        votes = s.scalars(select(VoteDecisionModel.vote).where(VoteDecisionModel.vote_label.in_(["ONE YEAR", "1 YEAR"]))).all()
    assert len(votes) == 122 and set(votes) == {"one_year"}


def test_registry_match_isin_under_other_universe_id(run, pg):
    with transaction(pg) as s:
        resolve_company(s, CompanyRef(company_id="toyota_jp", name="Toyota", isin="JP3633400001"))
        s.add(StwCompanyModel(company_id="toyota_jp", source="app", name="Toyota"))
        # ISIN registered without an stw row: falls through to the CUSIP
        socgen = resolve_company(s, CompanyRef(company_id="isin_FR0000130809", name="SocGen", isin="FR0000130809")).company_id
        other = resolve_company(s, CompanyRef(company_id="socgen_fr", name="SocGen listing")).company_id
        s.add(m.CompanyIdentifier(company_id=other, scheme="CUSIP", value="F43638141"))
        s.add(StwCompanyModel(company_id="socgen_fr", source="app", name="SocGen"))
        assert socgen != other
    run(FIXTURE)
    by_isin = {x.isin: x.company_id for x in _all(pg, VoteMeetingModel)}
    assert by_isin == {"US0378331005": None, "JP3633400001": "toyota_jp", "FR0000130809": "socgen_fr"}
