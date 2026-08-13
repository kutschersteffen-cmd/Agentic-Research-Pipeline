import httpx
import pytest

from arp.discovery import crawler as crawler_module
from arp.discovery.crawler import CrawlConfig, HomepageUnreachableError, crawl_for_documents


class _FakeResponse:
    def __init__(self, status_code=200, text="", content_type="text/html"):
        self.status_code = status_code
        self.text = text
        self.headers = {"content-type": content_type}


class _FakeClient:
    def __init__(self, get_impl):
        self._get_impl = get_impl

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, url, *args, **kwargs):
        return await self._get_impl(url)


def _client_factory(get_impl):
    def factory(*args, **kwargs):
        return _FakeClient(get_impl)

    return factory


async def test_root_network_error_raises_homepage_unreachable(monkeypatch):
    async def get_impl(url):
        if url.endswith("robots.txt"):
            return _FakeResponse(status_code=404)
        raise httpx.ConnectError("simulated proxy 403/connect failure")

    monkeypatch.setattr(crawler_module.httpx, "AsyncClient", _client_factory(get_impl))

    with pytest.raises(HomepageUnreachableError):
        await crawl_for_documents("https://acme.example/", CrawlConfig(user_agent="test", request_delay_seconds=0))


async def test_root_error_status_raises_homepage_unreachable(monkeypatch):
    async def get_impl(url):
        if url.endswith("robots.txt"):
            return _FakeResponse(status_code=404)
        return _FakeResponse(status_code=503)

    monkeypatch.setattr(crawler_module.httpx, "AsyncClient", _client_factory(get_impl))

    with pytest.raises(HomepageUnreachableError):
        await crawl_for_documents("https://acme.example/", CrawlConfig(user_agent="test", request_delay_seconds=0))


async def test_non_root_fetch_failure_is_silently_skipped(monkeypatch):
    root = "https://acme.example/"
    broken_link = "https://acme.example/broken"
    root_html = (
        f'<a href="{broken_link}">Other page</a>'
        '<a href="/reports/annual-report-2025.pdf">Annual Report</a>'
    )

    async def get_impl(url):
        if url.endswith("robots.txt"):
            return _FakeResponse(status_code=404)
        if url == root:
            return _FakeResponse(status_code=200, text=root_html)
        if url == broken_link:
            raise httpx.ConnectError("simulated failure on a deeper, non-root page")
        raise AssertionError(f"unexpected url fetched: {url}")

    monkeypatch.setattr(crawler_module.httpx, "AsyncClient", _client_factory(get_impl))

    results = await crawl_for_documents(root, CrawlConfig(user_agent="test", request_delay_seconds=0))

    assert len(results) == 1
    assert results[0].url.endswith("annual-report-2025.pdf")
