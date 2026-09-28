from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from arp.api.deps import get_llm_client, get_verifier_llm_client
from arp.config import Settings
from arp.llm.base import LLMClient
from arp.llm.factory import build_llm_client, build_verifier_llm_client


def schedule_llm_run(
    *,
    create_fn: Callable[[], str],
    run: Callable[[str, LLMClient, LLMClient], Awaitable[None]],
    settings: Settings | None = None,
) -> str:
    """The shared shape of every `POST /runs` endpoint that needs an LLM
    (themes, extraction, financials, voting, identity): resolve both LLM
    clients FIRST, so a missing/invalid key fails before any run manifest
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
    run_id, the resolved extractor-role client, and the resolved
    verifier-role client (on a different model -- see
    build_verifier_llm_client), and does the actual pipeline work; it's
    scheduled as a background asyncio task, not awaited here, so the
    endpoint returns immediately. A `run` for a pipeline with no separate
    verifier role (e.g. voting, identity) simply ignores the third arg.

    `settings`, when given, builds both clients from it rather than the
    app's settings -- how a run started with its own models gets them.
    """
    llm = build_llm_client(settings) if settings else get_llm_client()
    verifier_llm = build_verifier_llm_client(settings) if settings else get_verifier_llm_client()
    run_id = create_fn()
    asyncio.create_task(run(run_id, llm, verifier_llm))
    return run_id
