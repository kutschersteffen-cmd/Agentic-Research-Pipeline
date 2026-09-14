import json

import httpx

from arp.research.taxonomy_sources import fetch as fetch_module
from arp.research.taxonomy_sources.fetch import _cache_paths, fetch_source_original


async def test_fetch_source_original_returns_cached_bytes_without_network(tmp_path):
    url = "https://iea.org/report.pdf"
    content_path, meta_path = _cache_paths(tmp_path, url)
    content_path.write_bytes(b"%PDF-1.4 fake pdf content")
    meta_path.write_text(json.dumps({"content_type": "application/pdf", "url": url}))

    # user_agent is irrelevant here since the cache hit must short-circuit
    # before any httpx call is made -- if this test reaches the network it
    # will hang/fail in a sandboxed environment, which is exactly what it's
    # checking against.
    result = await fetch_source_original(url, "test-agent", tmp_path)
    assert result is not None
    content, content_type = result
    assert content == b"%PDF-1.4 fake pdf content"
    assert content_type == "application/pdf"


async def test_corrupted_cache_entry_is_not_fatal(tmp_path, monkeypatch):
    url = "https://iea.org/report.pdf"
    content_path, meta_path = _cache_paths(tmp_path, url)
    content_path.write_bytes(b"stale")
    meta_path.write_text("not valid json")

    class _FailingClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def get(self, *args, **kwargs):
            raise httpx.ConnectError("simulated network failure")

    monkeypatch.setattr(fetch_module.httpx, "AsyncClient", _FailingClient)

    # Falls through to a fetch attempt (network mocked to fail immediately)
    # -- confirming the corrupt cache entry doesn't raise on its own, it
    # just falls back to a real fetch, which then fails cleanly.
    result = await fetch_source_original(url, "test-agent", tmp_path)
    assert result is None
