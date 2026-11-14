"""Spec stewardship-priority-worklist, PR 1 (backend core, house scope). Fixture W: the synthetic sample universe
(SYN01..SYN12), no saved weights, no triggers, no engagement records, an empty vote ledger."""

from __future__ import annotations

import json
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("zen")

from arp.api.deps import get_stream_store, settings_dep  # noqa: E402
from arp.api.main import app  # noqa: E402
from arp.config import Settings, get_settings  # noqa: E402
from arp.schemas.engagement import Commitment, EngagementIssue, EngagementRecord  # noqa: E402
from arp.stewardship import worklist  # noqa: E402
from arp.stewardship.intake import intake_votes  # noqa: E402
from arp.stewardship.policies import PolicyStore  # noqa: E402
from arp.stewardship.process import StreamStore  # noqa: E402
from arp.stewardship.trigger_store import TriggerStore, trigger_id  # noqa: E402

pytestmark = pytest.mark.usefixtures("sample_house_universe", "pg")
SNAPSHOT = Path(__file__).parent / "fixtures" / "stewardship_worklist_unchanged_main.json"
BUNDLED = [c["id"] for c in json.loads((Path(worklist.__file__).parent / "data" / "priority_weights.json").read_text())["components"]]


@pytest.fixture
def root():
    return get_settings().stewardship_streams_dir


@pytest.fixture
def client(root, monkeypatch, tmp_path):
    monkeypatch.setenv("ARP_ENGAGEMENTS_DIR", str(tmp_path / "engagements"))
    monkeypatch.setenv("ARP_ENGAGEMENT_STORE", "postgres")
    get_settings.cache_clear()
    app.dependency_overrides[get_stream_store] = lambda: StreamStore(root)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_stream_store, None)


def _rows(client) -> dict[str, dict]:
    r = client.get("/api/stewardship/worklist")
    assert r.status_code == 200, r.text
    return {row["issuer_id"]: row for row in r.json()["rows"]}


def _part(row: dict, cid: str) -> dict:
    return next(p for p in row["parts"] if p["id"] == cid)


def _run(root: Path, *triggers: tuple[str, str, str]) -> None:
    TriggerStore(root).record_run(datetime.now(UTC).strftime("%Y-%m"), [
        {"issuer_id": i, "rule": rule, "type": "controversy", "theme": "climate", "severity": sev, "reason": "test"}
        for i, sev, rule in triggers
    ])  # fmt: skip


def _issue(client, company: str) -> str:
    assert client.post("/api/engagement/records", json={"company_id": company, "name": company}).status_code == 200
    r = client.post(f"/api/engagement/records/{company}/issues", params={"name": company}, json={"theme": "board_governance"})
    assert r.status_code == 200, r.text
    return r.json()["issue_id"]


def _quarter(today: date) -> str:
    return f"{today.year}-Q{(today.month - 1) // 3 + 1}"


def test_fixture_w_rows_parts_and_empty_columns(client):
    # AC-1, AC-2, AC-33, AC-3, AC-8, AC-9, AC-57
    body = client.get("/api/stewardship/worklist").json()
    ids = [r["issuer_id"] for r in body["rows"]]
    assert sorted(ids) == [f"SYN{n:02d}" for n in range(1, 13)] and len(set(ids)) == 12
    assert body["weights"] == {"version": 0, "activated_by": None, "activated_at": None}
    assert body["scope"] == {"key": "house", "label": "All house holdings", "kind": "house", "companies": 12}
    assert body["cycle"] == _quarter(datetime.now(UTC).date())
    rows = {r["issuer_id"]: r for r in body["rows"]}
    for row in rows.values():
        assert [p["id"] for p in row["parts"]] == BUNDLED
        assert round(sum(p["points"] for p in row["parts"]), 1) == row["score"]
        assert all(_part(row, c)["points"] == 0 for c in ("open_triggers", "overdue_commitments", "escalated"))
        assert row["selection"] is None and row["next_meeting"] is None
    assert _part(rows["SYN03"], "holdings_weight")["normalised"] == 1.0
    assert _part(rows["SYN10"], "holdings_weight")["normalised"] == 0.0
    assert rows["SYN01"]["transition_grade"] is None
    assert _part(rows["SYN01"], "transition_grade") == {"id": "transition_grade", "weight": 10, "normalised": 0.0, "points": 0.0, "empty": True}


def test_triggers_count_and_score_then_resolve(client, root):
    # AC-4, AC-34, AC-5, AC-55
    _run(root, ("SYN03", "high", "t_high"), ("SYN03", "medium", "t_med"))
    row = _rows(client)["SYN03"]
    assert row["triggers"] == {"high": 1, "medium": 1, "low": 0}
    assert {k: _part(row, "open_triggers")[k] for k in ("normalised", "points")} == {"normalised": 0.8, "points": 24.0}
    r = client.post(f"/api/stewardship/triggers/{trigger_id('SYN03', 't_high')}/transition", json={"status": "resolved", "decided_by": "tester"})
    assert r.status_code == 200
    row = _rows(client)["SYN03"]
    assert row["triggers"] == {"high": 0, "medium": 1, "low": 0}
    assert _part(row, "open_triggers")["points"] == 9.0


def test_new_trigger_shows_without_restart(client, root):
    # AC-13
    assert _rows(client)["SYN07"]["triggers"]["high"] == 0
    _run(root, ("SYN07", "high", "t_new"))
    assert _rows(client)["SYN07"]["triggers"]["high"] == 1


def test_overdue_commitment_counts_until_the_issue_closes(client):
    # AC-6, AC-56, AC-54
    past = (datetime.now(UTC).date() - timedelta(days=30)).isoformat()
    for company in ("SYN05", "SYN11"):
        issue = _issue(client, company)
        r = client.post("/api/stewardship/tracking/commitments", json={"company_id": company, "issue_id": issue, "text": "Publish targets", "target_date": past})
        assert r.status_code == 200, r.text
        if company == "SYN11":
            r = client.post("/api/stewardship/tracking/close", json={"company_id": company, "issue_id": issue, "status": "closed", "outcome": "done"})
            assert r.status_code == 200, r.text
    rows = _rows(client)
    assert rows["SYN05"]["overdue_commitments"] == 1 and _part(rows["SYN05"], "overdue_commitments")["points"] == 7.5
    assert rows["SYN11"]["overdue_commitments"] == 0 and rows["SYN11"]["open_engagements"] == 0


def test_escalated_issue(client):
    # AC-7, AC-35, AC-36
    issue = _issue(client, "SYN06")
    r = client.post(f"/api/engagement/records/SYN06/issues/{issue}/escalate", json={"stage": "joint_engagement"})
    assert r.status_code == 200, r.text
    row = _rows(client)["SYN06"]
    assert (row["escalated"], row["open_engagements"], _part(row, "escalated")["points"]) == (1, 1, 10.0)


def _v0_with(**weights: int) -> dict:
    content = PolicyStore(Path("/nonexistent")).content(worklist.POLICY, 0)
    return {**content, "components": [{**c, "weight": weights.get(c["id"], c["weight"])} for c in content["components"]]}


def test_weights_must_add_up_to_100(client):
    # AC-11, AC-37
    r = client.post("/api/stewardship/policies/priority_weights/versions", json={"content": _v0_with(open_triggers=25)})
    assert (r.status_code, r.json()["detail"]) == (422, "Weights must add up to 100 (now 95)")
    assert [v["version"] for v in client.get("/api/stewardship/policies/priority_weights").json()["versions"]] == [0]


@pytest.mark.parametrize(
    ("content", "detail"),
    [
        ({"components": [{"id": "open_triggers", "weight": 100}]}, "Missing components: holdings_weight"),
        (_v0_with() | {"components": [*_v0_with()["components"], {"id": "made_up", "weight": 0}]}, "Unknown components: made_up"),
        (_v0_with() | {"components": [*_v0_with()["components"], {"id": "esg_score", "weight": 0}]}, "Components listed twice: esg_score"),
        (_v0_with(open_triggers=29.5, holdings_weight=20.5), "The weight of open_triggers must be a whole number from 0 to 100"),
    ],
)
def test_weights_validation(content, detail):
    with pytest.raises(ValueError, match=detail):
        worklist.validate_weights(content)


def test_saved_weights_apply_after_four_eyes_activation(root):
    # AC-10, AC-12, AC-58
    store = PolicyStore(root)
    v1 = store.save(worklist.POLICY, _v0_with(open_triggers=0, holdings_weight=50), "", "user_a", {})
    with pytest.raises(ValueError, match="Four-eyes rule"):
        store.activate(worklist.POLICY, v1, "user_a")
    assert store.active_version(worklist.POLICY) == 0
    store.activate(worklist.POLICY, v1, "user_b")
    built = worklist.build(root, _sample(), [])
    assert built["weights"]["version"] == 1 and built["weights"]["activated_by"] == "user_b"
    assert all(_part(r, "open_triggers")["weight"] == 0 for r in built["rows"])


def _sample() -> dict:
    from arp.stewardship.process import load_sample

    return load_sample()


def test_preview_of_the_active_content_changes_nothing(client):
    # AC-14, AC-59
    body = client.post("/api/stewardship/studio/priority/preview", json={"content": _v0_with()}).json()
    assert body["companies"] == 12 and body["entering_top"] == [] and body["leaving_top"] == []
    assert [c["change"] for c in body["score_change"]] == [0] * 12
    assert len(body["top_active"]) == 12 and body["top_active"] == body["top_candidate"]


def test_preview_lists_rank_moves(client):
    rows = [{"issuer_id": f"C{i:02d}", "company": f"C{i:02d}", "normalised": {"holdings_weight": i / 29, "aum_held": 1 - i / 29}} for i in range(30)]
    out = worklist.preview(_v0_with(open_triggers=0, holdings_weight=0, aum_held=75, transition_grade=0, next_meeting=0), _v0_with(), rows)
    assert [m["issuer_id"] for m in out["entering_top"]] == ["C00", "C01", "C02", "C03", "C04"]
    assert out["entering_top"][0] == {"issuer_id": "C00", "company": "C00", "rank_active": 30, "rank_candidate": 1}
    assert {m["issuer_id"] for m in out["leaving_top"]} == {"C25", "C26", "C27", "C28", "C29"}
    assert out["top_candidate"][0]["score"] == 75.0 and out["score_change"][0]["issuer_id"] in ("C00", "C29")
    r = client.post("/api/stewardship/studio/priority/preview", json={"content": _v0_with(open_triggers=25)})
    assert (r.status_code, r.json()["detail"]) == (422, "Weights must add up to 100 (now 95)")


def test_selection_propose_confirm_and_rules(client):
    # AC-15, AC-16, AC-38, AC-17, AC-60, AC-18, AC-20
    q = _quarter(datetime.now(UTC).date())
    before = _rows(client)
    r = client.post("/api/stewardship/selection", json={"cycle": q, "add": ["SYN02", "SYN09"]})
    assert r.status_code == 200, r.text
    rows = _rows(client)
    assert {i for i, row in rows.items() if row["selection"]} == {"SYN02", "SYN09"}
    assert rows["SYN02"]["selection"]["status"] == "proposed" and rows["SYN02"]["selection"]["proposed_by"] == "Test"
    assert all((rows[i]["score"], rows[i]["parts"]) == (before[i]["score"], before[i]["parts"]) for i in rows)
    assert client.post("/api/stewardship/selection/confirm", json={"cycle": q}).json() == {"confirmed": 2}
    sel = client.get("/api/stewardship/selection", params={"cycle": q}).json()
    assert [(s["issuer_id"], s["status"], s["confirmed_by"], s["in_scope"]) for s in sel["rows"]] == [
        ("SYN02", "confirmed", "Test", True), ("SYN09", "confirmed", "Test", True)
    ]  # fmt: skip
    r = client.post("/api/stewardship/selection", json={"cycle": q, "remove": ["SYN02"]})
    assert (r.status_code, r.json()["detail"]) == (422, "confirmed selections cannot be removed")
    assert client.get("/api/stewardship/selection").json()["rows"][0]["status"] == "confirmed"
    first = date.fromisoformat(f"{q[:4]}-{(int(q[-1]) - 1) * 3 + 1:02d}-01")
    prev = _quarter(first - timedelta(days=1))
    r = client.post("/api/stewardship/selection", json={"cycle": prev, "add": ["SYN04"]})
    assert (r.status_code, r.json()["detail"]) == (422, f"only {q} can be changed")


def test_selection_add_remove_unknown_and_bad_cycle(client):
    assert client.post("/api/stewardship/selection", json={"add": ["SYN04"]}).status_code == 200
    assert client.post("/api/stewardship/selection", json={"remove": ["SYN04"]}).json()["rows"] == []
    r = client.post("/api/stewardship/selection", json={"add": ["SYN04", "NOPE"]})
    assert (r.status_code, r.json()["detail"]) == (422, "unknown company: NOPE")
    assert client.get("/api/stewardship/selection").json()["rows"] == []  # nothing written
    assert client.get("/api/stewardship/selection", params={"cycle": "../../x"}).status_code == 422


def test_viewer_cannot_select(tmp_path):
    # AC-19
    users = tmp_path / "users.json"
    users.write_text(json.dumps({"users": [{"token": "tv", "user_id": "u", "name": "V", "role": "viewer"}]}))
    app.dependency_overrides.clear()  # an autouse fixture signs everyone in
    app.dependency_overrides[settings_dep] = lambda: Settings(users_file=users, auth_mode="local")
    try:
        r = TestClient(app).post("/api/stewardship/selection", json={"add": ["SYN01"]}, headers={"Authorization": "Bearer tv"})
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 403


def test_next_meeting_rolls_forward_by_whole_years():
    # AC-106
    today = date(2026, 11, 14)
    sample = {"issuers": [{"issuer_id": "C", "name": "C", "sector": "x", "holding": {}}]}
    row = worklist.indicators(sample, [], [], {"C": ("systemic", False)}, {"C": today - timedelta(days=400)}, {}, today)[0]
    assert row["next_meeting"] == {"days": 330, "estimated": True, "last_meeting": "2025-10-10"}
    assert row["normalised"]["next_meeting"] == 0
    assert worklist.next_meeting(date(2026, 9, 1), today)["days"] == 291
    assert worklist.next_meeting(today, today)["days"] == 0
    assert worklist.next_meeting(date(2024, 2, 29), date(2026, 2, 1))["days"] == 27  # 28 Feb 2026


def test_ledger_meetings_feed_next_meeting(client, pg):
    assert client.post("/api/engagement/records", json={"company_id": "SYN04", "name": "SYN04"}).status_code == 200  # the stw_companies row
    rows = [{"external_id": f"d{n}", "company_id": "SYN04", "meeting_date": day, "item_number": "1", "description": "x",
             "management_recommendation": "for", "vote": "for"} for n, day in enumerate(("2025-05-01", "2026-05-01"))]  # fmt: skip
    assert intake_votes(rows, pg, "api").rejected == []
    assert worklist.last_meetings(pg) == {"SYN04": date(2026, 5, 1)}
    row = _rows(client)["SYN04"]
    assert row["next_meeting"]["last_meeting"] == "2026-05-01" and row["next_meeting"]["estimated"] is True


def test_percentile_rank():
    assert worklist._percentile({"a": 1.0, "b": 2.0, "c": 2.0, "d": 3.0}) == {"a": 0.0, "b": 1 / 3, "c": 1 / 3, "d": 1.0}
    assert worklist._percentile({"a": 5.0}) == {"a": 1.0}


def test_observed_columns_and_simulated_flag():
    from arp.schemas.portfolio import DataPointObservation as Obs

    obs = {"C": {f: Obs(company_id="C", field_id=f, field_name=f, value=v, source="simulated")
                 for f, v in (("transition_grade", "E"), ("esg_score", 3.9), ("controversy_level", 2), ("ghg_intensity", 12.0))}}  # fmt: skip
    sample = {"issuers": [{"issuer_id": "C", "name": "C", "sector": "x", "holding": {}}]}
    row = worklist.indicators(sample, [], [], {"C": ("priority_bilateral", True)}, {}, obs, date(2026, 11, 14))[0]
    assert row["transition_grade"] == {"value": "E", "simulated": True, "label": "Not credible"}
    assert row["esg_score"] == {"value": 3.9, "simulated": True}
    assert {k: row["normalised"][k] for k in ("transition_grade", "esg_score", "controversy", "carbon_intensity", "coverage_tier")} == {
        "transition_grade": 0.8, "esg_score": pytest.approx(0.61), "controversy": 0.4, "carbon_intensity": 1.0, "coverage_tier": 1.0
    }  # fmt: skip


def test_2500_companies_build_in_under_a_second(tmp_path):
    # AC-26
    issuers = [{"issuer_id": f"C{n}", "name": f"C{n}", "region": "EU", "sector": "Energy", "fields": {},
                "holding": {"index_weight_pct": n / 1000, "aum_held_eur_m": n / 10, "change_pct": 0}} for n in range(2500)]  # fmt: skip
    _run(tmp_path, *((f"C{n}", ("high", "medium", "low")[n % 3], "r") for n in range(1000)))
    assert len(TriggerStore(tmp_path).list_triggers()) == 1000
    past = (date.today() - timedelta(days=5)).isoformat()
    records = [
        EngagementRecord(company_id=f"C{n}", name=f"C{n}", issues=[EngagementIssue(theme="t", commitments=[Commitment(text="x", target_date=past)])])
        for n in range(500)
    ]
    start = time.perf_counter()
    built = worklist.build(tmp_path, {"issuers": issuers, "note": None}, records)
    elapsed = time.perf_counter() - start
    assert len(built["rows"]) == 2500 and elapsed < 1.0, elapsed


def test_existing_responses_unchanged(client):
    # AC-51, AC-52: recorded from main under Fixture W before this PR
    got = {
        "tiers": client.get("/api/stewardship/tiers").json(),
        "monitoring_triggers": client.get("/api/stewardship/studio/monitoring/triggers").json(),
        "universe": {k: v for k, v in client.get("/api/stewardship/universe").json().items() if k != "set_at"},
        "coverage_rules": client.get("/api/stewardship/policies/coverage_rules").json(),
    }
    assert got == json.loads(SNAPSHOT.read_text())


def test_non_numeric_observation_is_no_data():
    from arp.schemas.portfolio import DataPointObservation as Obs

    obs = {"C": {"esg_score": Obs(company_id="C", field_id="esg_score", field_name="e", value="3", source="extracted")}}
    sample = {"issuer_id": "C", "name": "C", "sector": "x", "holding": {}}
    row = worklist.indicators({"issuers": [sample]}, [], [], {"C": ("systemic", False)}, {}, obs, date(2026, 11, 14))[0]
    assert row["esg_score"] is None and row["normalised"]["esg_score"] is None


# PR 3: engagement programmes


def test_programmes_built_in_and_new_names(client):
    # AC-113, AC-114, AC-137
    progs = client.get("/api/stewardship/programmes").json()["programmes"]
    assert [(p["programme_id"], p["confirmed"], p["proposed"], p["built_in"]) for p in progs] == [
        ("climate", 0, 0, True), ("nature", 0, 0, True), ("ai", 0, 0, True), ("governance", 0, 0, True)
    ]  # fmt: skip
    r = client.post("/api/stewardship/programmes", json={"name": "Water engagement programme"})
    assert r.status_code == 200, r.text
    assert r.json() == {
        "programme_id": "water_engagement_programme", "name": "Water engagement programme", "built_in": False,
        "created_by": "Test", "created_at": r.json()["created_at"], "confirmed": 0, "proposed": 0,
    }  # fmt: skip
    for name, detail in [
        ("WATER ENGAGEMENT PROGRAMME", "A programme named WATER ENGAGEMENT PROGRAMME exists"),
        ("AI", "A programme with id ai exists"),
        ("  ", "A programme name needs 1 to 80 characters"),
        ("x" * 81, "A programme name needs 1 to 80 characters"),
        ("!!", "A programme name needs a letter or a digit"),
    ]:
        r = client.post("/api/stewardship/programmes", json={"name": name})
        assert (r.status_code, r.json()["detail"]) == (422, detail)
    progs = client.get("/api/stewardship/programmes").json()["programmes"]
    assert [p["programme_id"] for p in progs] == ["climate", "nature", "ai", "governance", "water_engagement_programme"]


def test_programme_members_propose_confirm_remove_end(client):
    # AC-115, AC-117, AC-118, AC-119, AC-120, AC-123
    before = _rows(client)
    for pid in ("climate", "nature"):
        assert client.post(f"/api/stewardship/programmes/{pid}/members", json={"add": ["SYN03"]}).status_code == 200
    rows = _rows(client)
    assert rows["SYN03"]["programmes"] == [
        {"programme_id": "climate", "name": "Climate engagement programme", "status": "proposed"},
        {"programme_id": "nature", "name": "Nature engagement programme", "status": "proposed"},
    ]
    assert all(rows[i]["programmes"] == [] for i in rows if i != "SYN03")
    assert client.post("/api/stewardship/programmes/climate/confirm", json={}).json() == {"confirmed": 1}
    member = client.get("/api/stewardship/programmes/climate").json()["members"][0]
    assert (member["issuer_id"], member["status"], member["confirmed_by"]) == ("SYN03", "confirmed", "Test")
    assert all(r["score"] == before[i]["score"] for i, r in _rows(client).items())
    r = client.post("/api/stewardship/programmes/climate/members", json={"remove": ["SYN03"]})
    assert (r.status_code, r.json()["detail"]) == (422, "confirmed members are ended, not removed")
    r = client.post("/api/stewardship/programmes/climate/members", json={"end": ["SYN03"]})
    assert (r.status_code, r.json()["detail"]) == (422, "Ending a membership needs a reason")
    r = client.post("/api/stewardship/programmes/climate/members", json={"end": ["SYN03"], "reason": "objective achieved"})
    assert r.status_code == 200, r.text
    member = client.get("/api/stewardship/programmes/climate").json()["members"][0]
    assert (member["status"], member["ended_by"], member["end_reason"]) == ("ended", "Test", "objective achieved")
    assert [p["programme_id"] for p in _rows(client)["SYN03"]["programmes"]] == ["nature"]
    # an ended company can be proposed again; a proposed one can be removed
    body = client.post("/api/stewardship/programmes/climate/members", json={"add": ["SYN03", "SYN04"], "remove": []}).json()
    assert [(m["issuer_id"], m["status"]) for m in body["members"]] == [("SYN03", "proposed"), ("SYN04", "proposed")]
    body = client.post("/api/stewardship/programmes/climate/members", json={"remove": ["SYN04"]}).json()
    assert [m["issuer_id"] for m in body["members"]] == ["SYN03"] and (body["proposed"], body["confirmed"]) == (1, 0)


def test_programme_unknown_company_and_programme(client):
    r = client.post("/api/stewardship/programmes/climate/members", json={"add": ["SYN01", "NOPE"]})
    assert (r.status_code, r.json()["detail"]) == (422, "unknown company: NOPE")
    assert client.get("/api/stewardship/programmes/climate").json()["members"] == []  # nothing written
    for method, path in [
        ("get", "nope"), ("post", "nope/members"), ("post", "nope/confirm"), ("get", "nope/suggestions")
    ]:  # fmt: skip
        r = getattr(client, method)(f"/api/stewardship/programmes/{path}", **({"json": {}} if method == "post" else {}))
        assert r.status_code == 404, path


def test_programme_suggestions(client, root):
    # AC-121, AC-122 (logic); the route returns [] when nothing matches
    from arp.stewardship.programmes import ProgrammeLog

    def record(cid: str, status: str, fir: str) -> EngagementRecord:
        return EngagementRecord(company_id=cid, name=cid, issues=[EngagementIssue(theme="t", status=status, fir_theme=fir)])

    records = [record("SYN07", "open", "climate_mitigation"), record("SYN08", "closed", "climate_mitigation"),
               record("SYN09", "stalled", "climate_mitigation"), record("SYN10", "open", "natural_capital"),
               record("GONE", "open", "climate_mitigation")]  # fmt: skip
    names = {i: i for i in ("SYN07", "SYN08", "SYN09", "SYN10")}
    log = ProgrammeLog(root)
    got = log.suggestions("climate", names, records)
    assert [s["issuer_id"] for s in got] == ["SYN07", "SYN09"]
    assert got[0]["issues"] == [{"issue_id": records[0].issues[0].issue_id, "fir_theme": "climate_mitigation"}]
    assert log.programme("climate")["members"] == []  # suggestions write nothing
    log.change("climate", names, ["SYN09"], [], [], None, "T")
    assert [s["issuer_id"] for s in log.suggestions("climate", names, records)] == ["SYN07"]
    assert [s["issuer_id"] for s in log.suggestions("nature", names, records)] == ["SYN10"]
    log.create("Water", "T")
    assert log.suggestions("water", names, records) == []
    assert client.get("/api/stewardship/programmes/climate/suggestions").json() == {"suggestions": []}


def test_viewer_cannot_create_programme(tmp_path):
    # AC-135
    users = tmp_path / "users.json"
    users.write_text(json.dumps({"users": [{"token": "tv", "user_id": "u", "name": "V", "role": "viewer"}]}))
    app.dependency_overrides.clear()  # an autouse fixture signs everyone in
    app.dependency_overrides[settings_dep] = lambda: Settings(users_file=users, auth_mode="local")
    try:
        r = TestClient(app).post("/api/stewardship/programmes", json={"name": "X"}, headers={"Authorization": "Bearer tv"})
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 403


# carried over from the code review of #451


def test_selection_removes_a_company_that_left_the_universe(root):
    # finding 1: only `add` ids are checked against the universe
    log, today = worklist.SelectionLog(root), datetime.now(UTC).date()
    q = worklist.cycle_of(today)
    log.change(q, today, {"SYN01": "One"}, ["SYN01"], [], "T", 0)
    log.change(q, today, {}, [], ["SYN01"], "T", 0)
    assert log.rows(q) == []


def test_selection_later_added_never_overwrites_a_confirmed_row(root):
    # finding 2
    log, q = worklist.SelectionLog(root), worklist.cycle_of(datetime.now(UTC).date())
    path = root / "selection" / q / "house.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    e = {"issuer_id": "SYN01", "company": "One", "at": "2026-11-01", "weights_version": 0}
    path.write_text("".join(json.dumps(x) + "\n" for x in [
        {**e, "event": "added", "by": "a"}, {**e, "event": "confirmed", "by": "b"}, {**e, "event": "added", "by": "c"}
    ]))  # fmt: skip
    [row] = log.rows(q)
    assert (row["status"], row["proposed_by"], row["confirmed_by"]) == ("confirmed", "a", "b")


def test_preview_validates_before_building_rows_and_reads_ids_once(client, monkeypatch):
    # finding 5
    def boom(*a, **k):
        raise AssertionError("rows built for invalid weights")

    with monkeypatch.context() as m:
        m.setattr(worklist, "house_rows", boom)
        r = client.post("/api/stewardship/studio/priority/preview", json={"content": _v0_with(open_triggers=25)})
    assert (r.status_code, r.json()["detail"]) == (422, "Weights must add up to 100 (now 95)")
    calls = []
    real = worklist.component_ids
    monkeypatch.setattr(worklist, "component_ids", lambda: calls.append(1) or real())
    rows = [{"issuer_id": f"C{i}", "company": f"C{i}", "normalised": {}} for i in range(5)]
    worklist.preview(_v0_with(), _v0_with(), rows)
    assert len(calls) == 1
    worklist.build(get_settings().stewardship_streams_dir, _sample(), [])
    assert len(calls) == 2
