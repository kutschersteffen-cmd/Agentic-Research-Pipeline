"""Lazy OpenSearch client (arp/storage/opensearch_indices.py for the index
mappings this creates), gated entirely on Settings.opensearch_url --
mirrors arp/storage/postgres.py's exact pattern (same lazy-import-on-first-
use contract, same "not configured" vs "extra not installed" exception
split) so a deployment that never sets ARP_OPENSEARCH_URL never needs
opensearch-py installed, let alone imported.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from opensearchpy import OpenSearch


class OpenSearchNotConfigured(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "Settings.opensearch_url is not set -- the user-facing search feature and the 'opensearch' "
            "retrieval_backend option are entirely opt-in. Set ARP_OPENSEARCH_URL (e.g. http://localhost:9200) "
            "to enable them. BM25/hybrid retrieval and every other feature are unaffected either way."
        )


class OpenSearchExtraNotInstalled(RuntimeError):
    def __init__(self, exc: Exception) -> None:
        super().__init__(
            "opensearch_url is set but opensearch-py isn't installed. Install the optional extra: "
            f"pip install -e '.[opensearch]'. Original import error: {exc}"
        )


@lru_cache
def get_client(url: str) -> OpenSearch:
    """One cached client per URL for the process lifetime, matching
    postgres.get_engine's one-Engine-per-DSN pattern. Imports opensearch-py
    lazily so the rest of this codebase never pays an import cost, let
    alone a hard dependency, for a store nobody has opted into."""
    try:
        from opensearchpy import OpenSearch
    except ImportError as exc:  # pragma: no cover - exercised only without the optional extra
        raise OpenSearchExtraNotInstalled(exc) from exc
    return OpenSearch(hosts=[url], http_compress=True)


def ensure_indices(url: str) -> None:
    """Creates every index (behind its stable alias) this codebase defines,
    idempotently -- mirrors postgres.ensure_schema's create-if-missing
    contract. Call once per fresh cluster (`arp db init-opensearch`), not
    per request."""
    from opensearchpy.exceptions import RequestError

    from arp.storage.opensearch_indices import INDEX_DEFINITIONS

    client = get_client(url)
    for definition in INDEX_DEFINITIONS:
        physical_index = f"{definition.alias}-v1"
        try:
            client.indices.create(
                index=physical_index,
                body={"mappings": definition.mappings, "settings": definition.settings},
            )
        except RequestError as exc:
            if exc.error != "resource_already_exists_exception":
                raise
        else:
            client.indices.put_alias(index=physical_index, name=definition.alias)
