"""Report finding, task 2: report names, year fallback, demotion words and off-site report PDFs."""

import pytest

from tests.report_finding_fixtures import SITE, discover, page

pytestmark = pytest.mark.usefixtures("pg")

PHRASES = ["Integrated Report", "Universal Registration Document", "Annual Review", "Geschäftsbericht",
           "Geschaeftsbericht", "Rapport annuel", "Informe anual", "Jaarverslag", "Årsrapport"]
DEMOTION = ["quarter", "quarterly", "q1", "q2", "q3", "q4", "half-year", "interim", "factsheet", "fact sheet",
            "presentation", "transcript", "remuneration", "tax", "summary", "extract"]


def home(*links):
    return {SITE + "/": page(*links)}


@pytest.mark.parametrize("phrase", PHRASES)
async def test_ac_48(phrase, tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch, routes=home(("/x.pdf", f"{phrase} 2022")))
    assert run.doc(SITE + "/x.pdf")["doc_type"] == "10-K"


async def test_ac_49(tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch, routes=home(("/Testwerke_Report_FY2025.pdf", "Testwerke Report")))
    assert run.doc(SITE + "/Testwerke_Report_FY2025.pdf")["doc_type"] == "10-K"


async def test_ac_50(tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch, routes=home(("/Testwerke_Report_2022.pdf", "Testwerke Report")))
    assert run.doc(SITE + "/Testwerke_Report_2022.pdf")["doc_type"] == "other"


@pytest.mark.parametrize("word", DEMOTION)
async def test_ac_51(word, tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch, routes=home(("/r.pdf", f"Report 2025 {word}")))
    assert run.doc(SITE + "/r.pdf")["doc_type"] != "10-K"


async def test_ac_52(tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch, routes=home(("/taxonomy-report-2025.pdf", "Taxonomy Report 2025")))
    assert run.doc(SITE + "/taxonomy-report-2025.pdf")["doc_type"] == "10-K"


async def test_ac_81(tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch, routes=home(("/irs.pdf", "Integrated Report 2025 Summary")))
    assert run.doc(SITE + "/irs.pdf")["doc_type"] != "10-K"


async def test_ac_83(tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch, routes=home(("/ars.pdf", "Annual Report 2025 Summary")))
    assert run.doc(SITE + "/ars.pdf")["doc_type"] == "10-K"


async def test_ac_21(tmp_path, pg, monkeypatch):
    url = "https://assets.cdn.example/r/ar.pdf"
    run = await discover(tmp_path, pg, monkeypatch, routes=home((url, "Annual Report 2025")))
    assert run.doc(url)["doc_type"] == "10-K"


async def test_ac_84(tmp_path, pg, monkeypatch):
    url = "https://assets.cdn.example/r/sr.pdf"
    run = await discover(tmp_path, pg, monkeypatch, routes=home((url, "Sustainability Report 2025")))
    assert run.doc(url)["doc_type"] == "sustainability_report"


async def test_ac_71(tmp_path, pg, monkeypatch):
    url = "https://reports.testwerke.de/ar-2025.pdf"
    run = await discover(tmp_path, pg, monkeypatch, routes=home((url, "Annual Report 2025")))
    assert run.doc(url)["doc_type"] == "10-K"


async def test_ac_22(tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch, routes=home(
        ("https://partner.example.com/page.html", "Partner"), ("https://partner.example.com/brochure.pdf", "Brochure")))
    assert run.count("https://partner.example.com/page.html") == 0
    assert run.count("https://partner.example.com/brochure.pdf") == 0


async def test_ac_89(tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch, routes=home(("https://reports.testwerke.de/page.html", "Reports")))
    assert run.count("https://reports.testwerke.de/page.html") == 0


async def test_ac_68(tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch, routes=home(
        ("http://metadata.example.net/sr-2025.pdf", "Sustainability Report 2025")))
    assert run.host_count("metadata.example.net") == 0
