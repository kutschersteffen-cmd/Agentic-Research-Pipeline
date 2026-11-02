"""A document's outline from its markdown heading lines. Describes the document only: nothing routes,
filters or drops chunks by it."""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass
from functools import lru_cache

from arp.schemas.common import SourceDocument

_MD_HEADING = re.compile(r"^(#{1,6})[ \t]+(.{1,120}?)[ \t#]*$", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class OutlineEntry:
    title: str
    level: int
    page: int
    char_start: int
    char_end: int  # the next heading's start, or the end of the text


def page_starts(doc: SourceDocument) -> list[int]:
    """Offsets where pages 2, 3, ... start. Parsers store page 1's start (0) too; tests may not."""
    return [b for b in doc.page_breaks if b > 0]


def page_at(starts: list[int], offset: int) -> int:
    return bisect.bisect_right(starts, offset) + 1


def page_count(doc: SourceDocument) -> int:
    return len(page_starts(doc)) + 1


def outline(doc: SourceDocument) -> list[OutlineEntry]:
    tables = tuple((t.char_start, t.char_end) for t in doc.table_spans)
    return list(_outline(doc.full_text, tables, tuple(page_starts(doc))))


@lru_cache(maxsize=32)  # index_text asks once per chunk; the text's hash is memoized by CPython
def _outline(text: str, tables: tuple[tuple[int, int], ...], starts: tuple[int, ...]) -> tuple[OutlineEntry, ...]:
    found = [
        (m.start(), m.group(2).strip(), len(m.group(1)))
        for m in _MD_HEADING.finditer(text)
        if not any(s <= m.start() < e for s, e in tables)
    ]
    ends = [f[0] for f in found[1:]] + ([len(text)] if found else [])
    return tuple(
        OutlineEntry(title=title, level=level, page=page_at(list(starts), start), char_start=start, char_end=end)
        for (start, title, level), end in zip(found, ends, strict=True)
    )


def heading_path(doc: SourceDocument, offset: int, entries: list[OutlineEntry] | None = None) -> list[str]:
    """The headings above `offset`, outermost first; a heading replaces every open heading of its level or deeper."""
    open_: list[OutlineEntry] = []
    for e in outline(doc) if entries is None else entries:
        if e.char_start > offset:
            break
        while open_ and open_[-1].level >= e.level:
            open_.pop()
        open_.append(e)
    return [e.title for e in open_]
