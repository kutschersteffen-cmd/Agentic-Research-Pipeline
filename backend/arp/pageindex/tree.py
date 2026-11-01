"""PageIndex tree: an LLM-built table of contents of one PDF, cached next to it."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from arp.ingestion.local_files import parse_file_to_text_with_pages
from arp.llm.base import LLMClient, LLMUsage

PROMPT_VERSION = "1"
_BATCH_PAGES = 20
_HEAD_CHARS = 600
_SUMMARY_CHARS = 6000

_SECTIONS_SYSTEM = (
    "You read the first lines of each page of a company report and find where its sections start. "
    "Return every section heading that starts on one of the pages shown, with its page number and level "
    "(1 = chapter, 2 = subsection). Use the report's own heading text as the title."
)
_SUMMARY_SYSTEM = "Summarise what this report section covers in at most 60 words. Name concrete topics, not tone."


class Section(BaseModel):
    title: str
    start_page: int
    level: Literal[1, 2]


class SectionList(BaseModel):
    sections: list[Section]


class Summary(BaseModel):
    summary: str


class Node(BaseModel):
    node_id: str
    title: str
    start_page: int
    end_page: int
    summary: str = ""
    children: list[Node] = []


def page_texts(pdf: Path) -> list[str]:
    text, starts, _ = parse_file_to_text_with_pages(pdf)
    if not starts:
        return [text]
    return [text[s:e] for s, e in zip(starts, [*starts[1:], len(text)], strict=True)]


def leaves(tree: list[Node]) -> list[Node]:
    return [leaf for n in tree for leaf in (leaves(n.children) if n.children else [n])]


def _nest(sections: list[Section], n_pages: int) -> list[Node]:
    # Clamp, then keep the first section per start page, in page order.
    seen: dict[int, Section] = {}
    for s in sections:
        seen.setdefault(min(max(s.start_page, 1), n_pages), s)
    ordered = [(p, seen[p]) for p in sorted(seen)]
    if not ordered or ordered[0][0] != 1:
        ordered.insert(0, (1, Section(title="Front matter", start_page=1, level=1)))
    if ordered[0][1].level == 2:  # a tree starts with a chapter
        ordered[0] = (1, Section(title=ordered[0][1].title, start_page=1, level=1))
    tops: list[Node] = []
    for i, (page, s) in enumerate(ordered):
        nxt = [p for p, t in ordered[i + 1:] if t.level <= s.level]
        end = (nxt[0] - 1) if nxt else n_pages
        if s.level == 1:
            tops.append(Node(node_id=str(len(tops) + 1), title=s.title, start_page=page, end_page=end))
        else:
            parent = tops[-1]
            parent.children.append(
                Node(node_id=f"{parent.node_id}.{len(parent.children) + 1}", title=s.title, start_page=page, end_page=end)
            )
    for t in tops:  # pages of a chapter before its first subsection become their own leaf
        if t.children and t.children[0].start_page > t.start_page:
            t.children.insert(0, Node(node_id=f"{t.node_id}.0", title=t.title, start_page=t.start_page,
                                      end_page=t.children[0].start_page - 1))
    return tops


async def build_tree(pages: list[str], llm: LLMClient) -> tuple[list[Node], list[LLMUsage]]:
    usages: list[LLMUsage] = []
    sections: list[Section] = []
    for lo in range(0, len(pages), _BATCH_PAGES):
        batch = pages[lo:lo + _BATCH_PAGES]
        prompt = "\n\n".join(f"[page {lo + i + 1}]\n{p[:_HEAD_CHARS]}" for i, p in enumerate(batch))
        out, u = await llm.complete_structured(system=_SECTIONS_SYSTEM, prompt=prompt, output_model=SectionList)
        usages.append(u)
        sections += out.sections
    tree = _nest(sections, max(len(pages), 1))
    for n in tree:
        text = "\n".join(pages[n.start_page - 1:n.end_page])[:_SUMMARY_CHARS]
        out, u = await llm.complete_structured(system=_SUMMARY_SYSTEM, prompt=f"{n.title}\n\n{text}", output_model=Summary)
        usages.append(u)
        n.summary = out.summary
    return tree, usages


async def load_or_build_tree(
    pdf: Path, llm: LLMClient, pages: list[str] | None = None
) -> tuple[list[Node], list[LLMUsage]]:
    cache = pdf.parent / f"{pdf.name}.pageindex.json"
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    if cache.exists():
        data = json.loads(cache.read_text())
        if data.get("sha256") == sha and data.get("prompt_version") == PROMPT_VERSION:
            return [Node.model_validate(n) for n in data["tree"]], []
    tree, usages = await build_tree(pages if pages is not None else page_texts(pdf), llm)
    cache.write_text(json.dumps({"sha256": sha, "prompt_version": PROMPT_VERSION,
                                 "tree": [n.model_dump() for n in tree]}, indent=1))
    return tree, usages
