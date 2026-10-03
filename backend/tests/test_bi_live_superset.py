"""Contract test against a live Superset (the pinned apache/superset:5.0.0).
It checks every endpoint and payload SupersetClient relies on, and that the
recorded chart params in fixtures/bi/<viz_type>.json (one per allowlisted
viz_type, all on the `holdings` dataset) are accepted and return rows.

Skipped unless ARP_TEST_SUPERSET_URL is set. Prerequisites, as for a real
deployment: Superset up (`docker compose up -d postgres superset`), and
ARP_POSTGRES_DSN pointing at a database that had `arp db init-postgres`
and `arp portfolio seed-demo` (with ARP_PORTFOLIO_BACKEND=postgres), plus
ARP_SUPERSET_PASSWORD and ARP_BI_READER_PASSWORD. Set
ARP_BI_SUPERSET_DB_HOST if Superset reaches that Postgres somewhere other
than postgres:5432. Everything the test creates in Superset is deleted."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import uuid
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from arp.bi.catalog import VIEW_DATASETS, VIZ_ALLOWLIST
from arp.bi.compiler import compile_chart, compile_dashboard, compile_native_filters
from arp.bi.plan import ChartPlan, ChartSpec, NativeFilter
from arp.bi.planner import PlannerRefusal
from arp.bi.service import SCRATCH_SLUG, NotAnARPDashboard, ask_chart, design_dashboard, embed_token
from arp.bi.superset_client import SupersetClient, SupersetError
from arp.bi.templates import load_templates
from arp.cli import app
from arp.config import get_settings
from arp.llm.base import LLMClient, LLMUsage

URL = os.environ.get("ARP_TEST_SUPERSET_URL")
pytestmark = [pytest.mark.live_superset, pytest.mark.skipif(not URL, reason="ARP_TEST_SUPERSET_URL not set -- live Superset")]

FIXTURES = Path(__file__).parent / "fixtures" / "bi"


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("ARP_SUPERSET_URL", URL)
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


TEMPLATE_SLUGS = [t.slug for t in load_templates()]


def _drop_dashboard(client: SupersetClient, slug: str) -> None:
    """Deletes the dashboard under `slug` and its charts, if present."""
    dash_id = client.find_dashboard(slug)
    if dash_id is not None:
        charts = client.dashboard_charts(dash_id)
        client.delete_dashboard(dash_id)
        for cid in charts:
            client.delete_chart(cid)


@pytest.fixture(autouse=True)
def drop_templates(settings):
    """Every bootstrap provisions the template dashboards; none may outlive a test."""
    yield
    client = SupersetClient(URL, settings.superset_user, settings.superset_password)
    for slug in TEMPLATE_SLUGS:
        with contextlib.suppress(SupersetError, httpx.HTTPError):  # one failure must not leak the rest
            _drop_dashboard(client, slug)


def _bootstrap() -> dict:
    result = CliRunner().invoke(app, ["bi", "bootstrap"])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def _position(chart_ids: list[int]) -> dict:
    pos = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": [], "parents": ["ROOT_ID"]},
    }
    for i in range(0, len(chart_ids), 3):
        row = f"ROW-{i}"
        pos["GRID_ID"]["children"].append(row)
        pos[row] = {
            "type": "ROW",
            "id": row,
            "children": [],
            "parents": ["ROOT_ID", "GRID_ID"],
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
        }
        for cid in chart_ids[i : i + 3]:
            key = f"CHART-{cid}"
            pos[row]["children"].append(key)
            pos[key] = {
                "type": "CHART",
                "id": key,
                "children": [],
                "parents": ["ROOT_ID", "GRID_ID", row],
                "meta": {"chartId": cid, "width": 4, "height": 50},
            }
    return pos


def test_live_superset_roundtrip(settings):
    out = _bootstrap()
    assert set(out["datasets"]) == set(VIEW_DATASETS) and out["reader_role"] == "bi_reader"
    again = _bootstrap()
    assert again == {**out, "templates": dict.fromkeys(TEMPLATE_SLUGS, "unchanged")}  # idempotent

    client = SupersetClient(URL, settings.superset_user, settings.superset_password)
    holdings = out["datasets"]["holdings"]
    meta = client.dataset_meta(holdings)
    assert meta.metrics == {m.name for m in VIEW_DATASETS["holdings"].metrics}
    assert meta.columns == set(VIEW_DATASETS["holdings"].columns)
    raw = client._dataset(holdings)
    assert raw["description"] == VIEW_DATASETS["holdings"].description
    col, text = next(iter(VIEW_DATASETS["holdings"].columns.items()))
    assert {c["column_name"]: c["description"] for c in raw["columns"]}[col] == text

    slug = f"arp-live-test-{uuid.uuid4().hex[:8]}"
    chart_ids: list[int] = []
    dash_id = None
    try:
        for viz in VIZ_ALLOWLIST:
            params = json.loads((FIXTURES / f"{viz}.json").read_text())
            chart_ids.append(client.create_chart(f"{slug} {viz}", holdings, viz, params))
            # The saved query_context runs against the seeded demo holdings.
            (data,) = client._request("GET", f"/chart/{chart_ids[-1]}/data/")["result"]
            assert data["status"] == "success" and data["rowcount"] > 0, (viz, data)

        dash_id = client.create_dashboard(slug, slug, _position(chart_ids), chart_ids)
        dash = client._request("GET", f"/dashboard/{dash_id}")["result"]
        assert dash["published"] is False
        assert client.find_dashboard(slug) == dash_id
        charts = client._request("GET", f"/dashboard/{dash_id}/charts")["result"]
        assert {c["id"]: c["form_data"]["viz_type"] for c in charts} == dict(zip(chart_ids, VIZ_ALLOWLIST, strict=True))

        embedded = client.ensure_embedded(dash_id)
        assert client.ensure_embedded(dash_id) == embedded
        token = client.guest_token(embedded, [])
        # The guest role (superset_config.GUEST_ROLE_NAME) can query the dashboard's charts.
        resp = httpx.post(
            f"{URL}/api/v1/chart/data",
            headers={"X-GuestToken": token},
            json={
                "datasource": {"id": holdings, "type": "table"},
                "form_data": {"slice_id": chart_ids[0], "dashboardId": dash_id},
                "queries": [{"columns": ["sector"], "metrics": ["Exposure (EUR)"], "row_limit": 5}],
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["result"][0]["rowcount"] > 0
    finally:
        if dash_id is not None:
            client.delete_dashboard(dash_id)
        for cid in chart_ids:
            client.delete_chart(cid)
    assert client.find_dashboard(slug) is None


def test_native_filters_are_stored_and_applied(settings):
    """One filter on holdings.portfolio_name scopes a holdings chart and a
    holdings_history chart (task-4 spike: the dashboard sends the filter value
    as `filters` in each in-scope chart's query, matched by column name)."""
    ds = _bootstrap()["datasets"]
    client = SupersetClient(URL, settings.superset_user, settings.superset_password)
    slug = f"arp-live-test-{uuid.uuid4().hex[:8]}"
    specs = [
        _h(f"{slug} holdings", "table", ["portfolio_name"]),
        ChartSpec(
            title=f"{slug} history", viz_type="table", dataset="holdings_history",
            metrics=["Exposure (EUR)"], groupby=["portfolio_name", "as_of_date"],
        ),
    ]  # fmt: skip
    meta = compile_native_filters([NativeFilter(name="Portfolio", dataset="holdings", column="portfolio_name")], ds, [])
    chart_ids: list[int] = []
    dash_id = None
    try:
        for s in specs:
            chart_ids.append(client.create_chart(s.title, ds[s.dataset], s.viz_type, compile_chart(s, ds[s.dataset])))
        dash_id = client.create_dashboard(slug, slug, compile_dashboard(chart_ids, [s.title for s in specs]), chart_ids, meta)
        dash = client.get_dashboard(dash_id)
        assert dash["published"] is False
        assert json.loads(dash["json_metadata"])["native_filter_configuration"] == meta["native_filter_configuration"]

        def portfolios(cid: int, dataset: str, filters: list[dict]) -> set[str]:
            body = {
                "datasource": {"id": ds[dataset], "type": "table"},
                "form_data": {"slice_id": cid, "dashboardId": dash_id},
                "queries": [{"columns": ["portfolio_name"], "metrics": ["Exposure (EUR)"], "filters": filters}],
            }
            (res,) = client._request("POST", "/chart/data", json=body)["result"]
            return {r["portfolio_name"] for r in res["data"]}

        # Proves column-name matching on the data API only; the dashboard-driven
        # behaviour (filter sent to both charts) was shown in the browser spike, see task-4-report.md.
        (nf,) = meta["native_filter_configuration"]
        value = sorted(portfolios(chart_ids[0], "holdings", []))[0]
        applied = [{"col": nf["targets"][0]["column"]["name"], "op": "IN", "val": [value]}]
        for cid, s in zip(chart_ids, specs, strict=True):
            assert len(portfolios(cid, s.dataset, [])) > 1
            assert portfolios(cid, s.dataset, applied) == {value}

        more = compile_native_filters(
            [NativeFilter(name="Portfolio", dataset="holdings", column="portfolio_name"),
             NativeFilter(name="Sector", dataset="holdings", column="sector")], ds, chart_ids,
        )  # fmt: skip
        client.update_dashboard(dash_id, compile_dashboard(chart_ids, [s.title for s in specs]), chart_ids, more)
        stored = json.loads(client.get_dashboard(dash_id)["json_metadata"])["native_filter_configuration"]
        assert [f["id"] for f in stored] == [f["id"] for f in more["native_filter_configuration"]]
    finally:
        if dash_id is not None:
            client.delete_dashboard(dash_id)
        for cid in chart_ids:
            client.delete_chart(cid)
    assert client.find_dashboard(slug) is None


def test_bootstrap_provisions_risk_exposure(settings):
    """The standard template: created unpublished with its native filters, every
    chart returns rows from the seeded data, and a re-run leaves it alone."""
    (template,) = [t for t in load_templates() if t.slug == "arp-risk-exposure"]
    client = SupersetClient(URL, settings.superset_user, settings.superset_password)
    _drop_dashboard(client, template.slug)  # start from absent; the fixture cleans up after
    out = _bootstrap()
    assert out["templates"]["arp-risk-exposure"] == "created"
    dash_id = client.find_dashboard(template.slug)
    _check_dashboard(client, dash_id, ChartPlan(title=template.title, charts=template.charts))
    stored = json.loads(client.get_dashboard(dash_id)["json_metadata"])["native_filter_configuration"]
    assert [(f["name"], f["targets"][0]["column"]["name"]) for f in stored] == [
        (f.name, f.column) for f in template.native_filters
    ]
    assert all(
        f["targets"][0]["datasetId"] == out["datasets"][nf.dataset] for f, nf in zip(stored, template.native_filters, strict=True)
    )
    assert _bootstrap()["templates"]["arp-risk-exposure"] == "unchanged"
    assert client.find_dashboard(template.slug) == dash_id


# --- Service end to end (design_dashboard / ask_chart / embed_token) -------------------


class ScriptedLLM(LLMClient):
    """Returns canned planner outputs, so the live test exercises everything after the LLM."""

    def __init__(self, *plans: ChartPlan) -> None:
        self.plans = list(plans)

    async def complete_structured(self, *, system, prompt, output_model, **kw):
        return PlannerRefusal(plan=self.plans.pop(0)), LLMUsage()


def _h(title: str, viz: str, groupby: list[str], metrics=("Exposure (EUR)",), **kw) -> ChartSpec:
    return ChartSpec(title=title, viz_type=viz, dataset="holdings", metrics=list(metrics), groupby=groupby, **kw)


def _check_dashboard(client: SupersetClient, dash_id: int, plan: ChartPlan) -> dict[int, str]:
    """Charts attached, laid out by compile_dashboard's position_json, unpublished, each returning rows."""
    charts = client.dashboard_charts(dash_id)
    assert sorted(charts.values()) == sorted(c.title for c in plan.charts)
    dash = client._request("GET", f"/dashboard/{dash_id}")["result"]
    assert dash["published"] is False
    layout = json.loads(dash["position_json"])
    assert {v["meta"]["chartId"] for v in layout.values() if isinstance(v, dict) and v.get("type") == "CHART"} == set(charts)
    for cid in charts:
        (data,) = client._request("GET", f"/chart/{cid}/data/")["result"]
        assert data["status"] == "success" and data["rowcount"] > 0, (charts[cid], data)
    return charts


def test_live_service_design_covers_every_viz_type(settings):
    _bootstrap()
    client = SupersetClient(URL, settings.superset_user, settings.superset_password)
    tag = uuid.uuid4().hex[:8]  # fresh plan hashes, so no earlier dashboard is reused
    plans = [
        ChartPlan(
            title=f"Live test {tag} overview",
            charts=[
                _h("Total exposure", "big_number_total", []),
                _h("Exposure by sector", "echarts_timeseries_bar", ["sector"]),
                _h("Exposure over time", "echarts_timeseries_line", ["as_of_date", "portfolio_name"]),
                _h("Sector mix", "pie", ["sector"]),
                _h(
                    "EUR equity positions",
                    "table",
                    ["portfolio_name", "security_name"],
                    ["Holdings", "Exposure (EUR)"],
                    filters={"asset_class": "equity", "currency": "EUR"},
                ),
                _h("Portfolio x sector", "pivot_table_v2", ["portfolio_name", "sector"]),
            ],
        ),
        ChartPlan(
            title=f"Live test {tag} concentration",
            charts=[
                _h("Sector heatmap", "heatmap_v2", ["portfolio_name", "sector"]),
                _h("Exposure treemap", "treemap_v2", ["sector", "company_name"]),
            ],
        ),
    ]
    assert {c.viz_type for p in plans for c in p.charts} == set(VIZ_ALLOWLIST)
    dash_ids: list[int] = []  # recorded before any check, so a failing assertion still cleans up
    slugs: list[str] = []
    try:
        for plan in plans:
            res = asyncio.run(design_dashboard("brief", ScriptedLLM(plan), client))
            dash_ids.append(res.dashboard_id)
            slugs.append(res.slug)
            assert res.rejected == [] and res.slug.startswith("arp-") and res.url.endswith(f"/superset/dashboard/{res.slug}/")
            charts = _check_dashboard(client, res.dashboard_id, plan)

            again = asyncio.run(design_dashboard("brief", ScriptedLLM(plan), client))
            if again.dashboard_id not in dash_ids:
                dash_ids.append(again.dashboard_id)
            assert again.dashboard_id == res.dashboard_id  # same plan hash: reused
            assert client.dashboard_charts(res.dashboard_id) == charts  # and nothing new created

        embedded_id, token = embed_token(client, str(dash_ids[0]))
        assert isinstance(token, str) and token and embedded_id

        # A person's own dashboard (no arp- slug) is refused and not made embeddable.
        human = client._request("POST", "/dashboard/", json={"dashboard_title": f"Human {tag}", "slug": f"human-{tag}"})["id"]
        try:
            with pytest.raises(NotAnARPDashboard):
                embed_token(client, str(human))
            with pytest.raises(SupersetError) as e:
                client._request("GET", f"/dashboard/{human}/embedded")
            assert e.value.status_code == 404
        finally:
            client.delete_dashboard(human)
    finally:
        for dash_id in dash_ids:
            with contextlib.suppress(SupersetError):  # one already gone must not leak the rest
                charts = client.dashboard_charts(dash_id)
                client.delete_dashboard(dash_id)
                for cid in charts:
                    client.delete_chart(cid)
    for slug in slugs:
        assert client.find_dashboard(slug) is None


def test_live_service_ask_accumulates_on_scratch(settings):
    _bootstrap()
    client = SupersetClient(URL, settings.superset_user, settings.superset_password)
    if client.find_dashboard(SCRATCH_SLUG) is not None:
        pytest.skip("this Superset already has a scratch dashboard; the test would add to it")
    q1 = ChartPlan(title="Q", charts=[_h("Exposure by country", "pie", ["country"])])
    q2 = ChartPlan(title="Q", charts=[_h("Positions by asset class", "echarts_timeseries_bar", ["asset_class"], ["Holdings"])])
    llm = ScriptedLLM(q1, q2)
    dash_id = None
    try:
        r1 = asyncio.run(ask_chart("exposure by country?", llm, client))
        dash_id = r1.dashboard_id
        r2 = asyncio.run(ask_chart("positions by asset class?", llm, client))
        assert r1.slug == r2.slug == SCRATCH_SLUG and r2.dashboard_id == dash_id
        _check_dashboard(client, dash_id, ChartPlan(title="Scratch", charts=q1.charts + q2.charts))
    finally:
        if dash_id is not None:
            charts = client.dashboard_charts(dash_id)
            client.delete_dashboard(dash_id)
            for cid in charts:
                client.delete_chart(cid)
    assert client.find_dashboard(SCRATCH_SLUG) is None


def test_live_list_dashboards_only_arp_slugs(settings):
    client = SupersetClient(URL, settings.superset_user, settings.superset_password)
    tag = uuid.uuid4().hex[:8]
    mine, other = f"arp-manual-{tag}", f"human-{tag}"
    ids: list[int] = []
    try:
        for slug, title in ((mine, "manual test"), (other, "not ours")):
            body = {"dashboard_title": title, "slug": slug, "published": False}
            ids.append(client._request("POST", "/dashboard/", json=body)["id"])
        listed = {d["slug"]: d for d in client.list_dashboards()}
        assert listed[mine]["published"] is False and listed[mine]["title"] == "manual test"
        assert other not in listed and all(s.startswith("arp-") for s in listed)
    finally:
        for dash_id in ids:
            with contextlib.suppress(SupersetError, httpx.HTTPError):
                client.delete_dashboard(dash_id)
