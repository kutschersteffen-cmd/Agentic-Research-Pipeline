from __future__ import annotations

import re
from difflib import SequenceMatcher

from arp.schemas.common import Citation, SourceDocument

_WS_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WS_RE.sub(" ", text).strip().lower()


def is_grounded(quote: str, source_text: str, fuzzy_threshold: float = 0.92) -> bool:
    """The hard, programmatic precision control: a citation only counts as
    grounded if its quote actually appears (allowing for minor whitespace/
    punctuation normalization) in the cited source document's text.

    This is deliberately NOT delegated to the LLM's self-report — it is a
    plain substring/fuzzy check against the real source text, so a
    hallucinated or paraphrased "quote" is caught mechanically.
    """
    if not quote or not quote.strip():
        return False
    norm_quote = _normalize(quote)
    norm_source = _normalize(source_text)
    if norm_quote in norm_source:
        return True
    if len(norm_quote) < 8:
        return False
    matcher = SequenceMatcher(None, norm_source, norm_quote, autojunk=False)
    match = matcher.find_longest_match(0, len(norm_source), 0, len(norm_quote))
    coverage = match.size / max(len(norm_quote), 1)
    return coverage >= fuzzy_threshold


def ground_citations(
    citations: list[Citation], documents_by_id: dict[str, SourceDocument], fuzzy_threshold: float = 0.92
) -> list[Citation]:
    """Returns a new list of citations with `.grounded` set correctly by
    checking each against its cited document's full text.
    """
    grounded: list[Citation] = []
    for c in citations:
        doc = documents_by_id.get(c.doc_id)
        ok = bool(doc) and is_grounded(c.quote, doc.full_text, fuzzy_threshold)
        grounded.append(c.model_copy(update={"grounded": ok}))
    return grounded
