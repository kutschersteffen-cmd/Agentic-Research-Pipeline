from __future__ import annotations


def extract_html_text(raw_html: str) -> str:
    """HTML -> plain text for every ingestion path: EDGAR filings, local
    disclosure files and fetched taxonomy sources.

    `favor_recall=True` keeps boilerplate-adjacent disclosure prose that
    trafilatura's default precision mode drops; the BeautifulSoup pass is
    the fallback for documents trafilatura declines entirely, and for large
    documents it cuts to a fragment: filing-agent 10-Ks wrap each printed
    page in its own block and trafilatura keeps only the cover (Nucor
    FY2025: 4,812 of ~440k characters). Both the parser choice and the
    `"\\n"` separator affect chunk boundaries and therefore citation
    offsets, so they are decided here once rather than per ingestion
    package. Changing this logic needs a bump of
    edgar._EDGAR_PARSER_LOGIC_VERSION.
    """
    import trafilatura

    extracted = trafilatura.extract(raw_html, favor_recall=True)
    if extracted and len(extracted) >= _TRUSTED_EXTRACT_CHARS:
        return extracted
    from bs4 import BeautifulSoup

    full = BeautifulSoup(raw_html, "lxml").get_text("\n")
    full_words = len(full.split())
    if extracted and not (full_words >= _LARGE_DOC_WORDS and len(extracted.split()) < _MIN_KEPT_SHARE * full_words):
        return extracted
    return full


# An extract this long is never the cover-page fragment, so the full-text parse is skipped.
_TRUSTED_EXTRACT_CHARS = 50_000
# Below this size a document is a web page, where dropping most words as navigation is correct.
_LARGE_DOC_WORDS = 10_000
# Truncated filings keep 1-2% of their words; complete ones keep about 100%.
_MIN_KEPT_SHARE = 0.2
