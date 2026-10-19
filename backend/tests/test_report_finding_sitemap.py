"""Report finding, task 4: sitemap seeding."""

import gzip

import httpx
import pytest

from tests.report_finding_fixtures import SITE, discover, page

pytestmark = pytest.mark.usefixtures("pg")

NS = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'


def robots(*lines):
    return httpx.Response(200, text="User-agent: *\n" + "".join(f"{line}\n" for line in lines))


def urlset_xml(*paths):
    return f"<urlset {NS}>" + "".join(f"<url><loc>{SITE + p}</loc></url>" for p in paths) + "</urlset>"


def index_xml(*paths):
    return f"<sitemapindex {NS}>" + "".join(f"<sitemap><loc>{SITE + p}</loc></sitemap>" for p in paths) + "</sitemapindex>"


def urlset(*paths):
    return httpx.Response(200, text=urlset_xml(*paths))


def index(*paths):
    return httpx.Response(200, text=index_xml(*paths))


AR_PAGE = page(("/ar-2025.pdf", "Annual Report 2025"))
AR = SITE + "/ar-2025.pdf"
AR_HTML = SITE + "/investors/annual-report.html"
SM_LINE = "Sitemap: https://www.testwerke.de/sm.xml"
SM14 = {SITE + "/robots.txt": robots(SM_LINE),
        SITE + "/sm.xml": urlset("/about.html", "/investors/annual-report.html"),
        AR_HTML: AR_PAGE}


def requested(run, prefix):
    return [e for e in run.log if e.startswith(f"request {SITE}{prefix}")]


async def test_ac_14_and_37(tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch, routes=SM14)
    assert AR in run.docs() and run.count(SITE + "/about.html") == 0


async def test_ac_15(tmp_path, pg, monkeypatch):
    routes = {SITE + "/sitemap.xml": SM14[SITE + "/sm.xml"], AR_HTML: AR_PAGE}
    run = await discover(tmp_path, pg, monkeypatch, routes=routes)
    assert AR in run.docs()


async def test_ac_16(tmp_path, pg, monkeypatch):
    routes = {SITE + "/robots.txt": robots("Sitemap: https://www.testwerke.de/idx.xml"),
              SITE + "/idx.xml": index(*[f"/sm-{i}.xml" for i in range(1, 8)])}
    routes |= {f"{SITE}/sm-{i}.xml": urlset() for i in range(1, 8)}
    run = await discover(tmp_path, pg, monkeypatch, routes=routes)
    assert requested(run, "/sm-") == [f"request {SITE}/sm-{i}.xml" for i in range(1, 6)]


async def test_ac_17(tmp_path, pg, monkeypatch):
    routes = {SITE + "/robots.txt": robots("Sitemap: https://www.testwerke.de/idx.xml"),
              SITE + "/idx.xml": index("/sitemap-de.xml", "/sitemap-energy.xml", "/sitemap-en.xml")}
    routes |= {f"{SITE}/sitemap-{n}.xml": urlset() for n in ("de", "energy", "en")}
    run = await discover(tmp_path, pg, monkeypatch, routes=routes)
    assert requested(run, "/sitemap-") == [f"request {SITE}/sitemap-{n}.xml" for n in ("en", "de", "energy")]


async def test_ac_18_and_38(tmp_path, pg, monkeypatch):
    routes = {SITE + "/robots.txt": robots(SM_LINE), SITE + "/": AR_PAGE,
              SITE + "/sm.xml": httpx.Response(200, content=urlset_xml("/reports/a.html").encode(),
                                               headers={"Content-Length": "20000000"})}
    run = await discover(tmp_path, pg, monkeypatch, routes=routes)
    assert run.count(SITE + "/reports/a.html") == 0 and AR in run.docs()


async def test_ac_19(tmp_path, pg, monkeypatch):
    routes = {SITE + "/robots.txt": robots(SM_LINE),
              SITE + "/sm.xml": urlset(*[f"/reports/r{i}.html" for i in range(1, 16)])}
    run = await discover(tmp_path, pg, monkeypatch, routes=routes)
    assert all(run.count(f"{SITE}/reports/r{i}.html") == 1 for i in range(1, 11))
    assert all(run.count(f"{SITE}/reports/r{i}.html") == 0 for i in range(11, 16))


async def test_ac_20(tmp_path, pg, monkeypatch):
    routes = SM14 | {SITE + "/robots.txt": robots(SM_LINE, "Disallow: /investors/")}
    run = await discover(tmp_path, pg, monkeypatch, routes=routes)
    assert run.count(AR_HTML) == 0


async def test_ac_55(tmp_path, pg, monkeypatch):
    routes = SM14 | {SITE + "/sitemap.xml": urlset()}
    run = await discover(tmp_path, pg, monkeypatch, routes=routes)
    assert run.count(SITE + "/sitemap.xml") == 0


async def test_ac_56(tmp_path, pg, monkeypatch):
    routes = {SITE + "/robots.txt": robots("Sitemap: https://www.testwerke.de/idx.xml"),
              SITE + "/idx.xml": index("/sm-a.xml"), SITE + "/sm-a.xml": index("/sm-a1.xml"),
              SITE + "/sm-a1.xml": urlset()}
    run = await discover(tmp_path, pg, monkeypatch, routes=routes)
    assert run.count(SITE + "/sm-a.xml") == 1 and run.count(SITE + "/sm-a1.xml") == 0


async def test_ac_57(tmp_path, pg, monkeypatch):
    routes = {SITE + "/robots.txt": robots("Sitemap: https://other.example.com/sm.xml")}
    run = await discover(tmp_path, pg, monkeypatch, routes=routes)
    assert run.count("https://other.example.com/sm.xml") == 0


async def test_ac_58(tmp_path, pg, monkeypatch):
    routes = {SITE + "/robots.txt": robots(SM_LINE),
              SITE + "/sm.xml": urlset(*[f"/reports/s{i}.html" for i in range(10)])}
    counter = iter(range(1000))

    def fallback(request):
        if request.url.path in ("/", "") or request.url.path.endswith(".html"):
            if request.url.path.startswith("/p/"):
                return page()
            return page(*[(f"/p/{next(counter)}.html", "More") for _ in range(5)])
        return None

    run = await discover(tmp_path, pg, monkeypatch, routes=routes, fallback=fallback)
    pages = [e for e in run.log if e.startswith(f"request {SITE}/") and not e.endswith(("/robots.txt", "/sm.xml"))]
    assert len(pages) == 40


async def test_ac_59(tmp_path, pg, monkeypatch):
    async def body():  # comments, not blanks: libxml2 refuses a single 10 MB text node on its own
        yield urlset_xml("/reports/a.html").replace("</urlset>", "").encode()
        for _ in range(16):
            yield b"<!--" + b"x" * 999_993 + b"-->"
        yield b"</urlset>"  # a valid document: only the byte cap can reject it

    routes = {SITE + "/robots.txt": robots(SM_LINE),
              SITE + "/sm.xml": lambda request: httpx.Response(200, content=body())}
    run = await discover(tmp_path, pg, monkeypatch, routes=routes)
    assert run.count(SITE + "/reports/a.html") == 0


async def test_ac_60(tmp_path, pg, monkeypatch):
    # the second sitemap's seed must survive the first one being junk
    routes = {SITE + "/robots.txt": robots(SM_LINE, "Sitemap: https://www.testwerke.de/sm2.xml"),
              SITE + "/sm.xml": httpx.Response(200, text="not xml"),
              SITE + "/sm2.xml": urlset("/investors/annual-report.html"), AR_HTML: AR_PAGE}
    run = await discover(tmp_path, pg, monkeypatch, routes=routes)
    assert AR in run.docs()


async def test_ac_61(tmp_path, pg, monkeypatch):
    routes = {SITE + "/robots.txt": robots("Sitemap: https://www.testwerke.de/sm.xml.gz"),
              SITE + "/sm.xml.gz": httpx.Response(200, content=gzip.compress(urlset_xml("/investors/annual-report.html").encode())),
              AR_HTML: AR_PAGE}
    run = await discover(tmp_path, pg, monkeypatch, routes=routes)
    assert AR in run.docs()


async def test_ac_62(tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch, routes=SM14)
    hits = [i for i, e in enumerate(run.log) if e in (f"request {SITE}/sm.xml", f"request {AR_HTML}")]
    assert len(hits) == 2 and all(run.log[i - 1] == "sleep 0.2" for i in hits)


@pytest.mark.parametrize("hint", ["annual-report", "annual_report", "annualreport", "reports", "reporting",
                                  "investor", "sustainab", "integrated-report", "geschaeftsbericht", "nachhaltigkeit"])
async def test_ac_75(hint, tmp_path, pg, monkeypatch):
    routes = {SITE + "/robots.txt": robots(SM_LINE), SITE + "/sm.xml": urlset(f"/x/{hint}/p.html")}
    run = await discover(tmp_path, pg, monkeypatch, routes=routes)
    assert run.count(SITE + f"/x/{hint}/p.html") == 1


async def test_ac_76(tmp_path, pg, monkeypatch):
    routes = {SITE + "/robots.txt": robots(SM_LINE), SITE + "/sm.xml": urlset("/Investors/Annual-Report.html")}
    run = await discover(tmp_path, pg, monkeypatch, routes=routes)
    assert run.count(SITE + "/Investors/Annual-Report.html") == 1


async def test_ac_77(tmp_path, pg, monkeypatch):
    routes = {SITE + "/robots.txt": robots("Sitemap: https://www.testwerke.de/sm-a.xml",
                                           "Sitemap: https://www.testwerke.de/sm-b.xml"),
              SITE + "/sm-a.xml": urlset(), SITE + "/sm-b.xml": urlset()}
    run = await discover(tmp_path, pg, monkeypatch, routes=routes)
    assert requested(run, "/sm-") == [f"request {SITE}/sm-a.xml", f"request {SITE}/sm-b.xml"]


async def test_ac_78(tmp_path, pg, monkeypatch):
    routes = {SITE + "/robots.txt": robots("Disallow: /sm.xml", SM_LINE), SITE + "/sm.xml": urlset()}
    run = await discover(tmp_path, pg, monkeypatch, routes=routes)
    assert run.count(SITE + "/sm.xml") == 0


async def test_ac_91(tmp_path, pg, monkeypatch):
    routes = {SITE + "/robots.txt": robots(*[f"Sitemap: https://www.testwerke.de/sm-{i}.xml" for i in range(1, 5)])}
    routes |= {f"{SITE}/sm-{i}.xml": urlset() for i in range(1, 5)}
    run = await discover(tmp_path, pg, monkeypatch, routes=routes)
    assert run.count(SITE + "/sm-3.xml") == 1 and run.count(SITE + "/sm-4.xml") == 0


async def test_ac_92(tmp_path, pg, monkeypatch):
    routes = {SITE + "/robots.txt": robots("Sitemap: https://www.testwerke.de/idx-a.xml",
                                           "Sitemap: https://www.testwerke.de/idx-b.xml"),
              SITE + "/idx-a.xml": index("/a1.xml", "/a2.xml", "/a3.xml"),
              SITE + "/idx-b.xml": index("/b1.xml", "/b2.xml", "/b3.xml")}
    routes |= {f"{SITE}/{n}.xml": urlset() for n in ("a1", "a2", "a3", "b1", "b2", "b3")}
    run = await discover(tmp_path, pg, monkeypatch, routes=routes)
    assert [run.count(f"{SITE}/{n}.xml") for n in ("a1", "a2", "a3", "b1", "b2", "b3")] == [1, 1, 1, 1, 1, 0]


async def test_ac_93(tmp_path, pg, monkeypatch):
    paths = [f"/reports/{i}.html" for i in range(1, 10)] + ["/reports/aaaaaaaaaa.html", "/reports/a/b.html"]
    routes = {SITE + "/robots.txt": robots(SM_LINE), SITE + "/sm.xml": urlset(*paths)}
    run = await discover(tmp_path, pg, monkeypatch, routes=routes)
    assert run.count(SITE + "/reports/a/b.html") == 1 and run.count(SITE + "/reports/aaaaaaaaaa.html") == 0


async def test_ac_97_and_98(tmp_path, pg, monkeypatch):
    routes = {SITE + "/robots.txt": robots("Sitemap: https://internal.testwerke.de/sm.xml"), SITE + "/": AR_PAGE}
    run = await discover(tmp_path, pg, monkeypatch, routes=routes)
    assert run.host_count("internal.testwerke.de") == 0 and AR in run.docs()


async def test_corrupt_gzip_sitemap_is_skipped(tmp_path, pg, monkeypatch):
    # the second sitemap's seed must survive the first one being corrupt
    routes = {SITE + "/robots.txt": robots("Sitemap: https://www.testwerke.de/sm.xml.gz", "Sitemap: https://www.testwerke.de/sm2.xml"),
              SITE + "/sm.xml.gz": httpx.Response(200, content=gzip.compress(urlset_xml("/investors/annual-report.html").encode())[:20]),
              SITE + "/sm2.xml": urlset("/investors/annual-report.html"), AR_HTML: AR_PAGE}
    run = await discover(tmp_path, pg, monkeypatch, routes=routes)
    assert AR in run.docs()


async def test_malformed_loc_is_skipped_on_its_own(tmp_path, pg, monkeypatch):
    xml = f"<urlset><url><loc>http://[bad</loc></url><url><loc>{AR_HTML}</loc></url></urlset>"
    routes = {SITE + "/robots.txt": robots(SM_LINE), SITE + "/sm.xml": httpx.Response(200, text=xml), AR_HTML: AR_PAGE}
    run = await discover(tmp_path, pg, monkeypatch, routes=routes)
    assert AR in run.docs()


async def test_sitemap_without_namespace_and_padded_loc(tmp_path, pg, monkeypatch):
    xml = f"<urlset><url><loc>\n  {AR_HTML}\n</loc></url></urlset>"
    routes = {SITE + "/robots.txt": robots(SM_LINE), SITE + "/sm.xml": httpx.Response(200, text=xml), AR_HTML: AR_PAGE}
    run = await discover(tmp_path, pg, monkeypatch, routes=routes)
    assert AR in run.docs()


async def test_gzip_sitemap_is_detected_by_content_not_url(tmp_path, pg, monkeypatch):
    body = gzip.compress(urlset_xml("/investors/annual-report.html").encode())
    routes = {SITE + "/robots.txt": robots(SM_LINE), SITE + "/sm.xml": httpx.Response(200, content=body), AR_HTML: AR_PAGE}
    run = await discover(tmp_path, pg, monkeypatch, routes=routes)
    assert AR in run.docs()


async def test_unbracketed_ipv6_sitemap_loc_does_not_fail_the_company(tmp_path, pg, monkeypatch):
    bad = "https://[www.testwerke.de/reports/x.html"
    xml = f"<urlset><url><loc>{bad}</loc></url><url><loc>{AR_HTML}</loc></url></urlset>"
    routes = {SITE + "/robots.txt": robots(SM_LINE), SITE + "/sm.xml": httpx.Response(200, text=xml), AR_HTML: AR_PAGE}
    run = await discover(tmp_path, pg, monkeypatch, routes=routes)
    assert run.count(AR_HTML) == 1 and AR in run.docs() and run.manifest.failed_count == 0


async def test_unbracketed_ipv6_robots_sitemap_line_does_not_fail_the_company(tmp_path, pg, monkeypatch):
    routes = {SITE + "/robots.txt": robots("Sitemap: https://[www.testwerke.de/sm.xml"), SITE + "/": AR_PAGE}
    run = await discover(tmp_path, pg, monkeypatch, routes=routes)
    assert AR in run.docs() and run.manifest.failed_count == 0
