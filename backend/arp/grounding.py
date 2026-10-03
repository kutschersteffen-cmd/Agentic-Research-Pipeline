from __future__ import annotations

import bisect
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

from arp.schemas.common import Citation, DocumentChunk, SourceDocument

_WS_RE = re.compile(r"\s+")
_SHEET_RE = re.compile(r"^## Sheet: (.+)$", re.MULTILINE)

# Enough to hold every document one company's assessment grounds against at
# once (a filing set is a handful of documents, not hundreds), while bounding
# what a long batch retains: each entry keeps a normalized copy of the text
# plus an int offset list, so this is the memory-vs-recompute knob.
# ponytail: a plain size cap, not a byte budget. One pathological 50MB
# document times 16 would be the ceiling; swap for a size-aware cache only
# if a run actually shows that memory profile.
_NORMALIZE_CACHE_SIZE = 16


# Below this many normalised chars: numbers need a label, nothing goes fuzzy.
SHORT_QUOTE_CHARS = 20

_DASHES = dict.fromkeys(map(ord, "\u2010\u2011\u2012\u2013\u2014\u2212"), "-")
_SINGLE_QUOTES = dict.fromkeys(map(ord, "\u2018\u2019\u201a\u201b"), "'")
_DOUBLE_QUOTES = dict.fromkeys(map(ord, "\u201c\u201d\u201e"), '"')
_MAP = {**_DASHES, **_SINGLE_QUOTES, **_DOUBLE_QUOTES}
_DROPPED = frozenset("\u00ad\u200b\u200c\u200d\ufeff")
_LIGATURES = frozenset("\ufb00\ufb01\ufb02\ufb03\ufb04\ufb05\ufb06")


def _normalize(text: str) -> str:
    # same algorithm as the source side, but uncached: quotes are one-offs
    # and must not evict (or be counted as) document entries.
    return _normalize_with_offsets.__wrapped__(text)[0]


def _hyphen_break_end(text: str, i: int, prev: str) -> int | None:
    """If text[i] is a hyphen inside `<alnum>-<ws with newline><alnum>`,
    returns the index of the alnum after the whitespace (the hyphen and the
    whitespace are dropped), else None."""
    if not (prev.isalnum() and text[i].translate(_MAP) == "-"):
        return None
    j = i + 1
    while j < len(text) and text[j].isspace():
        j += 1
    if j > i + 1 and "\n" in text[i + 1 : j] and j < len(text) and text[j].isalnum():
        return j
    return None


@lru_cache(maxsize=_NORMALIZE_CACHE_SIZE)
def _normalize_with_offsets(text: str) -> tuple[str, list[int]]:
    """Normalization (dashes, quotes, ligatures, PDF hyphenation, collapse whitespace runs to a
    single space, lowercase) but also returns, for each output char, the
    offset of the corresponding character in the original text -- lets a
    match position found in normalized text be mapped back to a real
    offset in the unmodified source, which page/sheet resolution needs.

    Cached on the source text, because the caller shape makes this
    quadratic otherwise: a document is normalized once per *citation*
    checked against it, and an extraction grounds many citations against
    the same filing. Measured at 531ms for a 2.1MB 10-K, so twenty
    citations against one document spent ~10s re-deriving an identical
    result. Python interns a str's hash after first use, so the cache
    lookup costs a pointer comparison on the repeat, not a re-hash of the
    document.

    The returned lists are shared with every later caller and must not be
    mutated; nothing here does, and `_find_match` only indexes them.
    """
    chars: list[str] = []
    offsets: list[int] = []
    in_ws_run = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in _DROPPED:
            i += 1
            continue
        if chars and chars[-1] != " ":
            j = _hyphen_break_end(text, i, chars[-1])
            if j is not None:
                i = j
                continue
        if ch.isspace():
            if not in_ws_run:
                chars.append(" ")
                offsets.append(i)
                in_ws_run = True
            i += 1
            continue
        in_ws_run = False
        out = unicodedata.normalize("NFKC", ch) if ch in _LIGATURES else ch.translate(_MAP)
        # lower() can expand (U+0130 -> 2 chars): every output char keeps offset i
        for oc in out.lower():
            chars.append(oc)
            offsets.append(i)
        i += 1
    start = 0
    end = len(chars)
    while start < end and chars[start] == " ":
        start += 1
    while end > start and chars[end - 1] == " ":
        end -= 1
    return "".join(chars[start:end]), offsets[start:end]


@dataclass(frozen=True)
class Match:
    char_start: int
    char_end: int  # exclusive; offsets index the original text
    method: str
    score: float


def _inside(m: Match, spans: list[tuple[int, int]]) -> bool:
    return any(s <= m.char_start and m.char_end <= e for s, e in spans)


def _find_in_span(quote: str, source_text: str, fuzzy_threshold: float, lo: int, hi: int) -> Match | None:
    """Raw, normalised, then fuzzy search restricted to source_text[lo:hi]."""
    idx = source_text.find(quote, lo, hi)
    if idx != -1:
        return Match(idx, idx + len(quote), "exact", 1.0)
    norm_quote = _normalize(quote)
    norm_source, offsets = _normalize_with_offsets(source_text)
    if not norm_quote or not offsets:
        return None
    # offsets are ascending, so the span maps to a slice of the normalised text.
    n_lo = bisect.bisect_left(offsets, lo)
    n_hi = bisect.bisect_left(offsets, hi)
    idx = norm_source.find(norm_quote, n_lo, n_hi)
    if idx != -1:
        return Match(offsets[idx], offsets[idx + len(norm_quote) - 1] + 1, "normalised", 1.0)
    if len(norm_quote) < SHORT_QUOTE_CHARS:  # short quotes never take the fuzzy path
        return None
    matcher = SequenceMatcher(None, norm_source[n_lo:n_hi], norm_quote, autojunk=False)
    m = matcher.find_longest_match(0, n_hi - n_lo, 0, len(norm_quote))
    coverage = m.size / max(len(norm_quote), 1)
    if coverage >= fuzzy_threshold and m.size > 0:
        a = n_lo + m.a
        return Match(offsets[a], offsets[a + m.size - 1] + 1, "fuzzy", coverage)
    return None


def _find_match(
    quote: str,
    source_text: str,
    fuzzy_threshold: float,
    *,
    within: list[tuple[int, int]] | None = None,
    prefer: tuple[int, int] | None = None,
) -> Match | None:
    """Locates `quote` in `source_text` (raw, then normalised, then fuzzy).
    Offsets index the original text. With `within`, only matches lying
    inside one of those spans count, and the search runs per span; the
    match inside `prefer` wins when there is one.
    """
    if not quote or not quote.strip():
        return None
    nq = _normalize(quote)
    # Short quotes (< SHORT_QUOTE_CHARS normalised chars): numeric evidence must carry
    # its label too (bare "42" is rejected); non-numeric evidence ("Yes") may ground
    # by exact/normalised match only. Neither ever takes the fuzzy path.
    if len(nq) < SHORT_QUOTE_CHARS and re.search(r"\d", nq) and not re.search(r"[a-z]{3,}", nq):
        return None
    if within is None:
        return _find_in_span(quote, source_text, fuzzy_threshold, 0, len(source_text))
    spans = sorted(within, key=lambda sp: sp != prefer)  # prefer first, stable
    for lo, hi in spans:
        m = _find_in_span(quote, source_text, fuzzy_threshold, lo, hi)
        if m is not None and _inside(m, [(lo, hi)]):
            return m
    return None


def is_grounded(quote: str, source_text: str, fuzzy_threshold: float = 0.92) -> bool:
    """The hard, programmatic precision control: a citation only counts as
    grounded if its quote actually appears (allowing for minor whitespace/
    punctuation normalization) in the cited source document's text.

    This is deliberately NOT delegated to the LLM's self-report — it is a
    plain substring/fuzzy check against the real source text, so a
    hallucinated or paraphrased "quote" is caught mechanically.
    """
    return _find_match(quote, source_text, fuzzy_threshold) is not None


def _page_for_offset(page_breaks: list[int], offset: int) -> int | None:
    if not page_breaks:
        return None
    return bisect.bisect_right(page_breaks, offset)


def _sheet_for_offset(full_text: str, offset: int) -> str | None:
    name = None
    for m in _SHEET_RE.finditer(full_text):
        if m.start() > offset:
            break
        name = m.group(1)
    return name


def ground_claim(
    citations: list[Citation],
    documents_by_id: dict[str, SourceDocument],
    fuzzy_threshold: float = 0.92,
    *,
    claim_is_empty: bool,
    passages: dict[str, DocumentChunk] | None = None,
) -> tuple[list[Citation], bool]:
    """`ground_citations` plus the per-claim roll-up: the citations with
    `.grounded` resolved, and whether the claim they support is grounded
    as a whole.

    The roll-up rule, stated once here because every aggregator used to
    re-derive it and they had already diverged: a claim is grounded when
    every citation grounds, and a claim with NO citations is grounded only
    if the claim is itself empty -- there is nothing to ground. A real
    claim with zero citations is exactly the model asserting something it
    never sourced, which is what this module exists to catch, so it is
    ungrounded and its record needs review.

    Callers pass what "empty" means for their claim: `value is None` for a
    numeric metric, `description is None` for a prose description.
    """
    grounded_citations = ground_citations(citations, documents_by_id, fuzzy_threshold, passages=passages)
    if not grounded_citations:
        return grounded_citations, claim_is_empty
    return grounded_citations, all(c.grounded for c in grounded_citations)


def ground_citations(
    citations: list[Citation],
    documents_by_id: dict[str, SourceDocument],
    fuzzy_threshold: float = 0.92,
    *,
    passages: dict[str, DocumentChunk] | None = None,
) -> list[Citation]:
    """Returns a new list of citations with `.grounded` set correctly by
    checking each against its cited document's full text, and -- only for
    citations that actually ground -- location and span evidence resolved
    from the verified match's real position. None of these fields is ever
    trusted from the LLM's self-report: an ungrounded citation gets none of
    them (except `passage_id`, which keeps the reported value).

    With `passages` (the evidence blocks the model was shown), a quote only
    grounds if it lies inside a shown passage of its document; the passage
    named by `passage_id` is preferred, and `passage_id` is rewritten to the
    passage the match actually lies in. Without it, the whole document.
    """
    grounded: list[Citation] = []
    for c in citations:
        doc = documents_by_id.get(c.doc_id)
        match = None
        mine: list[DocumentChunk] = []
        if doc:
            if passages is None:
                match = _find_match(c.quote, doc.full_text, fuzzy_threshold)
            else:
                mine = [p for p in passages.values() if p.doc_id == c.doc_id]
                reported = passages.get(c.passage_id) if c.passage_id else None
                prefer = (reported.char_start, reported.char_end) if reported and reported.doc_id == c.doc_id else None
                match = _find_match(
                    c.quote, doc.full_text, fuzzy_threshold,
                    within=[(p.char_start, p.char_end) for p in mine], prefer=prefer,
                )
        # Fields start cleared, not inherited: Citation is also the LLM-facing
        # draft schema, so the model can fill them itself.
        update: dict = {
            "grounded": match is not None, "page": None, "sheet": None, "company_id": None,
            "source_filename": None, "content_key": None, "parser_version": None, "span_text": None,
            "char_start": None, "char_end": None, "match_method": None, "match_score": None,
        }
        if match and doc:
            update["company_id"] = doc.company_id
            update["source_filename"] = Path(doc.local_path).name if doc.local_path else None
            update["page"] = _page_for_offset(doc.page_breaks, match.char_start)
            update["sheet"] = _sheet_for_offset(doc.full_text, match.char_start)
            update.update(
                content_key=doc.content_key, parser_version=doc.parser_version,
                span_text=doc.full_text[match.char_start : match.char_end],
                char_start=match.char_start, char_end=match.char_end,
                match_method=match.method, match_score=match.score,
            )
            if passages is not None:
                hit = next((p for p in mine if p.char_start <= match.char_start and match.char_end <= p.char_end), None)
                update["passage_id"] = hit.chunk_id if hit else c.passage_id
        grounded.append(c.model_copy(update=update))
    return grounded
