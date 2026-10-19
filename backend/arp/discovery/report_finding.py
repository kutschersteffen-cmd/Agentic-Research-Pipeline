"""Finding a company's latest annual and sustainability report: DuckDuckGo search, then ranking of every candidate."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from arp.discovery.crawler import (
    CandidateDocumentLink,
    _parsable,
    _same_site,
    classify_link,
    is_demoted,
    is_pdf,
    report_text,
    years_in,
)
from arp.discovery.site_finder import WebSearchClient
from arp.schemas.common import CompanyRef, DocType

logger = logging.getLogger(__name__)

SEARCH_MAX_RESULTS = 5
TOP_PER_TYPE = 2

_QUERY_WORDS = {DocType.ANNUAL_REPORT_10K: "annual report", DocType.SUSTAINABILITY_REPORT: "sustainability report"}


def report_query(name: str, doc_type: DocType, expected_year: int) -> str:
    name = name.replace('"', "")
    return f'"{name}" {_QUERY_WORDS[doc_type]} {expected_year} filetype:pdf'


async def search_candidates(
    company: CompanyRef, client: WebSearchClient, expected_year: int, doc_types: list[DocType], *, delay: float, sleep
) -> list[CandidateDocumentLink]:
    """Report-PDF hits for each requested type. Best-effort: a failed query gives no candidates for that type."""
    found: list[CandidateDocumentLink] = []
    for i, doc_type in enumerate(doc_types):
        if i:
            await sleep(delay)
        query = report_query(company.name, doc_type, expected_year)
        try:
            results = (await client.search(query, max_results=SEARCH_MAX_RESULTS))[:SEARCH_MAX_RESULTS]
        except Exception as exc:  # noqa: BLE001 -- a bot challenge or outage must not fail the company
            logger.info("Report search failed for %s: %s", company.company_id, exc)
            continue
        found += [
            CandidateDocumentLink(url=r.url, doc_type=doc_type, link_text=r.title)
            for r in results if _parsable(r.url) and is_pdf(r.url) and not is_demoted(report_text(r.url, r.title))
        ]
    return found


def select_candidates(
    crawl: list[CandidateDocumentLink], search: list[CandidateDocumentLink], root_url: str | None, expected_year: int,
    *, skip_annual: bool,
) -> list[CandidateDocumentLink]:
    """One candidate per URL at its best source, the top TOP_PER_TYPE annual and sustainability reports ranked by
    (year, real report name, source, discovery order), then every other crawled type as found."""
    root_netloc = urlparse(root_url).netloc if root_url else ""
    best: dict[str, tuple[int, int, CandidateDocumentLink]] = {}
    for index, (source, cand) in enumerate([(0 if _same_site(c.url, root_netloc) else 1, c) for c in crawl]
                                           + [(2, c) for c in search]):
        if cand.url not in best or source < best[cand.url][0]:
            best[cand.url] = (source, index, cand)

    def rank(entry: tuple[int, int, CandidateDocumentLink]) -> tuple[int, int, int, int]:
        source, index, cand = entry
        years = years_in(report_text(cand.url, cand.link_text))
        named = classify_link(cand.url, cand.link_text) == cand.doc_type  # a real report name, not a year-fallback guess
        return (0 if expected_year in years else 1 if expected_year - 1 in years else 2), 0 if named else 1, source, index

    def top(doc_type: DocType) -> list[CandidateDocumentLink]:
        entries = sorted((e for e in best.values() if e[2].doc_type == doc_type), key=rank)
        return [e[2] for e in entries[:TOP_PER_TYPE]]

    ranked = top(DocType.SUSTAINABILITY_REPORT) if skip_annual else top(DocType.ANNUAL_REPORT_10K) + top(DocType.SUSTAINABILITY_REPORT)
    others = [c for c in crawl if best[c.url][2] is c and c.doc_type not in _QUERY_WORDS]
    return ranked + others
