from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from arp.schemas.portfolio_monitoring import Alert, AlertCategory, AlertStatus
from arp.schemas.triggers import from_alert
from arp.stewardship.alerts_feed import issuer_fields
from arp.stewardship.trigger_store import TriggerStore


def _t(issuer="ACME", rule="r1"):
    return {
        "issuer_id": issuer,
        "company": "Acme",
        "sector": "Energy",
        "type": "climate",
        "theme": "climate_transition",
        "severity": "high",
        "rule": rule,
        "reason": "why",
        "engagement_id": None,
    }


@pytest.fixture
def store(tmp_path):
    return TriggerStore(tmp_path)


def test_record_run_marks_first_run_triggers_new(store):
    out = store.record_run("2026-09", [_t(), _t("BMW")])
    assert [t.is_new for t in out] == [True, True]
    assert all(t.source == "stewardship" and t.status == "open" and t.first_seen_month == "2026-09" for t in out)
    assert out[0].rule == "r1"  # the Company Profile strip opens an engagement by (issuer_id, rule)


def test_second_run_same_trigger_not_new(store):
    store.record_run("2026-09", [_t()])
    out = store.record_run("2026-10", [_t(), _t("BMW")])
    assert {t.issuer_id: t.is_new for t in out} == {"ACME": False, "BMW": True}
    assert out[0].first_seen_month == "2026-09"


def test_trigger_absent_next_month_stays_listed_until_resolved(store):
    first = store.record_run("2026-09", [_t()])[0]
    store.record_run("2026-10", [_t("BMW")])
    assert {t.issuer_id for t in store.list_triggers()} == {"ACME", "BMW"}
    store.transition(first.trigger_id, "resolved", "alice")
    assert {t.issuer_id for t in store.list_triggers("resolved")} == {"ACME"}
    assert {t.issuer_id for t in store.list_triggers("open")} == {"BMW"}


def test_transition_changes_status_and_keeps_history(store, tmp_path):
    tid = store.record_run("2026-09", [_t()])[0].trigger_id
    store.transition(tid, "acknowledged", "alice", "looking")
    assert store.transition(tid, "resolved", "bob").status == "resolved"
    lines = (tmp_path / "triggers" / "events.jsonl").read_text().splitlines()
    assert len(lines) == 3  # run + two transitions, nothing rewritten


def test_unknown_trigger_id_raises_keyerror(store):
    with pytest.raises(KeyError):
        store.transition("nope", "resolved", "alice")


def test_from_alert_maps_category_to_type_and_theme():
    breach = from_alert(Alert(category=AlertCategory.THRESHOLD_BREACH, scope_id="bmw", company_id="bmw", rationale="over"))
    news = from_alert(Alert(category=AlertCategory.NEWS_CONTROVERSY, scope_id="bmw", company_id="bmw"))
    assert (breach.type, breach.theme, breach.source, breach.severity, breach.reason) == (
        "threshold_breach",
        "climate_data",
        "risk_alert",
        "medium",
        "over",
    )
    assert (news.type, news.theme) == ("news_controversy", "controversy")


def test_issuer_fields_keeps_existing_keys_and_adds_total():
    mk = lambda c, s=AlertStatus.OPEN: Alert(category=c, scope_id="bmw", company_id="bmw", status=s)  # noqa: E731
    f = issuer_fields(
        [
            mk(AlertCategory.NEWS_CONTROVERSY),
            mk(AlertCategory.NEWS_CONTROVERSY, AlertStatus.RESOLVED),
            mk(AlertCategory.THRESHOLD_BREACH),
        ]
    )["bmw"]
    assert f == {"alert.open_news_controversy": 1, "alert.open_threshold_breach": 1, "alert.open_total": 2}


def test_trigger_routes(tmp_path, monkeypatch):
    from arp.api.deps import get_stream_store
    from arp.api.main import app
    from arp.stewardship.process import StreamStore

    app.dependency_overrides[get_stream_store] = lambda: StreamStore(tmp_path)
    try:
        tid = TriggerStore(tmp_path).record_run("2026-09", [_t()])[0].trigger_id
        c = TestClient(app)
        assert [t["trigger_id"] for t in c.get("/api/stewardship/triggers?status=open").json()["triggers"]] == [tid]
        r = c.post(f"/api/stewardship/triggers/{tid}/transition", json={"status": "resolved", "decided_by": "a"})
        assert r.status_code == 200 and r.json()["status"] == "resolved"
        assert (
            c.post("/api/stewardship/triggers/nope/transition", json={"status": "resolved", "decided_by": "a"}).status_code == 404
        )
    finally:
        app.dependency_overrides.pop(get_stream_store, None)


def test_resolved_trigger_reappearing_next_month_reopens(store):
    tid = store.record_run("2026-09", [_t()])[0].trigger_id
    store.transition(tid, "resolved", "alice")
    store.record_run("2026-10", [_t("BMW")])
    assert store.list_triggers("resolved")[0].trigger_id == tid
    out = store.record_run("2026-11", [_t()])
    assert out[0].status == "open" and out[0].is_new is True


def test_resolved_trigger_still_present_stays_resolved(store):
    tid = store.record_run("2026-09", [_t()])[0].trigger_id
    store.transition(tid, "resolved", "alice")
    assert store.record_run("2026-10", [_t()])[0].status == "resolved"


def test_record_run_rejects_trigger_without_issuer_or_rule_before_writing(store, tmp_path):
    for bad in ({"type": "x"}, {"issuer_id": "A"}, {"rule": "r"}):
        with pytest.raises(ValueError):
            store.record_run("2026-09", [_t(), bad])
    assert not (tmp_path / "triggers" / "events.jsonl").exists()


def test_triggers_route_rejects_bogus_status(tmp_path):
    from arp.api.deps import get_stream_store
    from arp.api.main import app
    from arp.stewardship.process import StreamStore

    app.dependency_overrides[get_stream_store] = lambda: StreamStore(tmp_path)
    try:
        assert TestClient(app).get("/api/stewardship/triggers?status=bogus").status_code == 422
    finally:
        app.dependency_overrides.pop(get_stream_store, None)
