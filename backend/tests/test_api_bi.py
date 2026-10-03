from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api import deps
from arp.api.deps import get_llm_client, get_superset_client
from arp.api.routers import bi as bi_router
from arp.bi.planner import PlannerRefusal
from arp.bi.superset_client import SupersetError
from arp.config import Settings
from tests.test_bi_service import PLAN, FakeClient, FakeLLM

SECRET_BODY = '{"message": "boom", "password": "hunter2"}'


class DownClient(FakeClient):
    """Every Superset call fails, like an unreachable or erroring instance."""

    def find_database(self, name):
        self.calls.append(("find_database", name))
        raise SupersetError(500, SECRET_BODY)

    def ensure_embedded(self, dashboard_id):
        self.calls.append(("ensure_embedded", dashboard_id))
        raise SupersetError(500, SECRET_BODY)


def _app(llm, superset) -> TestClient:
    app = FastAPI()
    app.include_router(bi_router.router)
    app.dependency_overrides[get_llm_client] = lambda: llm
    app.dependency_overrides[get_superset_client] = lambda: superset
    return TestClient(app)


def test_design_returns_result():
    fake = FakeClient()
    r = _app(FakeLLM(PlannerRefusal(plan=PLAN)), fake).post("/api/bi/design", json={"brief": "exposure overview"})
    assert r.status_code == 200
    body = r.json()
    assert body["dashboard_id"] and body["slug"].startswith("arp-") and len(body["plan"]["charts"]) == 3


def test_ask_returns_result():
    r = _app(FakeLLM(PlannerRefusal(plan=PLAN)), FakeClient()).post("/api/bi/ask", json={"question": "exposure by sector?"})
    assert r.status_code == 200 and len(r.json()["plan"]["charts"]) == 1


def test_rejected_plan_is_200_with_reasons():
    fake = FakeClient()
    r = _app(FakeLLM(PlannerRefusal(clarification_needed="No weather data.")), fake).post(
        "/api/bi/design", json={"brief": "weather?"}
    )
    assert r.status_code == 200
    assert r.json()["rejected"] == ["No weather data."] and r.json()["dashboard_id"] is None
    assert fake.writes() == []


def test_superset_down_returns_502_with_message_and_creates_nothing():
    down = DownClient()
    r = _app(FakeLLM(PlannerRefusal(plan=PLAN)), down).post("/api/bi/design", json={"brief": "exposure"})
    assert r.status_code == 502
    detail = r.json()["detail"]
    assert "Superset" in detail
    assert "hunter2" not in r.text and "boom" not in r.text  # raw response body stays server-side
    assert down.writes() == []


def test_ask_502_does_not_leak_body():
    r = _app(FakeLLM(), DownClient()).post("/api/bi/ask", json={"question": "exposure?"})
    assert r.status_code == 502 and "hunter2" not in r.text and "boom" not in r.text


def test_chart_failure_502_names_chart_but_not_body():
    class BadChart(FakeClient):
        def create_chart(self, *a, **k):
            raise SupersetError(422, SECRET_BODY)

    r = _app(FakeLLM(PlannerRefusal(plan=PLAN)), BadChart()).post("/api/bi/design", json={"brief": "x"})
    assert r.status_code == 502 and "'A'" in r.json()["detail"] and "hunter2" not in r.text


def test_embed_token_502_does_not_leak_body():
    r = _app(FakeLLM(), DownClient()).post("/api/bi/embed-token", json={"dashboard_id": "7"})
    assert r.status_code == 502 and "hunter2" not in r.text and "boom" not in r.text


def test_502_logs_body_server_side(caplog):
    _app(FakeLLM(), DownClient()).post("/api/bi/embed-token", json={"dashboard_id": "7"})
    assert "hunter2" in caplog.text


def test_embed_token_returns_token():
    fake = FakeClient()
    r = _app(FakeLLM(), fake).post("/api/bi/embed-token", json={"dashboard_id": "7"})
    assert r.status_code == 200 and r.json() == {"token": "tok", "embedded_id": "uuid-1"}
    assert ("ensure_embedded", 7) in fake.calls


@pytest.mark.parametrize("body", [{}, {"dashboard_id": ""}, {"dashboard_id": "  "}])
def test_embed_token_requires_dashboard_id(body):
    assert _app(FakeLLM(), FakeClient()).post("/api/bi/embed-token", json=body).status_code == 422


def test_embed_token_rejects_non_numeric_id():
    assert _app(FakeLLM(), FakeClient()).post("/api/bi/embed-token", json={"dashboard_id": "abc"}).status_code == 422


@pytest.mark.parametrize("path,key", [("/api/bi/design", "brief"), ("/api/bi/ask", "question")])
@pytest.mark.parametrize("value", ["", "   ", "x" * 2001])
def test_text_must_be_non_empty_and_bounded(path, key, value):
    assert _app(FakeLLM(), FakeClient()).post(path, json={key: value}).status_code == 422


@pytest.mark.parametrize(
    "settings",
    [Settings(superset_password=None, postgres_dsn="postgresql://x"), Settings(superset_password="pw", postgres_dsn=None)],
)
def test_missing_config_returns_503(monkeypatch, settings):
    monkeypatch.setattr(deps, "get_settings", lambda: settings)
    app = FastAPI()
    app.include_router(bi_router.router)
    app.dependency_overrides[get_llm_client] = lambda: FakeLLM()
    r = TestClient(app).post("/api/bi/design", json={"brief": "x"})
    assert r.status_code == 503 and "ARP_" in r.json()["detail"]
