"""The markdown headings of a parsed document (Docling renders PDF/DOCX headings as markdown)."""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass

from arp.ingestion.section_tags import section_tags_for
from arp.schemas.common import SourceDocument

_MD_HEADING = re.compile(r"^(#{1,6})[ \t]+(.{1,120}?)[ \t#]*$", re.MULTILINE)


def heading_path(text: str, offset: int) -> list[str]:
    """The headings above `offset`, outermost first: a heading replaces every open heading of its level or deeper."""
    path: list[tuple[int, str]] = []
    for m in _MD_HEADING.finditer(text, 0, offset):
        level = len(m.group(1))
        path = [p for p in path if p[0] < level] + [(level, m.group(2).strip())]
    return [title for _, title in path]


@dataclass(frozen=True, slots=True)
class OutlineEntry:
    title: str
    page: int | None
    char_start: int
    char_end: int  # the next heading's start, or the end of the text
    tags: list[str]


def outline(doc: SourceDocument) -> list[OutlineEntry]:
    """The document's headings with page, character range and section tags; a "#" line inside a table is no heading."""
    starts = [
        (m.start(), m.group(2).strip()) for m in _MD_HEADING.finditer(doc.full_text)
        if not any(t.char_start <= m.start() < t.char_end for t in doc.table_spans)
    ]
    ends = [s for s, _ in starts[1:]] + [len(doc.full_text)] * bool(starts)
    return [
        OutlineEntry(title, bisect.bisect_right(doc.page_breaks, start) if doc.page_breaks else None, start, end,
                     section_tags_for(title))
        for (start, title), end in zip(starts, ends, strict=True)
    ]
