import hashlib
import json
import logging
import threading
import time

import httpx
import pytest

from arp.compute import client
from arp.config import Settings
from arp.ingestion.local_files import parser_version

GET_OBJECT = ("GET", "/storage/v1/b/")
UPLOAD = ("POST", "/upload/storage/v1/b/")
PARSE = ("POST", "/parse")


class Recorder:
    """A MockTransport handler: routes by (method, path prefix), records every request."""

    def __init__(self):
        self.routes = {}
        self.requests = []
        self._lock = threading.Lock()

    def route(self, matcher, outcome, json=None):
        self.routes[matcher] = (outcome, json)

    def calls(self, matcher):
        return [r for r in self.requests if _matches(r, matcher)]

    def __call__(self, request):
        request.read()
        with self._lock:
            self.requests.append(request)
        for matcher, (outcome, body) in self.routes.items():
            if _matches(request, matcher):
                if callable(outcome) and not isinstance(outcome, type):
                    return outcome(request)
                if isinstance(outcome, type) and issubclass(outcome, Exception):
                    raise outcome("stub", request=request)
                return httpx.Response(outcome, json=body) if body is not None else httpx.Response(outcome)
        raise AssertionError(f"unrouted request {request.method} {request.url}")


def _matches(request, matcher):
    method, path = matcher
    return request.method == method and request.url.path.startswith(path)


def _settings(tmp_path, **overrides):
    key = tmp_path / "key.json"
    key.write_text("{}")
    values = dict(
        compute_parse_url="https://arp-parse.example.run.app",
        compute_models_url="https://arp-models.example.run.app",
        compute_bucket="proj-arp-compute",
        compute_credentials_file=str(key),
    )
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def transport(monkeypatch, tmp_path):
    rec = Recorder()
    monkeypatch.setattr(client, "_http", httpx.Client(transport=httpx.MockTransport(rec)))
    monkeypatch.setattr(client, "_cooldown_until", {})
    monkeypatch.setattr(client, "last_error", {})
    monkeypatch.setattr(client, "_warned", set())
    monkeypatch.setattr(client, "_id_token", lambda audience: "tok")
    monkeypatch.setattr(client, "_storage_token", lambda: "tok")
    monkeypatch.setattr(client, "_sleep", lambda s: None)
    settings = _settings(tmp_path)
    monkeypatch.setattr(client, "get_settings", lambda: settings)
    return rec


def pdf(tmp_path, data=b"%PDF-1.4 x", name="a.pdf"):
    path = tmp_path / name
    path.write_bytes(data)
    return path


OK = {"text": "T", "page_breaks": [0], "table_spans": []}


def test_parse_returns_service_result(tmp_path, transport):  # AC-3
    transport.route(GET_OBJECT, 404)
    transport.route(UPLOAD, 200)
    transport.route(PARSE, 200, json=OK)
    assert client.parse_pdf(pdf(tmp_path), "v1") == ("T", [0], [])


def test_parse_uploads_once_by_hash(tmp_path, transport):  # AC-4
    transport.route(GET_OBJECT, 404)
    transport.route(UPLOAD, 200)
    transport.route(PARSE, 200, json=OK)
    client.parse_pdf(pdf(tmp_path), "v1")
    uploads = transport.calls(UPLOAD)
    assert len(uploads) == 1
    assert uploads[0].url.params["name"] == f"parse/{hashlib.sha256(b'%PDF-1.4 x').hexdigest()}.pdf"
    assert uploads[0].content == b"%PDF-1.4 x"
    assert transport.calls(PARSE)[0].headers["X-ARP-Parser-Version"] == "v1"


def test_parse_skips_upload_when_object_exists(tmp_path, transport):  # AC-5
    transport.route(GET_OBJECT, 200, json={})
    transport.route(PARSE, 200, json=OK)
    client.parse_pdf(pdf(tmp_path), "v1")
    assert transport.calls(UPLOAD) == []
    parses = transport.calls(PARSE)
    assert len(parses) == 1
    assert json.loads(parses[0].content) == {"object": f"parse/{hashlib.sha256(b'%PDF-1.4 x').hexdigest()}.pdf"}


def test_409_falls_back_once(tmp_path, transport, caplog):  # AC-6
    transport.route(GET_OBJECT, 200, json={})
    transport.route(PARSE, 409, json={"detail": "parser_version mismatch: service=R-ver client=L-ver"})
    with caplog.at_level(logging.WARNING, logger="arp.compute.client"):
        assert client.parse_pdf(pdf(tmp_path), "L-ver") is None
    assert len(transport.calls(PARSE)) == 1
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "R-ver" in warnings[0] and "L-ver" in warnings[0]


def test_cooldown_skips_for_600s(tmp_path, transport, monkeypatch, caplog):  # AC-7
    clock = [1000.0]
    monkeypatch.setattr(client, "_now", lambda: clock[0])
    transport.route(GET_OBJECT, 200, json={})
    transport.route(PARSE, 409, json={"detail": "parser_version mismatch: service=R client=L"})
    client.parse_pdf(pdf(tmp_path), "L")
    sent = len(transport.requests)
    clock[0] += 599
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="arp.compute.client"):
        assert client.parse_pdf(pdf(tmp_path, b"%PDF other", "b.pdf"), "L") is None
    assert len(transport.requests) == sent
    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []


def test_cloud_retried_after_cooldown(tmp_path, transport, monkeypatch):  # AC-8
    clock = [1000.0]
    monkeypatch.setattr(client, "_now", lambda: clock[0])
    transport.route(GET_OBJECT, 200, json={})
    transport.route(PARSE, 500)
    assert client.parse_pdf(pdf(tmp_path), "v1") is None
    transport.route(PARSE, 200, json=OK)
    before = len(transport.calls(PARSE))
    clock[0] += 601
    assert client.parse_pdf(pdf(tmp_path), "v1") == ("T", [0], [])
    assert len(transport.calls(PARSE)) - before == 1


def test_connect_error_retried_once(tmp_path, transport):  # AC-9
    transport.route(GET_OBJECT, 200, json={})
    transport.route(PARSE, httpx.ConnectError)
    assert client.parse_pdf(pdf(tmp_path), "v1") is None
    assert len(transport.calls(PARSE)) == 2


def test_read_timeout_not_retried(tmp_path, transport):  # AC-10
    transport.route(GET_OBJECT, 200, json={})
    transport.route(PARSE, httpx.ReadTimeout)
    start = time.monotonic()
    assert client.parse_pdf(pdf(tmp_path), "v1") is None
    assert time.monotonic() - start < 3
    assert len(transport.calls(PARSE)) == 1


def test_storage_500_skips_parse(tmp_path, transport):  # AC-11
    transport.route(GET_OBJECT, 404)
    transport.route(UPLOAD, 500)
    assert client.parse_pdf(pdf(tmp_path), "v1") is None
    assert transport.calls(PARSE) == []


def test_422_no_cooldown(tmp_path, transport):  # AC-12
    transport.route(GET_OBJECT, 200, json={})
    transport.route(PARSE, 422, json={"detail": "parse failed: ValueError: bad"})
    assert client.parse_pdf(pdf(tmp_path), "v1") is None
    transport.route(PARSE, 200, json=OK)
    assert client.parse_pdf(pdf(tmp_path), "v1") == ("T", [0], [])


def _two_at_once(outcome):
    """A /parse handler that holds each request until a second one is in flight."""
    state = {"in_flight": 0, "max": 0, "both": threading.Event()}
    lock = threading.Lock()

    def handler(request):
        with lock:
            state["in_flight"] += 1
            state["max"] = max(state["max"], state["in_flight"])
            if state["in_flight"] >= 2:
                state["both"].set()
        state["both"].wait(5)
        time.sleep(0.05)
        with lock:
            state["in_flight"] -= 1
        if isinstance(outcome, type):
            raise outcome("stub", request=request)
        return httpx.Response(outcome, json=OK)

    return handler, state


def _parse_concurrently(tmp_path, n):
    paths = [pdf(tmp_path, f"%PDF {i}".encode(), f"{i}.pdf") for i in range(n)]
    results = [None] * n

    def run(i):
        results[i] = client.parse_pdf(paths[i], "v1")

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    return results


def test_two_parses_in_flight(tmp_path, transport):  # AC-13
    handler, state = _two_at_once(200)
    transport.route(GET_OBJECT, 200, json={})
    transport.route(PARSE, handler)
    results = _parse_concurrently(tmp_path, 4)
    assert state["both"].is_set()
    assert state["max"] == 2
    assert results == [("T", [0], [])] * 4


def test_hung_service_costs_two_requests(tmp_path, transport):  # AC-40
    handler, _ = _two_at_once(httpx.ReadTimeout)
    transport.route(GET_OBJECT, 200, json={})
    transport.route(PARSE, handler)
    assert _parse_concurrently(tmp_path, 4) == [None] * 4
    assert len(transport.calls(PARSE)) == 2


def test_404_retried_once_without_cooldown(tmp_path, transport):  # AC-42, AC-43
    transport.route(GET_OBJECT, 200, json={})
    transport.route(PARSE, 404, json={"detail": "object not found"})
    assert client.parse_pdf(pdf(tmp_path), "v1") is None
    assert len(transport.calls(PARSE)) == 2
    client.parse_pdf(pdf(tmp_path), "v1")
    assert len(transport.calls(PARSE)) == 4


def test_partial_settings_warn_once(tmp_path, transport, monkeypatch, caplog):  # AC-16
    settings = _settings(tmp_path, compute_bucket="")
    monkeypatch.setattr(client, "get_settings", lambda: settings)
    with caplog.at_level(logging.WARNING, logger="arp.compute.client"):
        assert client.parse_pdf(pdf(tmp_path), "v1") is None
        assert client.parse_pdf(pdf(tmp_path), "v1") is None
    assert transport.requests == []
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "ARP_COMPUTE_BUCKET" in warnings[0]


def test_missing_key_file_warns_once(tmp_path, transport, monkeypatch, caplog):  # AC-47
    missing = str(tmp_path / "nope.json")
    settings = _settings(tmp_path, compute_credentials_file=missing)
    monkeypatch.setattr(client, "get_settings", lambda: settings)
    with caplog.at_level(logging.WARNING, logger="arp.compute.client"):
        assert client.parse_pdf(pdf(tmp_path), "v1") is None
        assert client.parse_pdf(pdf(tmp_path), "v1") is None
    assert transport.requests == []
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and missing in warnings[0]


def test_upload_412_counts_as_success(tmp_path, transport):  # Review 1
    transport.route(GET_OBJECT, 404)
    transport.route(UPLOAD, 412)
    transport.route(PARSE, 200, json=OK)
    assert client.parse_pdf(pdf(tmp_path), "v1") == ("T", [0], [])


def test_large_pdf_request_carries_only_name(tmp_path, transport):  # Review 2
    big = tmp_path / "big.pdf"
    with big.open("wb") as f:
        f.truncate(40 * 2**20)
    transport.route(GET_OBJECT, 404)
    transport.route(UPLOAD, 200)
    transport.route(PARSE, 200, json=OK)
    client.parse_pdf(big, "v1")
    upload = transport.calls(UPLOAD)[0]
    assert upload.headers["Content-Length"] == str(40 * 2**20)
    assert len(transport.calls(PARSE)[0].content) < 200


def test_empty_parse_passes_through(tmp_path, transport):  # Review 3
    transport.route(GET_OBJECT, 200, json={})
    transport.route(PARSE, 200, json={"text": "", "page_breaks": [], "table_spans": []})
    assert client.parse_pdf(pdf(tmp_path), "v1") == ("", [], [])


def test_unset_settings_make_no_requests(tmp_path, transport, monkeypatch):  # AC-1
    empty = Settings(compute_parse_url="", compute_models_url="", compute_bucket="", compute_credentials_file="")
    monkeypatch.setattr(client, "get_settings", lambda: empty)
    assert client.parse_pdf(pdf(tmp_path), "v1") is None
    assert transport.requests == []


def test_parser_version_unchanged():  # AC-27
    assert parser_version() == "logic=4|docling=2.140.0|docling-core=2.101.1|trafilatura=2.3.1|openpyxl=3.1.5"
