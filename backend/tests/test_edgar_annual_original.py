from __future__ import annotations

import asyncio
import json
import time

import httpx

from arp.ingestion.edgar import AnnualOriginal, EdgarDocumentSource

CIK = "0000320193"


def _source(tmp_path, forms, *, seed=True):
    cache = tmp_path / "cache"
    cache.mkdir()
    if seed:
        recent = {
            "form": forms,
            "accessionNumber": [f"0000320193-24-00000{i}" for i in range(len(forms))],
            "primaryDocument": [f"doc{i}.htm" for i in range(len(forms))],
            "filingDate": [f"2024-0{i + 1}-01" for i in range(len(forms))],
        }
        payload = {"_fetched_at": time.time(), "data": {"filings": {"recent": recent}}}
        (cache / f"submissions_{CIK}.json").write_text(json.dumps(payload))
    return EdgarDocumentSource(user_agent="t t@example.com", cache_dir=cache, request_delay_seconds=0)


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_returns_first_10k_with_bytes(tmp_path):
    src = _source(tmp_path, ["10-Q", "10-K", "10-K"])
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200, content=b"<html>annual</html>")

    async def go():
        async with _client(handler) as c:
            return await src.fetch_latest_annual_original(CIK, client=c)

    got = asyncio.run(go())
    assert isinstance(got, AnnualOriginal)
    assert got.accession == "0000320193-24-000001" and got.form == "10-K"
    assert got.filing_date == "2024-02-01" and got.primary_document == "doc1.htm"
    assert got.content == b"<html>annual</html>"
    assert "320193/000032019324000001/doc1.htm" in got.source_url
    assert len(seen) == 1


def test_none_without_10k(tmp_path):
    src = _source(tmp_path, ["10-Q"])

    async def go():
        async with _client(lambda r: httpx.Response(200, content=b"x")) as c:
            return await src.fetch_latest_annual_original(CIK, client=c)

    assert asyncio.run(go()) is None


def test_none_when_submissions_unavailable(tmp_path):
    src = _source(tmp_path, [], seed=False)

    async def go():
        async with _client(lambda r: httpx.Response(404)) as c:
            return await src.fetch_latest_annual_original(CIK, client=c)

    assert asyncio.run(go()) is None
