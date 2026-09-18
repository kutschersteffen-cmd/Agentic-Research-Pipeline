import httpx

from arp.discovery import academic_search as academic_search_module
from arp.discovery.academic_search import (
    ArxivSearchClient,
    CompositeSearchClient,
    SemanticScholarSearchClient,
    _parse_arxiv_atom,
    _parse_semantic_scholar_response,
)
from arp.discovery.site_finder import SearchResult, WebSearchClient

_SAMPLE_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1234.5678v1</id>
    <title>  Momentum
      Strategies in Equity Markets  </title>
    <summary>We study   momentum returns
      across global equity markets and find persistent outperformance.</summary>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/9999.0000v2</id>
    <title>Unrelated Physics Paper</title>
    <summary>No relevant summary here.</summary>
  </entry>
</feed>
"""

_SAMPLE_SEMANTIC_SCHOLAR_RESPONSE = {
    "data": [
        {
            "title": "Value and Momentum Everywhere",
            "url": "https://ssrn.com/abstract=1234",
            "venue": "Journal of Finance",
            "year": 2013,
            "abstract": "We find consistent value and momentum return premia in multiple asset classes.",
        },
        {
            "title": "No URL Paper",
            "url": None,
            "venue": "Somewhere",
            "year": 2020,
            "abstract": "Should be skipped.",
        },
    ]
}


class _FakeResponse:
    def __init__(self, *, text: str = "", json_data: dict | None = None, status_code: int = 200):
        self.text = text
        self._json_data = json_data or {}
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)

    def json(self):
        return self._json_data


class _FakeAsyncClient:
    """Records the last .get() call's url/params/headers and returns a
    pre-scripted response -- mirrors the monkeypatch-httpx.AsyncClient
    pattern already used in tests/test_source_fetch_cache.py."""

    last_instance: "_FakeAsyncClient | None" = None

    def __init__(self, *args, **kwargs):
        self.init_kwargs = kwargs
        self.last_get_url = None
        self.last_get_params = None
        _FakeAsyncClient.last_instance = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, url, params=None, **kwargs):
        self.last_get_url = url
        self.last_get_params = params
        return self._response

    _response: _FakeResponse = _FakeResponse()


def test_parse_arxiv_atom_extracts_and_cleans_entries():
    results = _parse_arxiv_atom(_SAMPLE_ATOM)
    assert len(results) == 2
    assert results[0].title == "Momentum Strategies in Equity Markets"
    assert results[0].url == "http://arxiv.org/abs/1234.5678v1"
    assert "momentum returns" in results[0].snippet
    assert results[1].title == "Unrelated Physics Paper"


def test_parse_arxiv_atom_empty_feed_returns_empty():
    empty = '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'
    assert _parse_arxiv_atom(empty) == []


async def test_arxiv_search_client_builds_category_restricted_query(monkeypatch):
    fake_client_cls = _FakeAsyncClient
    fake_client_cls._response = _FakeResponse(text=_SAMPLE_ATOM)
    monkeypatch.setattr(academic_search_module.httpx, "AsyncClient", fake_client_cls)

    client = ArxivSearchClient(categories=["q-fin.PM", "q-fin.ST"])
    results = await client.search("momentum anomaly", max_results=5)

    assert len(results) == 2
    sent_params = fake_client_cls.last_instance.last_get_params
    assert "cat:q-fin.PM" in sent_params["search_query"]
    assert "cat:q-fin.ST" in sent_params["search_query"]
    assert "all:momentum anomaly" in sent_params["search_query"]
    assert sent_params["max_results"] == 5


def test_parse_semantic_scholar_response_skips_entries_without_url():
    results = _parse_semantic_scholar_response(_SAMPLE_SEMANTIC_SCHOLAR_RESPONSE)
    assert len(results) == 1
    assert results[0].title == "Value and Momentum Everywhere"
    assert results[0].url == "https://ssrn.com/abstract=1234"
    assert "Journal of Finance 2013" in results[0].snippet
    assert "value and momentum return premia" in results[0].snippet


def test_parse_semantic_scholar_response_empty_data_returns_empty():
    assert _parse_semantic_scholar_response({"data": []}) == []
    assert _parse_semantic_scholar_response({}) == []


async def test_semantic_scholar_search_client_sends_api_key_header(monkeypatch):
    fake_client_cls = _FakeAsyncClient
    fake_client_cls._response = _FakeResponse(json_data=_SAMPLE_SEMANTIC_SCHOLAR_RESPONSE)
    monkeypatch.setattr(academic_search_module.httpx, "AsyncClient", fake_client_cls)

    client = SemanticScholarSearchClient(api_key="secret-key")
    results = await client.search("value premium", max_results=3)

    assert len(results) == 1
    assert fake_client_cls.last_instance.init_kwargs["headers"] == {"x-api-key": "secret-key"}


async def test_semantic_scholar_search_client_no_api_key_sends_no_header(monkeypatch):
    fake_client_cls = _FakeAsyncClient
    fake_client_cls._response = _FakeResponse(json_data={"data": []})
    monkeypatch.setattr(academic_search_module.httpx, "AsyncClient", fake_client_cls)

    client = SemanticScholarSearchClient()
    await client.search("value premium")
    assert fake_client_cls.last_instance.init_kwargs["headers"] == {}


class _StubSearchClient(WebSearchClient):
    def __init__(self, results: list[SearchResult], raises: bool = False):
        self._results = results
        self._raises = raises
        self.calls: list[str] = []

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        self.calls.append(query)
        if self._raises:
            raise RuntimeError("simulated search failure")
        return self._results[:max_results]


async def test_composite_search_client_merges_and_dedupes_by_url():
    client_a = _StubSearchClient([SearchResult(title="A", url="https://x.com/1"), SearchResult(title="B", url="https://x.com/2")])
    client_b = _StubSearchClient([SearchResult(title="B dup", url="https://x.com/2"), SearchResult(title="C", url="https://x.com/3")])
    composite = CompositeSearchClient([client_a, client_b])

    results = await composite.search("momentum", max_results=10)
    urls = [r.url for r in results]
    assert urls == ["https://x.com/1", "https://x.com/2", "https://x.com/3"]
    assert client_a.calls == ["momentum"]
    assert client_b.calls == ["momentum"]


async def test_composite_search_client_skips_a_failing_client():
    failing = _StubSearchClient([], raises=True)
    working = _StubSearchClient([SearchResult(title="ok", url="https://x.com/1")])
    composite = CompositeSearchClient([failing, working])

    results = await composite.search("momentum")
    assert len(results) == 1
    assert results[0].url == "https://x.com/1"


async def test_composite_search_client_respects_max_results_on_merged_total():
    client_a = _StubSearchClient([SearchResult(title="A", url=f"https://x.com/{i}") for i in range(5)])
    client_b = _StubSearchClient([SearchResult(title="B", url=f"https://y.com/{i}") for i in range(5)])
    composite = CompositeSearchClient([client_a, client_b])

    results = await composite.search("momentum", max_results=3)
    assert len(results) == 3
