"""Spec `stewardship-cockpit` PR 1: `planned_meeting_date` intake, `GET /api/stewardship/cockpit` and
`arp stewardship seed-cockpit-demo`."""

from __future__ import annotations

import io
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import func, select, update
from typer.testing import CliRunner

pytest.importorskip("zen")

from arp.api.auth import current_user  # noqa: E402
from arp.api.main import app  # noqa: E402
from arp.cli import app as cli  # noqa: E402
from arp.config import get_settings  # noqa: E402
from arp.db.session import transaction  # noqa: E402
from arp.schemas.common import CompanyRef  # noqa: E402
from arp.schemas.portfolio import Holding, Portfolio, SecurityRef  # noqa: E402
from arp.stewardship import cockpit  # noqa: E402
from arp.stewardship.cockpit_demo import OFFSETS, planned_date  # noqa: E402
from arp.stewardship.tiers import TIERS, TierStore  # noqa: E402
from arp.storage.portfolio_store_factory import build_portfolio_store  # noqa: E402
from arp.storage.postgres_models import (  # noqa: E402
    StwCompanyModel,
    StwEngagementModel,
    StwTransitionModel,
    VoteDecisionModel,
    VoteItemModel,
    VoteMeetingModel,
)
from tests.conftest import PRINCIPAL  # noqa: E402

A = "isin_XA0000000001"
AS_OF = "2026-11-17"


@pytest.fixture
def client(pg, monkeypatch, tmp_path):
    monkeypatch.setenv("ARP_ENGAGEMENTS_DIR", str(tmp_path / "engagements"))
    monkeypatch.setenv("ARP_ENGAGEMENT_STORE", "postgres")
    monkeypatch.setenv("ARP_STEWARDSHIP_STREAMS_DIR", str(tmp_path / "streams"))
    monkeypatch.setenv("ARP_PORTFOLIOS_DIR", str(tmp_path / "portfolios"))
    monkeypatch.setenv("ARP_RUNS_DIR", str(tmp_path / "runs"))
    get_settings.cache_clear()
    app.dependency_overrides[current_user] = lambda: PRINCIPAL
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _company(pg, company_id, name):
    with transaction(pg) as s:
        s.add(StwCompanyModel(company_id=company_id, source="test", name=name))


def _engagement(client, pg, *, company_id=A, name="Alpha AG", ext="A", objectives=None, **eng):
    with transaction(pg) as s:
        if s.get(StwCompanyModel, company_id) is None:
            s.add(StwCompanyModel(company_id=company_id, source="test", name=name))
    row = {"external_id": ext, "company_id": company_id, "theme": "climate", "fir_theme": "climate_mitigation",
           "started_at": "2026-10-03", "status": "open", "planned_meeting_date": "2026-11-20", **eng}  # fmt: skip
    if objectives is None:
        objectives = [{"description": "Cut coal", "status": "in_progress"}]
    objs = [{"external_id": f"{ext}o{i}", "engagement_external_id": ext, "objective_type": "strategic", **o} for i, o in enumerate(objectives)]
    r = client.post("/api/stewardship/intake/engagements", json={"engagements": [row], "objectives": objs})
    assert r.status_code == 200, r.json()
    with transaction(pg) as s:
        return s.scalar(select(StwEngagementModel.engagement_id).where(StwEngagementModel.external_id == ext))


def _get(client, **params):
    r = client.get("/api/stewardship/cockpit", params={"as_of": AS_OF, **params})
    assert r.status_code == 200, r.text
    return r.json()


def _confirm(issuer_id, tier, rule=None, by="tests"):
    TierStore(get_settings().stewardship_streams_dir).confirm({"issuer_id": issuer_id, "name": issuer_id, "tier": tier, "rule": rule}, by)


def _meeting(pg, company_id, day, items=3, decided=0, source="test", key="m1", **item_kw):
    with transaction(pg) as s:
        s.add(VoteMeetingModel(meeting_id=key, source=source, external_id=key, company_id=company_id, issuer_name="Issuer",
                               meeting_date=datetime.fromisoformat(day).replace(hour=10, tzinfo=UTC)))  # fmt: skip
        s.flush()
        for i in range(items):
            s.add(VoteItemModel(item_id=f"{key}i{i}", source=source, external_id=f"{key}i{i}", meeting_id=key, item_number=str(i), **item_kw))
        s.flush()
        for i in range(decided):
            s.add(VoteDecisionModel(decision_id=f"{key}d{i}", source=source, external_id=f"{key}d{i}", item_id=f"{key}i{i}", vote="for"))


# --- intake -------------------------------------------------------------------------------------------------


def test_template_lists_planned_meeting_date_last_ac6(client):
    r = client.get("/api/stewardship/intake/template", params={"kind": "engagements"})
    header = [c.value for c in next(load_workbook(io.BytesIO(r.content))["engagements"].iter_rows(max_row=1))]
    assert header[-2:] == ["severity", "planned_meeting_date"]


def test_intake_planned_date_unchanged_updated_and_malformed_ac7_ac8_ac9(client, pg):
    _engagement(client, pg)
    batch = {"engagements": [{"external_id": "A", "company_id": A, "theme": "climate", "fir_theme": "climate_mitigation",
                              "started_at": "2026-10-03", "status": "open", "planned_meeting_date": "2026-11-20"}]}  # fmt: skip
    r = client.post("/api/stewardship/intake/engagements", json=batch)
    assert (r.json()["created"], r.json()["updated"]) == (0, 0)
    batch["engagements"][0]["planned_meeting_date"] = "2026-11-25"
    assert client.post("/api/stewardship/intake/engagements", json=batch).json()["updated"] == 1
    with transaction(pg) as s:
        assert s.scalar(select(StwEngagementModel.planned_meeting_date)) == date(2026, 11, 25)
    batch["engagements"][0].update(external_id="B", planned_meeting_date="20.11.2026")
    r = client.post("/api/stewardship/intake/engagements", json=batch)
    assert r.status_code == 422
    assert r.json()["rejected"] == [{"sheet": "engagements", "row": 1, "field": "planned_meeting_date", "reason": "not a date"}]


def test_escalation_keeps_planned_date_ac86(client, pg):
    eid = _engagement(client, pg)
    r = client.post(f"/api/engagement/records/{A}/issues/{eid}/escalate", json={"stage": "written_escalation_to_board"})
    assert r.status_code == 200, r.text
    with transaction(pg) as s:
        assert s.get(StwEngagementModel, eid).planned_meeting_date == date(2026, 11, 20)


# --- cockpit: shape, meetings, gaps ---------------------------------------------------------------------------


def test_empty_ac1_ac2_ac85(client):
    body = _get(client)
    assert body["summary"] == {"selected": 0, "engaged_selected": 0, "engaged_outside_selection": 0}
    assert body["engagement_meetings"] == body["shareholder_meetings"] == body["control_gaps"] == []
    assert (body["voting"]["votes"], body["demo"], body["emissions"]) == (0, False, None)
    assert [d["date"] for d in body["days"]][::29] == ["2026-11-17", "2026-12-16"] and len(body["days"]) == 30
    assert all(d["engagement_meetings"] == d["shareholder_meetings"] == 0 for d in body["days"])
    assert [(s["step"], s["label"], s["companies"]) for s in body["ladder"]] == [
        (1, "Private dialogue", []), (2, "Letter to the board", []), (3, "Meeting with the chair", []),
        (4, "Vote against management", []), (5, "File a resolution", []), (6, "Public statement", []),
    ]  # fmt: skip


def test_bad_as_of_and_unknown_portfolio_ac4_ac5(client):
    assert client.get("/api/stewardship/cockpit", params={"as_of": "2026-13-01"}).status_code == 422
    r = client.get("/api/stewardship/cockpit", params={"as_of": AS_OF, "portfolio_id": "nope"})
    assert (r.status_code, r.json()["detail"]) == (404, "Unknown portfolio nope")


def test_engagement_meeting_ac11_ac12_ac13(client, pg):
    eid = _engagement(client, pg)
    body = _get(client)
    assert body["engagement_meetings"] == [{"date": "2026-11-20", "company_id": A, "company": "Alpha AG", "engagement_id": eid, "theme": "Climate",
                                            "objective": "Cut coal", "step": 1, "stage": "private_engagement"}]  # fmt: skip
    assert body["days"][3] == {"date": "2026-11-20", "engagement_meetings": 1, "shareholder_meetings": 0}
    assert body["control_gaps"] == []


@pytest.mark.parametrize(("planned", "listed", "gaps"), [
    ("2026-12-17", False, []), ("2026-11-17", True, []), ("", False, ["no_next_meeting"]), ("2026-11-16", False, ["no_next_meeting"]),
])  # fmt: skip
def test_window_and_next_meeting_gap_ac14_to_ac17_ac74(client, pg, planned, listed, gaps):
    _engagement(client, pg, planned_meeting_date=planned)
    body = _get(client)
    assert bool(body["engagement_meetings"]) is listed
    assert [g["gaps"] for g in body["control_gaps"]] == ([gaps] if gaps else [])
    if gaps:
        assert body["control_gaps"][0]["open_days"] == 45


def test_objective_gaps_and_current_objective_ac18_to_ac21(client, pg):
    _engagement(client, pg, objectives=[])
    body = _get(client)
    assert [g["gaps"] for g in body["control_gaps"]] == [["no_objective"]]
    assert body["engagement_meetings"][0]["objective"] is None
    _engagement(client, pg, company_id="isin_XB", name="Beta", ext="B", planned_meeting_date="", objectives=[{"description": "x", "status": "closed"}])
    _engagement(client, pg, company_id="isin_XC", name="Gamma", ext="C", objectives=[
        {"description": "Old aim", "status": "in_progress", "started_at": "2026-01-10"},
        {"description": "New aim", "status": "in_progress", "started_at": "2026-09-01"},
    ])  # fmt: skip
    body = _get(client)
    assert {g["company"]: g["gaps"] for g in body["control_gaps"]}["Beta"] == ["no_objective", "no_next_meeting"]
    assert {m["company"]: m["objective"] for m in body["engagement_meetings"]}["Gamma"] == "New aim"


@pytest.mark.parametrize(("status", "shown"), [("resolved", False), ("stalled", True)])
def test_only_open_or_stalled_count_ac22_ac23_ac75(client, pg, status, shown):
    _engagement(client, pg, status=status, planned_meeting_date="2026-11-20" if shown else "")
    body = _get(client)
    assert bool(body["engagement_meetings"]) is shown
    assert body["control_gaps"] == []


def test_ladder_highest_open_step_ac87_ac89(client, pg):
    e1 = _engagement(client, pg)
    e2 = _engagement(client, pg, ext="A2")
    for eid, stage in ((e1, "written_escalation_to_board"), (e2, "escalation_to_chair")):
        assert client.post(f"/api/engagement/records/{A}/issues/{eid}/escalate", json={"stage": stage}).status_code == 200
    ladder = _get(client)["ladder"]
    assert [s["step"] for s in ladder if s["companies"]] == [3]
    assert ladder[2]["companies"] == [{"company_id": A, "company": "Alpha AG"}]
    client.post(f"/api/engagement/records/{A}/issues/{e1}/escalate", json={"stage": "vote_against_management"})
    client.post(f"/api/engagement/records/{A}/issues/{e2}/escalate", json={"stage": "public_statement"})
    _engagement(client, pg, ext="A2", status="resolved")
    assert [s["step"] for s in _get(client)["ladder"] if s["companies"]] == [4]


# --- selection: tiers and themes --------------------------------------------------------------------------------


def test_summary_counts_confirmed_tiers_only_ac26_ac27(client, pg):
    for c in "BCDEF":
        _company(pg, f"isin_X{c}", c)
    _confirm("isin_XB", TIERS[0])
    _confirm("isin_XC", TIERS[1])
    _confirm("isin_XD", TIERS[2])
    _confirm("isin_XE", "retired_tier")
    _engagement(client, pg, company_id="isin_XB", ext="B")
    _engagement(client, pg, company_id="isin_XF", ext="F")
    assert _get(client)["summary"] == {"selected": 3, "engaged_selected": 1, "engaged_outside_selection": 1}
    _confirm("isin_XB", TIERS[1])
    tiers = {t["tier"]: t for t in _get(client)["tiers"]}
    assert (tiers[TIERS[0]]["selected"], tiers[TIERS[1]]["selected"]) == (0, 2)


def test_themes_by_tier_ac28_ac82_ac83(client, pg):
    _confirm("isin_XB", TIERS[0], rule="top_weight")
    _engagement(client, pg, company_id="isin_XB", name="B", ext="B", fir_theme="governance_board_pay")
    _confirm("isin_XC", TIERS[1], rule="high_emitter")
    _confirm("isin_XD", TIERS[0], rule="top_weight")
    body = _get(client)
    assert [(t["theme"], t["selected"], t["engaged"]) for t in body["themes"]] == [
        ("Climate", 1, 0), ("Corporate governance", 1, 1), ("Nature", 0, 0), ("AI and digital", 0, 0), ("Norm violations", 0, 0), ("Other", 1, 0),
    ]  # fmt: skip
    cells = {(t["theme"], c["tier"]): (c["selected"], c["engaged"]) for t in body["themes"] for c in t["tiers"]}
    assert {k: v for k, v in cells.items() if v != (0, 0)} == {
        ("Corporate governance", TIERS[0]): (1, 1), ("Climate", TIERS[1]): (1, 0), ("Other", TIERS[0]): (1, 0),
    }  # fmt: skip
    assert all([c["tier"] for c in t["tiers"]] == TIERS for t in body["themes"])
    assert [(t["tier"], t["selected"], t["engaged"]) for t in body["tiers"]][:2] == [(TIERS[0], 2, 1), (TIERS[1], 1, 0)]


def test_company_in_two_themes_and_no_other_row_ac29_ac30(client, pg):
    _confirm("isin_XB", TIERS[0])
    _engagement(client, pg, company_id="isin_XB", name="B", ext="B1")
    _engagement(client, pg, company_id="isin_XB", name="B", ext="B2", fir_theme="digital_responsibility")
    body = _get(client)
    rows = {t["theme"]: (t["selected"], t["engaged"]) for t in body["themes"]}
    assert rows["Climate"] == rows["AI and digital"] == (1, 1) and body["summary"]["engaged_selected"] == 1
    assert "Other" not in rows and len(body["themes"]) == 5


# --- shareholder meetings ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(("day", "decided", "state", "due", "days"), [
    ("2026-11-20", 0, "not_started", True, 3), ("2026-11-25", 0, "not_started", False, 8),
    ("2026-11-20", 2, "awaiting", True, 3), ("2026-11-20", 3, "cast", False, 3),
])  # fmt: skip
def test_ledger_meeting_ac31_to_ac34(client, pg, day, decided, state, due, days):
    _company(pg, "isin_XG", "Gamma SE")
    _meeting(pg, "isin_XG", day, decided=decided)
    [row] = _get(client)["shareholder_meetings"]
    assert row == {"date": day, "company_id": "isin_XG", "company": "Gamma SE", "items": 3, "flagged": None, "ballot_state": state,
                   "action_due": due, "days_to_meeting": days, "run_id": None}  # fmt: skip


def test_ledger_meeting_outside_window_or_without_company_ac35(client, pg):
    _company(pg, "isin_XG", "Gamma SE")
    _meeting(pg, "isin_XG", "2026-12-17")
    _meeting(pg, None, "2026-11-20", key="m2")
    assert _get(client)["shareholder_meetings"] == []


def _run(statuses, policy=("against", "against", "for", "for"), run_id="r1", day="2026-11-19"):
    return [
        {"run_id": run_id, "company_id": "H", "company": "Hotel", "meeting_date": day, "item": str(i), "type": "say_on_pay",
         "management": "for", "policy": p, "vote": "for" if st != "awaiting" else None, "status": st, "against_management": False}
        for i, (st, p) in enumerate(zip(statuses, policy, strict=True))
    ]  # fmt: skip


@pytest.mark.parametrize(("statuses", "state", "due"), [
    (["awaiting"] * 4, "awaiting", True), (["cast", "decided", "decided", "declined"], "decided", False), (["cast"] * 4, "cast", False),
])  # fmt: skip
def test_run_ballot_state_ac36_to_ac38(pg, statuses, state, due):
    [row] = cockpit.build(pg, date(2026, 11, 17), _run(statuses), {}, None)["shareholder_meetings"]
    assert (row["items"], row["flagged"], row["ballot_state"], row["action_due"], row["run_id"]) == (4, 2, state, due, "r1")


def test_run_row_replaces_ledger_meeting_and_latest_run_wins_ac39(pg):
    _company(pg, "H", "Hotel")
    _meeting(pg, "H", "2026-11-19")
    runs = _run(["cast"] * 4, run_id="new") + _run(["awaiting"] * 4, run_id="old")
    [row] = cockpit.build(pg, date(2026, 11, 17), runs, {}, None)["shareholder_meetings"]
    assert (row["run_id"], row["ballot_state"]) == ("new", "cast")


# --- voting season ----------------------------------------------------------------------------------------------


def _decisions(pg, day, rows, key):
    with transaction(pg) as s:
        s.add(VoteMeetingModel(meeting_id=key, source="test", external_id=key, company_id="isin_XG", meeting_date=datetime.fromisoformat(day).replace(tzinfo=UTC)))
        s.flush()
        for i, (cats, proponent, vote, am) in enumerate(rows):
            item = f"{key}i{i}"
            s.add(VoteItemModel(item_id=item, source="test", external_id=item, meeting_id=key, categories=cats, proponent=proponent))
            s.flush()
            s.add(VoteDecisionModel(decision_id=f"{key}d{i}", source="test", external_id=f"{key}d{i}", item_id=item, vote=vote, against_management=am))


def test_voting_season_and_topics_ac40_ac41(client, pg):
    _company(pg, "isin_XG", "Gamma SE")
    _decisions(pg, "2026-03-10", [
        (["DIRECTOR ELECTIONS"], "issuer", "for", False), (["SECTION 14A SAY-ON-PAY VOTES"], "issuer", "against", True),
        (["AUDIT-RELATED"], "issuer", "abstain", None), (["OTHER SOCIAL MATTERS"], "shareholder", "for", True),
    ], "m1")  # fmt: skip
    _decisions(pg, "2025-12-01", [(["X"], None, "for", False)], "m2")
    _decisions(pg, "2026-11-20", [(["X"], None, "for", False)], "m3")
    v = _get(client)["voting"]
    assert {k: v[k] for k in ("season", "meetings", "votes", "for", "against", "abstain", "other", "against_management")} == {
        "season": 2026, "meetings": 1, "votes": 4, "for": 2, "against": 1, "abstain": 1, "other": 0, "against_management": 2,
    }  # fmt: skip
    assert [(t["topic"], t["votes"], t["against_management"]) for t in v["topics"]] == [
        ("Shareholder proposals", 1, 1), ("Remuneration", 1, 1), ("Director elections", 1, 0), ("Auditors", 1, 0), ("Capital and other", 0, 0),
    ]  # fmt: skip


def test_vote_values_ac42():
    assert [cockpit._vote_bucket(v) for v in ("withhold", "one_year", "do_not_vote", "for")] == ["against", "other", "other", "for"]


def test_split_vote_counts_twice_ac43(client, pg):
    _company(pg, "isin_XG", "Gamma SE")
    _decisions(pg, "2026-03-10", [(["X"], None, "for", False)], "m1")
    with transaction(pg) as s:
        s.add(VoteDecisionModel(decision_id="split", source="test", external_id="split", item_id="m1i0", vote="for"))
    v = _get(client)["voting"]
    assert (v["votes"], v["meetings"]) == (2, 1)


def test_cast_run_vote_counts_unless_in_ledger(pg):
    rows = _run(["cast"] * 4, day="2026-05-01")
    assert cockpit.build(pg, date(2026, 11, 17), rows, {}, None)["voting"]["topics"][1]["votes"] == 4
    _company(pg, "isin_XG", "G")
    _decisions(pg, "2026-05-01", [(["X"], None, "for", False)], "m1")
    with transaction(pg) as s:
        s.execute(update(VoteDecisionModel).values(run_id="r1"))
    assert cockpit.build(pg, date(2026, 11, 17), rows, {}, None)["voting"]["votes"] == 1


# --- scope and demo -----------------------------------------------------------------------------------------------


def test_portfolio_scope_and_list_ac44_ac45(client, pg):
    store = build_portfolio_store(get_settings())
    store.save_portfolio(Portfolio(portfolio_id="P", name="Zeta fund"))
    store.save_portfolio(Portfolio(portfolio_id="Q", name="Alpha fund"))
    store.save_company(CompanyRef(company_id=A, name="Alpha AG"))
    store.save_security(SecurityRef(security_id="XA0000000001", isin="XA0000000001", name="Alpha", asset_class="equity", currency="EUR", company_id=A))
    store.save_snapshot("P", "2026-11-01", [Holding(holder_id="P", security_id="XA0000000001", as_of_date="2026-11-01", market_value_eur=1.0)])
    for c, ext in ((A, "A"), ("isin_XB", "B")):
        _confirm(c, TIERS[0])
        _engagement(client, pg, company_id=c, name=ext, ext=ext, objectives=[])
        _meeting(pg, c, "2026-11-20", key=f"m{ext}")
    body = _get(client, portfolio_id="P")
    assert body["scope"] == {"portfolio_id": "P", "label": "Zeta fund"}
    assert body["summary"]["selected"] == 1
    for key in ("engagement_meetings", "shareholder_meetings", "control_gaps"):
        assert {r["company_id"] for r in body[key]} == {A}, key
    assert {c["company_id"] for s in body["ladder"] for c in s["companies"]} == {A}
    everything = _get(client)
    assert everything["scope"] == {"portfolio_id": None, "label": f"All portfolios ({len(everything['portfolios'])})"}
    names = [p["name"] for p in everything["portfolios"]]
    assert names == sorted(names) and {"Alpha fund", "Zeta fund"} <= set(names)


def test_demo_flag_ac46(client, pg):
    eid = _engagement(client, pg)
    assert _get(client)["demo"] is False
    with transaction(pg) as s:
        s.execute(update(StwEngagementModel).where(StwEngagementModel.engagement_id == eid).values(source="mock_voice_seed"))
    assert _get(client)["demo"] is True


# --- seed-cockpit-demo ----------------------------------------------------------------------------------------------


def _demo_stack(pg, n_companies=16, n_engagements=40, outside_eur=0.0):
    """`outside_eur`: one more held company, with no stewardship row, holding that much."""
    store = build_portfolio_store(get_settings())
    store.save_portfolio(Portfolio(portfolio_id="D", name="Demo"))
    holdings = []
    if outside_eur:
        store.save_company(CompanyRef(company_id="isin_XO0000000000", name="Outside"))
        store.save_security(SecurityRef(security_id="XO0000000000", isin="XO0000000000", name="Outside", asset_class="equity", currency="EUR", company_id="isin_XO0000000000"))
        holdings.append(Holding(holder_id="D", security_id="XO0000000000", as_of_date="2026-11-01", market_value_eur=outside_eur))
    with transaction(pg) as s:
        for i in range(n_companies):
            isin = f"XD{i:010d}"
            store.save_company(CompanyRef(company_id=f"isin_{isin}", name=f"Co {i}"))
            store.save_security(SecurityRef(security_id=isin, isin=isin, name=f"Co {i}", asset_class="equity", currency="EUR", company_id=f"isin_{isin}"))
            holdings.append(Holding(holder_id="D", security_id=isin, as_of_date="2026-11-01", market_value_eur=1e6))
            s.add(StwCompanyModel(company_id=f"isin_{isin}", source="mock_voice_seed", name=f"Co {i}"))
        s.flush()
        for i in range(n_engagements):
            s.add(StwEngagementModel(engagement_id=f"iss_demo{i}", source="mock_voice_seed", external_id=f"s7:{i}", company_id=f"isin_XD{i % n_companies:010d}",
                                     status="open", fir_theme="climate_mitigation", escalation_stage="private_engagement",
                                     started_at=datetime(2026, 6, 1, tzinfo=UTC)))  # fmt: skip
    store.save_snapshot("D", "2026-11-01", holdings)


def _seed(as_of):
    return CliRunner().invoke(cli, ["stewardship", "seed-cockpit-demo", "--as-of", as_of])


def _counts(pg):
    with transaction(pg) as s:
        rows = [s.scalar(select(func.count()).select_from(m)) for m in (StwEngagementModel, StwTransitionModel, VoteMeetingModel, VoteItemModel)]
        dates = dict(s.execute(select(StwEngagementModel.engagement_id, StwEngagementModel.planned_meeting_date)).all())
    tiers = TierStore(get_settings().stewardship_streams_dir)
    return rows, dates, len(tiers.all())


def test_seed_cockpit_demo_ac47_to_ac51_ac76_to_ac78(client, pg):
    _demo_stack(pg)
    result = _seed("2026-11-27")
    lines = result.stdout.splitlines()
    assert result.exit_code == 0, result.stdout
    assert len(lines) == 4 and lines[0] == "ok planned: 40 engagements" and lines[3] == "ok meetings: 14 upcoming"
    assert [line.split(":")[0] for line in lines] == ["ok planned", "ok escalation", "ok tiers", "ok meetings"]
    body = _get(client, as_of="2026-11-27")
    rows = body["shareholder_meetings"]
    assert [r["days_to_meeting"] for r in rows] == OFFSETS and {r["ballot_state"] for r in rows} == {"not_started"}
    assert sum(r["action_due"] for r in rows) == 4 and body["demo"] is True
    # owner decision 15 Nov: tiers are confirmed under the held ledger companies' keys, so they count as engaged
    held = {f"isin_XD{i:010d}" for i in range(16)}
    assert {r["issuer_id"] for r in TierStore(get_settings().stewardship_streams_dir).all()} == held
    assert body["summary"] == {"selected": 16, "engaged_selected": 16, "engaged_outside_selection": 0}
    with transaction(pg) as s:
        for e in s.scalars(select(StwEngagementModel)):
            assert e.planned_meeting_date == planned_date(e.engagement_id, date(2026, 11, 27))
    before = _counts(pg)
    assert _seed("2026-11-27").exit_code == 0
    assert _counts(pg) == before
    eid = _engagement(client, pg, company_id="isin_XD0000000000", ext="api1", planned_meeting_date="")
    with transaction(pg) as s:
        stage = s.get(StwEngagementModel, eid).escalation_stage
    assert _seed("2026-12-01").exit_code == 0
    with transaction(pg) as s:
        e = s.get(StwEngagementModel, eid)
        assert (e.planned_meeting_date, e.escalation_stage) == (None, stage)
    assert [r["days_to_meeting"] for r in _get(client, as_of="2026-12-01")["shareholder_meetings"]] == OFFSETS


def test_seed_tiers_cover_every_held_company_by_house_share(client, pg):
    # 16 ledger companies at EUR 1m beside EUR 10bn in a held company with no ledger row (owner decisions 15 Nov):
    # every held company gets a tier under its company key, weighted by its share of all house holdings
    _demo_stack(pg, outside_eur=1e10)
    assert _seed("2026-11-27").exit_code == 0
    rows = {r["issuer_id"]: r for r in TierStore(get_settings().stewardship_streams_dir).all()}
    outside = rows.pop("isin_XO0000000000")
    assert (outside["tier"], outside["rule"], outside["name"]) == ("bilateral", "top_weight", "Outside")
    assert len(rows) == 16 and "top_weight" not in {r["rule"] for r in rows.values()}
    assert all(r["inputs"]["holding"]["index_weight_pct"] < 0.05 for r in rows.values())
    assert _get(client, as_of="2026-11-27")["summary"] == {"selected": 17, "engaged_selected": 16, "engaged_outside_selection": 0}


def test_seed_cockpit_demo_fails_without_enough_held_companies(client, pg):
    result = _seed("2026-11-27")
    assert result.exit_code == 1
    assert result.stdout.splitlines()[-1].startswith("FAIL meetings:")
