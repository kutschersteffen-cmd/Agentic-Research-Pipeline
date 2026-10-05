"""Monthly ESG pull from the corporate internal API. The provider's response format is unknown, so the fetcher is pluggable;
whatever bytes it returns go through the same intake as an upload (assumed CSV until the real format is known)."""

from __future__ import annotations

from collections.abc import Callable

import httpx

from arp.config import Settings
from arp.holdings.file_source import file_ref
from arp.portfolio.climate.esg_intake import MONTH, EsgIntakeResult, ingest_esg_bytes, load_esg_mapping
from arp.portfolio.loads import LoadRecord, record_load

Fetcher = Callable[[str, dict], bytes]


def _http_fetch(url: str, headers: dict) -> bytes:
    r = httpx.get(url, headers=headers, timeout=60, follow_redirects=False)
    r.raise_for_status()
    return r.content


def pull_esg(store, settings: Settings, month: str, provider: str = "default", fetcher: Fetcher | None = None) -> EsgIntakeResult:
    load_esg_mapping(provider)  # ValueError for anything but a known [A-Za-z0-9_-]+ mapping: both go into the URL
    if not MONTH.fullmatch(month):
        raise ValueError("month must be YYYY-MM")

    def fail(detail: str) -> None:  # never the token, the URL or str(exc): only a fixed message or the exception type
        record_load(store, LoadRecord(kind="esg", source_id=provider, month=month, status="failed", content_hash="", detail=detail))

    if not settings.esg_api_base_url or not settings.esg_api_token:
        fail("ESG API URL or token not configured")
        raise ValueError("ESG API is not configured (ARP_ESG_API_URL, ARP_ESG_API_TOKEN)")
    # ponytail: the real endpoint shape is unknown; this assumes <base>/<month>?provider=...
    url = f"{settings.esg_api_base_url.rstrip('/')}/{month}?provider={provider}"
    try:
        data = (fetcher or _http_fetch)(url, {"Authorization": f"Bearer {settings.esg_api_token}"})
    except Exception as exc:
        fail(f"fetch failed: {type(exc).__name__}")
        raise
    return ingest_esg_bytes(store, data, "esg.csv", provider=provider, month=month, source_ref=file_ref(data))
