"""Sign-in guard, users-file reload and /raw headers (spec signin-headers-containers, slice 1)."""

from __future__ import annotations

import json
import logging
import os

import pytest
from fastapi.testclient import TestClient

from arp.api.auth import load_users
from arp.api.deps import settings_dep
from arp.api.main import app
from arp.config import Settings, get_settings
from arp.errors import NotConfigured

M3 = ('ARP_AUTH_MODE=dev with "*" in ARP_ALLOWED_ORIGINS lets any website act as the dev approver. '
      "List the real origins in ARP_ALLOWED_ORIGINS, or set ARP_AUTH_MODE=local.")


@pytest.mark.parametrize("origins", ['["*"]', '["http://localhost:5173","*"]'])  # AC-1, AC-2, AC-3
def test_dev_mode_with_any_origin_refuses_to_start(monkeypatch, origins):
    monkeypatch.setenv("ARP_AUTH_MODE", "dev")
    monkeypatch.setenv("ARP_ALLOWED_ORIGINS", origins)
    monkeypatch.delenv("ARP_POSTGRES_DSN", raising=False)
    get_settings.cache_clear()
    try:
        Settings()  # AC-6: the settings themselves stay valid
        with pytest.raises(NotConfigured) as err, TestClient(app):
            pass
        assert str(err.value) == M3
    finally:
        get_settings.cache_clear()


def _users(path, *tokens, mtime_step=0):
    rows = [{"token": f"tok-{t}", "user_id": t, "name": t, "role": "viewer"} for t in tokens]
    before = path.stat().st_mtime_ns if path.exists() else 0
    path.write_text(json.dumps({"users": rows}))
    if mtime_step:
        os.utime(path, ns=(before + mtime_step, before + mtime_step))


def test_users_file_edits_apply_without_restart(tmp_path, caplog):  # AC-7 to AC-10
    path = tmp_path / "users.json"
    load_users.cache_clear()
    _users(path, "a")
    assert load_users(path)["tok-a"].user_id == "a"
    _users(path, "b", mtime_step=2_000_000_000)
    assert set(load_users(path)) == {"tok-b"}
    _users(path, "a", "b", mtime_step=2_000_000_000)
    assert set(load_users(path)) == {"tok-a", "tok-b"}

    before = path.stat().st_mtime_ns
    path.write_text("{not json")
    os.utime(path, ns=(before + 2_000_000_000,) * 2)
    with caplog.at_level(logging.ERROR, logger="arp.api.auth"):
        assert set(load_users(path)) == {"tok-a", "tok-b"}
        assert set(load_users(path)) == {"tok-a", "tok-b"}
        path.unlink()
        assert set(load_users(path)) == {"tok-a", "tok-b"}
    errors = [r.getMessage() for r in caplog.records if r.name == "arp.api.auth"]
    assert len(errors) == 2
    assert all(m.startswith("Users file ") and m.endswith("Still using the users from the last valid version.")
               and "tok-a" not in m for m in errors)
    load_users.cache_clear()
    with pytest.raises(NotConfigured, match="is missing or invalid"):  # AC-11, AC-12: no earlier good read
        load_users(path)


@pytest.fixture
def raw(tmp_path):
    folder = tmp_path / "docs" / "acme" / "other"
    folder.mkdir(parents=True)
    app.dependency_overrides[settings_dep] = lambda: Settings(documents_dir=tmp_path / "docs")

    def get(name, body=b"x"):
        (folder / name).write_bytes(body)
        return TestClient(app).get(f"/api/documents/acme/other/{name}/raw")

    yield get
    app.dependency_overrides.pop(settings_dep, None)


def test_raw_pdf_gets_nosniff_but_no_csp(raw):  # AC-13
    r = raw("report.pdf", b"%PDF-1.4")
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" not in r.headers
    assert r.headers["content-disposition"] == 'inline; filename="report.pdf"'


@pytest.mark.parametrize("name", ["page.html", "pic.svg", "data.xml", "notes.txt", "blob.bin"])  # AC-14, AC-15
def test_raw_other_files_are_sandboxed(raw, name):
    r = raw(name, b"<script>alert(1)</script>")
    assert r.status_code == 200 and r.content == b"<script>alert(1)</script>"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-security-policy"] == "sandbox"
    assert r.headers["content-disposition"] == f'inline; filename="{name}"'
