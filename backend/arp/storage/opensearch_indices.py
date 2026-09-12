"""Index mappings for the opt-in OpenSearch store (see opensearch_client.py),
kept in their own module so they're reviewable independently of the client
plumbing -- the same separation postgres_models.py has from postgres.py.

Every index is addressed through a stable alias (e.g. "arp-chunks"), never
through its versioned physical index name (e.g. "arp-chunks-v1"): a future
mapping or embedding-model change creates a new physical index, backfills
it, and atomically re-points the alias (opensearch_client.ensure_indices
only creates index v1 today; a v2 migration is a separate, explicit step,
not something this module needs to anticipate further than leaving the
alias indirection in place). Application code should always query the
alias name below, never `f"{alias}-v1"` directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from arp.retrieval.embeddings import EMBED_DIM


@dataclass(frozen=True)
class IndexDefinition:
    alias: str
    mappings: dict
    settings: dict = field(default_factory=dict)


COMPANIES = IndexDefinition(
    alias="arp-companies",
    mappings={
        "properties": {
            "company_id": {"type": "keyword"},
            "name": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "ticker": {"type": "keyword"},
            "sector": {"type": "keyword"},
            "country": {"type": "keyword"},
            "isic_code": {"type": "keyword"},
        }
    },
)

DOCUMENTS = IndexDefinition(
    alias="arp-documents",
    mappings={
        "properties": {
            "doc_id": {"type": "keyword"},
            "company_id": {"type": "keyword"},
            "doc_type": {"type": "keyword"},
            "title": {"type": "text"},
            "source_url": {"type": "keyword"},
            "local_path": {"type": "keyword"},
            "storage_uri": {"type": "keyword"},
            "first_seen_at": {"type": "date"},
            "last_seen_at": {"type": "date"},
        }
    },
)

CHUNKS = IndexDefinition(
    alias="arp-chunks",
    mappings={
        "properties": {
            "chunk_id": {"type": "keyword"},
            "doc_id": {"type": "keyword"},
            "company_id": {"type": "keyword"},
            "doc_type": {"type": "keyword"},
            "text": {"type": "text", "analyzer": "standard"},
            "char_start": {"type": "integer"},
            "char_end": {"type": "integer"},
            "embedding": {
                "type": "knn_vector",
                "dimension": EMBED_DIM,
                "method": {"name": "hnsw", "space_type": "cosinesimil", "engine": "nmslib"},
            },
        }
    },
    settings={"index.knn": True},
)

TAXONOMY = IndexDefinition(
    alias="arp-taxonomy",
    mappings={
        "properties": {
            "taxonomy_id": {"type": "keyword"},
            "version": {"type": "keyword"},
            "entry_id": {"type": "keyword"},
            "label": {"type": "text"},
            "description": {"type": "text"},
            "keywords": {"type": "text"},
        }
    },
)

INDEX_DEFINITIONS: tuple[IndexDefinition, ...] = (COMPANIES, DOCUMENTS, CHUNKS, TAXONOMY)
