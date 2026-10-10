"""Projects end to end against a live Superset and the real Postgres portfolio store.

Skipped unless ARP_TEST_SUPERSET_URL is set; needs ARP_TEST_SUPERSET_DESTRUCTIVE=1 (the
helpers delete dashboards by slug) and the stack of test_bi_live_superset.py
(ARP_POSTGRES_DSN, ARP_PORTFOLIO_BACKEND=postgres, ARP_BI_READER_PASSWORD, ...).
It runs `arp bi bootstrap` first so the views carry project_id. Everything it creates
(project dashboards and charts, holdings, portfolios, securities, companies) is deleted.
Point it only at a throwaway stack."""

from __future__ import annotations

import contextlib
import json
import os
import uuid

import httpx
import pytest
from sqlalchemy import create_engine, text
from typer.testing import CliRunner

from arp.bi.compiler import compile_chart
from arp.bi.plan import ChartPlan, ChartSpec
from arp.bi.superset_client import SupersetClient, SupersetError
from arp.cli import app
from arp.config import get_settings
from arp.projects.dashboards import plan_to_template
from arp.projects.service import export_dashboard_to_project, open_project
from arp.projects.store import ProjectStore
from arp.storage.portfolio_store_factory import build_portfolio_store
from tests.test_constituent_import import _xlsx

URL = os.environ.get("ARP_TEST_SUPERSET_URL")
pytestmark = [
    pytest.mark.live_superset,
    pytest.mark.skipif(not URL, reason="ARP_TEST_SUPERSET_URL not set -- live Superset"),
    pytest.mark.skipif(
        os.environ.get("ARP_TEST_SUPERSET_DESTRUCTIVE") != "1",
        reason="ARP_TEST_SUPERSET_DESTRUCTIVE=1 not set -- this test deletes dashboards",
    ),
]


@pytest.fixture
def settings(monkeypatch, tmp_path):
    monkeypatch.setenv("ARP_SUPERSET_URL", URL)
    monkeypatch.setenv("ARP_PORTFOLIOS_DIR", str(tmp_path / "portfolios"))
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.fixture
def client(settings):
    return SupersetClient(URL, settings.superset_user, settings.superset_password)


@pytest.fixture
def cleanup(settings, client):
    """Collects what a test creates; deletes it afterwards, even when the test failed."""
    slugs: list[str] = []
    portfolios: list[str] = []
    isins: list[str] = []
    yield slugs, portfolios, isins
    for slug in slugs:
        with contextlib.suppress(SupersetError, httpx.HTTPError):
            dash_id = client.find_dashboard(slug)
            if dash_id is not None:
                charts = client.dashboard_charts(dash_id)
                client.delete_dashboard(dash_id)
                for cid in charts:
                    client.delete_chart(cid)
    engine = create_engine(settings.postgres_dsn)
    with engine.begin() as c:
        c.execute(text("DELETE FROM holdings WHERE portfolio_id = ANY(:p)"), {"p": portfolios})
        c.execute(text("DELETE FROM portfolios WHERE portfolio_id = ANY(:p)"), {"p": portfolios})
        c.execute(text("DELETE FROM securities WHERE security_id = ANY(:i)"), {"i": isins})
        c.execute(text("DELETE FROM legacy_companies WHERE company_id = ANY(:i)"), {"i": [f"isin_{i}" for i in isins]})
    engine.dispose()


def _rows(tag: str, w1: float, w2: float) -> list[tuple]:
    return [
        (f"A {tag}", f"XS{tag}A".upper(), "Deutschland", "EUR", "Aktien", "Finanzen", w1),
        (f"B {tag}", f"XS{tag}B".upper(), "Frankreich", "EUR", "Aktien", "Informationstechnologie", w2),
    ]


def _chart_total(client: SupersetClient, chart_id: int) -> tuple[float, set[str]]:
    (data,) = client._request("GET", f"/chart/{chart_id}/data/")["result"]
    assert data["status"] == "success", data
    return sum(r["Exposure (EUR)"] for r in data["data"]), {r["portfolio_name"] for r in data["data"]}


def _make_project(store, tmp_path, cleanup, pid, tag, notional, w1, w2):
    slugs, portfolios, isins = cleanup
    fund = f"IE00{tag}".upper()
    sec = [r[1] for r in _rows(tag, w1, w2)]
    isins.extend(sec)
    portfolios.append(f"{pid}-dws-{fund.lower()}")
    (tmp_path / pid).mkdir()
    path = _xlsx(tmp_path / pid, _rows(tag, w1, w2), isin=fund)
    store.create(pid, pid)
    store.add_data_file(pid, path.name, path.read_bytes(), {"notional_eur": notional})
    plan = ChartPlan(
        title="Live",
        charts=[ChartSpec(title=f"{pid} by fund", viz_type="table", dataset="holdings",
                          metrics=["Exposure (EUR)"], groupby=["portfolio_name"])],
    )  # fmt: skip
    t = plan_to_template(pid, f"Live {pid}", plan)
    store.save_dashboard(pid, t.slug, t.title, "template", t.model_dump_json().encode())
    slugs.append(t.slug)
    return t.slug, f"DWS ETF {fund}"


def test_projects_end_to_end(settings, client, cleanup, tmp_path):
    assert settings.portfolio_backend == "postgres", "needs ARP_PORTFOLIO_BACKEND=postgres"
    result = CliRunner().invoke(app, ["bi", "bootstrap"])  # views gain project_id
    assert result.exit_code == 0, result.output

    tag = uuid.uuid4().hex[:8]
    ta, tb = uuid.uuid4().hex[:8], uuid.uuid4().hex[:8]  # unique fund and security ids
    store = ProjectStore(tmp_path / "projects")
    pstore = build_portfolio_store(settings)
    slug_a, fund_a = _make_project(store, tmp_path, cleanup, f"lta{tag}", ta, 1_000_000, 0.6, 0.3)
    slug_b, fund_b = _make_project(store, tmp_path, cleanup, f"ltb{tag}", tb, 2_000_000, 0.25, 0.25)
    expected = {slug_a: (900_000.0, fund_a), slug_b: (1_000_000.0, fund_b)}

    for pid, slug in ((f"lta{tag}", slug_a), (f"ltb{tag}", slug_b)):
        first = open_project(store, pstore, client, pid)
        assert [d.status for d in first.dashboards] == ["created"]
        assert all(not d.published for d in first.dashboards)
        second = open_project(store, pstore, client, pid)
        assert [d.status for d in second.dashboards] == ["unchanged"]

        total, funds = _chart_total(client, next(iter(client.dashboard_charts(client.find_dashboard(slug)))))
        assert total == pytest.approx(expected[slug][0])
        assert funds == {expected[slug][1]}  # only this project's fund

        stored = json.loads(client.get_dashboard(client.find_dashboard(slug))["json_metadata"])["native_filter_configuration"]
        assert [f["name"] for f in stored] == ["Fund", "Sector", "Country"]
        for f in stored:
            assert [(a["subject"], a["comparator"]) for a in f["adhoc_filters"]] == [("project_id", pid)]
        # The Fund filter's option query, as the dashboard sends it, lists only this project's fund.
        fund_filter = stored[0]
        body = {
            "datasource": {"id": fund_filter["targets"][0]["datasetId"], "type": "table"},
            "queries": [{
                "columns": ["portfolio_name"], "metrics": [],
                "filters": [{"col": a["subject"], "op": "==", "val": a["comparator"]} for a in fund_filter["adhoc_filters"]],
            }],
        }  # fmt: skip
        (res,) = client._request("POST", "/chart/data", json=body)["result"]
        assert {r["portfolio_name"] for r in res["data"]} == {expected[slug][1]}

    assert expected[slug_a][0] != expected[slug_b][0]


def test_hand_built_dashboard_roundtrips_through_project(settings, client, cleanup, tmp_path):
    result = CliRunner().invoke(app, ["bi", "bootstrap"])
    assert result.exit_code == 0, result.output
    ds = json.loads(result.output)["datasets"]
    tag = uuid.uuid4().hex[:8]
    pid, slug = f"lth{tag}", f"arp-live-hand-{tag}"
    cleanup[0].append(slug)
    store = ProjectStore(tmp_path / "projects")
    store.create(pid, pid)
    spec = ChartSpec(title=f"{slug} chart", viz_type="table", dataset="holdings", metrics=["Exposure (EUR)"], groupby=["sector"])
    cid = client.create_chart(spec.title, ds["holdings"], spec.viz_type, compile_chart(spec, ds["holdings"]))
    dash_id = client.create_dashboard(slug, slug, _layout(cid), [cid])

    stored = export_dashboard_to_project(store, client, pid, dash_id)
    assert stored.slug == slug and stored.source == "superset-export"
    client.delete_dashboard(dash_id)  # the chart stays, as in the export spike
    assert client.find_dashboard(slug) is None

    first = open_project(store, build_portfolio_store(settings), client, pid)
    (d,) = first.dashboards
    assert (d.status, d.published) == ("created", False)
    again = open_project(store, build_portfolio_store(settings), client, pid)
    assert [x.status for x in again.dashboards] == ["unchanged"]


def _layout(cid: int) -> dict:
    return {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": ["ROW-0"], "parents": ["ROOT_ID"]},
        "ROW-0": {"type": "ROW", "id": "ROW-0", "children": [f"CHART-{cid}"], "parents": ["ROOT_ID", "GRID_ID"],
                  "meta": {"background": "BACKGROUND_TRANSPARENT"}},
        f"CHART-{cid}": {"type": "CHART", "id": f"CHART-{cid}", "children": [], "parents": ["ROOT_ID", "GRID_ID", "ROW-0"],
                         "meta": {"chartId": cid, "width": 4, "height": 50}},
    }  # fmt: skip
