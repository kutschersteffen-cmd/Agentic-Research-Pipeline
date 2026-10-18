from __future__ import annotations

import logging

import httpx

from arp.schemas.discovery import GleifMatch

logger = logging.getLogger(__name__)

GLEIF_API = "https://api.gleif.org/api/v1"


async def _issued_records(client: httpx.AsyncClient, params: dict[str, str]) -> list[dict]:
    resp = await client.get(f"{GLEIF_API}/lei-records", params=params)
    resp.raise_for_status()
    return [r for r in resp.json()["data"] if r["attributes"]["registration"]["status"] == "ISSUED"]


async def lei_for_isin(client: httpx.AsyncClient, isin: str) -> str | None:
    """The LEI GLEIF links to an ISIN, only when exactly one ISSUED record comes back."""
    try:
        records = await _issued_records(client, {"filter[isin]": isin})
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
        logger.info("GLEIF ISIN lookup failed for %s: %s", isin, exc)
        return None
    return records[0]["id"] if len(records) == 1 else None


async def name_matches(client: httpx.AsyncClient, name: str, limit: int = 5) -> list[GleifMatch]:
    """ISSUED GLEIF records whose full-text index matches the name, at most `limit`."""
    params = {"filter[fulltext]": name, "filter[registration.status]": "ISSUED", "page[size]": str(limit)}
    try:
        records = await _issued_records(client, params)
        return [
            GleifMatch(
                lei=r["id"],
                legal_name=r["attributes"]["entity"]["legalName"]["name"],
                country=(r["attributes"]["entity"].get("legalAddress") or {}).get("country"),
            )
            for r in records[:limit]
        ]
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
        logger.info("GLEIF name search failed for %r: %s", name, exc)
        return []
