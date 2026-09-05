import json

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


_MULTI_COMPANY_MAP = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 1067983, "ticker": "BRK-A", "title": "Berkshire Hathaway Inc"},
    "2": {"cik_str": 6201, "ticker": "AAL", "title": "American Airlines Group Inc."},
    "3": {"cik_str": 4515, "ticker": "AAL2", "title": "American Airlines Inc"},
}


async def test_search_by_name_exact_match(tmp_path):
    (tmp_path / "sec_company_tickers.json").write_text(json.dumps(_MULTI_COMPANY_MAP))
    source = EdgarDocumentSource(user_agent="test-agent test@example.com", cache_dir=tmp_path)

    matches = await source.search_by_name("Apple Inc.")

    assert len(matches) == 1
    assert matches[0].cik == "320193"
    assert matches[0].ticker == "AAPL"


async def test_search_by_name_case_insensitive_exact_match(tmp_path):
    (tmp_path / "sec_company_tickers.json").write_text(json.dumps(_MULTI_COMPANY_MAP))
    source = EdgarDocumentSource(user_agent="test-agent test@example.com", cache_dir=tmp_path)

    matches = await source.search_by_name("apple inc.")

    assert len(matches) == 1
    assert matches[0].ticker == "AAPL"


async def test_search_by_name_substring_returns_multiple_ambiguous_matches(tmp_path):
    (tmp_path / "sec_company_tickers.json").write_text(json.dumps(_MULTI_COMPANY_MAP))
    source = EdgarDocumentSource(user_agent="test-agent test@example.com", cache_dir=tmp_path)

    matches = await source.search_by_name("American Airlines")

    # deliberately ambiguous -- two distinct, similarly-named filers -- and
    # this returns both rather than silently picking one, so the
    # identity-resolution challenge step can flag the ambiguity itself.
    assert len(matches) == 2
    assert {m.cik for m in matches} == {"6201", "4515"}


async def test_search_by_name_fuzzy_match_for_a_slight_misspelling(tmp_path):
    (tmp_path / "sec_company_tickers.json").write_text(json.dumps(_MULTI_COMPANY_MAP))
    source = EdgarDocumentSource(user_agent="test-agent test@example.com", cache_dir=tmp_path)

    matches = await source.search_by_name("Berkshire Hathaway Incorporated")

    assert any(m.cik == "1067983" for m in matches)


async def test_search_by_name_no_match_returns_empty(tmp_path):
    (tmp_path / "sec_company_tickers.json").write_text(json.dumps(_MULTI_COMPANY_MAP))
    source = EdgarDocumentSource(user_agent="test-agent test@example.com", cache_dir=tmp_path)

    assert await source.search_by_name("Totally Unrelated Nonexistent Corp") == []


async def test_search_by_name_empty_string_returns_empty(tmp_path):
    (tmp_path / "sec_company_tickers.json").write_text(json.dumps(_MULTI_COMPANY_MAP))
    source = EdgarDocumentSource(user_agent="test-agent test@example.com", cache_dir=tmp_path)

    assert await source.search_by_name("   ") == []


async def test_search_by_name_respects_limit(tmp_path):
    many = {str(i): {"cik_str": i, "ticker": f"T{i}", "title": f"Widget Corp {i}"} for i in range(10)}
    (tmp_path / "sec_company_tickers.json").write_text(json.dumps(many))
    source = EdgarDocumentSource(user_agent="test-agent test@example.com", cache_dir=tmp_path)

    matches = await source.search_by_name("Widget Corp", limit=3)

    assert len(matches) == 3


async def test_search_by_name_uses_cached_map_without_network(tmp_path, monkeypatch):
    import httpx

    (tmp_path / "sec_company_tickers.json").write_text(json.dumps(_MULTI_COMPANY_MAP))
    source = EdgarDocumentSource(user_agent="test-agent test@example.com", cache_dir=tmp_path)

    class _FailingClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def get(self, *args, **kwargs):
            raise httpx.ConnectError("simulated network failure")

    import arp.ingestion.edgar as edgar_module

    monkeypatch.setattr(edgar_module.httpx, "AsyncClient", _FailingClient)

    matches = await source.search_by_name("Apple Inc.")
    assert len(matches) == 1
