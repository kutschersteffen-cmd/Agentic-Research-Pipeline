from arp.discovery.crawler import _same_site, classify_link
from arp.schemas.common import DocType


def test_classify_link_by_text_keyword():
    assert classify_link("https://acme.com/reports/x123.pdf", "2025 Sustainability Report") == DocType.SUSTAINABILITY_REPORT


def test_classify_link_by_url_keyword():
    assert classify_link("https://acme.com/filings/10-k-2025.htm", "Download") == DocType.ANNUAL_REPORT_10K


def test_classify_link_pdf_without_keyword_is_other():
    assert classify_link("https://acme.com/misc/brochure.pdf", "Learn more") == DocType.OTHER


def test_classify_link_no_match_returns_none():
    assert classify_link("https://acme.com/about-us", "About Us") is None


def test_same_site_subdomain_matches():
    assert _same_site("https://investors.acme.com/reports", "acme.com")
    assert _same_site("https://acme.com/x", "acme.com")


def test_same_site_different_domain_rejected():
    assert not _same_site("https://notacme.com/x", "acme.com")


def test_classify_link_form_code_must_stand_alone():
    from arp.discovery.crawler import classify_link
    from arp.schemas.common import DocType

    assert classify_link("https://tv.apple.com/us/show/maximum-pleasure-guaranteed/umc.cmc.10k6tes7rmc2ti0ho1ozgwezc", "Maximum Pleasure Guaranteed") is None
    assert classify_link("https://acme.com/ir/acme-10k-2025.pdf", "Download") == DocType.ANNUAL_REPORT_10K
    assert classify_link("https://acme.com/sustainability2025.pdf", "Download") == DocType.SUSTAINABILITY_REPORT
