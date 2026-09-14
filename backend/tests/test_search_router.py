import os

import pytest

from arp.api.routers.search import _map_hit, _search_one_index, _snippet_from_highlight, search
from arp.schemas.search import SearchResultType


def _raw_hit(source, score=1.0, highlight=None):
    row = {"_score": score, "_source": source}
    if highlight is not None:
        row["highlight"] = highlight
    return row


def test_snippet_from_highlight_strips_em_tags():
    assert _snippet_from_highlight({"title": ["<em>Annual</em> Report"]}) == "Annual Report"


def test_snippet_from_highlight_empty_when_no_highlight():
    assert _snippet_from_highlight({}) == ""


def test_map_hit_document_with_company_id():
    raw = _raw_hit({"doc_id": "doc_1", "company_id": "acme", "title": "Annual Report"}, highlight={"title": ["<em>Annual</em> Report"]})
    hit = _map_hit(SearchResultType.DOCUMENT, raw)
    assert hit.id == "doc_1"
    assert hit.company_id == "acme"
    assert hit.link == "/api/documents/acme"
    assert hit.snippet == "Annual Report"


def test_map_hit_document_without_company_id_has_no_link():
    raw = _raw_hit({"doc_id": "doc_1", "title": "Untitled"})
    hit = _map_hit(SearchResultType.DOCUMENT, raw)
    assert hit.company_id is None
    assert hit.link is None
    assert hit.snippet == ""


def test_map_hit_company():
    raw = _raw_hit({"company_id": "acme", "name": "Acme Corp"})
    hit = _map_hit(SearchResultType.COMPANY, raw)
    assert hit.id == "acme"
    assert hit.title == "Acme Corp"
    assert hit.link == "/api/documents/acme"


def test_map_hit_taxonomy():
    raw = _raw_hit({"entry_id": "e1", "label": "Electrification", "taxonomy_id": "tax_1"})
    hit = _map_hit(SearchResultType.TAXONOMY, raw)
    assert hit.id == "e1"
    assert hit.company_id is None
    assert hit.link == "/api/taxonomies/tax_1"


class _FakeClient:
    def __init__(self, response):
        self._response = response

    def search(self, index, body):
        self.last_index = index
        self.last_body = body
        return self._response


def test_search_one_index_returns_mapped_hits():
    client = _FakeClient({"hits": {"hits": [_raw_hit({"doc_id": "d1", "company_id": "acme", "title": "A"})]}})
    hits = _search_one_index(client, SearchResultType.DOCUMENT, "q", 20)
    assert len(hits) == 1
    assert client.last_index == "arp-documents"


def test_search_defaults_types_to_document_only():
    client = _FakeClient({"hits": {"hits": []}})
    response = search(q="green capex", types=None, limit=20, client=client)
    assert response.query == "green capex"
    assert client.last_index == "arp-documents"


def test_search_queries_each_requested_type():
    calls = []

    class RecordingClient:
        def search(self, index, body):
            calls.append(index)
            return {"hits": {"hits": []}}

    search(q="x", types=[SearchResultType.DOCUMENT, SearchResultType.COMPANY], limit=20, client=RecordingClient())
    assert calls == ["arp-documents", "arp-companies"]


def test_search_sorts_by_score_and_truncates_to_limit():
    class MultiHitClient:
        def search(self, index, body):
            return {
                "hits": {
                    "hits": [
                        _raw_hit({"doc_id": "low", "title": "low"}, score=0.5),
                        _raw_hit({"doc_id": "high", "title": "high"}, score=9.0),
                    ]
                }
            }

    response = search(q="x", types=[SearchResultType.DOCUMENT], limit=1, client=MultiHitClient())
    assert response.total == 1
    assert response.hits[0].id == "high"


@pytest.mark.skipif(not os.environ.get("ARP_TEST_OPENSEARCH_URL"), reason="set ARP_TEST_OPENSEARCH_URL to run against a real OpenSearch instance")
def test_search_against_a_real_opensearch_instance():
    """Opt-in integration test, mirrors test_postgres_portfolio_store.py's
    ARP_TEST_POSTGRES_DSN-gated pattern -- indexes a document into a real
    cluster, searches for it, cleans up afterwards."""
    from arp.storage.opensearch_client import ensure_indices, get_client

    url = os.environ["ARP_TEST_OPENSEARCH_URL"]
    ensure_indices(url)
    client = get_client(url)
    client.index(index="arp-documents", id="test_doc_1", body={"doc_id": "test_doc_1", "company_id": "test_co", "title": "Integration Test Filing"}, refresh=True)
    try:
        response = search(q="Integration Test", types=[SearchResultType.DOCUMENT], limit=10, client=client)
        assert any(h.id == "test_doc_1" for h in response.hits)
    finally:
        client.delete(index="arp-documents", id="test_doc_1", ignore=[404])
