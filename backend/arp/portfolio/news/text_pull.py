"""Thomson Reuters headlines plus full story text into the point-in-time TextStore (one record per matched issuer)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.parse import urlencode

from arp.config import Settings
from arp.ingestion.html_text import extract_html_text
from arp.portfolio.news.api_source import MAX_PAGES, PERMIDS_PER_QUERY, Fetcher, _http_fetch, _stories, _token
from arp.signal_lab.text_store import TextStore, make_record
from arp.signal_lab.times import normalise_time
from arp.storage.identifier_map import IdentifierMapStore

SOURCE = "tr_news"


def _story_body(data: bytes) -> str:
    # Response shape follows the RDP documentation and is unverified against a live feed.
    try:
        html = json.loads(data)["newsItem"]["contentSet"]["inlineXML"][0]["$"]
        if not isinstance(html, str):
            raise TypeError
        return extract_html_text(html)
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        raise ValueError("unexpected Refinitiv story response") from exc


def pull_news_text(store: TextStore, settings: Settings, idmap: IdentifierMapStore, *, since: str | None = None,
                   fetcher: Fetcher | None = None, now: str | None = None) -> dict:
    fetch = fetcher or _http_fetch
    if not settings.news_api_client_id or not settings.news_api_client_secret:
        raise ValueError("News API is not configured (ARP_NEWS_API_CLIENT_ID, ARP_NEWS_API_CLIENT_SECRET)")
    permids = sorted({r.value for r in idmap.rows() if r.scheme == "PERMID"})
    if not permids:
        raise ValueError("The security master holds no PermIDs: add a permid column to tie Refinitiv news to issuers")
    known_at = now or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    base = settings.news_api_url.rstrip("/")
    headers = {"Authorization": f"Bearer {_token(base, settings, fetch)}"}
    stories: dict[str, dict] = {}
    for i in range(0, len(permids), PERMIDS_PER_QUERY):
        params = {"query": " OR ".join(f"P:{p}" for p in permids[i:i + PERMIDS_PER_QUERY]), "limit": 100}
        if since:
            params["dateFrom"] = f"{since[:10]}T00:00:00Z"
        for _ in range(MAX_PAGES):
            batch, cursor = _stories(fetch(f"{base}/data/news/v1/headlines?{urlencode(params)}", headers, None))
            stories.update({s["id"]: s for s in batch})
            if not cursor or not batch:
                break
            params = {"cursor": cursor}
    records = unmatched = 0
    for s in stories.values():
        on = str(s["published_at"])[:10]
        issuers = sorted({k[0] for p in s["permids"] if len(k := idmap.resolve("PERMID", p, on=on)) == 1})
        keys = [(f"{s['id']}:{k}", k) for k in issuers] or [(s["id"], None)]
        revised = normalise_time(s["revised_at"])
        if all((seen := store.latest_revision_time(SOURCE, sid)) is not None and seen >= revised for sid, _ in keys):
            continue
        text = _story_body(fetch(f"{base}/data/news/v1/stories/{s['id']}", headers, None))
        unmatched += not issuers
        for sid, company in keys:
            records += store.add(make_record(
                source=SOURCE, source_item_id=sid, company_id=company, event_time=s["published_at"],
                knowledge_time=known_at, revision_time=s["revised_at"], title=s["headline"], body=text))
    return {"stories": len(stories), "records": records, "unmatched": unmatched}
