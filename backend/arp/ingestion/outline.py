"""The markdown headings of a parsed document (Docling renders PDF/DOCX headings as markdown)."""

from __future__ import annotations

import re

_MD_HEADING = re.compile(r"^(#{1,6})[ \t]+(.{1,120}?)[ \t#]*$", re.MULTILINE)


def heading_path(text: str, offset: int) -> list[str]:
    """The headings above `offset`, outermost first: a heading replaces every open heading of its level or deeper."""
    path: list[tuple[int, str]] = []
    for m in _MD_HEADING.finditer(text, 0, offset):
        level = len(m.group(1))
        path = [p for p in path if p[0] < level] + [(level, m.group(2).strip())]
    return [title for _, title in path]
