"""superset/superset_config.py refuses unset, placeholder and short secrets.
Loaded from its file path; it imports only `os`, so no Superset needed."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

CONFIG = Path(__file__).resolve().parents[2] / "superset" / "superset_config.py"
GOOD = "x" * 32


def _load(monkeypatch, **env):
    base = {
        "SUPERSET_SECRET_KEY": GOOD,
        "SUPERSET_GUEST_TOKEN_JWT_SECRET": GOOD,
        "SUPERSET_DATABASE_URI": "postgresql://h/superset",
    }
    for k, v in {**base, **env}.items():
        monkeypatch.setenv(k, v)
    spec = importlib.util.spec_from_file_location("superset_config", CONFIG)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_valid_env_loads(monkeypatch):
    assert _load(monkeypatch).SECRET_KEY == GOOD


@pytest.mark.parametrize(
    "name,value",
    [
        ("SUPERSET_SECRET_KEY", ""),
        ("SUPERSET_SECRET_KEY", "CHANGE_ME_SECRET_KEY"),
        ("SUPERSET_SECRET_KEY", "change-me-dev-only"),
        ("SUPERSET_SECRET_KEY", "x" * 31),
        ("SUPERSET_GUEST_TOKEN_JWT_SECRET", "test-guest-secret-change-me"),
        ("SUPERSET_GUEST_TOKEN_JWT_SECRET", "short"),
    ],
)
def test_bad_secret_refuses_to_load(monkeypatch, name, value):
    with pytest.raises(RuntimeError, match="openssl rand"):
        _load(monkeypatch, **{name: value})


def test_designer_password_placeholder_rejected(monkeypatch):
    config = _load(monkeypatch)
    monkeypatch.setenv("ARP_SUPERSET_PASSWORD", "change-me-dev-only")
    with pytest.raises(RuntimeError):
        config.required("ARP_SUPERSET_PASSWORD")
    monkeypatch.setenv("ARP_SUPERSET_PASSWORD", "a-real-password")
    assert config.required("ARP_SUPERSET_PASSWORD") == "a-real-password"


def test_embeddable_from_the_cross_origin_isolated_ui(monkeypatch):
    """The ARP UI sends COEP require-corp; without these Chrome blocks the iframe
    (ERR_BLOCKED_BY_RESPONSE, CorpNotSameOriginAfterDefaultedToSameOriginByCoep)."""
    headers = _load(monkeypatch).OVERRIDE_HTTP_HEADERS
    assert headers["Cross-Origin-Resource-Policy"] == "cross-origin"
    assert headers["Cross-Origin-Embedder-Policy"] in {"require-corp", "credentialless"}
    ancestors = _load(monkeypatch).TALISMAN_CONFIG["content_security_policy"]["frame-ancestors"]
    assert {"http://localhost:5173", "http://127.0.0.1:5173"} <= set(ancestors)  # the origins CORS allows
