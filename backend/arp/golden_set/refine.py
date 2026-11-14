"""Golden set for the Refine chat turn: does the real model map an instruction to the right edit ops (AC-45)."""

from __future__ import annotations

import json
from pathlib import Path

from arp.llm.base import LLMClient
from arp.refine.agent import _SYSTEM, RefineOps, build_prompt

_TARGETS = ("slide", "slot", "variant", "chart_type", "to")


def _key(op: dict) -> tuple:
    """Op name and targets; `instruction` and `text` are free wording and left out."""
    return (op["op"], tuple(sorted(op.get("question_ids") or [])), *(str(op.get(t)) for t in _TARGETS))


async def run_refine_golden(cases_path: Path, llm: LLMClient) -> tuple[int, int]:
    """(passed, total). A case's `doc_fixture` is a JSON file next to the cases in `fixtures/`: an RFP's
    `{"questions": [...]}` or a deck's JSON. Ops are compared as a list, in order."""
    cases = json.loads(cases_path.read_text(encoding="utf-8"))["cases"]
    passed = 0
    for c in cases:
        document = json.loads((cases_path.parent / "fixtures" / f"{c['doc_fixture']}.json").read_text(encoding="utf-8"))
        kind = "rfp" if "questions" in document else "deck"
        out, _ = await llm.complete_structured(
            system=_SYSTEM[kind], prompt=build_prompt(kind, document, c["message"], c["history"]), output_model=RefineOps)
        got = [_key(op.model_dump(exclude_none=True)) for op in out.ops]
        passed += got == [_key(op) for op in c["expected_ops"]]
    return passed, len(cases)
