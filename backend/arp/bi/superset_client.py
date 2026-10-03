from __future__ import annotations

import json

import httpx

from arp.bi.catalog import MetricDef
from arp.bi.plan import DatasetMeta

_API = "/api/v1"


class SupersetError(Exception):
    """A non-2xx response from Superset; keeps the status and raw body so
    callers can surface Superset's own validation message."""

    def __init__(self, status_code: int, body: str, message: str = ""):
        super().__init__(f"Superset {status_code}: {message or body[:300]}")
        self.status_code = status_code
        self.body = body


class SupersetClient:
    """Sync REST client for Apache Superset 5.x. Logs in lazily, sends the
    bearer token + CSRF token + Referer on every call, and re-logs-in once
    on a 401. Payload keys marked `# unverified` are checked against a live
    Superset in Task 4."""

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
        q = json.dumps({"filters": filters})  # unverified: JSON accepted in place of rison for ?q=
        result = self._request("GET", f"/{resource}/", params={"q": q})["result"]
        return result[0]["id"] if result else None

    def ensure_database(self, name: str, sqlalchemy_uri: str) -> int:
        found = self._find_id("database", [{"col": "database_name", "opr": "eq", "value": name}])
        if found is not None:
            return found
        body = {"database_name": name, "sqlalchemy_uri": sqlalchemy_uri, "expose_in_sqllab": True}  # unverified: expose_in_sqllab
        return self._request("POST", "/database/", json=body)["id"]

    def ensure_dataset(self, database_id: int, schema: str, table: str) -> int:
        found = self._find_id(
            "dataset",
            [
                {"col": "table_name", "opr": "eq", "value": table},
                {"col": "schema", "opr": "eq", "value": schema},
                {"col": "database", "opr": "rel_o_m", "value": database_id},  # unverified: relation filter opr
            ],
        )
        if found is not None:
            return found
        body = {"database": database_id, "schema": schema, "table_name": table}
        return self._request("POST", "/dataset/", json=body)["id"]

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
        # unverified: PUT with only catalog metrics drops any others (intended: catalog is source of truth)
        self._request("PUT", f"/dataset/{dataset_id}", json={"metrics": payload})

    def create_chart(self, name: str, dataset_id: int, viz_type: str, params: dict) -> int:
        form_data = {**params, "datasource": f"{dataset_id}__table", "viz_type": viz_type}
        query_context = {  # unverified: minimal query_context shape
            "datasource": {"id": dataset_id, "type": "table"},
            "queries": [],
            "form_data": form_data,
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
            "json_metadata": json.dumps({}),  # unverified: empty metadata accepted
            "published": False,
        }
        dash_id = self._request("POST", "/dashboard/", json=body)["id"]
        for cid in chart_ids:  # unverified: charts are attached by PUT /chart/{id} {"dashboards": [...]}
            self._request("PUT", f"/chart/{cid}", json={"dashboards": [dash_id]})
        return dash_id

    def find_dashboard(self, slug: str) -> int | None:
        return self._find_id("dashboard", [{"col": "slug", "opr": "eq", "value": slug}])

    def delete_chart(self, id: int) -> None:
        self._request("DELETE", f"/chart/{id}")

    def delete_dashboard(self, id: int) -> None:
        self._request("DELETE", f"/dashboard/{id}")

    def guest_token(self, dashboard_id: str, rls: list[dict]) -> str:
        body = {
            "user": {"username": "arp_guest"},  # unverified: guest user shape
            "resources": [{"type": "dashboard", "id": dashboard_id}],
            "rls": rls,
        }
        return self._request("POST", "/security/guest_token/", json=body)["token"]


def _check(resp: httpx.Response) -> None:
    if resp.status_code >= 400:
        raise SupersetError(resp.status_code, resp.text)
