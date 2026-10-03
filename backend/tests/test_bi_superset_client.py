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
