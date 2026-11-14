"""Golden set for the watch check and find-commitments (spec stewardship-commitment-loop, "Golden set"): the real
model on labelled cases, scored on the suggestions code would store."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING

from arp.schemas.common import DocType, SourceDocument
from arp.schemas.engagement import WatchItem
from arp.stewardship.watch_check import commitment_suggestions, draft_check, draft_find, evidence_suggestions, note_document

if TYPE_CHECKING:
    from arp.llm.base import LLMClient

_CONCURRENCY = 4


async def _gather(fn, cases: list[dict]) -> list:
    gate = asyncio.Semaphore(_CONCURRENCY)

    async def one(case):
        async with gate:
            return await fn(case)

    return await asyncio.gather(*(one(c) for c in cases))


async def score_check(cases: list[dict], documents_dir: Path, llm: LLMClient, fuzzy_threshold: float, misses: list[str]) -> tuple[float, float]:
    """precision = stored suggestions whose verdict equals the label / stored suggestions (0 with none);
    coverage = found/against cases with a correct suggestion / found/against cases."""

    async def run(case: dict) -> list[str]:
        path = documents_dir / case["document"]
        doc = SourceDocument(doc_id=path.stem, company_id="golden", doc_type=DocType(case.get("doc_type", "other")), title=path.name, full_text=path.read_text())
        item = WatchItem(item_kind=case["item_kind"], item_id=case["id"], engagement_id="golden", text=case["text"], proof_statement=case.get("proof_statement"))
        suggestions, _ = evidence_suggestions(await draft_check(llm, doc, [item]), [item], doc, "golden", fuzzy_threshold)
        return [s.verdict for s in suggestions]

    verdicts = await _gather(run, cases)
    stored = correct = 0
    labelled = covered = 0
    for case, got in zip(cases, verdicts, strict=True):
        stored += len(got)
        hits = sum(v == case["label"] for v in got)
        correct += hits
        if case["label"] != "silent":
            labelled += 1
            covered += hits > 0
        if hits != len(got) or (case["label"] != "silent" and not hits):
            misses.append(f"{case['id']}: label {case['label']}, suggested {got or 'nothing'}")
    return (correct / stored if stored else 0.0), (covered / labelled if labelled else 0.0)


async def score_find(cases: list[dict], llm: LLMClient, fuzzy_threshold: float, misses: list[str]) -> tuple[float, float]:
    """A suggestion is correct when its quote contains a labelled key phrase (case-insensitive);
    precision = correct / suggestions; coverage = key phrases matched / key phrases."""

    async def run(case: dict) -> list[str]:
        note = note_document(case["id"], "golden", case["note"])
        suggestions, _ = commitment_suggestions(await draft_find(llm, case["note"]), note, "golden", fuzzy_threshold)
        return [s.quote.lower() for s in suggestions]

    quotes = await _gather(run, cases)
    suggested = correct = phrases = matched = 0
    for case, got in zip(cases, quotes, strict=True):
        keys = [k.lower() for k in case["key_phrases"]]
        suggested += len(got)
        correct += sum(any(k in q for k in keys) for q in got)
        phrases += len(keys)
        found = [k for k in keys if any(k in q for q in got)]
        matched += len(found)
        if len(found) != len(keys) or any(not any(k in q for k in keys) for q in got):
            misses.append(f"{case['id']}: key phrases {keys}, quotes {got}")
    return (correct / suggested if suggested else 0.0), (matched / phrases if phrases else 0.0)


def load_cases(path: Path, kind: str) -> list[dict]:
    return json.loads(path.read_text())[kind]
