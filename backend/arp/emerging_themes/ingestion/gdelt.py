from __future__ import annotations

import logging
from datetime import datetime

import httpx

from arp.emerging_themes.ingestion.base import MentionSource
from arp.schemas.emerging_themes import MentionSourceType, RawMention

logger = logging.getLogger(__name__)

_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

# Broad global-news query terms -- see edgar_fts.py's _DEFAULT_QUERY_TERMS
# docstring for why these are generic rather than thematic, and the same
# Phase 2 note about closing the loop with the Detect layer's own terms.
_DEFAULT_QUERY_TERMS = [
    "emerging technology investment",
    "supply chain shift",
    "new regulation industry",
    "market disruption",
]


class GdeltSource(MentionSource):
    """GDELT DOC 2.0 API -- free, no key, real-time global news coverage
    with tone/entity tagging. The source plan's primary volume/velocity
    signal.

    Known limitation, documented rather than silently worked around: the
    DOC 2.0 `artlist` mode returns article metadata (title, url, domain,
    seendate) but not body text or even a snippet, so `RawMention.text`
    here is the headline alone -- thinner material for the Extract layer
    to ground a claim/quote against than a real snippet. `seendate` is
    closer to crawl time than true publication time, same caveat as any
    web-crawled feed.
    """

    name = "gdelt"

    def __init__(self, query_terms: list[str] | None = None, max_records: int = 75) -> None:
        self._query_terms = query_terms or _DEFAULT_QUERY_TERMS
        self._max_records = max_records

    async def fetch(self, since: datetime) -> list[RawMention]:
        mentions: list[RawMention] = []
        start = since.strftime("%Y%m%d%H%M%S")
        end = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        async with httpx.AsyncClient(timeout=30.0) as client:
            for term in self._query_terms:
                params = {
                    "query": term,
                    "mode": "artlist",
                    "format": "json",
                    "maxrecords": str(self._max_records),
                    "sort": "hybridrel",
                    "startdatetime": start,
                    "enddatetime": end,
                }
                try:
                    resp = await client.get(_DOC_URL, params=params)
                    resp.raise_for_status()
                    payload = resp.json()
                except (httpx.HTTPError, ValueError) as exc:
                    logger.warning("GDELT query failed for %r: %s", term, exc)
                    continue
                mentions.extend(self._parse_articles(payload))
        return mentions

    @staticmethod
    def _parse_articles(payload: dict) -> list[RawMention]:
        articles = payload.get("articles", [])
        mentions: list[RawMention] = []
        for article in articles:
            title = article.get("title", "").strip()
            url = article.get("url", "")
            if not title or not url:
                continue
            mentions.append(
                RawMention(
                    source_type=MentionSourceType.GDELT,
                    title=title,
                    text=title,
                    url=url,
                    published_at=None,  # seendate is crawl time, not true publish time -- see class docstring
                )
            )
        return mentions
