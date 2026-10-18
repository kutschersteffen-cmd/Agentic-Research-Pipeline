import json
import time

import httpx
import pytest

from arp.ingestion import edgar as edgar_module
from arp.ingestion.edgar import EdgarDocumentSource
from arp.schemas.common import CompanyRef, DocType

_REAL_CLIENT = httpx.AsyncClient
_SUBMISSIONS_123 = "https://data.sec.gov/submissions/CIK0000000123.json"


@pytest.fixture
def requests_seen(monkeypatch):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if "/Archives/" in str(request.url):
            return httpx.Response(200, text="<html><body><p>Annual report text.</p></body></html>")
        return httpx.Response(404)

    def factory(*args, **kwargs):
        return _REAL_CLIENT(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(edgar_module.httpx, "AsyncClient", factory)
    return seen


def _source(tmp_path, forms=None):
    (tmp_path / "sec_company_tickers.json").write_text(
        json.dumps({"0": {"cik_str": 123, "ticker": "TSTW", "title": "Test W"}})
    )
    if forms is not None:
        recent = {
            "form": forms,
            "accessionNumber": [f"0000000123-24-00000{i}" for i in range(len(forms))],
            "primaryDocument": [f"doc{i}.htm" for i in range(len(forms))],
            "filingDate": [f"2024-0{i + 1}-01" for i in range(len(forms))],
        }
        payload = {"_fetched_at": time.time(), "data": {"filings": {"recent": recent}}}
        (tmp_path / "submissions_0000000123.json").write_text(json.dumps(payload))
    return EdgarDocumentSource(user_agent="t t@example.com", cache_dir=tmp_path, request_delay_seconds=0)


async def _fetch(source, **company):
    company = CompanyRef(company_id="tstw", name="Test W", **company)
    return await source.fetch(company, [DocType.ANNUAL_REPORT_10K])


async def test_ac_33_20f(tmp_path, requests_seen):
    docs = await _fetch(_source(tmp_path, ["6-K", "20-F"]), cik="123")
    assert len(docs) == 1
    assert docs[0].doc_type == DocType.ANNUAL_REPORT_10K
    assert "20-F" in docs[0].title


async def test_ac_34_40f(tmp_path, requests_seen):
    docs = await _fetch(_source(tmp_path, ["40-F"]), cik="123")
    assert len(docs) == 1
    assert "40-F" in docs[0].title


async def test_ac_35_amendment_skipped(tmp_path, requests_seen):
    docs = await _fetch(_source(tmp_path, ["10-K/A", "10-K"]), cik="123")
    assert len(docs) == 1
    assert "10-K (" in docs[0].title
    assert "10-K/A" not in docs[0].title


async def test_ac_36_non_us_ticker_no_request(tmp_path, requests_seen):
    docs = await _fetch(_source(tmp_path), ticker="TSTW", country="DE")
    assert docs == []
    assert not any("data.sec.gov" in u for u in requests_seen)


async def test_ac_37_empty_country_resolves(tmp_path, requests_seen):
    await _fetch(_source(tmp_path), ticker="TSTW")
    assert _SUBMISSIONS_123 in requests_seen


async def test_ac_38_lowercase_us_resolves(tmp_path, requests_seen):
    await _fetch(_source(tmp_path), ticker="TSTW", country="us")
    assert _SUBMISSIONS_123 in requests_seen
