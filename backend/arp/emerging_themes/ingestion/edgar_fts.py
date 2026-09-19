from __future__ import annotations

import logging
from datetime import datetime

import httpx

from arp.emerging_themes.ingestion.base import MentionSource
from arp.schemas.emerging_themes import MentionSourceType, RawMention

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"

# A broad, generic seed list of "notable business event" phrases -- not a
# thematic keyword list (that would defeat the bottom-up point of this
# tool). Phase 2 closes the loop properly: query terms become the Detect
# layer's own current top cluster terms instead of this fixed seed list,
# so EDGAR filings can corroborate a theme GDELT/RSS already flagged. See
# docs: this is a documented Phase 1 simplification, not the target design.
_DEFAULT_QUERY_TERMS = [
    "strategic partnership",
    "definitive agreement",
    "commercial launch",
    "regulatory approval",
    "capacity expansion",
]


class EdgarFullTextSearchSource(MentionSource):
    """SEC EDGAR's full-text search API (efts.sec.gov) -- free, no key,
    real-time coverage of all US filings. Distinct job from
    `ingestion/edgar.py::EdgarDocumentSource`, which fetches a *specific*
    company's 10-K/DEF-14A once you already know what to look for; this
    one searches *across every filer* for a query term, which is what
    discovery (as opposed to extraction) needs.
    """

    name = "edgar_fts"

    def __init__(self, user_agent: str, query_terms: list[str] | None = None, forms: str | None = None) -> None:
        self._user_agent = user_agent
        self._query_terms = query_terms or _DEFAULT_QUERY_TERMS
        self._forms = forms

    async def fetch(self, since: datetime) -> list[RawMention]:
        mentions: list[RawMention] = []
        async with httpx.AsyncClient(headers={"User-Agent": self._user_agent}, timeout=30.0) as client:
            for term in self._query_terms:
                params = {
                    "q": f'"{term}"',
                    "dateRange": "custom",
                    "startdt": since.date().isoformat(),
                    "enddt": datetime.utcnow().date().isoformat(),
                }
                if self._forms:
                    params["forms"] = self._forms
                try:
                    resp = await client.get(_SEARCH_URL, params=params)
                    resp.raise_for_status()
                    payload = resp.json()
                except (httpx.HTTPError, ValueError) as exc:
                    logger.warning("EDGAR full-text search failed for %r: %s", term, exc)
                    continue
                mentions.extend(self._parse_hits(payload, term))
        return mentions

    @staticmethod
    def _parse_hits(payload: dict, query_term: str) -> list[RawMention]:
        hits = payload.get("hits", {}).get("hits", [])
        mentions: list[RawMention] = []
        for hit in hits:
            source = hit.get("_source", {})
            display_names = source.get("display_names", [])
            adsh = source.get("adsh", "")
            ciks = source.get("ciks", [])
            cik = ciks[0].lstrip("0") if ciks else None
            accession_nodash = adsh.replace("-", "")
            url = (
                f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodash}/{adsh}-index.htm"
                if cik and adsh
                else "https://www.sec.gov/cgi-bin/browse-edgar"
            )
            highlight_fragments = [frag for values in hit.get("highlight", {}).values() for frag in values]
            root_forms = source.get("root_forms") or []
            form = root_forms[0] if root_forms else source.get("file_type", "filing")
            title = f"{form} filed by {', '.join(display_names) or 'unknown filer'}".strip()
            text = " ".join(highlight_fragments) if highlight_fragments else f"Matched search term '{query_term}' in a {form} filing by {', '.join(display_names)}."
            mentions.append(
                RawMention(
                    source_type=MentionSourceType.EDGAR_FTS,
                    title=title,
                    text=text,
                    url=url,
                    raw_entity_names=[n.split(" (CIK")[0].strip() for n in display_names],
                    published_at=source.get("file_date"),
                )
            )
        return mentions
