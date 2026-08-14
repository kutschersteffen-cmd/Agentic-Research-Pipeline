from __future__ import annotations

import re

from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import Document as LlamaDocument

from arp.schemas.common import DocType, DocumentChunk, SourceDocument

_SPEAKER_LINE = re.compile(r"^\s*([A-Z][A-Za-z.'\-]+(?:\s[A-Z][A-Za-z.'\-]+){0,3})\s*[:\-]\s*$")
_SECTION_HEADER = re.compile(r"^\s*(ITEM\s+\d+[A-Z]?\.?.{0,80}|PART\s+[IVX]+.{0,80})\s*$", re.IGNORECASE)

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
    """Sentence/paragraph-boundary-aware, section/speaker-aware chunking,
    via LlamaIndex's SentenceSplitter. chunk_chars is sized conservatively
    under typical model context limits.
    """
    keywords = keywords or []
    is_transcript = doc.doc_type == DocType.EARNINGS_TRANSCRIPT
    chunks: list[DocumentChunk] = []
    for start, end in _sentence_aware_split(doc.full_text, chunk_chars, overlap_chars):
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
