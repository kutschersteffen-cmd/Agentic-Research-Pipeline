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

import json
import os
import uuid
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from arp.bi.catalog import VIEW_DATASETS, VIZ_ALLOWLIST
from arp.bi.superset_client import SupersetClient
from arp.cli import app
from arp.config import get_settings

URL = os.environ.get("ARP_TEST_SUPERSET_URL")
pytestmark = [pytest.mark.live_superset, pytest.mark.skipif(not URL, reason="ARP_TEST_SUPERSET_URL not set -- live Superset")]

FIXTURES = Path(__file__).parent / "fixtures" / "bi"


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("ARP_SUPERSET_URL", URL)
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


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
    assert _bootstrap() == out  # idempotent

    client = SupersetClient(URL, settings.superset_user, settings.superset_password)
    holdings = out["datasets"]["holdings"]
    meta = client.dataset_meta(holdings)
    assert meta.metrics == {m.name for m in VIEW_DATASETS["holdings"].metrics}
    assert meta.columns == set(VIEW_DATASETS["holdings"].columns)

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
