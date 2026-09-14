"""User-facing search across companies, documents, and taxonomy entries --
a thin fan-out over the opt-in OpenSearch indices (arp/storage/
opensearch_indices.py), populated by arp/retrieval/search_indexer.py's
live/backfill indexing. Returns a clean 503 (via get_opensearch_client_or_503
-> the global RuntimeError handler in arp/api/main.py) if OpenSearch isn't
configured, rather than a silent degraded fallback -- consistent with how
every other opt-in backend in this codebase states its prerequisite
plainly.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Query

from arp.api.deps import get_opensearch_client_or_503
from arp.schemas.search import SearchHit, SearchResponse, SearchResultType

router = APIRouter(prefix="/api/search", tags=["search"])

_INDEX_FOR_TYPE = {
    SearchResultType.COMPANY: "arp-companies",
    SearchResultType.DOCUMENT: "arp-documents",
    SearchResultType.TAXONOMY: "arp-taxonomy",
}
# Boosted fields per index: name/title/label weighted over the rest.
_FIELDS_FOR_TYPE = {
    SearchResultType.COMPANY: ["name^3", "ticker", "sector", "country"],
    SearchResultType.DOCUMENT: ["title^3", "doc_type"],
    SearchResultType.TAXONOMY: ["label^3", "description", "keywords"],
}

# arp-companies and arp-taxonomy have mappings (arp db init-opensearch
# creates their aliases) but no indexer populates them yet -- only
# arp-documents/arp-chunks are written to today (search_indexer.py). A
# query against them is harmless (0 hits, not an error), so this only
# affects the zero-config default: narrower but correct today, rather than
# "all three" silently looking broken for 2/3 of them. Widen this default
# once a company/taxonomy indexer exists (# TODO(phase-2b)).
_DEFAULT_TYPES = [SearchResultType.DOCUMENT]

_TAG_RE = re.compile(r"</?em>")


@router.get("", response_model=SearchResponse)
def search(
    q: str = Query(..., min_length=1),
    types: list[SearchResultType] | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    client=Depends(get_opensearch_client_or_503),
) -> SearchResponse:
    selected_types = types or _DEFAULT_TYPES
    hits: list[SearchHit] = []
    for result_type in selected_types:
        hits.extend(_search_one_index(client, result_type, q, limit))
    hits.sort(key=lambda h: h.score, reverse=True)
    hits = hits[:limit]
    return SearchResponse(query=q, total=len(hits), hits=hits)


def _search_one_index(client, result_type: SearchResultType, q: str, limit: int) -> list[SearchHit]:
    index = _INDEX_FOR_TYPE[result_type]
    fields = _FIELDS_FOR_TYPE[result_type]
    body = {
        "query": {"multi_match": {"query": q, "fields": fields}},
        "highlight": {"fields": dict.fromkeys(fields, {})},
        "size": limit,
    }
    response = client.search(index=index, body=body)
    return [_map_hit(result_type, raw) for raw in response["hits"]["hits"]]


def _snippet_from_highlight(highlight: dict) -> str:
    for fragments in highlight.values():
        if fragments:
            return _TAG_RE.sub("", fragments[0])
    return ""


def _map_hit(result_type: SearchResultType, raw: dict) -> SearchHit:
    source = raw["_source"]
    snippet = _snippet_from_highlight(raw.get("highlight", {}))
    score = raw["_score"]

    if result_type is SearchResultType.COMPANY:
        company_id = source["company_id"]
        return SearchHit(
            type=result_type, id=company_id, title=source["name"], snippet=snippet, score=score,
            company_id=company_id, link=f"/api/documents/{company_id}",
        )
    if result_type is SearchResultType.DOCUMENT:
        company_id = source.get("company_id")
        return SearchHit(
            type=result_type, id=source["doc_id"], title=source.get("title") or source["doc_id"], snippet=snippet,
            score=score, company_id=company_id, link=f"/api/documents/{company_id}" if company_id else None,
        )
    # TAXONOMY
    taxonomy_id = source.get("taxonomy_id")
    return SearchHit(
        type=result_type, id=source["entry_id"], title=source.get("label") or source["entry_id"], snippet=snippet,
        score=score, company_id=None, link=f"/api/taxonomies/{taxonomy_id}" if taxonomy_id else None,
    )
