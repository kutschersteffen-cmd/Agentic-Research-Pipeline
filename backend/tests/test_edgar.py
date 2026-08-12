import json

import pytest

from arp.ingestion.edgar import EdgarDocumentSource


async def test_resolve_cik_uses_cached_ticker_map_without_network(tmp_path):
    cache_dir = tmp_path
    (cache_dir / "sec_company_tickers.json").write_text(
        json.dumps({"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}})
    )
    source = EdgarDocumentSource(user_agent="test-agent test@example.com", cache_dir=cache_dir)
    cik = await source._resolve_cik("AAPL")
    assert cik == "320193"


async def test_resolve_cik_returns_none_for_missing_ticker(tmp_path):
    (tmp_path / "sec_company_tickers.json").write_text(
        json.dumps({"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}})
    )
    source = EdgarDocumentSource(user_agent="test-agent test@example.com", cache_dir=tmp_path)
    assert await source._resolve_cik("NOPE") is None


async def test_resolve_cik_none_ticker_returns_none(tmp_path):
    source = EdgarDocumentSource(user_agent="test-agent test@example.com", cache_dir=tmp_path)
    assert await source._resolve_cik(None) is None
