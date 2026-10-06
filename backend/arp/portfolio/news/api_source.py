"""News pull from Refinitiv News over the Refinitiv Data Platform (Data Hub · Feeds).

1. POST <ARP_NEWS_API_URL>/auth/oauth2/v2/token (client credentials, scope trapi) for a short-lived token.
2. GET  <ARP_NEWS_API_URL>/data/news/v1/headlines?query=P:<permid> OR ...&dateFrom=...&limit=100, following meta.next.
   Each headline: {"storyId", "newsItem": {"itemMeta": {"title": [{"$"}], "versionCreated": {"$"}},
                                           "contentMeta": {"subject": [{"_qcode": "P:4295905573"}, ...]}}}
The shape follows the RDP documentation; only `_stories` has to change if a live response differs.

Only issuers whose PermID is in the security master are asked for, and a story is tied to an issuer by PermID exact
match only (one stored row per matched issuer); a story naming none of them is stored without a company. Stories
already stored (same story id) are skipped."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import date
from urllib.parse import urlencode

import httpx

from arp.config import Settings
from arp.portfolio.loads import LoadRecord, record_load
from arp.schemas.portfolio import NewsItem
from arp.storage.identifier_map import IdentifierMapStore

# (url, headers, form) -> body; a form means POST.
Fetcher = Callable[[str, dict, dict | None], bytes]
PERMIDS_PER_QUERY = 50
MAX_PAGES = 20  # ponytail: per query and pull; a backlog past 2,000 headlines waits for the next pull


def _http_fetch(url: str, headers: dict, form: dict | None) -> bytes:
    r = (httpx.post(url, headers=headers, data=form, timeout=60) if form is not None
         else httpx.get(url, headers=headers, timeout=60, follow_redirects=False))
    r.raise_for_status()
    return r.content


def _token(base: str, settings: Settings, fetch: Fetcher) -> str:
    body = fetch(f"{base}/auth/oauth2/v2/token", {}, {
        "grant_type": "client_credentials", "client_id": settings.news_api_client_id,
        "client_secret": settings.news_api_client_secret, "scope": "trapi",
    })
    try:
        return json.loads(body)["access_token"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("unexpected Refinitiv token response") from exc


def _stories(data: bytes) -> tuple[list[dict], str | None]:
    """(stories as {id, headline, published_at, permids}, next-page cursor); ValueError for any other shape."""
    try:
        body = json.loads(data)
        out = []
        for h in body["data"]:
            item = h["newsItem"]
            meta = item["itemMeta"]
            out.append({
                "id": h["storyId"],
                "headline": meta["title"][0]["$"],
                "published_at": (meta.get("versionCreated") or meta["firstCreated"])["$"],
                "permids": [s["_qcode"][2:] for s in item.get("contentMeta", {}).get("subject", []) if s.get("_qcode", "").startswith("P:")],
            })
        return out, (body.get("meta") or {}).get("next")
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        raise ValueError("unexpected Refinitiv headlines response") from exc


def pull_news(store, settings: Settings, idmap: IdentifierMapStore, *, since: str | None = None,
              fetcher: Fetcher | None = None, today: date | None = None) -> dict:
    today = today or date.today()
    month = today.isoformat()[:7]
    fetch = fetcher or _http_fetch

    def fail(detail: str) -> None:  # never the secret, the URL or str(exc): a fixed message or the exception type
        record_load(store, LoadRecord(kind="news", source_id="default", month=month, status="failed", content_hash="", detail=detail))

    if not settings.news_api_client_id or not settings.news_api_client_secret:
        fail("news API credentials not configured")
        raise ValueError("News API is not configured (ARP_NEWS_API_CLIENT_ID, ARP_NEWS_API_CLIENT_SECRET)")
    day = today.isoformat()
    permids = sorted({r.value for r in idmap.rows() if r.scheme == "PERMID"
                      and not (r.valid_from and day < r.valid_from) and not (r.valid_to and day >= r.valid_to)})
    if not permids:
        fail("no PermIDs in the security master")
        raise ValueError("The security master holds no PermIDs: add a permid column to tie Refinitiv news to issuers")
    stored = store.list_news()
    since = since or max((n.published_at[:10] for n in stored), default=None)
    base = settings.news_api_url.rstrip("/")
    stories: list[dict] = []
    digest = hashlib.sha256()
    try:
        headers = {"Authorization": f"Bearer {_token(base, settings, fetch)}"}
        for i in range(0, len(permids), PERMIDS_PER_QUERY):
            params = {"query": " OR ".join(f"P:{p}" for p in permids[i:i + PERMIDS_PER_QUERY]), "limit": 100}
            if since:
                params["dateFrom"] = f"{since}T00:00:00Z"
            for _ in range(MAX_PAGES):
                data = fetch(f"{base}/data/news/v1/headlines?{urlencode(params)}", headers, None)
                digest.update(data)
                page, cursor = _stories(data)
                stories += page
                if not cursor or not page:
                    break
                params = {"cursor": cursor}
    except Exception as exc:
        fail(f"fetch failed: {type(exc).__name__}")
        raise
    known = {n.news_id for n in stored}
    added = unmatched = 0
    for s in stories:
        on = str(s["published_at"])[:10]
        issuers: set[str] = set()
        for p in s["permids"]:
            keys = idmap.resolve("PERMID", p, on=on)
            if len(keys) == 1:
                issuers.add(keys[0])
        rows = [(f"news:{s['id']}:{k}", k) for k in sorted(issuers)] or [(f"news:{s['id']}", None)]
        new = [(nid, k) for nid, k in rows if nid not in known]
        for nid, k in new:
            store.append_news(NewsItem(news_id=nid, company_id=k, headline=s["headline"], excerpt="", source_url=None,
                                       published_at=str(s["published_at"])))
            known.add(nid)
        added += bool(new)
        unmatched += bool(new) and not issuers
    record_load(store, LoadRecord(kind="news", source_id="default", month=month, status="ok", content_hash=digest.hexdigest(),
                                  detail=f"{added} new stories" + (f", {unmatched} not matched to an issuer" if unmatched else "")))
    return {"added": added, "unmatched": unmatched, "received": len(stories)}
