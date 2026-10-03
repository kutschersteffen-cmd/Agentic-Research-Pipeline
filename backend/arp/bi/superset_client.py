from __future__ import annotations

import contextlib
import json

import httpx

from arp.bi.catalog import MetricDef
from arp.bi.plan import DatasetMeta

_API = "/api/v1"


class SupersetError(Exception):
    """A non-2xx response from Superset; keeps the status and raw body so
    callers can log Superset's own validation message."""

    def __init__(self, status_code: int, body: str, message: str = ""):
        # The body is kept on .body for logs but kept out of str(): it can echo hosts/DSNs to API clients.
        super().__init__(f"Superset returned HTTP {status_code}" + (f": {message}" if message else ""))
        self.status_code = status_code
        self.body = body


class SupersetClient:
    """Sync REST client for Apache Superset 5.x. Logs in lazily, sends the
    bearer token + CSRF token + Referer on every call, and re-logs-in once
    on a 401. Endpoints and payloads were checked against a live Superset
    5.0.0 (tests/test_bi_live_superset.py is the contract)."""

    def __init__(self, base_url: str, user: str, password: str, *, transport: httpx.BaseTransport | None = None):
        self._base = base_url.rstrip("/")
        self._user = user
        self._password = password
        self._http = httpx.Client(base_url=self._base, transport=transport, timeout=30.0)
        self._headers: dict[str, str] | None = None

    def _login(self) -> None:
        resp = self._http.post(
            f"{_API}/security/login",
            json={"username": self._user, "password": self._password, "provider": "db", "refresh": False},
        )
        _check(resp)
        token = resp.json()["access_token"]
        auth = {"Authorization": f"Bearer {token}"}
        resp = self._http.get(f"{_API}/security/csrf_token/", headers=auth)
        _check(resp)
        self._headers = {
            **auth,
            "X-CSRFToken": resp.json()["result"],
            "Referer": self._base,  # CSRF check on writes requires a Referer
        }

    def _request(self, method: str, path: str, **kwargs) -> dict:
        for attempt in (0, 1):
            if self._headers is None:
                self._login()
            resp = self._http.request(method, f"{_API}{path}", headers=self._headers, **kwargs)
            if resp.status_code == 401 and attempt == 0:
                self._headers = None
                continue
            _check(resp)
            return resp.json() if resp.content else {}
        raise AssertionError("unreachable")

    def _find_id(self, resource: str, filters: list[dict]) -> int | None:
        q = json.dumps({"filters": filters})  # Superset's rison parser accepts JSON for ?q=
        result = self._request("GET", f"/{resource}/", params={"q": q})["result"]
        return result[0]["id"] if result else None

    def find_database(self, name: str) -> int | None:
        return self._find_id("database", [{"col": "database_name", "opr": "eq", "value": name}])

    def ensure_database(self, name: str, sqlalchemy_uri: str) -> int:
        found = self.find_database(name)
        if found is not None:
            # Re-sent every time so a rotated reader password lands.
            self._request("PUT", f"/database/{found}", json={"sqlalchemy_uri": sqlalchemy_uri})
            return found
        body = {"database_name": name, "sqlalchemy_uri": sqlalchemy_uri, "expose_in_sqllab": True}
        return self._request("POST", "/database/", json=body)["id"]

    def find_dataset(self, database_id: int, schema: str, table: str) -> int | None:
        return self._find_id(
            "dataset",
            [
                {"col": "table_name", "opr": "eq", "value": table},
                {"col": "schema", "opr": "eq", "value": schema},
                {"col": "database", "opr": "rel_o_m", "value": database_id},
            ],
        )

    def ensure_dataset(self, database_id: int, schema: str, table: str) -> int:
        found = self.find_dataset(database_id, schema, table)
        if found is not None:
            return found
        body = {"database": database_id, "schema": schema, "table_name": table}
        return self._request("POST", "/dataset/", json=body)["id"]

    def refresh_dataset(self, dataset_id: int) -> None:
        """Re-reads the view's columns, so a changed view definition shows up."""
        self._request("PUT", f"/dataset/{dataset_id}/refresh")

    def _dataset(self, dataset_id: int) -> dict:
        return self._request("GET", f"/dataset/{dataset_id}")["result"]

    def dataset_meta(self, dataset_id: int) -> DatasetMeta:
        r = self._dataset(dataset_id)
        return DatasetMeta(
            columns={c["column_name"] for c in r.get("columns", [])},
            metrics={m["metric_name"] for m in r.get("metrics", [])},
        )

    def sync_metrics(self, dataset_id: int, metrics: list[MetricDef]) -> None:
        # PUT replaces the metrics list; existing ids are kept so Superset
        # updates in place instead of deleting + recreating.
        existing = {m["metric_name"]: m["id"] for m in self._dataset(dataset_id).get("metrics", [])}
        payload = []
        for m in metrics:
            item = {"metric_name": m.name, "expression": m.expression, "description": m.description, "verbose_name": m.name}
            if m.name in existing:
                item["id"] = existing.pop(m.name)
            payload.append(item)
        # The PUT replaces the whole list: metrics not in the catalog are dropped
        # (the catalog is the source of truth).
        self._request("PUT", f"/dataset/{dataset_id}", json={"metrics": payload})

    def sync_descriptions(self, dataset_id: int, description: str, columns: dict[str, str]) -> None:
        """Sets the dataset description and the named columns' descriptions.
        The PUT replaces the columns and metrics lists, so every existing
        item goes back with its id and writable fields; no PUT if nothing differs."""
        # The catalog owns the dataset description and the descriptions of the columns it names:
        # they are overwritten on every bootstrap (edit catalog.py, not Superset). Catalog columns
        # absent from the dataset are silently ignored.
        ds = self._dataset(dataset_id)
        cols = ds.get("columns", [])
        changed = (ds.get("description") or "") != description or any(
            c["column_name"] in columns and (c.get("description") or "") != columns[c["column_name"]] for c in cols
        )
        if not changed:
            return
        new_cols = [
            {**_keep(c, _COLUMN_FIELDS), "description": columns.get(c["column_name"], c.get("description"))} for c in cols
        ]
        new_metrics = [_keep(m, _METRIC_FIELDS) for m in ds.get("metrics", [])]
        self._request(
            "PUT", f"/dataset/{dataset_id}", json={"description": description, "columns": new_cols, "metrics": new_metrics}
        )

    def create_chart(self, name: str, dataset_id: int, viz_type: str, params: dict) -> int:
        form_data = {**params, "datasource": f"{dataset_id}__table", "viz_type": viz_type}
        # Dashboards render from `params` (the frontend builds its own query);
        # the saved query_context only serves GET /chart/<id>/data/, reports
        # and cache warm-up. With empty `queries` that endpoint returns nothing.
        query_context = {
            "datasource": {"id": dataset_id, "type": "table"},
            "queries": [_query(form_data)],
            "form_data": form_data,
            "result_format": "json",
            "result_type": "full",
        }
        body = {
            "slice_name": name,
            "datasource_id": dataset_id,
            "datasource_type": "table",
            "viz_type": viz_type,
            "params": json.dumps(form_data),
            "query_context": json.dumps(query_context),
        }
        return self._request("POST", "/chart/", json=body)["id"]

    def create_dashboard(self, title: str, slug: str, position_json: dict, chart_ids: list[int]) -> int:
        body = {
            "dashboard_title": title,
            "slug": slug,
            "position_json": json.dumps(position_json),
            "json_metadata": json.dumps({}),
            "published": False,
        }
        dash_id = self._request("POST", "/dashboard/", json=body)["id"]
        try:
            self._attach(dash_id, chart_ids)
        except Exception:
            # Remove the half-made dashboard by id; the caller never learns it.
            with contextlib.suppress(SupersetError, httpx.HTTPError):
                self.delete_dashboard(dash_id)
            raise
        return dash_id

    def update_dashboard(self, dashboard_id: int, position_json: dict, chart_ids: list[int]) -> None:
        """Attaches `chart_ids` (the chart's dashboard list is replaced) and
        replaces the layout. Leaves title, slug and published untouched."""
        self._attach(dashboard_id, chart_ids)
        self._request("PUT", f"/dashboard/{dashboard_id}", json={"position_json": json.dumps(position_json)})

    def _attach(self, dashboard_id: int, chart_ids: list[int]) -> None:
        for cid in chart_ids:  # POST /dashboard/ cannot take charts; they attach from the chart side
            self._request("PUT", f"/chart/{cid}", json={"dashboards": [dashboard_id]})

    def dashboard_charts(self, dashboard_id: int) -> dict[int, str]:
        """{chart id: chart name} of the charts attached to the dashboard."""
        result = self._request("GET", f"/dashboard/{dashboard_id}/charts")["result"]
        return {c["id"]: c["slice_name"] for c in result}

    def get_dashboard(self, dashboard_id: int) -> dict:
        """The dashboard's metadata (slug, published, ...); 404 SupersetError if unknown."""
        return self._request("GET", f"/dashboard/{dashboard_id}")["result"]

    def find_dashboard(self, slug: str) -> int | None:
        return self._find_id("dashboard", [{"col": "slug", "opr": "eq", "value": slug}])

    def delete_chart(self, id: int) -> None:
        self._request("DELETE", f"/chart/{id}")

    def delete_dashboard(self, id: int) -> None:
        self._request("DELETE", f"/dashboard/{id}")

    def ensure_embedded(self, dashboard_id: int) -> str:
        """The dashboard's embedded UUID, which guest tokens and the embed SDK
        need (not the numeric id). The POST is an upsert: same UUID on repeat."""
        body = {"allowed_domains": []}  # framing is limited by the CSP frame-ancestors instead
        return self._request("POST", f"/dashboard/{dashboard_id}/embedded", json=body)["result"]["uuid"]

    def guest_token(self, dashboard_id: str, rls: list[dict]) -> str:
        """`dashboard_id` is the embedded UUID from `ensure_embedded`. Superset
        does not check it here; a wrong id only fails when the embed loads."""
        body = {
            "user": {"username": "arp_guest"},
            "resources": [{"type": "dashboard", "id": dashboard_id}],
            "rls": rls,
        }
        return self._request("POST", "/security/guest_token/", json=body)["token"]


# Writable fields of Superset's dataset PUT schema; GET also returns read-only
# ones (changed_on, created_on, uuid, ...) that a PUT would reject. None values
# are dropped so Superset keeps its defaults.
_COLUMN_FIELDS = (
    "id", "column_name", "type", "advanced_data_type", "verbose_name", "description", "expression",
    "extra", "filterable", "groupby", "is_active", "is_dttm", "python_date_format",
)  # fmt: skip
_METRIC_FIELDS = (
    "id", "metric_name", "metric_type", "verbose_name", "description", "expression", "extra",
    "d3format", "currency", "warning_text",
)  # fmt: skip


# Superset validates these with Length(1, N), so "" would 422; drop them when empty.
# description/expression/extra and booleans pass through ("" and False are real values).
_NONEMPTY = {"verbose_name", "advanced_data_type", "python_date_format", "metric_type", "d3format", "currency"}


def _keep(item: dict, fields: tuple[str, ...]) -> dict:
    return {k: item[k] for k in fields if item.get(k) is not None and (item[k] != "" or k not in _NONEMPTY)}


def _query(form_data: dict) -> dict:
    """One query object covering the allowlisted viz types: every column
    control becomes a group-by column, `metric`/`metrics` the metrics.
    Close to what each viz's frontend buildQuery sends, minus its
    post-processing, which only reshapes rows for drawing."""
    columns: list = []
    x_axis = form_data.get("x_axis")
    if x_axis and form_data.get("time_grain_sqla"):
        columns.append(
            {
                "columnType": "BASE_AXIS",
                "sqlExpression": x_axis,
                "label": x_axis,
                "expressionType": "SQL",
                "timeGrain": form_data["time_grain_sqla"],
            }
        )
    elif x_axis:
        columns.append(x_axis)
    for key in ("groupby", "groupbyRows", "groupbyColumns", "all_columns"):
        value = form_data.get(key) or []
        columns.extend([value] if isinstance(value, str) else value)
    metrics = form_data.get("metrics") or ([form_data["metric"]] if form_data.get("metric") else [])
    filters = [
        {"col": f["subject"], "op": f["operator"], "val": f.get("comparator")}
        for f in form_data.get("adhoc_filters", [])
        if f.get("expressionType") == "SIMPLE"
    ]
    return {
        "columns": columns,
        "metrics": metrics,
        "filters": filters,
        "orderby": [[metrics[0], False]] if metrics else [],
        "row_limit": form_data.get("row_limit", 10000),
        "time_range": "No filter",
    }


def _check(resp: httpx.Response) -> None:
    if resp.status_code >= 400:
        raise SupersetError(resp.status_code, resp.text)
