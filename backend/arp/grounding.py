from __future__ import annotations

import bisect
import re
from difflib import SequenceMatcher
from pathlib import Path

from arp.schemas.common import Citation, SourceDocument

_WS_RE = re.compile(r"\s+")
_SHEET_RE = re.compile(r"^## Sheet: (.+)$", re.MULTILINE)


def _normalize(text: str) -> str:
    return _WS_RE.sub(" ", text).strip().lower()


def _normalize_with_offsets(text: str) -> tuple[str, list[int]]:
    """Same normalization as _normalize (collapse whitespace runs to a
    single space, lowercase) but also returns, for each output char, the
    offset of the corresponding character in the original text -- lets a
    match position found in normalized text be mapped back to a real
    offset in the unmodified source, which page/sheet resolution needs.
    """
    chars: list[str] = []
    offsets: list[int] = []
    in_ws_run = False
    for i, ch in enumerate(text):
        if ch.isspace():
            if not in_ws_run:
                chars.append(" ")
                offsets.append(i)
                in_ws_run = True
            continue
        in_ws_run = False
        chars.append(ch.lower())
        offsets.append(i)
    start = 0
    end = len(chars)
    while start < end and chars[start] == " ":
        start += 1
    while end > start and chars[end - 1] == " ":
        end -= 1
    return "".join(chars[start:end]), offsets[start:end]


def _find_match(quote: str, source_text: str, fuzzy_threshold: float) -> tuple[bool, int | None]:
    """Locates `quote` in `source_text` (exact-after-normalization, falling
    back to a fuzzy longest-common-substring match), returning whether it
    grounds and, if so, the match's char offset in the *original*
    (non-normalized) source_text.
    """
    if not quote or not quote.strip():
        return False, None
    norm_quote = _normalize(quote)
    norm_source, offsets = _normalize_with_offsets(source_text)
    idx = norm_source.find(norm_quote)
    if idx != -1:
        return True, offsets[idx] if offsets else None
    if len(norm_quote) < 8:
        return False, None
    matcher = SequenceMatcher(None, norm_source, norm_quote, autojunk=False)
    match = matcher.find_longest_match(0, len(norm_source), 0, len(norm_quote))
    coverage = match.size / max(len(norm_quote), 1)
    if coverage >= fuzzy_threshold and match.size > 0:
        return True, offsets[match.a]
    return False, None


def is_grounded(quote: str, source_text: str, fuzzy_threshold: float = 0.92) -> bool:
    """The hard, programmatic precision control: a citation only counts as
    grounded if its quote actually appears (allowing for minor whitespace/
    punctuation normalization) in the cited source document's text.

    This is deliberately NOT delegated to the LLM's self-report — it is a
    plain substring/fuzzy check against the real source text, so a
    hallucinated or paraphrased "quote" is caught mechanically.
    """
    return _find_match(quote, source_text, fuzzy_threshold)[0]


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


def ground_citations(
    citations: list[Citation], documents_by_id: dict[str, SourceDocument], fuzzy_threshold: float = 0.92
) -> list[Citation]:
    """Returns a new list of citations with `.grounded` set correctly by
    checking each against its cited document's full text, and -- only for
    citations that actually ground -- `.page`/`.sheet`/`.company_id`/
    `.source_filename` resolved from the verified match's real position.
    These location fields are never trusted from the LLM's self-report,
    the same precision discipline as `.grounded` itself: an ungrounded
    citation gets none of them, so the UI never offers a "view source"
    link for a location it couldn't actually verify.
    """
    grounded: list[Citation] = []
    for c in citations:
        doc = documents_by_id.get(c.doc_id)
        ok, offset = _find_match(c.quote, doc.full_text, fuzzy_threshold) if doc else (False, None)
        update: dict = {"grounded": ok}
        if ok and doc and offset is not None:
            update["company_id"] = doc.company_id
            update["source_filename"] = Path(doc.local_path).name if doc.local_path else None
            update["page"] = _page_for_offset(doc.page_breaks, offset)
            update["sheet"] = _sheet_for_offset(doc.full_text, offset)
        grounded.append(c.model_copy(update=update))
    return grounded
