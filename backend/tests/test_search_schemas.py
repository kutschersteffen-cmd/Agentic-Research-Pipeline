import pytest
from pydantic import ValidationError

from arp.schemas.search import SearchHit, SearchResponse, SearchResultType


def test_search_hit_round_trips():
    hit = SearchHit(type=SearchResultType.DOCUMENT, id="doc_1", title="Annual Report", score=1.5, company_id="acme", link="/api/documents/acme")
    dumped = hit.model_dump()
    assert dumped["type"] == "document"
    assert SearchHit.model_validate(dumped) == hit


def test_search_hit_defaults():
    hit = SearchHit(type=SearchResultType.TAXONOMY, id="entry_1", title="Electrification", score=0.5)
    assert hit.snippet == ""
    assert hit.company_id is None
    assert hit.link is None


def test_search_result_type_rejects_invalid_value():
    with pytest.raises(ValidationError):
        SearchHit(type="not_a_real_type", id="x", title="x", score=0.0)


def test_search_response_defaults_to_empty_hits():
    response = SearchResponse(query="green capex", total=0)
    assert response.hits == []
