"""Whole-request size limit (spec server-paths-upload-limits, slice 4). AC-45 and AC-50 are holdout rows; AC-50 is smoke-tested here.."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from arp.api.deps import settings_dep
from arp.api.main import app
from arp.config import Settings, get_settings

WORKBENCH = "/api/universe/workbench"


def _json_body(size: int) -> bytes:
    head, tail = b'{"companies": [], "pad": "', b'"}'
    return head + b"a" * (size - len(head) - len(tail)) + tail


def _settings(monkeypatch, **update) -> None:
    monkeypatch.setitem(app.dependency_overrides, settings_dep, lambda: get_settings().model_copy(update=update))


def test_ac44_json_body_over_20_mb_is_413():
    body = _json_body(20_000_001)
    assert len(body) == 20_000_001
    r = TestClient(app).post(WORKBENCH, content=body, headers={"Content-Type": "application/json"})
    assert r.status_code == 413
    assert r.json() == {"detail": "Request is larger than the 20 MB limit."}


def _headers_only(path: str, content_type: bytes, length: int) -> tuple[int, bytes]:
    """Calls the app with headers only: its receive fails the test if the body is read."""
    sent: list[dict] = []

    async def receive():
        raise AssertionError("the body was read")

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"testserver"), (b"content-type", content_type), (b"content-length", str(length).encode())],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }
    asyncio.run(app(scope, receive, send))
    return sent[0]["status"], b"".join(m.get("body", b"") for m in sent[1:])


def test_ac46_multipart_content_length_over_250_mb_is_413_before_the_body_is_read():
    status, body = _headers_only("/api/universe/raw-upload", b"multipart/form-data; boundary=x", 250_000_001)
    assert (status, body) == (413, b'{"detail":"Request is larger than the 250 MB limit."}')


def test_multipart_type_is_matched_in_any_case():
    status, body = _headers_only("/api/universe/raw-upload", b"Multipart/Form-Data; boundary=x", 250_000_001)
    assert (status, body) == (413, b'{"detail":"Request is larger than the 250 MB limit."}')


def test_a_route_without_files_keeps_the_20_mb_limit_when_the_body_claims_multipart():
    status, body = _headers_only(WORKBENCH, b"multipart/form-data; boundary=x", 20_000_001)
    assert (status, body) == (413, b'{"detail":"Request is larger than the 20 MB limit."}')


def test_a_file_route_with_a_path_parameter_gets_the_250_mb_limit():
    status, body = _headers_only("/api/argus/flows/f1/documents/upload", b"multipart/form-data; boundary=x", 250_000_001)
    assert (status, body) == (413, b'{"detail":"Request is larger than the 250 MB limit."}')


def test_ac47_chunked_body_without_content_length_is_413_once_over(monkeypatch):
    _settings(monkeypatch, max_body_bytes=1_000_000)

    def chunks(total: int):
        for _ in range(total // 100_000):
            yield b"a" * 100_000
        yield b"a" * (total % 100_000)

    client = TestClient(app)
    r = client.post(WORKBENCH, content=chunks(1_000_001), headers={"Content-Type": "application/json"})
    assert "content-length" not in {k.lower() for k in r.request.headers}
    assert r.status_code == 413
    assert r.json() == {"detail": "Request is larger than the 1 MB limit."}
    # at the limit the request is not touched: the route answers (the body is not JSON)
    r = client.post(WORKBENCH, content=chunks(1_000_000), headers={"Content-Type": "application/json"})
    assert r.status_code == 422


def test_ac48_file_over_the_upload_limit_gets_the_per_file_sentence(monkeypatch, tmp_path):
    _settings(monkeypatch, max_request_bytes=3_000_000, max_upload_bytes=2_000_000, runs_dir=tmp_path)
    r = TestClient(app).post("/api/universe/raw-upload", files={"file": ("h.csv", b"a" * 2_000_001, "text/csv")})
    assert r.status_code == 413
    assert r.json() == {"detail": "File is larger than the 2 MB upload limit."}
    assert not any(p.is_file() for p in tmp_path.rglob("*"))


def test_ac49_limits_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("ARP_MAX_REQUEST_BYTES", "5000000")
    monkeypatch.setenv("ARP_MAX_BODY_BYTES", "3000000")
    s = Settings()
    assert (s.max_request_bytes, s.max_body_bytes) == (5_000_000, 3_000_000)


def test_ac49_defaults():
    s = Settings()
    assert (s.max_request_bytes, s.max_body_bytes) == (250_000_000, 20_000_000)


def test_ac50_bodyless_and_normal_requests_pass():
    client = TestClient(app)
    assert client.get("/api/health").status_code == 200


def test_ac61_413_comes_before_sign_in_and_carries_cors(monkeypatch):
    origin = "http://localhost:5173"
    assert origin in get_settings().allowed_origins
    _settings(monkeypatch, auth_mode="local")
    body = _json_body(20_000_001)
    r = TestClient(app).post(WORKBENCH, content=body, headers={"Content-Type": "application/json", "Origin": origin})
    assert r.status_code == 413
    assert r.headers["access-control-allow-origin"] == origin
