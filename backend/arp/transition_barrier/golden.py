"""Golden set: phase-3 extraction scored against labelled cases (spec section 8)."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from arp.config import Settings
from arp.llm.base import LLMClient
from arp.llm.factory import build_llm_client, build_verifier_llm_client
from arp.transition_barrier import fetching
from arp.transition_barrier.dataset import data_dir, load_criteria
from arp.transition_barrier.extraction import extract
from arp.transition_barrier.rule_book import load_rule_book


@dataclass
class Case:
    code: str
    region: str
    fact: str
    document: str  # file name inside the documents directory
    value: object
    unit: str | None
    page: int | None


def load_cases(path: Path) -> list[Case]:
    return [Case(**row) for row in json.loads(path.read_text(encoding="utf-8"))]


def _llms(settings: Settings) -> tuple[LLMClient, LLMClient]:
    return build_llm_client(settings), build_verifier_llm_client(settings)


def _cents(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _matches(kind: str, got, label) -> bool:
    if label is None:  # the answer is absent from the document: any counted value is wrong
        return False
    if kind == "number":
        return _cents(got) == _cents(label)
    if kind == "date":
        return date.fromisoformat(str(got)[:10]) == date.fromisoformat(str(label)[:10])
    return got == label  # booleans and enums exactly


async def score(
    cases: list[Case], documents_dir: Path, *, llm, verifier_llm, settings: Settings, today: date
) -> tuple[float, float]:
    """(precision, coverage): counted values that match their label and page / counted cases, and counted / all."""
    book = load_rule_book(data_dir())[0]
    sectors = {c.code: c.sector for c in load_criteria()}
    files = list(dict.fromkeys(c.document for c in cases))
    docs = {}
    for doc_id, name in enumerate(files, 1):
        fetched = fetching.Fetched((documents_dir / name).read_bytes(), fetching.HTML if name.endswith(".html") else fetching.PDF, None)
        pages, html = fetching.parse(fetched)
        docs[name] = {
            "id": doc_id, "title": name, "tier": "primary", "as_of": fetching.doc_as_of(fetched, today),
            "page_texts": pages, "html": html, "url": None, "content_key": name,
        }
    limit = asyncio.Semaphore(4)

    async def one(case: Case) -> tuple[bool, bool]:
        """(counted, correct)"""
        fact = next(f for f in book.criteria[case.code].facts if f.id == case.fact)
        async with limit:
            got = await extract(
                fact, f"{sectors[case.code]}, {case.region}, {case.code}", docs[case.document], book.conversions,
                llm=llm, verifier_llm=verifier_llm, settings=settings,
            )
        if got is None or not got.counted:
            return False, False
        return True, _matches(fact.type, got.value, case.value) and got.page == case.page

    results = await asyncio.gather(*(one(c) for c in cases))
    counted = [correct for is_counted, correct in results if is_counted]
    return sum(counted) / len(counted) if counted else 0.0, len(counted) / len(cases) if cases else 0.0
