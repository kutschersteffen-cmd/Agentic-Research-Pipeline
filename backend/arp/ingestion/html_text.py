from __future__ import annotations


def extract_html_text(raw_html: str) -> str:
    """HTML -> plain text for every ingestion path: EDGAR filings, local
    disclosure files and fetched taxonomy sources.

    `favor_recall=True` keeps boilerplate-adjacent disclosure prose that
    trafilatura's default precision mode drops; the BeautifulSoup pass is
    the fallback for documents trafilatura declines entirely. Both the
    parser choice and the `"\\n"` separator affect chunk boundaries and
    therefore citation offsets, so they are decided here once rather than
    per ingestion package.
    """
    import trafilatura

    extracted = trafilatura.extract(raw_html, favor_recall=True)
    if extracted:
        return extracted
    from bs4 import BeautifulSoup

    return BeautifulSoup(raw_html, "lxml").get_text("\n")
