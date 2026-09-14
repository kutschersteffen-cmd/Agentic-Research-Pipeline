from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx

from arp.emerging_themes.ingestion.base import MentionSource
from arp.schemas.emerging_themes import MentionSourceType, RawMention

logger = logging.getLogger(__name__)

# Official press/rule-release feeds, free, no key. UK NSM / EU ESAP
# machine access is a Phase 2 addition (see docs) -- these are the Phase 1
# regulator feeds the source plan names explicitly.
_DEFAULT_FEED_URLS = [
    "https://www.federalreserve.gov/feeds/press_all.xml",
    "https://www.ecb.europa.eu/rss/press.xml",
    "https://www.bankofengland.co.uk/rss/news",
    "https://www.fca.org.uk/news/rss.xml",
    "https://www.sec.gov/news/pressreleases.rss",
]


class RegulatoryRssSource(MentionSource):
    """Polls fixed regulator press/rule-release RSS feeds (Fed, ECB, BoE,
    FCA, SEC), deduplicating by entry GUID/link -- same dedup-on-source-ID
    convention `discovery/change_detector.py` already uses for documents.
    """

    name = "regulatory_rss"

    def __init__(self, feed_urls: list[str] | None = None) -> None:
        self._feed_urls = feed_urls or _DEFAULT_FEED_URLS

    async def fetch(self, since: datetime) -> list[RawMention]:
        import feedparser

        mentions: list[RawMention] = []
        seen_guids: set[str] = set()
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            for feed_url in self._feed_urls:
                try:
                    resp = await client.get(feed_url)
                    resp.raise_for_status()
                except httpx.HTTPError as exc:
                    logger.warning("Regulatory RSS fetch failed for %s: %s", feed_url, exc)
                    continue
                parsed = feedparser.parse(resp.content)
                for entry in parsed.entries:
                    guid = entry.get("id") or entry.get("link", "")
                    if not guid or guid in seen_guids:
                        continue
                    seen_guids.add(guid)
                    published_at = self._entry_published_at(entry)
                    if published_at is not None and published_at < since:
                        continue
                    mentions.append(
                        RawMention(
                            source_type=MentionSourceType.REGULATORY_RSS,
                            title=entry.get("title", "").strip(),
                            text=entry.get("summary", entry.get("title", "")).strip(),
                            url=entry.get("link", feed_url),
                            published_at=published_at.isoformat() if published_at else None,
                        )
                    )
        return mentions

    @staticmethod
    def _entry_published_at(entry) -> datetime | None:
        parsed_time = entry.get("published_parsed") or entry.get("updated_parsed")
        if not parsed_time:
            return None
        try:
            return datetime(*parsed_time[:6], tzinfo=UTC)
        except (TypeError, ValueError):
            return None
