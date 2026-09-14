import pytest

from arp.api import deps
from arp.storage.opensearch_client import OpenSearchNotConfigured


class _FakeSettings:
    def __init__(self, opensearch_url):
        self.opensearch_url = opensearch_url


def test_raises_when_opensearch_url_unset(monkeypatch):
    monkeypatch.setattr(deps, "get_settings", lambda: _FakeSettings(None))

    with pytest.raises(OpenSearchNotConfigured):
        deps.get_opensearch_client_or_503()


def test_returns_client_when_configured(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(deps, "get_settings", lambda: _FakeSettings("http://localhost:9200"))
    monkeypatch.setattr(deps, "get_opensearch_client", lambda url: sentinel if url == "http://localhost:9200" else None)

    assert deps.get_opensearch_client_or_503() is sentinel
