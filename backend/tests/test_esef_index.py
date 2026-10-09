import httpx
import pytest

from arp.ingestion.esef import download_capped, list_esef_filings
from arp.net_safety import UnsafeURLError

IDX = "https://filings.example.org"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_list_filings_404_is_empty():
    async with _client(lambda r: httpx.Response(404)) as c:
        assert await list_esef_filings(c, IDX, "LEI1") == []


async def test_list_filings_returns_attributes_with_id():
    def handler(request):
        assert request.url.path == "/api/entities/LEI1/filings"
        return httpx.Response(200, json={"data": [
            {"id": "a", "attributes": {"fxo_id": "x1", "period_end": "2023-12-31"}},
            {"id": "b", "attributes": {"fxo_id": "x2", "period_end": "2024-12-31"}},
        ]})

    async with _client(handler) as c:
        out = await list_esef_filings(c, IDX + "/", "LEI1")
    assert [f["fxo_id"] for f in out] == ["x1", "x2"]
    assert [f["id"] for f in out] == ["a", "b"]


async def test_download_capped_rejects_declared_oversize():
    async with _client(lambda r: httpx.Response(200, content=b"x" * 10, headers={"content-length": "10"})) as c:
        with pytest.raises(ValueError):
            await download_capped(c, "https://8.8.8.8/p.zip", max_bytes=5)


async def test_download_capped_rejects_streamed_oversize():
    async def body():
        yield b"x" * 4
        yield b"x" * 4

    async with _client(lambda r: httpx.Response(200, content=body())) as c:
        with pytest.raises(ValueError):
            await download_capped(c, "https://8.8.8.8/p.zip", max_bytes=5)


async def test_download_capped_blocks_loopback():
    async with _client(lambda r: httpx.Response(200, content=b"ok")) as c:
        with pytest.raises(UnsafeURLError):
            await download_capped(c, "http://127.0.0.1/x.zip")
