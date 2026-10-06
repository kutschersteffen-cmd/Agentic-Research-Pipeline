"""News pull from the news API (Data Hub · Feeds). The vendor's format is not known yet, so the fetcher is pluggable and
the response shape below is assumed until it is; only `_parse` has to change when it is.

Assumed: GET <ARP_NEWS_API_URL>/articles?since=YYYY-MM-DD with a Bearer token returns
    {"articles": [{"id", "headline", "excerpt", "url", "published_at", "isin"?, "lei"?}]}

Each article is tied to an issuer through the security master only (ISIN, else LEI, exact match); an article it cannot
match is stored without a company, never matched by name. Articles already stored (same vendor id) are skipped."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import date

import httpx

from arp.config import Settings
from arp.portfolio.loads import LoadRecord, record_load
from arp.schemas.issuer import normalise_lei
from arp.schemas.portfolio import NewsItem
from arp.storage.identifier_map import IdentifierMapStore

Fetcher = Callable[[str, dict], bytes]


def _http_fetch(url: str, headers: dict) -> bytes:
    r = httpx.get(url, headers=headers, timeout=60, follow_redirects=False)
    r.raise_for_status()
    return r.content


def _parse(data: bytes) -> list[dict]:
    """The assumed vendor shape; raises ValueError for anything else."""
    try:
        articles = json.loads(data)["articles"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("unexpected news API response: expected {\"articles\": [...]}") from exc
    if not isinstance(articles, list):
        raise ValueError("unexpected news API response: articles is not a list")
    return articles


def _issuer(a: dict, idmap: IdentifierMapStore, on: str) -> str | None:
    for scheme, value in (("ISIN", a.get("isin") or ""), ("LEI", normalise_lei(a.get("lei") or ""))):
        keys = idmap.resolve(scheme, value, on=on) if value else []
        if len(keys) == 1:
            return keys[0]
    return None


def pull_news(store, settings: Settings, idmap: IdentifierMapStore, *, since: str | None = None,
              fetcher: Fetcher | None = None, today: date | None = None) -> dict:
    today = today or date.today()
    month = today.isoformat()[:7]

    def fail(detail: str) -> None:  # never the token, the URL or str(exc): a fixed message or the exception type
        record_load(store, LoadRecord(kind="news", source_id="default", month=month, status="failed", content_hash="", detail=detail))

    if not settings.news_api_url or not settings.news_api_token:
        fail("news API URL or token not configured")
        raise ValueError("News API is not configured (ARP_NEWS_API_URL, ARP_NEWS_API_TOKEN)")
    stored = store.list_news()
    since = since or max((n.published_at[:10] for n in stored), default=None)
    url = f"{settings.news_api_url.rstrip('/')}/articles" + (f"?since={since}" if since else "")
    try:
        data = (fetcher or _http_fetch)(url, {"Authorization": f"Bearer {settings.news_api_token}"})
        articles = _parse(data)
    except Exception as exc:
        fail(f"fetch failed: {type(exc).__name__}")
        raise
    known = {n.news_id for n in stored}
    added = unmatched = 0
    for a in articles:
        if not a.get("id") or not a.get("headline") or not a.get("published_at"):
            continue
        news_id = f"news:{a['id']}"
        if news_id in known:
            continue
        company = _issuer(a, idmap, on=str(a["published_at"])[:10])
        unmatched += company is None
        store.append_news(NewsItem(news_id=news_id, company_id=company, headline=a["headline"], excerpt=a.get("excerpt") or "",
                                   source_url=a.get("url"), published_at=str(a["published_at"])))
        known.add(news_id)
        added += 1
    record_load(store, LoadRecord(kind="news", source_id="default", month=month, status="ok",
                                  content_hash=hashlib.sha256(data).hexdigest(),
                                  detail=f"{added} new articles" + (f", {unmatched} not matched to an issuer" if unmatched else "")))
    return {"added": added, "unmatched": unmatched, "received": len(articles)}
