"""security-errors-ssrf PR 1: check-postgres password (AC-1..5), CGNAT (AC-6..8, 30, 31), reindex SSRF (AC-9..29)."""
from __future__ import annotations

import dataclasses
import socket
from types import SimpleNamespace

import httpx
import pytest
from typer.testing import CliRunner

import arp.cli.db as db_cli
from arp.config import Settings
from arp.db.documents import StoredDocumentRef
from arp.net_safety import UnsafeURLError, assert_safe_fetch_target

runner = CliRunner()
DSN = "postgresql+psycopg://arp:s3cr3t-pw@db.example:5432/arp"
EDGAR = "EDGAR Test test@example.invalid"
DISCOVERY = "ARP-DiscoveryBot/0.1 (+research use; respects robots.txt)"


# ---- check-postgres -------------------------------------------------------------------------
def _report(current: bool) -> dict:
    return {"vector_extension": True, "applied_steps": [], "missing_tables": [], "missing_columns": [],
            "pending_steps": [], "drift": [], "unmatched_company_rows": {}, "current": current}


def _check(monkeypatch, dsn: str, current: bool):
    monkeypatch.setattr(db_cli, "get_settings", lambda: SimpleNamespace(postgres_dsn=dsn))
    monkeypatch.setattr("arp.storage.postgres_schema.schema_report", lambda _dsn: _report(current))
    return runner.invoke(db_cli.db_app, ["check-postgres"])


def test_ac1_ac2_ac4_current_hides_password(monkeypatch):
    res = _check(monkeypatch, DSN, True)
    assert res.exit_code == 0
    assert res.output.splitlines()[0] == "Postgres schema at postgresql+psycopg://arp:***@db.example:5432/arp:"
    assert "s3cr3t-pw" not in res.output


def test_ac3_ac4_not_current(monkeypatch):
    res = _check(monkeypatch, DSN, False)
    assert res.exit_code == 1
    assert "NOT current -- run `arp db init-postgres` to apply what's missing." in res.output
    assert "s3cr3t-pw" not in res.output


def test_ac5_no_password_unchanged(monkeypatch):
    res = _check(monkeypatch, "postgresql+psycopg://arp@db.example/arp", True)
    assert res.exit_code == 0
    assert res.output.splitlines()[0] == "Postgres schema at postgresql+psycopg://arp@db.example/arp:"


# ---- net_safety -----------------------------------------------------------------------------
def _literal_resolver(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, *a, **k: [(2, 1, 6, "", (host, 0))])


def _host(h: str) -> str:
    return h.strip("[]")


@pytest.mark.parametrize("host", ["100.64.0.0", "100.64.0.1", "100.100.100.200", "100.127.255.255",
                                  "[::ffff:100.64.0.1]", "[::ffff:100.100.100.200]"])
def test_ac6_cgnat_blocked(monkeypatch, host):
    _literal_resolver(monkeypatch)
    with pytest.raises(UnsafeURLError) as e:
        assert_safe_fetch_target(f"http://{host}/")
    assert str(e.value) == f"{_host(host)} resolves to a disallowed address ({_host(host)})"


@pytest.mark.parametrize("host", ["100.63.255.255", "100.128.0.0", "[::ffff:100.63.255.255]", "[::ffff:100.128.0.0]"])
def test_ac7_cgnat_neighbours_allowed(monkeypatch, host):
    _literal_resolver(monkeypatch)
    assert_safe_fetch_target(f"http://{host}/")


def test_ac8_mixed_resolution_blocked(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0)), (2, 1, 6, "", ("100.64.0.1", 0))])
    with pytest.raises(UnsafeURLError) as e:
        assert_safe_fetch_target("http://mixed.test/")
    assert str(e.value) == "mixed.test resolves to a disallowed address (100.64.0.1)"


@pytest.mark.parametrize("host", ["127.0.0.1", "10.0.0.1", "172.16.0.1", "192.168.1.1", "169.254.169.254", "192.0.0.8",
                                  "0.0.0.0", "224.0.0.1", "[::1]", "[fe80::1]", "[::ffff:127.0.0.1]", "[64:ff9b::a00:1]"])
def test_ac30_still_blocked(monkeypatch, host):
    _literal_resolver(monkeypatch)
    with pytest.raises(UnsafeURLError) as e:
        assert_safe_fetch_target(f"http://{host}/")
    assert str(e.value) == f"{_host(host)} resolves to a disallowed address ({_host(host)})"


@pytest.mark.parametrize("host", ["8.8.8.8", "1.1.1.1", "93.184.216.34", "192.0.0.9", "[2606:4700::1111]"])
def test_ac31_still_allowed(monkeypatch, host):
    _literal_resolver(monkeypatch)
    assert_safe_fetch_target(f"http://{host}/")


# ---- reindex object-store -------------------------------------------------------------------
HOSTS = {"sec.gov": "93.184.216.34", "www.sec.gov": "93.184.216.34", "example.org": "93.184.216.34",
         "www.sec.gov.evil.example": "93.184.216.34", "internal.test": "10.0.0.5"}


class Env:
    def __init__(self, monkeypatch, tmp_path):
        self.docs_dir = tmp_path / "documents"
        self.docs_dir.mkdir()
        self.requests: list[httpx.Request] = []
        self.responses: dict[str, list[httpx.Response]] = {}
        self.uploads: dict[str, bytes] = {}
        self.uri: dict[str, str] = {}
        self.docs: list[StoredDocumentRef] = []
        env = self
        settings = Settings(anthropic_api_key="unused", object_store_endpoint_url="http://store.test",
                            edgar_user_agent=EDGAR, discovery_user_agent=DISCOVERY, documents_dir=self.docs_dir)
        self.settings = settings
        monkeypatch.setattr(db_cli, "get_settings", lambda: settings)

        class Store:
            def list_all_documents(self_):
                return [dataclasses.replace(d, storage_uri=env.uri.get(d.doc_id, d.storage_uri)) for d in env.docs]

            def set_storage_uri(self_, doc_id, uri):
                env.uri[doc_id] = uri

        monkeypatch.setattr("arp.retrieval.content_store_factory.content_store_for", lambda s: Store())

        def fake_upload(config, key, data):
            env.uploads[key] = data
            return f"s3://b/{key}"

        monkeypatch.setattr("arp.storage.document_blob_store.upload_document", fake_upload)

        def gai(host, *a, **k):
            if host not in HOSTS:
                return [(2, 1, 6, "", (host, 0))]
            return [(2, 1, 6, "", (HOSTS[host], 0))]

        monkeypatch.setattr(socket, "getaddrinfo", gai)

        def handle(self_, request):
            env.requests.append(request)
            queue = env.responses.get(str(request.url)) or [httpx.Response(200, content=b"PDF")]
            return queue.pop(0) if len(queue) > 1 else queue[0]

        monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle)

    def doc(self, doc_id="d1", *, url=None, local=None, key="k", storage_uri=None):
        d = StoredDocumentRef(doc_id=doc_id, company_id="c", doc_type="t", content_key=key, title="t",
                              local_path=str(local) if local else None, source_url=url, storage_uri=storage_uri)
        self.docs.append(d)
        return d

    def run(self):
        res = runner.invoke(db_cli.db_app, ["reindex", "object-store"])
        self.res = res
        self.summary = res.stdout.strip().splitlines()[-1]
        return res


@pytest.fixture
def env(monkeypatch, tmp_path):
    return Env(monkeypatch, tmp_path)


def _summary(u, s, f):
    return f"Object-store backfill complete: uploaded={u} skipped={s} failed={f}."


def test_ac9_ac10_ac11_metadata_url(env):
    env.doc(url="http://169.254.169.254/latest/meta-data/")
    res = env.run()
    assert env.requests == []
    assert env.summary == _summary(0, 0, 1) and res.exit_code == 0
    assert "Failed to archive d1: 169.254.169.254 resolves to a disallowed address (169.254.169.254)" in res.stderr.splitlines()
    assert env.uploads == {}


@pytest.mark.parametrize("url,msg", [
    ("http://100.100.100.200/", "100.100.100.200 resolves to a disallowed address (100.100.100.200)"),
    ("file:///etc/passwd", "Unsupported URL scheme: 'file'"),
    ("http://internal.test/a.pdf", "internal.test resolves to a disallowed address (10.0.0.5)"),
])
def test_ac12_unsafe_urls(env, url, msg):
    env.doc(url=url)
    res = env.run()
    assert env.requests == [] and env.uploads == {} and res.exit_code == 0
    assert env.summary == _summary(0, 0, 1)
    assert f"Failed to archive d1: {msg}" in res.stderr.splitlines()


def test_ac13_ac14_redirect_to_metadata(env):
    env.docs.append(StoredDocumentRef("d1", "c", "t", "k", "t", None, "https://www.sec.gov/a"))
    env.responses["https://www.sec.gov/a"] = [httpx.Response(302, headers={"Location": "http://169.254.169.254/x"})]
    res = env.run()
    assert [r.url.host for r in env.requests] == ["www.sec.gov"]
    assert env.uploads == {}
    assert env.summary == _summary(0, 0, 1) and res.exit_code == 0


def test_ac16_ac17_mixed(env):
    env.doc("d1", url="http://169.254.169.254/x")
    env.doc("d2", url="http://100.100.100.200/")
    env.doc("d3", url="file:///etc/passwd")
    env.doc("d4", url="https://www.sec.gov/Archives/x.htm", key="k4")
    env.run()
    assert env.summary == _summary(1, 0, 3)
    assert env.uploads == {"k4": b"PDF"} and list(env.uri) == ["d4"]


def test_ac18_sec_ua(env):
    env.doc(url="https://www.sec.gov/Archives/x.htm")
    env.run()
    assert [r.headers["User-Agent"] for r in env.requests] == [EDGAR]


def test_ac19_other_host_ua(env):
    env.doc(url="https://example.org/a.pdf")
    env.run()
    assert [r.headers["User-Agent"] for r in env.requests] == [DISCOVERY]


def test_ac20_lookalike_host(env):
    env.doc(url="https://www.sec.gov.evil.example/a.pdf")
    env.run()
    ua = env.requests[0].headers["User-Agent"]
    assert ua == DISCOVERY and "test@example.invalid" not in ua


def test_ac21_sec_apex_and_case(env):
    env.doc("d1", url="https://sec.gov/a", key="k1")
    env.doc("d2", url="https://SEC.GOV/b", key="k2")
    env.run()
    assert [r.headers["User-Agent"] for r in env.requests] == [EDGAR, EDGAR]


def test_ac22_ua_per_hop(env):
    env.doc(url="https://www.sec.gov/a")
    env.responses["https://www.sec.gov/a"] = [httpx.Response(302, headers={"Location": "https://example.org/b"})]
    env.responses["https://example.org/b"] = [httpx.Response(200, content=b"x")]
    env.run()
    assert [r.headers["User-Agent"] for r in env.requests] == [EDGAR, DISCOVERY]
    assert env.summary == _summary(1, 0, 0)


def test_ac23_local_inside(env):
    f = env.docs_dir / "a.txt"
    f.write_bytes(b"inside")
    env.doc(local=f)
    env.run()
    assert env.uploads == {"k": b"inside"} and env.requests == []


def _outside(tmp_path):
    f = tmp_path / "outside.txt"
    f.write_bytes(b"outside")
    return f


def test_ac24_local_outside(env, tmp_path):
    env.doc(local=_outside(tmp_path))
    env.run()
    assert env.summary == _summary(0, 1, 0) and env.uploads == {}


def test_ac25_symlink_escape(env, tmp_path):
    link = env.docs_dir / "link.txt"
    link.symlink_to(_outside(tmp_path))
    env.doc(local=link)
    env.run()
    assert env.summary == _summary(0, 1, 0) and env.uploads == {}


def test_ac26a_dotdot(env, tmp_path):
    _outside(tmp_path)
    env.doc(local=env.docs_dir / ".." / "outside.txt")
    env.run()
    assert env.summary == _summary(0, 1, 0) and env.uploads == {}


def test_ac26_outside_falls_back_to_url(env, tmp_path):
    env.doc(local=_outside(tmp_path), url="https://www.sec.gov/a")
    env.responses["https://www.sec.gov/a"] = [httpx.Response(200, content=b"url")]
    env.run()
    assert env.uploads == {"k": b"url"} and env.summary == _summary(1, 0, 0)


def test_ac27_already_stored(env):
    env.doc(storage_uri="s3://b/k")
    env.run()
    assert env.summary == _summary(0, 1, 0) and env.requests == []


def test_ac28_nothing_to_read(env):
    env.doc()
    env.run()
    assert env.summary == _summary(0, 1, 0) and env.requests == []


def test_ac29_endpoint_unset(env, monkeypatch):
    s = env.settings.model_copy(update={"object_store_endpoint_url": None})
    monkeypatch.setattr(db_cli, "get_settings", lambda: s)
    res = runner.invoke(db_cli.db_app, ["reindex", "object-store"])
    assert res.exit_code == 1
    assert "ARP_OBJECT_STORE_ENDPOINT_URL is not set -- nothing to upload." in res.output
