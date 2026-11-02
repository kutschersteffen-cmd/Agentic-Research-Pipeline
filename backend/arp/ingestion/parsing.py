from __future__ import annotations

import bisect
import re

from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import Document as LlamaDocument

from arp.config import get_settings
from arp.ingestion.chunk_spans import ChunkSpan, get_span_cache
from arp.ingestion.outline import outline
from arp.schemas.common import DocType, DocumentChunk, SourceDocument

_SPEAKER_LINE = re.compile(r"^\s*([A-Z][A-Za-z.'\-]+(?:\s[A-Z][A-Za-z.'\-]+){0,3})\s*[:\-]\s*$")
_SECTION_HEADER = re.compile(r"^[ \t]*(ITEM[ \t]+\d+[A-Z]?\.?.{0,80}|PART[ \t]+[IVX]+.{0,80}?)[ \t]*$", re.IGNORECASE | re.MULTILINE)
_MD_HEADING = re.compile(r"^#{1,6}[ \t]+(.{1,120}?)[ \t#]*$", re.MULTILINE)  # Docling renders PDF/DOCX headings as markdown

DEFAULT_CHUNK_CHARS = 3500
DEFAULT_OVERLAP_CHARS = 300

# LlamaIndex's SentenceSplitter counts chunk_size/chunk_overlap in whatever
# unit its `tokenizer` callable returns len() of -- passing the builtin
# `list` (splits a string into one-char-per-element) makes those units
# plain characters, matching this module's existing chunk_chars/
# overlap_chars contract exactly, instead of switching to a token count
# every one of the 7 call sites would otherwise need to be re-tuned for.
_CHAR_TOKENIZER = list


def _fill_coverage_gaps(text_len: int, spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """LlamaIndex's SentenceSplitter can, on pathological input (confirmed
    via repro: many near-identical repeated paragraphs), leave a real gap
    of dropped content between chunks -- silently skipping it entirely
    rather than merely mis-sizing a boundary. Whole-document coverage (no
    evidence a citation could point at is ever silently unreachable) is a
    precision guarantee this app is built around, so restore it here
    regardless of the splitter's internal quirks: insert a filler span for
    any gap, including before the first span or after the last.
    """
    if not spans:
        return spans
    spans = sorted(spans)
    filled: list[tuple[int, int]] = []
    cursor = 0
    for start, end in spans:
        if start > cursor:
            filled.append((cursor, start))
        filled.append((start, end))
        cursor = max(cursor, end)
    if cursor < text_len:
        filled.append((cursor, text_len))
    return filled


def _sentence_aware_split(text: str, chunk_chars: int, overlap_chars: int) -> list[tuple[int, int]]:
    """Split text into (start, end) char spans via LlamaIndex's
    SentenceSplitter (sentence/paragraph-boundary aware, same spirit as
    the char-window splitter this replaces) so citations remain readable
    quotes rather than mid-sentence fragments.
    """
    if not text:
        return []
    splitter = SentenceSplitter(
        chunk_size=chunk_chars, chunk_overlap=overlap_chars, tokenizer=_CHAR_TOKENIZER, paragraph_separator="\n\n"
    )
    nodes = splitter.get_nodes_from_documents([LlamaDocument(text=text)])
    spans = [(n.start_char_idx, n.end_char_idx) for n in nodes]
    return _fill_coverage_gaps(len(text), spans)


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


def _section_segments(doc: SourceDocument, min_chars: int) -> list[tuple[int, int, str | None]] | None:
    """(start, end, first heading) per section, short sections joined with the ones after them while the
    joined span is under `min_chars`, the next heading is not shallower than the first, and the next section
    is itself under `min_chars` (a large section keeps its own label). None when the document has fewer than
    2 headings (it chunks as before)."""
    entries = outline(doc)
    if len(entries) < 2:
        return None
    segments: list[tuple[int, int, str | None]] = []
    if entries[0].char_start > 0:
        segments.append((0, entries[0].char_start, None))  # text before the first heading
    i = 0
    while i < len(entries):
        first, end = entries[i], entries[i].char_end
        i += 1
        while (
            end - first.char_start < min_chars and i < len(entries) and entries[i].level >= first.level
            and entries[i].char_end - entries[i].char_start < min_chars
        ):
            end = entries[i].char_end
            i += 1
        segments.append((first.char_start, end, first.title))
    return segments


def _compute_spans(
    doc: SourceDocument, chunk_chars: int, overlap_chars: int, section_min_chars: int | None = None
) -> tuple[ChunkSpan, ...]:
    """`section_min_chars` set = section-bounded chunking (`section_chunking_enabled`)."""
    is_transcript = doc.doc_type == DocType.EARNINGS_TRANSCRIPT
    # 10-K ITEM/PART header lines and markdown headings: a chunk's section is the last one at or before it
    headings = sorted((m.start(), m.group(1).strip()) for p in (_SECTION_HEADER, _MD_HEADING) for m in p.finditer(doc.full_text))
    starts = [h[0] for h in headings]

    def last_heading(start: int) -> str | None:
        i = bisect.bisect_right(starts, start)
        return headings[i - 1][1] if i else None

    segments = None if section_min_chars is None else _section_segments(doc, section_min_chars)
    if segments is None:
        pieces = [(start, end, last_heading(start)) for start, end in _sentence_aware_split(doc.full_text, chunk_chars, overlap_chars)]
    else:
        pieces = []
        for seg_start, seg_end, title in segments:
            if seg_end - seg_start <= chunk_chars:  # whole section in one chunk, boundaries exact
                inner = [(0, seg_end - seg_start)]
            else:  # overlap stays inside the section
                inner = _sentence_aware_split(doc.full_text[seg_start:seg_end], chunk_chars, overlap_chars)
            for start, end in inner:
                pieces.append((seg_start + start, seg_start + end, title if title is not None else last_heading(seg_start + start)))
    spans = []
    for start, end, section in pieces:
        speaker = detect_speaker(doc.full_text, start) if is_transcript else None
        spans.append(ChunkSpan(char_start=start, char_end=end, section=None if is_transcript else section, speaker=speaker))
    return tuple(spans)


def chunk_document(
    doc: SourceDocument,
    *,
    chunk_chars: int = DEFAULT_CHUNK_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
    keywords: list[str] | None = None,
) -> list[DocumentChunk]:
    """Sentence/paragraph-boundary-aware, section/speaker-aware chunking,
    via LlamaIndex's SentenceSplitter. chunk_chars is sized conservatively
    under typical model context limits.

    The split/section/speaker work (everything except keyword_hits) is
    identical for the same document regardless of which keywords are
    passed -- callers like the extraction pipeline call this once per
    field and the theme pipeline once per activity, so that work is cached
    per-document (see arp.ingestion.chunk_spans) rather than redone on
    every call. chunk_id is deterministic (derived from doc_id + span),
    not random, so citations and BM25 indexes can reference a chunk
    stably across calls.
    """
    keywords = keywords or []
    settings = get_settings()
    section_min_chars = settings.section_min_chars if settings.section_chunking_enabled else None
    cache = get_span_cache()
    key = cache.make_key(doc.full_text, doc.doc_type, chunk_chars, overlap_chars, section_min_chars, doc.table_spans)
    spans = cache.get_or_compute(key, lambda: _compute_spans(doc, chunk_chars, overlap_chars, section_min_chars))

    chunks: list[DocumentChunk] = []
    for s in spans:
        span_text = doc.full_text[s.char_start : s.char_end]
        chunks.append(
            DocumentChunk(
                chunk_id=f"chk_{doc.doc_id}_{s.char_start}_{s.char_end}",
                doc_id=doc.doc_id,
                company_id=doc.company_id,
                doc_type=doc.doc_type,
                section=s.section,
                speaker=s.speaker,
                text=span_text,
                char_start=s.char_start,
                char_end=s.char_end,
                keyword_hits=find_keyword_hits(span_text, keywords),
            )
        )
    for t in doc.table_spans:  # each whole table as one passage too, labelled by its caption
        span_text = doc.full_text[t.char_start : t.char_end]
        chunks.append(
            DocumentChunk(
                chunk_id=f"chk_{doc.doc_id}_table_{t.char_start}_{t.char_end}",
                table_id=t.table_id,
                doc_id=doc.doc_id,
                company_id=doc.company_id,
                doc_type=doc.doc_type,
                section=t.caption,
                unit_note=t.unit_note,
                text=span_text,
                char_start=t.char_start,
                char_end=t.char_end,
                keyword_hits=find_keyword_hits(span_text, keywords),
            )
        )
    return chunks
