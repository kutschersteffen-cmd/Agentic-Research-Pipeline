from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from arp.api.deps import get_llm_client
from arp.llm.base import LLMClient


def schedule_llm_run(*, create_fn: Callable[[], str], run: Callable[[str, LLMClient], Awaitable[None]]) -> str:
    """The shared shape of every `POST /runs` endpoint that needs an LLM
    (themes, extraction, financials, voting, identity): resolve the LLM
    client FIRST, so a missing/invalid key fails before any run manifest
    exists, then create the run and schedule its background execution.

    This ordering is not incidental -- it's the exact fix for a bug where
    every one of these five endpoints independently created the manifest
    *before* calling get_llm_client(), leaving an orphaned "running"
    manifest forever when the key check failed (the background task that
    would have called finish_run() never got scheduled). Centralizing the
    order here means a sixth run-creation endpoint gets the fix for free
    instead of needing the same two-line reordering applied by hand.

    `create_fn` takes no arguments (none of the create_X_run functions
    need the LLM client) and returns the new run_id. `run` receives the
    run_id and the resolved LLM client and does the actual pipeline work;
    it's scheduled as a background asyncio task, not awaited here, so the
    endpoint returns immediately.
    """
    llm = get_llm_client()
    run_id = create_fn()
    asyncio.create_task(run(run_id, llm))
    return run_id
