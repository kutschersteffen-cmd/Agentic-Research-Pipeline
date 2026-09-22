"""CLI-side names for the store and document-source builders.

Every one of these was a hand-written copy of the matching `get_*` in
`arp/api/deps.py`, so the same ten constructions lived in two places and
had to be kept in step by hand. They are now aliases of those builders --
which is what this module already did for `portfolio_directories`.

`api/deps.py` imports no FastAPI, only `lru_cache` and `arp.*`, so the
dependency direction costs the CLI nothing; the `Depends()` wiring lives
in the routers, not in the builders. The CLI also picks up their
`@lru_cache`, which for a one-shot process means each store is built once
instead of once per call site.

The `_`-prefixed names are kept because twelve `arp/cli/*.py` modules
import them by those names.
"""

from __future__ import annotations

import typer

from arp.api.deps import (
    get_ballot_platform,
    get_document_content_store,
    get_engagement_store,
    get_portfolio_store,
    get_registry,
    get_reporting_store,
    get_run_store,
    get_taxonomy_store,
    get_topic_store,
    get_xbrl_source,
)
from arp.schemas.taxonomy import TaxonomyRef
from arp.storage.portfolio_store import portfolio_directories

_ballot_platform = get_ballot_platform
_document_content_store = get_document_content_store
_engagement_store = get_engagement_store
_portfolio_directories = portfolio_directories
_portfolio_store = get_portfolio_store
_registry = get_registry
_reporting_store = get_reporting_store
_run_store = get_run_store
_taxonomy_store = get_taxonomy_store
_topic_store = get_topic_store

# Composes on deps.get_edgar_source()'s single EdgarDocumentSource, the way
# the API does, rather than building a throwaway one: the CLI copy used to
# construct its own, so `arp extraction`/`arp emerging-themes` each paid a
# separate CIK ticker-map fetch that the API instance had already cached.
_xbrl_source = get_xbrl_source


def _parse_taxonomy_ref(ref: str) -> TaxonomyRef:
    """Parses 'tax_xxx' or 'tax_xxx:3' (id, or id:version)."""
    if ":" in ref:
        taxonomy_id, version_str = ref.rsplit(":", 1)
        return TaxonomyRef(taxonomy_id=taxonomy_id, version=int(version_str))
    return TaxonomyRef(taxonomy_id=ref, version=None)


def _resolve_taxonomy_ref_or_exit(ref_str: str):
    store = _taxonomy_store()
    ref = _parse_taxonomy_ref(ref_str)
    taxonomy = store.get(ref.taxonomy_id, ref.version)
    if taxonomy is None:
        typer.echo(f"Taxonomy not found: {ref_str}", err=True)
        raise typer.Exit(1)
    return taxonomy
