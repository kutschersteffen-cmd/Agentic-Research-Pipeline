"""Readiness checks for a deployed ARP (`arp preflight`, `scripts/launch_jupyter.sh check`).

Seven lines, always all seven, in a fixed order: `ok <name>`, `skip <name>` or `FAIL <name>: <reason>`.
The model checks make one real call on exactly the configured model: no other provider is left
available, so a fallback cannot hide a model that does not answer.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import httpx
from pydantic import BaseModel

from arp.compute.client import _auth
from arp.config import Settings
from arp.db.session import require_cutover, require_postgres
from arp.llm.factory import build_llm_client


class _Ok(BaseModel):
    ok: bool


def _reason(exc: BaseException) -> str:
    return (str(exc).splitlines() or [type(exc).__name__])[0][:200]


async def _line(name: str, check: Callable[[], Awaitable[None]] | None) -> str:
    if check is None:
        return f"skip {name}"
    try:
        await check()
    except Exception as exc:  # noqa: BLE001 - every failure becomes its line; the later checks still run
        return f"FAIL {name}: {_reason(exc)}"
    return f"ok {name}"


async def run_preflight(
    settings: Settings, *, base_url: str = "http://127.0.0.1:8000", llm_factory=build_llm_client,
    http: httpx.AsyncClient | None = None,
) -> list[str]:
    client = http or httpx.AsyncClient(timeout=30, follow_redirects=True)

    async def postgres() -> None:
        await asyncio.to_thread(require_postgres, settings)
        await asyncio.to_thread(require_cutover, settings)

    def model(model_id: str) -> Callable[[], Awaitable[None]]:
        gemini = model_id.startswith("gemini-")
        only = settings.model_copy(update={"anthropic_api_key": None} if gemini else {"gemini_api_key": None, "gemini_use_vertex": False})

        async def check() -> None:
            llm = llm_factory(only, model=model_id, cache_refresh=True)
            await llm.complete_structured(system="Reply with JSON only.", prompt='Return {"ok": true}.', output_model=_Ok)

        return check

    def get(url: str, headers: Callable[[], dict[str, str]] = dict) -> Callable[[], Awaitable[None]]:
        async def check() -> None:
            response = await client.get(url, headers=headers())
            if response.status_code != 200:
                raise RuntimeError(f"{url} answered {response.status_code}")

        return check

    def compute(url: str | None) -> Callable[[], Awaitable[None]] | None:
        return get(f"{url.rstrip('/')}/healthz", lambda: _auth(url)) if url else None

    try:
        return [
            await _line("postgres", postgres),
            await _line(f"model {settings.llm_model}", model(settings.llm_model)),
            await _line(f"verifier {settings.llm_verifier_model}", model(settings.llm_verifier_model)),
            await _line("compute models", compute(settings.compute_models_url)),
            await _line("compute parse", compute(settings.compute_parse_url)),
            await _line("frontend", get(f"{base_url.rstrip('/')}/")),
            # sent as the document fetchers send it: sec.gov refuses a client without a contact User-Agent
            await _line("fetch", get(settings.preflight_fetch_url, lambda: {"User-Agent": settings.edgar_user_agent})),
        ]
    finally:
        if http is None:
            await client.aclose()
