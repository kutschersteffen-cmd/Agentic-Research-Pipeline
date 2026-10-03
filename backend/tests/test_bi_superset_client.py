from __future__ import annotations

import json

import httpx
import pytest

from arp.bi.superset_client import MAX_DASHBOARD_PAGES, SupersetClient, SupersetError


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


def test_create_dashboard_sends_json_metadata_and_still_unpublished():
    c, calls = _client(lambda r: httpx.Response(201, json={"id": 3}))
    meta = {"native_filter_configuration": [{"id": "NATIVE_FILTER-x"}]}
    c.create_dashboard("T", "slug", {"k": 1}, [1], json_metadata=meta)
    body = json.loads(next(c for c in calls if c.url.path == "/api/v1/dashboard/").content)
    assert body["json_metadata"] == json.dumps(meta) and body["published"] is False


def test_create_dashboard_without_json_metadata_sends_empty_object():
    c, calls = _client(lambda r: httpx.Response(201, json={"id": 3}))
    c.create_dashboard("T", "slug", {"k": 1}, [])
    assert json.loads(calls[-1].content)["json_metadata"] == "{}"


def test_update_dashboard_sends_json_metadata_only_when_given():
    c, calls = _client(lambda r: httpx.Response(200, json={}))
    c.update_dashboard(5, {"k": 1}, [], json_metadata={"a": 1})
    assert json.loads(calls[-1].content) == {"position_json": json.dumps({"k": 1}), "json_metadata": json.dumps({"a": 1})}


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


def test_find_dataset_filters_by_database_and_never_creates():
    def h(r):
        assert r.method == "GET"
        q = json.loads(r.url.params["q"])
        assert {"col": "database", "opr": "rel_o_m", "value": 4} in q["filters"]
        return httpx.Response(200, json={"result": []})

    c, _ = _client(h)
    assert c.find_dataset(4, "bi", "holdings") is None


def test_update_dashboard_attaches_charts_then_puts_layout():
    c, calls = _client(lambda r: httpx.Response(200, json={}))
    c.update_dashboard(5, {"k": 1}, [8])
    puts = [x for x in calls if x.method == "PUT"]
    assert [x.url.path for x in puts] == ["/api/v1/chart/8", "/api/v1/dashboard/5"]
    assert json.loads(puts[0].content) == {"dashboards": [5]}
    assert json.loads(puts[1].content) == {"position_json": json.dumps({"k": 1})}


def test_dashboard_charts_maps_id_to_name():
    c, _ = _client(lambda r: httpx.Response(200, json={"result": [{"id": 2, "slice_name": "B"}, {"id": 1, "slice_name": "A"}]}))
    assert c.dashboard_charts(5) == {2: "B", 1: "A"}


def test_create_dashboard_deletes_itself_when_attach_fails():
    def h(r):
        if r.method == "POST":
            return httpx.Response(201, json={"id": 3})
        if r.method == "PUT":
            return httpx.Response(422, text="bad chart")
        return httpx.Response(200, json={})

    c, calls = _client(h)
    with pytest.raises(SupersetError):
        c.create_dashboard("T", "slug", {}, [1])
    assert [(x.method, x.url.path) for x in calls][-1] == ("DELETE", "/api/v1/dashboard/3")


def test_get_dashboard_returns_result():
    def h(r):
        assert r.method == "GET" and r.url.path == "/api/v1/dashboard/5"
        return httpx.Response(200, json={"result": {"id": 5, "slug": "arp-x", "published": False}})

    c, _ = _client(h)
    assert c.get_dashboard(5)["slug"] == "arp-x"


def _dataset_handler(state):
    def h(r):
        if r.method == "GET":
            return httpx.Response(200, json={"result": state})
        return httpx.Response(200, json={})

    return h


def _state():
    return {
        "description": None,
        "columns": [
            {"id": 1, "column_name": "a", "type": "TEXT", "description": None, "groupby": True, "filterable": True,
             "is_dttm": False, "expression": "", "verbose_name": None, "changed_on": "x", "uuid": "u1"},
            {"id": 2, "column_name": "b", "type": "NUMERIC", "description": "keep me", "groupby": False, "filterable": True,
             "is_dttm": False, "expression": "", "verbose_name": "B", "created_on": "y"},
        ],
        "metrics": [{"id": 9, "metric_name": "m", "expression": "COUNT(*)", "description": "d", "changed_on": "z"}],
    }


def _puts(calls):
    return [c for c in calls if c.method == "PUT"]


def test_sync_descriptions_sets_dataset_and_column_descriptions():
    c, calls = _client(_dataset_handler(_state()))
    c.sync_descriptions(5, "Dataset text.", {"a": "Col a."})
    (put,) = _puts(calls)
    assert put.url.path == "/api/v1/dataset/5"
    body = json.loads(put.content)
    assert body["description"] == "Dataset text."
    cols = {x["column_name"]: x for x in body["columns"]}
    assert cols["a"]["description"] == "Col a."
    assert cols["b"]["description"] == "keep me"  # not named: untouched


def test_sync_descriptions_keeps_existing_columns_and_metrics():
    c, calls = _client(_dataset_handler(_state()))
    c.sync_descriptions(5, "Dataset text.", {"a": "Col a."})
    body = json.loads(_puts(calls)[0].content)
    assert [(x["id"], x["column_name"]) for x in body["columns"]] == [(1, "a"), (2, "b")]
    assert body["columns"][0]["type"] == "TEXT" and body["columns"][1]["verbose_name"] == "B"
    assert [(m["id"], m["metric_name"], m["expression"]) for m in body["metrics"]] == [(9, "m", "COUNT(*)")]
    # read-only fields Superset rejects on PUT are not sent
    assert all(not ({"changed_on", "created_on", "uuid"} & set(x)) for x in body["columns"] + body["metrics"])


def test_sync_descriptions_is_idempotent():
    state = _state()

    def h(r):
        if r.method == "PUT":
            body = json.loads(r.content)
            state["description"] = body["description"]
            for col, new in zip(state["columns"], body["columns"], strict=True):
                col["description"] = new["description"]
        return httpx.Response(200, json={"result": state})

    c, calls = _client(h)
    c.sync_descriptions(5, "Dataset text.", {"a": "Col a."})
    c.sync_descriptions(5, "Dataset text.", {"a": "Col a."})
    assert len(_puts(calls)) == 1


def test_sync_descriptions_drops_empty_length_validated_fields_but_keeps_flags():
    state = _state()
    state["columns"][0].update(verbose_name="", advanced_data_type="", python_date_format="", groupby=False)
    state["metrics"][0].update(metric_type="", d3format="", currency="", verbose_name="")
    c, calls = _client(_dataset_handler(state))
    c.sync_descriptions(5, "Dataset text.", {"a": "Col a."})
    body = json.loads(_puts(calls)[0].content)
    col, metric = body["columns"][0], body["metrics"][0]
    assert col["id"] == 1 and col["groupby"] is False and col["filterable"] is True
    assert not {"verbose_name", "advanced_data_type", "python_date_format"} & set(col)
    assert metric["id"] == 9 and not {"metric_type", "d3format", "currency", "verbose_name"} & set(metric)


def test_sync_descriptions_puts_again_when_catalog_description_changes():
    state = _state()

    def h(r):
        if r.method == "PUT":
            body = json.loads(r.content)
            state["description"] = body["description"]
            for col, new in zip(state["columns"], body["columns"], strict=True):
                col["description"] = new["description"]
        return httpx.Response(200, json={"result": state})

    c, calls = _client(h)
    c.sync_descriptions(5, "One.", {"a": "Col a."})
    c.sync_descriptions(5, "Two.", {"a": "Col a."})
    assert len(_puts(calls)) == 2


def test_sync_descriptions_treats_none_and_empty_as_equal():
    state = _state()
    state["columns"][0]["description"] = ""
    c, calls = _client(_dataset_handler(state))
    c.sync_descriptions(5, "", {"a": ""})  # stored: description None, column a ""
    assert _puts(calls) == []


def _row(i, slug, title="T", published=False):
    return {"id": i, "slug": slug, "dashboard_title": title, "published": published}


def test_list_dashboards_filters_by_prefix():
    rows = [_row(1, "arp-a", "A", True), _row(2, "ARP-b"), _row(3, "arpx"), _row(4, " arp-c"), _row(5, None), _row(6, "human")]

    def h(r):
        assert r.method == "GET" and r.url.path == "/api/v1/dashboard/"
        q = json.loads(r.url.params["q"])
        assert {"col": "slug", "opr": "sw", "value": "arp-"} in q["filters"]
        return httpx.Response(200, json={"count": len(rows), "result": rows})

    c, _ = _client(h)
    assert c.list_dashboards() == [{"id": 1, "slug": "arp-a", "title": "A", "published": True}]


def test_list_dashboards_pages_through_results():
    rows = [_row(i, f"arp-{i}") for i in range(250)]
    pages = []

    def h(r):
        q = json.loads(r.url.params["q"])
        pages.append(q["page"])
        s = q["page"] * q["page_size"]
        return httpx.Response(200, json={"count": len(rows), "result": rows[s : s + q["page_size"]]})

    c, _ = _client(h)
    assert len(c.list_dashboards()) == 250 and pages == [0, 1, 2]


def test_list_dashboards_without_count_pages_until_short_page():
    rows = [_row(i, f"arp-{i}") for i in range(150)]

    def h(r):
        q = json.loads(r.url.params["q"])
        s = q["page"] * q["page_size"]
        return httpx.Response(200, json={"result": rows[s : s + q["page_size"]]})

    c, _ = _client(h)
    assert len(c.list_dashboards()) == 150


def test_list_dashboards_stops_at_page_cap():
    pages = []

    def h(r):  # a broken server: always a full page, never a count
        q = json.loads(r.url.params["q"])
        pages.append(q["page"])
        return httpx.Response(200, json={"result": [_row(i, f"arp-{i}") for i in range(q["page_size"])]})

    c, _ = _client(h)
    c.list_dashboards()
    assert pages == list(range(MAX_DASHBOARD_PAGES))


def test_export_dashboard_returns_zip_bytes():
    c, calls = _client(lambda r: httpx.Response(200, content=b"PK-zip", headers={"content-type": "application/zip"}))
    assert c.export_dashboard(5) == b"PK-zip"
    req = calls[-1]
    assert req.method == "GET" and req.url.path == "/api/v1/dashboard/export/"
    assert req.url.params["q"] == "!(5)"
    assert req.headers["Authorization"] == "Bearer tok1"


def test_export_dashboard_error_keeps_body_out_of_message():
    c, _ = _client(lambda r: httpx.Response(404, text="secret-host:5432"))
    with pytest.raises(SupersetError) as exc:
        c.export_dashboard(5)
    assert "secret-host" not in str(exc.value) and exc.value.body == "secret-host:5432"


def test_import_dashboard_posts_multipart_with_overwrite_and_passwords():
    c, calls = _client(lambda r: httpx.Response(200, json={"message": "OK"}))
    c.import_dashboard(b"PK-zip", {"databases/arp_bi.yaml": "pw"})
    req = calls[-1]
    assert req.method == "POST" and req.url.path == "/api/v1/dashboard/import/"
    assert req.headers["content-type"].startswith("multipart/form-data")
    assert req.headers["X-CSRFToken"] == "csrf"
    body = req.content
    assert b'name="formData"' in body and b"PK-zip" in body
    assert b'name="overwrite"' in body and b"true" in body
    assert b'{"databases/arp_bi.yaml": "pw"}' in body


def test_import_dashboard_error_keeps_body_out_of_message():
    c, _ = _client(lambda r: httpx.Response(422, text="postgresql://bi_reader:pw@h/db"))
    with pytest.raises(SupersetError) as exc:
        c.import_dashboard(b"x", {})
    assert "bi_reader" not in str(exc.value)


def test_export_dashboard_relogs_in_once_on_401():
    seen = []

    def handler(req):
        seen.append(req.headers["Authorization"])
        return httpx.Response(401) if len(seen) == 1 else httpx.Response(200, content=b"PK")

    c, _ = _client(handler)
    assert c.export_dashboard(5) == b"PK"
    assert seen == ["Bearer tok1", "Bearer tok2"]


def test_unpublish_dashboard_puts_published_false():
    c, calls = _client(lambda r: httpx.Response(200, json={}))
    c.unpublish_dashboard(5)
    assert calls[-1].method == "PUT" and calls[-1].url.path == "/api/v1/dashboard/5"
    assert json.loads(calls[-1].content) == {"published": False}
