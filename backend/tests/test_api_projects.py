from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api import deps
from arp.api.deps import get_portfolio_store, get_project_store, get_superset_client
from arp.api.routers import projects as projects_router
from arp.bi.plan import ChartPlan
from arp.bi.superset_client import SupersetError
from arp.config import Settings
from arp.projects import store as store_mod
from arp.projects.dashboards import slugify_dashboard
from arp.projects.store import ProjectStore
from arp.storage.portfolio_store import PortfolioStore
from tests.test_bi_service import PLAN, FakeClient, _spec
from tests.test_constituent_import import ROWS, _xlsx

SECRET_BODY = '{"message": "boom", "password": "hunter2"}'
XLSX = b"PK-not-really-parsed-on-upload"


class DownClient(FakeClient):
    def find_dashboard(self, slug):
        self.calls.append(("find_dashboard", slug))
        raise SupersetError(500, SECRET_BODY)


def _env(tmp_path, monkeypatch, client=None, backend="postgres"):
    monkeypatch.setattr(
        deps, "get_settings", lambda: Settings(portfolio_backend=backend, postgres_dsn="postgresql://x")
    )
    store, pf, client = ProjectStore(tmp_path / "projects"), PortfolioStore(tmp_path / "pf"), client or FakeClient()
    app = FastAPI()
    app.include_router(projects_router.router)
    app.dependency_overrides[get_project_store] = lambda: store
    app.dependency_overrides[get_portfolio_store] = lambda: pf
    app.dependency_overrides[get_superset_client] = lambda: client
    return TestClient(app), store, pf, client


@pytest.fixture
def env(tmp_path, monkeypatch):
    return _env(tmp_path, monkeypatch)


def _upload(http, pid="alpha", name="Constituent_X.xlsx", content=XLSX, notional="100"):
    return http.post(f"/api/projects/{pid}/data", files={"file": (name, content)}, data={"notional_eur": notional})


def test_create_list_get(env):
    http, *_ = env
    r = http.post("/api/projects", json={"name": "My Fund", "description": "d"})
    assert r.status_code == 201 and r.json()["id"] == "my-fund"
    assert http.get("/api/projects").json()[0] | {"created_at": ""} == {
        "id": "my-fund", "name": "My Fund", "description": "d", "created_at": "", "data_files": 0, "dashboards": 0,
    }  # fmt: skip
    assert http.get("/api/projects/my-fund").json()["name"] == "My Fund"
    assert http.get("/api/projects/nope").status_code == 404
    assert http.post("/api/projects", json={"id": "my-fund", "name": "x"}).status_code == 422  # duplicate


@pytest.mark.parametrize("bad", ["Upper", "..", "a" * 64, "-x", "a_b"])
def test_bad_ids_422(env, bad):
    http, store, *_ = env
    assert http.post("/api/projects", json={"id": bad, "name": "x"}).status_code == 422
    assert not store.root.exists() or list(store.root.iterdir()) == []


def test_upload_ok(env):
    http, store, *_ = env
    http.post("/api/projects", json={"id": "alpha", "name": "A"})
    r = _upload(http)
    assert r.status_code == 200
    assert r.json()["data"][0]["files"] == ["Constituent_X.xlsx"]
    assert r.json()["data"][0]["params"] == {"notional_eur": 100.0}
    assert store.file_path("alpha", "data", "Constituent_X.xlsx").read_bytes() == XLSX
    assert http.get("/api/projects").json()[0]["data_files"] == 1


def test_upload_rejects_xlsm_and_traversal_and_leaves_no_file(env):
    http, store, *_ = env
    http.post("/api/projects", json={"id": "alpha", "name": "A"})
    assert _upload(http, name="x.xlsm").status_code == 422
    assert _upload(http, name="../x.xlsx").status_code == 422
    assert not (store.root / "alpha" / "data").exists()
    assert not (store.root / "x.xlsx").exists()


def test_upload_oversize_422(env, monkeypatch):
    http, store, *_ = env
    http.post("/api/projects", json={"id": "alpha", "name": "A"})
    monkeypatch.setattr(store_mod, "MAX_UPLOAD_BYTES", 10)
    assert _upload(http, content=b"x" * 11).status_code == 422
    assert _upload(http, content=b"x" * 10).status_code == 200


@pytest.mark.parametrize("n", ["", "abc", "0", "-5", "nan", "inf"])
def test_upload_notional_must_be_positive_finite(env, n):
    http, *_ = env
    http.post("/api/projects", json={"id": "alpha", "name": "A"})
    assert _upload(http, notional=n).status_code == 422


def test_upload_unknown_project_404(env):
    assert _upload(env[0], pid="nope").status_code == 404


def _seed(http, store, tmp_path):
    http.post("/api/projects", json={"id": "alpha", "name": "A"})
    _upload(http, name="Constituent_IE00TESTFUND.xlsx", content=_xlsx(tmp_path, ROWS).read_bytes())
    for t in ("One", "Two"):
        r = http.post("/api/projects/alpha/dashboards", json={"title": t, "plan": PLAN.model_dump()})
        assert r.status_code == 200, r.text


def test_save_dashboard_stores_template_and_provisions_with_project_filter(env, tmp_path):
    http, store, pf, client = env
    http.post("/api/projects", json={"id": "alpha", "name": "A"})
    r = http.post("/api/projects/alpha/dashboards", json={"title": "My Dash", "plan": PLAN.model_dump()})
    slug = slugify_dashboard("alpha", "My Dash")
    assert r.status_code == 200
    assert r.json() == {"id": client.dashboards[slug]["id"], "slug": slug, "title": "My Dash", "published": False, "status": "created"}
    p = store.get("alpha")
    assert [(d.slug, d.source) for d in p.dashboards] == [(slug, "template")]
    stored = store.file_path("alpha", "dashboards", p.dashboards[0].file).read_text()
    assert '"project_id":"alpha"' in stored.replace(" ", "")
    assert [c for c in client.calls if c[0] == "create_chart"]


def test_save_dashboard_rejected_plan_422_with_problems(env):
    http, store, pf, client = env
    http.post("/api/projects", json={"id": "alpha", "name": "A"})
    bad = ChartPlan(title="Bad", charts=[_spec("A", metrics=["No such metric"])]).model_dump()
    r = http.post("/api/projects/alpha/dashboards", json={"title": "Bad", "plan": bad})
    assert r.status_code == 422 and isinstance(r.json()["detail"], list) and r.json()["detail"]
    assert store.get("alpha").dashboards == [] and client.writes() == []


def test_save_dashboard_unknown_project_404_no_writes(env):
    http, _, _, client = env
    r = http.post("/api/projects/nope/dashboards", json={"title": "T", "plan": PLAN.model_dump()})
    assert r.status_code == 404 and client.calls == []


def test_open_returns_dashboards_then_all_unchanged(env, tmp_path):
    http, store, pf, client = env
    _seed(http, store, tmp_path)
    first = http.post("/api/projects/alpha/open")
    assert first.status_code == 200, first.text
    assert [p.portfolio_id for p in pf.list_portfolios()] == ["alpha-dws-ie00testfund"]
    assert len(first.json()["dashboards"]) == 2
    second = http.post("/api/projects/alpha/open").json()
    assert [d["status"] for d in second["dashboards"]] == ["unchanged", "unchanged"]


def test_open_unknown_project_404(env):
    assert env[0].post("/api/projects/nope/open").status_code == 404


def test_open_file_backend_is_503_and_writes_nothing(tmp_path, monkeypatch):
    http, store, pf, client = _env(tmp_path, monkeypatch, backend="file")
    http.post("/api/projects", json={"id": "alpha", "name": "A"})
    _upload(http, name="Constituent_IE00TESTFUND.xlsx", content=_xlsx(tmp_path, ROWS).read_bytes())
    assert http.post("/api/projects/alpha/open").status_code == 503
    r = http.post("/api/projects/alpha/dashboards", json={"title": "T", "plan": PLAN.model_dump()})
    assert r.status_code == 503
    assert pf.list_portfolios() == [] and client.calls == [] and store.get("alpha").dashboards == []


def test_open_502_names_step_without_superset_body(tmp_path, monkeypatch):
    http, store, pf, client = _env(tmp_path, monkeypatch)
    _seed(http, store, tmp_path)
    down = DownClient()
    http.app.dependency_overrides[get_superset_client] = lambda: down
    r = http.post("/api/projects/alpha/open")
    assert r.status_code == 502 and "Opening the project failed at dashboard:" in r.json()["detail"]
    assert "hunter2" not in r.text and "boom" not in r.text


def test_save_dashboard_502_without_superset_body(tmp_path, monkeypatch):
    http, *_ = _env(tmp_path, monkeypatch, client=DownClient())
    http.post("/api/projects", json={"id": "alpha", "name": "A"})
    r = http.post("/api/projects/alpha/dashboards", json={"title": "T", "plan": PLAN.model_dump()})
    assert r.status_code == 502 and "hunter2" not in r.text and "boom" not in r.text
