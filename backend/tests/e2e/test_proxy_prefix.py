"""The app behind a path prefix, the way Jupyter Server Proxy serves it (spec bank-jupyter-launch, AC-7, AC-8, AC-29).

Self-contained: builds the frontend twice into temp dirs, starts its own API on a free port with
ARP_FRONTEND_DIST and a small prefix-stripping proxy in front. Opt-in like the other browser tests
(needs the migrated Postgres the e2e stack uses, and frontend/node_modules).
"""

import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from arp.config import Settings

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not os.environ.get("ARP_E2E_URL"), reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]

REPO = Path(__file__).resolve().parents[3]
PREFIX = "/user/x/proxy/8000"
DSN = os.environ.get("ARP_POSTGRES_DSN", "postgresql+psycopg://arp:arp@localhost:5432/arp_test")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _build(out: Path, api_base: str | None) -> Path:
    env = {k: v for k, v in os.environ.items() if k != "VITE_API_BASE"}
    if api_base is not None:
        env["VITE_API_BASE"] = api_base
    subprocess.run(["node_modules/.bin/vite", "build", "--outDir", str(out), "--emptyOutDir"],
                   cwd=REPO / "frontend", env=env, check=True, capture_output=True)
    return out


def _asset_refs(dist: Path) -> list[str]:
    return re.findall(r'(?:src|href)="([^"]*assets/[^"]*)"', (dist / "index.html").read_text())


@pytest.fixture(scope="module")
def relative_dist(tmp_path_factory):
    return _build(tmp_path_factory.mktemp("dist-relative"), ".")


def test_relative_build_has_no_absolute_urls(relative_dist):
    refs = _asset_refs(relative_dist)
    assert refs and all(r.startswith("./assets/") for r in refs)
    for f in relative_dist.rglob("*"):
        if f.is_file() and f.suffix in {".js", ".html", ".css"}:
            assert "http://localhost:8000" not in f.read_text(errors="ignore"), f


def test_default_build_is_unchanged(tmp_path):
    dist = _build(tmp_path / "dist", None)
    refs = _asset_refs(dist)
    assert refs and all(r.startswith("/assets/") for r in refs)
    assert any("http://localhost:8000" in f.read_text(errors="ignore") for f in (dist / "assets").glob("*.js"))


class _PrefixProxy(BaseHTTPRequestHandler):
    """Accepts only PREFIX/..., strips it and forwards, like Jupyter Server Proxy. Anything else is a 404."""

    upstream = ""

    def _forward(self):
        if not self.path.startswith(PREFIX + "/"):
            self.send_error(404, "outside the proxy prefix")
            return
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)) or None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in {"host", "connection", "accept-encoding"}}
        request = urllib.request.Request(self.upstream + self.path[len(PREFIX):], data=body, headers=headers, method=self.command)
        try:
            response = urllib.request.urlopen(request, timeout=30)  # noqa: S310 -- loopback upstream started by this test
        except urllib.error.HTTPError as exc:
            response = exc
        payload = response.read()
        self.send_response(response.status if hasattr(response, "status") else response.code)
        for k, v in response.headers.items():
            if k.lower() not in {"transfer-encoding", "connection", "content-length"}:
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = _forward

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def proxied_app(relative_dist):
    api_port, proxy_port = _free_port(), _free_port()
    env = {**os.environ, "ARP_FRONTEND_DIST": str(relative_dist), "ARP_POSTGRES_DSN": DSN, "ARP_AUTH_MODE": "dev",
           "ARP_NEO4J_URI": ""}
    api = subprocess.Popen([sys.executable, "-m", "uvicorn", "arp.api.main:app", "--host", "127.0.0.1", "--port", str(api_port)],
                           cwd=REPO / "backend", env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _PrefixProxy.upstream = f"http://127.0.0.1:{api_port}"
    proxy = ThreadingHTTPServer(("127.0.0.1", proxy_port), _PrefixProxy)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{api_port}/api/health", timeout=1)  # noqa: S310
                break
            except OSError:
                time.sleep(1)
        else:
            pytest.fail("the API did not start")
        yield f"http://127.0.0.1:{proxy_port}{PREFIX}/"
    finally:
        proxy.shutdown()
        api.terminate()
        api.wait(timeout=10)


def test_app_works_under_the_proxy_prefix(proxied_app):
    from playwright.sync_api import sync_playwright

    origin = proxied_app.split(PREFIX)[0]
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=Settings().chromium_path)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        responses = []
        page.on("response", lambda r: r.url.startswith(origin) and responses.append((r.status, r.url[len(origin):])))

        page.goto(proxied_app + "#home")
        page.wait_for_load_state("networkidle")
        assert page.get_by_role("heading", name=re.compile(r"^Good (morning|afternoon|evening)")).is_visible()
        for tab in ("decision", "argus"):  # other views must stay inside the prefix too
            page.goto(proxied_app + "#" + tab)
            page.wait_for_load_state("networkidle")
        browser.close()

    assert responses
    outside_or_failed = [(s, path) for s, path in responses if not path.startswith(PREFIX + "/") or s >= 400]
    assert outside_or_failed == []
    assert any(s == 200 and path.startswith(PREFIX + "/api/") for s, path in responses)
