from __future__ import annotations

import json

import httpx
import pytest

from arp.bi.superset_client import SupersetClient, SupersetError


def _client(handler):
    calls: list[httpx.Request] = []

    def wrapped(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        path = req.url.path
        if path == "/api/v1/security/login":
            return httpx.Response(200, json={"access_token": f"tok{sum('login' in c.url.path for c in calls)}"})
        if path == "/api/v1/security/csrf_token/":
            return httpx.Response(200, json={"result": "csrf"})
        return handler(req)

    return SupersetClient("http://ss", "u", "p", transport=httpx.MockTransport(wrapped)), calls


def test_login_then_csrf_header_sent_on_writes():
    c, calls = _client(lambda r: httpx.Response(201, json={"id": 7}))
    c.create_chart("n", 1, "table", {"a": 1})
    login = json.loads(calls[0].content)
    assert login["provider"] == "db" and login["refresh"] is False
    post = calls[-1]
    assert post.headers["Authorization"] == "Bearer tok1"
    assert post.headers["X-CSRFToken"] == "csrf"
    assert post.headers["Referer"] == "http://ss"
    body = json.loads(post.content)
    assert isinstance(body["params"], str) and isinstance(body["query_context"], str)


def test_create_dashboard_sends_published_false():
    c, calls = _client(lambda r: httpx.Response(201, json={"id": 3}))
    assert c.create_dashboard("T", "slug", {"k": 1}, [1, 2]) == 3
    body = json.loads(next(c for c in calls if c.url.path == "/api/v1/dashboard/").content)
    assert body["published"] is False
    assert isinstance(body["position_json"], str)
    assert [c.url.path for c in calls if c.method == "PUT"] == ["/api/v1/chart/1", "/api/v1/chart/2"]


def test_error_response_raises_superset_error_with_body():
    c, _ = _client(lambda r: httpx.Response(422, text="bad payload"))
    with pytest.raises(SupersetError) as e:
        c.delete_chart(1)
    assert e.value.status_code == 422 and "bad payload" in e.value.body


def test_ensure_dataset_is_idempotent():
    def h(r):
        assert r.method == "GET"
        return httpx.Response(200, json={"result": [{"id": 9}]})

    c, calls = _client(h)
    assert c.ensure_dataset(1, "arp_bi", "v") == 9
    assert all(x.method != "POST" or "security" in x.url.path for x in calls)


def test_token_refreshed_on_401_once():
    state = {"n": 0}

    def h(r):
        state["n"] += 1
        return httpx.Response(401, text="exp") if state["n"] == 1 else httpx.Response(200, json={"result": []})

    c, calls = _client(h)
    assert c.find_dashboard("s") is None
    assert [x.url.path for x in calls].count("/api/v1/security/login") == 2
    # persistent 401 raises after a single retry
    c2, _ = _client(lambda r: httpx.Response(401, text="no"))
    with pytest.raises(SupersetError):
        c2.find_dashboard("s")


def test_create_chart_query_context_queries_params_columns_and_metrics():
    # Superset's GET /chart/<id>/data/ runs the saved query_context; with
    # empty `queries` it returns no rows (checked live in Task 4).
    c, calls = _client(lambda r: httpx.Response(201, json={"id": 7}))
    params = {
        "x_axis": "as_of_date",
        "time_grain_sqla": "P1M",
        "groupby": ["portfolio_name"],
        "metrics": ["Exposure (EUR)"],
        "adhoc_filters": [
            {"expressionType": "SIMPLE", "subject": "sector", "operator": "IN", "comparator": ["Energy"], "clause": "WHERE"}
        ],
        "row_limit": 50,
    }
    c.create_chart("n", 3, "echarts_timeseries_line", params)
    qc = json.loads(json.loads(calls[-1].content)["query_context"])
    assert qc["datasource"] == {"id": 3, "type": "table"}
    (q,) = qc["queries"]
    assert q["columns"][0]["sqlExpression"] == "as_of_date" and q["columns"][0]["timeGrain"] == "P1M"
    assert q["columns"][1:] == ["portfolio_name"]
    assert q["metrics"] == ["Exposure (EUR)"]
    assert q["filters"] == [{"col": "sector", "op": "IN", "val": ["Energy"]}]
    assert q["row_limit"] == 50


def test_create_chart_query_context_single_metric_and_pivot_rows():
    c, calls = _client(lambda r: httpx.Response(201, json={"id": 7}))
    c.create_chart("n", 3, "pie", {"groupby": ["sector"], "metric": "Holdings"})
    c.create_chart("n", 3, "pivot_table_v2", {"groupbyRows": ["sector"], "groupbyColumns": ["country"], "metrics": ["Holdings"]})
    pie, pivot = (
        json.loads(json.loads(x.content)["query_context"])["queries"][0] for x in calls if x.url.path == "/api/v1/chart/"
    )
    assert pie["columns"] == ["sector"] and pie["metrics"] == ["Holdings"]
    assert pivot["columns"] == ["sector", "country"]


def test_ensure_embedded_returns_uuid():
    c, calls = _client(lambda r: httpx.Response(200, json={"result": {"uuid": "u-1", "dashboard_id": "5"}}))
    assert c.ensure_embedded(5) == "u-1"
    assert calls[-1].method == "POST" and calls[-1].url.path == "/api/v1/dashboard/5/embedded"


def test_ensure_database_updates_uri_when_found():
    def h(r):
        if r.method == "GET":
            return httpx.Response(200, json={"result": [{"id": 4}]})
        return httpx.Response(200, json={"id": 4})

    c, calls = _client(h)
    assert c.ensure_database("arp_bi", "postgresql://bi_reader:new@h/arp") == 4
    put = calls[-1]
    assert put.method == "PUT" and put.url.path == "/api/v1/database/4"
    assert json.loads(put.content) == {"sqlalchemy_uri": "postgresql://bi_reader:new@h/arp"}
