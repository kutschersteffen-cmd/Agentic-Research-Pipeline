"""Board golden set (spec agent-board AC-32): real-model drafts over Done plan D's thread data."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from arp.agent_board.checks import BlockInvalid, check_block
from arp.agent_board.draw import SYSTEM, BoardBlockDraft, build_prompt, unverified
from arp.llm.base import LLMClient

# The spec's fixture "Done plan D": one stored index_construct call with two sector weights.
DONE_PLAN_D = {"brief": "Sector weights of the index", "status": "done", "steps": [
    {"seq": 1, "kind": "index_construct", "params": {}, "status": "done", "run_id": None,
     "result": {"weights": [{"sector": "Energy", "weight": 0.125}, {"sector": "Utilities", "weight": 0.31}]}},
]}


def load_cases(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


async def run_case(llm: LLMClient, case: dict) -> str | None:
    """None when the first draft passes every check, has the expected kind and no unverified number; else why not."""
    try:
        draft, _ = await llm.complete_structured(system=SYSTEM, prompt=build_prompt(case["prompt"], DONE_PLAN_D),
                                                 output_model=BoardBlockDraft)
    except Exception as exc:  # noqa: BLE001 - a failed call fails the case, not the run
        return f"model call failed: {exc}"
    if draft.kind != case["expected_kind"]:
        return f"kind {draft.kind}, expected {case['expected_kind']}"
    try:
        await asyncio.to_thread(check_block, draft.kind, draft.title, draft.source)
    except BlockInvalid as exc:
        return f"refused: {exc}"
    missing = unverified(draft.kind, draft.source, DONE_PLAN_D)
    return f"not in ARP data: {missing}" if missing else None
