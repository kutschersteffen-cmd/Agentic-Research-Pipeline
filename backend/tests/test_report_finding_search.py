"""Report finding, task 3: DuckDuckGo report-PDF search, ranking and best-2 download."""

import httpx
import pytest

from arp.discovery.report_finding import report_query
from arp.schemas.common import DocType, SourceDocument
from tests.pdf_fixtures import FILLER
from tests.report_finding_fixtures import (
    ANNUAL_Q,
    SITE,
    SUST_Q,
    FakeEdgar,
    W,
    discover,
    image_pdf_response,
    page,
    pdf_response,
)

pytestmark = pytest.mark.usefixtures("pg")

CDN = "https://cdn.example.net"
NO_SITE = W.model_copy(update={"website": None})


def home(*links):
    return {SITE + "/": page(*links)}


async def test_ac_2(tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch, esef="current")
    assert run.queries == [SUST_Q]


async def test_ac_3(tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch, esef="current", routes=home(("/ar-2025.pdf", "Annual Report 2025")))
    assert run.count(SITE + "/ar-2025.pdf") == 0


async def test_ac_4(tmp_path, pg, monkeypatch):
    routes = home(("/sustainability-report-2025.pdf", "Sustainability Report 2025"))
    run = await discover(tmp_path, pg, monkeypatch, esef="current", routes=routes)
    assert SITE + "/sustainability-report-2025.pdf" in run.docs()


async def test_ac_10_and_34(tmp_path, pg, monkeypatch):
    search = {ANNUAL_Q: ["https://www.testwerke.de/about", CDN + "/files/TW-AR-2025.pdf"]}
    run = await discover(tmp_path, pg, monkeypatch, search=search)
    assert run.doc(CDN + "/files/TW-AR-2025.pdf")["doc_type"] == "10-K"
    assert run.count("https://www.testwerke.de/about") == 0


async def test_ac_11_and_35(tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch, search=httpx.ConnectError("down"),
                         routes=home(("/ar-2025.pdf", "Annual Report 2025")))
    assert SITE + "/ar-2025.pdf" in run.docs() and run.manifest.failed_count == 0


async def test_ac_12(tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch, search={ANNUAL_Q: [SITE + "/ar-2025.pdf"]},
                         routes=home(("/ar-2025.pdf", "Annual Report 2025")))
    assert run.count(SITE + "/ar-2025.pdf") == 1


async def test_ac_13_and_36(tmp_path, pg, monkeypatch):
    url = "https://other.example.org/otherco-ar-2025.pdf"
    run = await discover(tmp_path, pg, monkeypatch, search={ANNUAL_Q: [url]},
                         routes={url: pdf_response(tmp_path, "Otherco plc Annual Report 2025\n" + FILLER)})
    assert run.doc(url)["company_match"] == "none"
    assert run.manifest.review_count == 1


async def test_ac_24_and_25(tmp_path, pg, monkeypatch):
    routes = home(("/ar-2024.pdf", "Annual Report 2024"), ("/ar-2023.pdf", "Annual Report 2023"), ("/ar-2025.pdf", "Annual Report 2025"))
    run = await discover(tmp_path, pg, monkeypatch, routes=routes)
    assert run.docs("10-K") == [SITE + "/ar-2025.pdf", SITE + "/ar-2024.pdf"]
    assert run.count(SITE + "/ar-2023.pdf") == 0


async def test_ac_26(tmp_path, pg, monkeypatch):
    routes = home(*((f"/sr-{y}.pdf", f"Sustainability Report {y}") for y in (2023, 2025, 2024)))
    run = await discover(tmp_path, pg, monkeypatch, esef="current", routes=routes)
    assert run.docs("sustainability_report") == [SITE + "/sr-2025.pdf", SITE + "/sr-2024.pdf"]


async def test_ac_27(tmp_path, pg, monkeypatch):
    routes = home(*((f"/ip-{y}.pdf", f"Investor Presentation {y}") for y in (2023, 2024, 2025)))
    run = await discover(tmp_path, pg, monkeypatch, routes=routes)
    assert sorted(run.docs("investor_presentation")) == [SITE + f"/ip-{y}.pdf" for y in (2023, 2024, 2025)]


async def test_ac_30(tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch)
    i = run.log.index(f"query {ANNUAL_Q}")
    assert run.log[i:i + 3] == [f"query {ANNUAL_Q}", "sleep 0.2", f"query {SUST_Q}"]


async def test_ac_31(tmp_path, pg, monkeypatch):
    assert ANNUAL_Q in (await discover(tmp_path, pg, monkeypatch, esef="old")).queries


async def test_ac_32(tmp_path, pg, monkeypatch):
    assert ANNUAL_Q in (await discover(tmp_path, pg, monkeypatch, esef="error")).queries


async def test_ac_33(tmp_path, pg, monkeypatch):
    assert ANNUAL_Q in (await discover(tmp_path, pg, monkeypatch, esef="current", esef_enabled=False)).queries


async def test_ac_39(tmp_path, pg, monkeypatch):
    assert (await discover(tmp_path, pg, monkeypatch)).queries == [ANNUAL_Q, SUST_Q]


async def test_ac_40_and_70(tmp_path, pg, monkeypatch):
    urls = [f"https://x.example/f{i}.pdf" for i in range(1, 6)] + ["https://x.example/f6-2025.pdf", "https://x.example/f7-2025.pdf"]
    run = await discover(tmp_path, pg, monkeypatch, search={ANNUAL_Q: urls})
    assert run.count("https://x.example/f1.pdf") == 1 and run.count("https://x.example/f2.pdf") == 1
    assert run.count("https://x.example/f6-2025.pdf") == 0 and run.count("https://x.example/f7-2025.pdf") == 0
    assert {m for _, m in run.search.calls} == {5}


async def test_ac_41(tmp_path, pg, monkeypatch):
    urls = ["https://x.example/A.PDF", "https://x.example/b.pdf?dl=1", "https://x.example/c.pdf.html"]
    run = await discover(tmp_path, pg, monkeypatch, search={ANNUAL_Q: urls})
    assert run.count("https://x.example/A.PDF") == 1 and run.count("https://x.example/b.pdf?dl=1") == 1
    assert run.count("https://x.example/c.pdf.html") == 0


async def test_ac_43(tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch, routes={SITE + "/": httpx.Response(403)},
                         search={ANNUAL_Q: [SITE + "/ar-2025.pdf"]})
    assert SITE + "/ar-2025.pdf" in run.docs()


async def test_ac_45(tmp_path, pg, monkeypatch):
    url = SITE + "/scan-2025.pdf"
    run = await discover(tmp_path, pg, monkeypatch, search={ANNUAL_Q: [url]}, routes={url: image_pdf_response(tmp_path)})
    assert run.doc(url)["company_match"] == "no_text" and run.manifest.review_count == 1


async def test_ac_46(tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch, esef=("2025-04-19", "https://filings.xbrl.org/w/edge-in.zip"))
    assert run.queries == [SUST_Q]


async def test_ac_47(tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch, esef=("2025-04-18", "https://filings.xbrl.org/w/edge-out.zip"))
    assert ANNUAL_Q in run.queries


async def test_ac_53(tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch, search={ANNUAL_Q: [SITE + "/ar-2024.pdf"]},
                         routes=home(("/ar-2025.pdf", "Annual Report 2025")))
    assert run.docs("10-K") == [SITE + "/ar-2025.pdf", SITE + "/ar-2024.pdf"]


async def test_ac_54(tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch, search={ANNUAL_Q: [CDN + "/ar-2025.pdf"]},
                         routes=home(("/ar-2025-a.pdf", "Annual Report 2025"), ("/ar-2025-b.pdf", "Annual Report 2025")))
    assert run.docs("10-K") == [SITE + "/ar-2025-a.pdf", SITE + "/ar-2025-b.pdf"]
    assert run.count(CDN + "/ar-2025.pdf") == 0


async def test_ac_66(tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch, search={ANNUAL_Q: ["http://metadata.example.net/ar-2025.pdf"]})
    assert run.host_count("metadata.example.net") == 0


async def test_ac_69(tmp_path, pg, monkeypatch):
    routes = home(("http://metadata.example.net/sr-2025.pdf", "Sustainability Report 2025"), ("/ar-2025.pdf", "Annual Report 2025"))
    run = await discover(tmp_path, pg, monkeypatch, search={ANNUAL_Q: ["http://metadata.example.net/ar-2025.pdf"]}, routes=routes)
    assert SITE + "/ar-2025.pdf" in run.docs()


async def test_ac_72(tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch, company=NO_SITE, search={ANNUAL_Q: ["https://other.example/ar-2025.pdf"]})
    assert "https://other.example/ar-2025.pdf" in run.docs()


async def test_ac_73(tmp_path, pg, monkeypatch):
    other = "https://www.otherco.co.uk/"
    routes = {other: httpx.Response(200, html="<html><head><title>Otherco plc</title></head><body></body></html>")}
    run = await discover(tmp_path, pg, monkeypatch, company=NO_SITE, wikidata=other, routes=routes,
                         search={ANNUAL_Q: [SITE + "/ar-2025.pdf"]})
    assert SITE + "/ar-2025.pdf" in run.docs()


async def test_ac_74(tmp_path, pg, monkeypatch):
    routes = home(("/ar-2025.pdf", "Annual Report 2025"), ("/ar-2024.pdf", "Annual Report 2024"))
    run = await discover(tmp_path, pg, monkeypatch, esef="old", routes=routes)
    assert run.docs("10-K") == ["https://filings.xbrl.org/w/2024.zip", SITE + "/ar-2025.pdf", SITE + "/ar-2024.pdf"]


async def test_ac_79_and_88(tmp_path, pg, monkeypatch):
    routes = home(("/ar-2025.pdf", "Annual Report 2025"), (CDN + "/ar-2025-cdn.pdf", "Annual Report 2025"))
    run = await discover(tmp_path, pg, monkeypatch, routes=routes, search={ANNUAL_Q: ["https://search.example/ar-2025-s.pdf"]})
    assert run.docs("10-K") == [SITE + "/ar-2025.pdf", CDN + "/ar-2025-cdn.pdf"]
    assert run.count("https://search.example/ar-2025-s.pdf") == 0


async def test_ac_80(tmp_path, pg, monkeypatch):
    search = {ANNUAL_Q: ["https://search.example/ar-2025-s.pdf", "https://search.example/ar-2025-t.pdf"]}
    run = await discover(tmp_path, pg, monkeypatch, routes=home((CDN + "/ar-2025-cdn.pdf", "Annual Report 2025")), search=search)
    assert run.docs("10-K") == [CDN + "/ar-2025-cdn.pdf", "https://search.example/ar-2025-s.pdf"]


async def test_ac_82(tmp_path, pg, monkeypatch):
    url = "https://x.example/ar-2025-summary.pdf"
    run = await discover(tmp_path, pg, monkeypatch, search={ANNUAL_Q: [(url, "Annual Report 2025 Summary")]})
    assert run.count(url) == 0


async def test_ac_85(tmp_path, pg, monkeypatch):
    tenk = SourceDocument(company_id="w", doc_type=DocType.ANNUAL_REPORT_10K, title="10-K", source_url="https://sec.example/10k", full_text="x")
    run = await discover(tmp_path, pg, monkeypatch, company=W.model_copy(update={"cik": "123"}), edgar=FakeEdgar(docs=[tenk]))
    assert ANNUAL_Q in run.queries


async def test_ac_95(tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch, default_search=True, routes=home(("/ar-2025.pdf", "Annual Report 2025")))
    assert SITE + "/ar-2025.pdf" in run.docs()


async def test_ac_96(tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch, esef="current", search={SUST_Q: [SITE + "/sr-2025.pdf"]})
    assert run.doc(SITE + "/sr-2025.pdf")["doc_type"] == "sustainability_report"


async def test_only_requested_types_are_queried(tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch, doc_types=[DocType.ANNUAL_REPORT_10K])
    assert run.queries == [ANNUAL_Q]


def test_quotes_removed_from_query_name():
    assert report_query('Foo "Bar" AG', DocType.ANNUAL_REPORT_10K, 2025) == '"Foo Bar AG" annual report 2025 filetype:pdf'
