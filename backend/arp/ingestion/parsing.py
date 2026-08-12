from __future__ import annotations

import re

from arp.schemas.common import DocType, DocumentChunk, SourceDocument

_SPEAKER_LINE = re.compile(r"^\s*([A-Z][A-Za-z.'\-]+(?:\s[A-Z][A-Za-z.'\-]+){0,3})\s*[:\-]\s*$")
_SECTION_HEADER = re.compile(r"^\s*(ITEM\s+\d+[A-Z]?\.?.{0,80}|PART\s+[IVX]+.{0,80})\s*$", re.IGNORECASE)

DEFAULT_CHUNK_CHARS = 3500
DEFAULT_OVERLAP_CHARS = 300


def _approx_tokenish_split(text: str, chunk_chars: int, overlap_chars: int) -> list[tuple[int, int]]:
    """Split text into (start, end) char spans, breaking on paragraph
    boundaries where possible so citations remain readable quotes rather
    than mid-sentence fragments.
    """
    spans: list[tuple[int, int]] = []
    n = len(text)
    if n == 0:
        return spans
    start = 0
    while start < n:
        end = min(start + chunk_chars, n)
        if end < n:
            boundary = text.rfind("\n\n", start, end)
            if boundary == -1 or boundary <= start + chunk_chars // 3:
                boundary = text.rfind(". ", start, end)
            if boundary != -1 and boundary > start:
                end = boundary + 1
        spans.append((start, end))
        if end >= n:
            break
        start = max(end - overlap_chars, start + 1)
    return spans


def detect_section(text: str, pos: int, window: int = 400) -> str | None:
    snippet = text[max(0, pos - window) : pos]
    matches = list(_SECTION_HEADER.finditer(snippet))
    if matches:
        return matches[-1].group(1).strip()
    return None


def detect_speaker(text: str, pos: int, window: int = 400) -> str | None:
    snippet = text[max(0, pos - window) : pos]
    for line in reversed(snippet.splitlines()):
        m = _SPEAKER_LINE.match(line)
        if m:
            return m.group(1).strip()
    return None


def find_keyword_hits(text: str, keywords: list[str]) -> list[str]:
    lowered = text.lower()
    return [kw for kw in keywords if kw.lower() in lowered]


def chunk_document(
    doc: SourceDocument,
    *,
    chunk_chars: int = DEFAULT_CHUNK_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
    keywords: list[str] | None = None,
) -> list[DocumentChunk]:
    """Token-aware-ish, section/speaker-aware chunking.

    Kept deliberately simple (char-based, not a real tokenizer) so it has
    no extra heavy dependency; chunk_chars is sized conservatively under
    typical model context limits.
    """
    keywords = keywords or []
    is_transcript = doc.doc_type == DocType.EARNINGS_TRANSCRIPT
    chunks: list[DocumentChunk] = []
    for start, end in _approx_tokenish_split(doc.full_text, chunk_chars, overlap_chars):
        span_text = doc.full_text[start:end]
        section = None if is_transcript else detect_section(doc.full_text, start)
        speaker = detect_speaker(doc.full_text, start) if is_transcript else None
        chunks.append(
            DocumentChunk(
                doc_id=doc.doc_id,
                company_id=doc.company_id,
                doc_type=doc.doc_type,
                section=section,
                speaker=speaker,
                text=span_text,
                char_start=start,
                char_end=end,
                keyword_hits=find_keyword_hits(span_text, keywords),
            )
        )
    return chunks
