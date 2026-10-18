from __future__ import annotations

import socket

import httpx
import pytest

from arp.discovery import site_check
from arp.discovery.site_check import check_homepage
from arp.schemas.common import CompanyRef

UA = "arp-test/1.0"
W = CompanyRef(company_id="w", name="Testwerke AG", lei="5299009TESTWERKE0063", isin="DE000TST0006", country="DE")

H1_URL = "https://www.testwerke.de/"
H1 = '<html><head><title>Testwerke – Startseite</title></head><body><a href="/impressum">Impressum</a></body></html>'
IMPRINT_URL = "https://www.testwerke.de/impressum"
IMPRINT = "<html><body><p>Testwerke AG, Musterstrasse 1, Teststadt</p><p>LEI: 5299009TESTWERKE0063</p></body></html>"
H2_URL = "https://www.marketscreener.com/quote/stock/TESTWERKE-AG-1/"
H3_URL = "https://www.otherco.co.uk/"
H3 = "<html><head><title>Otherco plc | Home</title></head><body><p>Welcome</p></body></html>"
H4 = "<html><head><title>Testwerke AG</title></head><body><p>Welcome</p></body></html>"


@pytest.fixture(autouse=True)
def _no_ssrf(monkeypatch):
    async def noop(request):
        return None

    monkeypatch.setattr(site_check, "ssrf_guard_request_hook", noop)


def _transport(routes: dict[str, httpx.Response | Exception]) -> tuple[httpx.MockTransport, list[str]]:
    """Serves `routes` by exact URL (anything else is 404) and records every requested URL."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        seen.append(url)
        route = routes.get(url, httpx.Response(404))
        if isinstance(route, Exception):
            raise route
        return route

    return httpx.MockTransport(handler), seen


def _html(body: str) -> httpx.Response:
    return httpx.Response(200, html=body)


def _redirect(to: str) -> httpx.Response:
    return httpx.Response(301, headers={"Location": to})


async def test_ac_1_owned_by_lei_on_imprint():
    transport, _ = _transport({H1_URL: _html(H1), IMPRINT_URL: _html(IMPRINT)})
    result = await check_homepage(H1_URL, W, UA, transport=transport)
    assert result.verdict == "owned"
    assert "lei_on_imprint" in result.evidence


async def test_ac_2_aggregator_rejected():
    transport, _ = _transport({})
    result = await check_homepage(H2_URL, W, UA, transport=transport)
    assert result.verdict == "rejected"
    assert result.evidence == ["blocklisted_domain"]


async def test_ac_3_aggregator_no_request():
    transport, seen = _transport({})
    await check_homepage(H2_URL, W, UA, transport=transport)
    assert seen == []


async def test_ac_4_aggregator_subdomain():
    transport, _ = _transport({})
    url = "https://de.marketscreener.com/quote/stock/TESTWERKE-AG-1/"
    result = await check_homepage(url, W, UA, transport=transport)
    assert result.verdict == "rejected"
    assert result.evidence == ["blocklisted_domain"]


async def test_ac_5_other_company_rejected():
    transport, _ = _transport({H3_URL: _html(H3)})
    result = await check_homepage(H3_URL, W, UA, transport=transport)
    assert result.verdict == "rejected"
    assert result.evidence == []


async def test_ac_6_name_in_title_unclear():
    transport, _ = _transport({H1_URL: _html(H4)})
    result = await check_homepage(H1_URL, W, UA, transport=transport)
    assert result.verdict == "unclear"
    assert result.evidence == ["name_in_title"]


async def test_ac_7_title_case_and_suffix():
    transport, _ = _transport({H1_URL: _html(H4.replace("Testwerke AG", "TESTWERKE"))})
    result = await check_homepage(H1_URL, W, UA, transport=transport)
    assert result.evidence == ["name_in_title"]


async def test_ac_8_connect_error():
    transport, _ = _transport({H1_URL: httpx.ConnectError("connection refused")})
    result = await check_homepage(H1_URL, W, UA, transport=transport)
    assert result.verdict == "unclear"
    assert result.evidence == ["fetch_failed"]


async def test_ac_9_no_suffix_list_fetch(monkeypatch, tmp_path):
    calls: list[tuple] = []

    def connect(self, *args):
        calls.append(args)
        raise OSError("network disabled in this test")

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setenv("TLDEXTRACT_CACHE", str(tmp_path))
    site_check._tld.cache_clear()  # build the extractor and load its suffix list under the patch
    transport, _ = _transport({})
    await check_homepage(H2_URL, W, UA, transport=transport)
    assert len(calls) == 0


async def test_ac_48_imprint_failure_ignored():
    transport, _ = _transport({H1_URL: _html(H1), IMPRINT_URL: httpx.ConnectError("connection refused")})
    result = await check_homepage(H1_URL, W, UA, transport=transport)
    assert result.verdict == "unclear"
    assert result.evidence == ["name_in_title"]


async def test_ac_49_homepage_404():
    transport, _ = _transport({H1_URL: httpx.Response(404)})
    result = await check_homepage(H1_URL, W, UA, transport=transport)
    assert result.verdict == "unclear"
    assert result.evidence == ["fetch_failed"]


async def test_ac_52_redirect_followed():
    transport, _ = _transport({"https://testwerke.de/": _redirect(H1_URL), H1_URL: _html(H1), IMPRINT_URL: _html(IMPRINT)})
    result = await check_homepage("https://testwerke.de/", W, UA, transport=transport)
    assert result.verdict == "owned"
    assert "lei_on_imprint" in result.evidence


async def test_ac_53_imprint_on_subdomain():
    legal = "https://legal.testwerke.de/impressum"
    transport, _ = _transport({H1_URL: _html(H1.replace('"/impressum"', f'"{legal}"')), legal: _html(IMPRINT)})
    result = await check_homepage(H1_URL, W, UA, transport=transport)
    assert result.verdict == "owned"
    assert set(result.evidence) == {"name_in_title", "name_on_imprint", "lei_on_imprint"}


async def test_ac_54_redirect_to_aggregator_rejected():
    transport, _ = _transport({"https://testwerke.de/": _redirect("https://www.linkedin.com/company/testwerke/")})
    result = await check_homepage("https://testwerke.de/", W, UA, transport=transport)
    assert result.verdict == "rejected"
    assert result.evidence == ["blocklisted_domain"]


async def test_ac_55_redirect_to_aggregator_not_requested():
    transport, seen = _transport({"https://testwerke.de/": _redirect("https://www.linkedin.com/company/testwerke/")})
    await check_homepage("https://testwerke.de/", W, UA, transport=transport)
    assert [u for u in seen if httpx.URL(u).host == "www.linkedin.com"] == []


async def test_non_html_homepage_is_fetch_failed():
    pdf = httpx.Response(200, content=b"%PDF-1.4", headers={"Content-Type": "application/pdf"})
    transport, _ = _transport({H1_URL: pdf})
    result = await check_homepage(H1_URL, W, UA, transport=transport)
    assert result.verdict == "unclear"
    assert result.evidence == ["fetch_failed"]
