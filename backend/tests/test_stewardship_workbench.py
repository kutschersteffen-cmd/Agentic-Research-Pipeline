"""Spec stewardship-priority-worklist, PR 2 (backend workbench): scopes, selection per scope, `held_in`,
`selected_elsewhere`, the always-shown fields, Equity held and Ownership share, notes and the vote ledger per company.
Fixture W is the synthetic sample universe; the fund tests load two small funds into the portfolio store."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("zen")

from arp.api.deps import get_portfolio_store, get_stream_store, settings_dep  # noqa: E402
from arp.api.main import app  # noqa: E402
from arp.config import Settings, get_settings  # noqa: E402
from arp.schemas.common import CompanyRef  # noqa: E402
from arp.schemas.engagement import CorrespondenceEntry, EngagementIssue, EngagementRecord  # noqa: E402
from arp.schemas.portfolio import DataPointObservation, Holding, Portfolio, SecurityRef, SecurityResolution  # noqa: E402
from arp.stewardship import worklist  # noqa: E402
from arp.stewardship.intake import intake_votes  # noqa: E402
from arp.stewardship.process import StreamStore  # noqa: E402
from arp.stewardship.universe import HouseUniverseSetting  # noqa: E402
from arp.storage.portfolio_store_factory import build_portfolio_store  # noqa: E402

pytestmark = pytest.mark.usefixtures("sample_house_universe", "pg")
Q = worklist.cycle_of(datetime.now(UTC).date())


@pytest.fixture
def root():
    return get_settings().stewardship_streams_dir


@pytest.fixture
def client(root, monkeypatch, tmp_path):
    monkeypatch.setenv("ARP_ENGAGEMENTS_DIR", str(tmp_path / "engagements"))
    monkeypatch.setenv("ARP_ENGAGEMENT_STORE", "postgres")
    monkeypatch.setenv("ARP_PORTFOLIOS_DIR", str(tmp_path / "portfolios"))
    get_settings.cache_clear()
    get_portfolio_store.cache_clear()  # cached by the groups routes
    app.dependency_overrides[get_stream_store] = lambda: StreamStore(root)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_stream_store, None)
    get_portfolio_store.cache_clear()


def _rows(client, scope: str = "house") -> dict[str, dict]:
    r = client.get("/api/stewardship/worklist", params={"scope": scope})
    assert r.status_code == 200, r.text
    return {row["issuer_id"]: row for row in r.json()["rows"]}


def _group(client, kind: str, members: list[str], name: str = "g") -> str:
    r = client.post("/api/portfolio/groups", json={"name": name, "kind": kind, "members": members})
    assert r.status_code == 200, r.text
    return r.json()["group_id"]


def test_always_shown_fields_under_fixture_w(client):
    # AC-107
    row = _rows(client)["SYN03"]
    assert (row["identifier"], row["engaged"], row["last_topics"]) == ("SYN03", {"yes": False, "last": None}, [])
    assert row["norms_violation"] is None and row["ownership_pct"] is None and row["esg_extra"] == {}
    assert (row["equity_held_eur_m"], row["held_in"], row["selected_elsewhere"]) == (0.0, [], [])
    assert row["notes"] == {"count": 0, "latest": None}


def test_engaged_from_intake_activity(client, pg):
    # AC-108, AC-109
    assert client.post("/api/engagement/records", json={"company_id": "SYN06", "name": "SYN06"}).status_code == 200
    batch = {
        "engagements": [{"external_id": "e1", "company_id": "SYN06", "theme": "board_governance", "started_at": "2026-08-01T00:00:00Z", "status": "open"}],
        "activities": [{"external_id": "a1", "engagement_external_id": "e1", "occurred_at": "2026-09-12T10:00:00Z", "activity_type": "meeting",
                        "interaction_type": "informational", "summary": "x"}],
    }  # fmt: skip
    r = client.post("/api/stewardship/intake/engagements", json=batch)
    assert r.status_code == 200, r.text
    row = _rows(client)["SYN06"]
    assert row["engaged"] == {"yes": True, "last": "2026-09-12"} and row["last_topics"] == ["board_governance"]


def test_engaged_and_topics_rules():
    def issue(theme, opened, *dates, fir=None):
        return EngagementIssue(theme=theme, opened_at=opened, fir_theme=fir,
                               correspondence=[CorrespondenceEntry(date=d, type="letter", summary="s") for d in dates])  # fmt: skip

    record = EngagementRecord(company_id="C", name="C", issues=[
        issue("a", "2026-01-01T00:00:00Z", "2026-03-01T23:30:00-02:00"),  # 2 Mar in UTC
        issue("b", "2026-06-01T00:00:00Z", fir="climate_mitigation"),
        issue("c", "2026-02-01T00:00:00Z"),
        issue("a", "2026-01-15T00:00:00Z"),
        issue("d", "2025-01-01T00:00:00Z"),
    ])  # fmt: skip
    engaged, topics = worklist.engaged(record)
    # last: the latest correspondence, not the newer opened_at of an issue without correspondence
    assert engaged == {"yes": True, "last": "2026-03-02"}
    assert topics == ["Climate Mitigation & Paris Alignment", "a", "c"]
    assert worklist.engaged(EngagementRecord(company_id="C", name="C", issues=[issue("x", "2026-04-05T08:00:00Z")]))[0]["last"] == "2026-04-05"
    assert worklist.engaged(EngagementRecord(company_id="C", name="C"))[0] == {"yes": False, "last": None}


def test_fund_scopes_need_the_portfolio_universe(client):
    # AC-67, AC-72
    r = client.get("/api/stewardship/worklist", params={"scope": "portfolio:anything"})
    assert (r.status_code, r.json()["detail"]) == (422, "Fund scopes need the portfolio universe")
    funds = _group(client, "portfolios", ["p1"])
    assert client.get("/api/stewardship/worklist", params={"scope": f"group:{funds}"}).json()["detail"] == "Fund scopes need the portfolio universe"
    sec = _group(client, "securities", ["s1"])
    r = client.get("/api/stewardship/worklist", params={"scope": f"group:{sec}"})
    assert (r.status_code, r.json()["detail"]) == (422, "Groups of securities are not a workbench scope")
    assert client.get("/api/stewardship/worklist", params={"scope": "group:nope"}).status_code == 404
    assert client.get("/api/stewardship/worklist", params={"scope": "nope"}).status_code == 422
    assert client.get("/api/stewardship/selection", params={"scope": "group:nope"}).status_code == 404
    # with the sample universe only the house and groups of companies are scopes
    companies = _group(client, "companies", ["SYN01"], name="c")
    scopes = client.get("/api/stewardship/worklist/scopes").json()["scopes"]
    assert scopes == [{"key": "house", "label": "All house holdings", "kind": "house", "companies": 12},
                      {"key": f"group:{companies}", "label": "c", "kind": "group", "companies": 1}]  # fmt: skip


def test_selection_per_scope(client):
    # AC-71, AC-73, AC-74, AC-97, AC-75, AC-76
    g = _group(client, "companies", ["SYN01", "SYN02"])
    assert set(_rows(client, f"group:{g}")) == {"SYN01", "SYN02"}
    r = client.post("/api/stewardship/selection", json={"cycle": Q, "scope": f"group:{g}", "add": ["SYN05"]})
    assert (r.status_code, r.json()["detail"]) == (422, f"not in scope group:{g}: SYN05")
    assert client.post("/api/stewardship/selection", json={"cycle": Q, "scope": f"group:{g}", "add": ["SYN01"]}).status_code == 200
    syn01 = _rows(client)["SYN01"]
    assert syn01["selected_elsewhere"] == [{"scope": f"group:{g}", "label": "g", "status": "proposed"}]
    assert syn01["selection"] is None
    assert _rows(client, f"group:{g}")["SYN01"]["selection"]["status"] == "proposed"
    assert client.post("/api/stewardship/selection", json={"cycle": Q, "scope": "house", "add": ["SYN02"]}).status_code == 200
    assert client.post("/api/stewardship/selection/confirm", json={"cycle": Q, "scope": "house"}).json() == {"confirmed": 1}
    rows = client.get("/api/stewardship/selection", params={"cycle": Q, "scope": f"group:{g}"}).json()["rows"]
    assert [(r["issuer_id"], r["status"], r["in_scope"]) for r in rows] == [("SYN01", "proposed", True)]
    assert _rows(client, f"group:{g}")["SYN02"]["selected_elsewhere"] == [{"scope": "house", "label": "All house holdings", "status": "confirmed"}]


def test_notes(client):
    # AC-77 to AC-83, AC-98, AC-101
    before = {k: r["score"] for k, r in _rows(client).items()}
    r = client.post("/api/stewardship/notes", json={"company_id": "SYN04", "text": "  Board change expected  "})
    assert r.status_code == 200, r.text
    assert (r.json()["text"], r.json()["by"], r.json()["scope"]) == ("Board change expected", "Test", "house")
    for text in ("   ", "x" * 2001):
        r = client.post("/api/stewardship/notes", json={"company_id": "SYN04", "text": text})
        assert (r.status_code, r.json()["detail"]) == (422, "A note needs 1 to 2,000 characters")
    assert client.post("/api/stewardship/notes", json={"company_id": "SYN99", "text": "x"}).json()["detail"] == "unknown company"
    assert client.post("/api/stewardship/notes", json={"company_id": "SYN04", "text": "x", "scope": "group:nope"}).status_code == 404
    assert client.post("/api/stewardship/notes", json={"company_id": "SYN04", "text": "x" * 2000}).status_code == 200
    client.post("/api/stewardship/notes", json={"company_id": "SYN04", "text": "second"})
    notes = client.get("/api/stewardship/notes", params={"company_id": "SYN04"}).json()["notes"]
    assert [n["text"] for n in notes] == ["second", "x" * 2000, "Board change expected"]
    for method in ("put", "delete"):
        assert getattr(client, method)(f"/api/stewardship/notes/{notes[0]['note_id']}").status_code in (404, 405)
    row = _rows(client)["SYN04"]
    assert row["notes"]["count"] == 3 and row["notes"]["latest"]["text"] == "second"
    assert {k: r["score"] for k, r in _rows(client).items()} == before
    assert client.post("/api/stewardship/notes", json={"company_id": "SYN05", "text": "y" * 300}).status_code == 200
    assert _rows(client)["SYN05"]["notes"]["latest"]["text"] == "y" * 120


def test_viewer_cannot_add_a_note(tmp_path):
    # AC-84
    users = tmp_path / "users.json"
    users.write_text(json.dumps({"users": [{"token": "tv", "user_id": "u", "name": "V", "role": "viewer"}]}))
    app.dependency_overrides.clear()  # an autouse fixture signs everyone in
    app.dependency_overrides[settings_dep] = lambda: Settings(users_file=users, auth_mode="local")
    try:
        r = TestClient(app).post("/api/stewardship/notes", json={"company_id": "SYN01", "text": "x"}, headers={"Authorization": "Bearer tv"})
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 403


def test_votes_of_a_company(client, pg):
    # AC-85, AC-86, AC-100
    assert client.post("/api/engagement/records", json={"company_id": "SYN04", "name": "SYN04"}).status_code == 200

    def vote(n, day, item, **extra):
        return {"external_id": f"d{n}", "company_id": "SYN04", "meeting_date": day, "item_number": item, "description": "x",
                "management_recommendation": "for", "vote": "for", **extra}  # fmt: skip

    rows = [vote(1, "2025-05-01", "1"), vote(2, "2026-05-01", "10"), vote(3, "2026-05-01", "2")]
    assert intake_votes(rows, pg, "api").rejected == []
    assert intake_votes([vote(4, "2024-05-01", "1")], pg, "npx_urth_demo").rejected == []
    body = client.get("/api/stewardship/votes", params={"company_id": "SYN04"}).json()
    assert body["total"] == 4
    assert [(v["meeting_date"], v["item_number"], v["demo"]) for v in body["votes"]] == [
        ("2026-05-01", "2", False), ("2026-05-01", "10", False), ("2025-05-01", "1", False), ("2024-05-01", "1", True)
    ]  # fmt: skip
    assert client.get("/api/stewardship/votes", params={"company_id": "SYN05"}).json() == {"votes": [], "total": 0}
    # two meetings on one date (one per source): each meeting's items stay together, not 1, 2, 3, 10 interleaved
    assert intake_votes([vote(5, "2026-05-01", "1"), vote(6, "2026-05-01", "3")], pg, "npx_urth_demo").rejected == []
    same_day = [(v["item_number"], v["demo"]) for v in client.get("/api/stewardship/votes", params={"company_id": "SYN04"}).json()["votes"][:4]]
    assert same_day in ([("2", False), ("10", False), ("1", True), ("3", True)], [("1", True), ("3", True), ("2", False), ("10", False)])


@pytest.fixture
def funds(client, pg):
    """Two funds on the portfolio universe: P1 holds A (equity 30 m + bond 20 m) and B (equity 50 m); P2 holds B
    (equity 100 m). EVIC of A is 10,000 m (simulated)."""
    settings = get_settings()
    store = build_portfolio_store(settings)
    for cid in ("A", "B"):
        store.save_company(CompanyRef(company_id=cid, name=f"Company {cid}", sector="Energy"))
    for sid, cid, cls in (("A-EQ", "A", "equity"), ("A-BD", "A", "corporate_bond"), ("B-EQ", "B", "equity")):
        store.save_security(SecurityRef(security_id=sid, name=sid, asset_class=cls, currency="EUR", company_id=cid))
        store.save_resolution(SecurityResolution(security_id=sid, company_id=cid, confidence=1.0))
    for pid, held in (("P1", (("A-EQ", 30e6), ("A-BD", 20e6), ("B-EQ", 50e6))), ("P2", (("B-EQ", 100e6),))):
        store.save_portfolio(Portfolio(portfolio_id=pid, name=f"Fund {pid}"))
        store.save_snapshot(pid, "2026-11-02", [Holding(holder_id=pid, security_id=s, as_of_date="2026-11-02", market_value_eur=v) for s, v in held])
    for fid, value in (("climate_evic_eur_m", 10000.0), ("norms_violation", True), ("coal_revenue_pct", 0.1)):  # read as of the snapshot
        store.append_observation(DataPointObservation(company_id="A", field_id=fid, field_name=fid, value=value, source="simulated", observed_at="2026-11-01"))
    HouseUniverseSetting(settings.stewardship_streams_dir).set("portfolio", "tests")
    return store


def test_fund_scopes(client, funds):
    # AC-66, AC-68, AC-69, AC-70, AC-111, AC-112 (on two small funds)
    scopes = client.get("/api/stewardship/worklist/scopes").json()["scopes"]
    assert [(s["key"], s["label"], s["companies"]) for s in scopes] == [
        ("house", "All house holdings", 2), ("portfolio:P1", "Fund P1", 2), ("portfolio:P2", "Fund P2", 1)
    ]  # fmt: skip
    p1 = _rows(client, "portfolio:P1")
    assert sum(r["holdings_weight_pct"] for r in p1.values()) == pytest.approx(100, abs=0.1)
    assert all("P1" in [h["portfolio_id"] for h in r["held_in"]] for r in p1.values())
    a = p1["A"]
    assert (a["aum_held_eur_m"], a["equity_held_eur_m"], a["holdings_weight_pct"]) == (50.0, 30.0, 50.0)
    assert a["ownership_pct"] == {"value": 0.5, "simulated": True}
    assert a["norms_violation"] == {"value": True, "simulated": True}
    assert a["esg_extra"] == {"coal_revenue_pct": {"value": 0.1, "simulated": True}}
    house = _rows(client)
    assert (house["B"]["aum_held_eur_m"], house["B"]["equity_held_eur_m"]) == (150.0, 150.0)
    assert house["B"]["held_in"] == [
        {"portfolio_id": "P1", "name": "Fund P1", "weight_pct": 50.0, "market_value_eur_m": 50.0, "selection_status": None},
        {"portfolio_id": "P2", "name": "Fund P2", "weight_pct": 100.0, "market_value_eur_m": 100.0, "selection_status": None},
    ]
    for cid in ("open_triggers", "overdue_commitments", "escalated", "transition_grade"):
        assert [p for p in p1["B"]["parts"] if p["id"] == cid][0]["normalised"] == [p for p in house["B"]["parts"] if p["id"] == cid][0]["normalised"]
    # a fund selection shows in held_in and selected_elsewhere of every other scope
    assert client.post("/api/stewardship/selection", json={"scope": "portfolio:P2", "add": ["A"]}).json()["detail"] == "not in scope portfolio:P2: A"
    assert client.post("/api/stewardship/selection", json={"scope": "portfolio:P2", "add": ["B"]}).status_code == 200
    b = _rows(client)["B"]
    assert [h["selection_status"] for h in b["held_in"]] == [None, "proposed"]
    assert b["selected_elsewhere"] == [{"scope": "portfolio:P2", "label": "Fund P2", "status": "proposed"}]
    g = _group(client, "portfolios", ["P2"], name="Only P2")
    assert set(_rows(client, f"group:{g}")) == {"B"}
    assert client.get("/api/stewardship/worklist", params={"scope": "portfolio:P9"}).status_code == 404


def test_ownership_and_equity_in_build(tmp_path):
    # AC-111, AC-112 (unit): C held for EUR 50 m (equity 30 m, a bond 20 m), EVIC 10,000 m
    sample = {"source": "portfolio", "note": None, "issuers": [{"issuer_id": "C", "name": "C", "region": "EU", "sector": "x", "fields": {}, "holding": {}}]}
    funds = {"P": {"name": "P", "companies": {"C": [50e6, 30e6]}}}
    evic = {"C": {"climate_evic_eur_m": DataPointObservation(company_id="C", field_id="climate_evic_eur_m", field_name="e", value=10000.0, source="extracted")}}
    scope = {"key": "portfolio:P", "label": "P", "kind": "portfolio", "members": None, "portfolios": ["P"]}
    row = worklist.build(tmp_path, sample, [], observations=evic, today=date(2026, 11, 15), scope=scope, funds=funds)["rows"][0]
    assert (row["equity_held_eur_m"], row["aum_held_eur_m"]) == (30.0, 50.0)
    assert row["ownership_pct"] == {"value": 0.5, "simulated": False}
    # the share divides the unrounded value: EUR 1.04 m of 10,000 m is 0.0104 %, not 1.0 m's 0.0100 %
    small = {"P": {"name": "P", "companies": {"C": [1.04e6, 0.0]}}}
    row = worklist.build(tmp_path, sample, [], observations=evic, today=date(2026, 11, 15), scope=scope, funds=small)["rows"][0]
    assert (row["aum_held_eur_m"], row["ownership_pct"]["value"]) == (1.0, 0.0104)


def test_selection_file_of_an_odd_group_id_stays_in_the_cycle(tmp_path):
    log = worklist.SelectionLog(tmp_path)
    today = date(2026, 11, 15)
    log.change("2026-Q4", today, {"C": "C"}, ["C"], [], "u", 0, scope="group:../../x")
    assert [p.name for p in (tmp_path / "selection" / "2026-Q4").iterdir()] == ["group__..%2F..%2Fx.jsonl"]
    assert list(log.all_rows("2026-Q4")) == ["group:../../x"]
