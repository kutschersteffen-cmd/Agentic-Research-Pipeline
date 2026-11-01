"""Per-indicator PageIndex loop: the LLM reads the tree, opens sections, then answers."""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from arp.llm.base import LLMClient, LLMUsage
from arp.pageindex import tree as tree_mod
from arp.pageindex.tree import Node
from arp.schemas.transition_plan import TransitionPlanIndicator

MAX_STEPS = 6
PAGE_BUDGET = 12
CONCURRENCY = 8

_SYSTEM = (
    "You assess a company report against one transition-plan indicator. You see the report's table of contents "
    "(node id | title | pages | summary) and the pages you opened so far. Either open up to 3 nodes whose pages "
    "you need to read, or answer YES or NO following the guideline, citing the page numbers and exact quotes "
    "that support the answer. Answer NO when the opened pages do not show the indicator is met."
)


class TreeError(Exception):
    pass


class Answer(BaseModel):
    answer: Literal["YES", "NO"]
    pages: list[int] = []
    quotes: list[str] = []
    reasoning: str = ""


class Step(BaseModel):
    action: Literal["open", "answer"]
    open: list[str] = []
    answer: Literal["YES", "NO"] | None = None
    pages: list[int] = []
    quotes: list[str] = []
    reasoning: str = ""


class Result(BaseModel):
    identifier: str
    answer: Literal["YES", "NO", "ERROR"]
    pages: list[int] = []
    pages_opened: list[int] = []
    quotes: list[str] = []
    reasoning: str = ""
    steps: int = 0
    error: str | None = None


def _all_nodes(tree: list[Node]) -> dict[str, Node]:
    out: dict[str, Node] = {}
    for n in tree:
        out[n.node_id] = n
        out.update(_all_nodes(n.children))
    return out


def _render(tree: list[Node], depth: int = 0) -> str:
    return "\n".join(
        f"{'  ' * depth}{n.node_id} | {n.title} | pp {n.start_page}-{n.end_page} | {n.summary}"
        + (("\n" + _render(n.children, depth + 1)) if n.children else "")
        for n in tree
    )


async def answer_indicator(
    ind: TransitionPlanIndicator, tree: list[Node], pages: list[str], llm: LLMClient
) -> tuple[Result, list[LLMUsage]]:
    nodes, toc, opened, usages = _all_nodes(tree), _render(tree), [], []
    for step in range(1, MAX_STEPS + 1):
        forced = step == MAX_STEPS or len(opened) >= PAGE_BUDGET
        text = "\n\n".join(f"[page {p}]\n{pages[p - 1]}" for p in opened)
        prompt = (f"Indicator {ind.identifier}: {ind.question}\nGuideline: {ind.guideline}\n\n"
                  f"Table of contents:\n{toc}\n\nOpened pages:\n{text or '(none)'}"
                  + ("\n\nYou must answer now." if forced else ""))
        model = Answer if forced else Step
        for attempt in (1, 2):  # one retry; the retry is not a step
            try:
                out, u = await llm.complete_structured(system=_SYSTEM, prompt=prompt, output_model=model)
                if isinstance(out, Step) and out.action == "answer" and out.answer is None:
                    raise ValueError("answer action without an answer")
                break
            except Exception as exc:  # noqa: BLE001 -- one indicator's failure must not stop the run
                if attempt == 2:
                    return Result(identifier=ind.identifier, answer="ERROR", error=str(exc), pages_opened=opened,
                                  steps=step), usages
        usages.append(u)
        if isinstance(out, Answer) or out.action == "answer":
            return Result(identifier=ind.identifier, answer=out.answer, pages=out.pages, quotes=out.quotes,
                          reasoning=out.reasoning, pages_opened=opened, steps=step), usages
        for node_id in out.open[:3]:
            n = nodes.get(node_id)  # unknown ids are ignored; the step still counts
            for p in range(n.start_page, n.end_page + 1) if n else ():
                if p not in opened and len(opened) < PAGE_BUDGET and p <= len(pages):
                    opened.append(p)
    raise AssertionError("unreachable: the last step is forced to answer")


async def run_document(
    pdf: Path, indicators: list[TransitionPlanIndicator], llm: LLMClient, model: str, pages: list[str] | None = None
) -> tuple[dict, list[LLMUsage]]:
    pages = pages if pages is not None else tree_mod.page_texts(pdf)  # parsed once: the cached tree and the loop share it
    try:
        tree, usages = await tree_mod.load_or_build_tree(pdf, llm, pages)
    except Exception as exc:
        raise TreeError(str(exc)) from exc
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(ind):
        async with sem:
            return await answer_indicator(ind, tree, pages, llm)

    done = await asyncio.gather(*(one(i) for i in indicators))
    for _, u in done:
        usages += u
    return {
        "document": pdf.name,
        "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
        "model": model,
        "tree_nodes": len(_all_nodes(tree)),
        "results": [r.model_dump(exclude_none=True) for r, _ in done],
    }, usages
