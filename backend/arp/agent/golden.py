"""Exploration golden set (spec agent-panel-code-mode AC-51): real-model code for each question, run in the real
`sandbox/` service; a case passes when the run is `done` and called every expected capability at least once."""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse

import httpx

from arp.agent.explorations import run_question
from arp.api.auth import Principal
from arp.config import Settings
from arp.llm.base import LLMClient

SANDBOX_DIR = Path(__file__).resolve().parents[3] / "sandbox"
PRINCIPAL = Principal(user_id="golden", name="golden", role="analyst")


def load_cases(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


async def run_case(settings: Settings, llm: LLMClient, case: dict) -> str | None:
    """None when the case passes; else why not."""
    try:
        _code, _model, _cost, run = await run_question(settings, case["question"], PRINCIPAL, llm=llm)
    except Exception as exc:  # noqa: BLE001 - a failed call fails the case, not the run
        return f"model call failed: {type(exc).__name__}: {exc}"
    if run["status"] != "done":
        return f"{run['status']}: {run['error']}"
    called = {c["capability_id"] for c in run["tool_calls"]}
    missing = [c for c in case["expected_capabilities"] if c not in called]
    return f"did not call {', '.join(missing)}" if missing else None


def _answers(url: str) -> bool:
    try:
        return httpx.get(f"{url.rstrip('/')}/health", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait(url: str, what: str, seconds: float = 60) -> None:
    end = time.monotonic() + seconds
    while not _answers(url):
        if time.monotonic() > end:
            raise RuntimeError(f"{what} did not start at {url}")
        time.sleep(0.2)


@contextmanager
def tool_route() -> Iterator[str]:
    """Serves the sandbox tool route from this process, where the execution tokens are minted; yields its origin."""
    import uvicorn
    from fastapi import FastAPI

    from arp.api.routers import sandbox_tools

    app = FastAPI()
    app.include_router(sandbox_tools.router)
    app.get("/health")(lambda: {"ok": True})
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{port}"
    try:
        _wait(origin, "the tool route")
        yield origin
    finally:
        server.should_exit = True
        thread.join(10)


@contextmanager
def sandbox_service(settings: Settings, api_origin: str) -> Iterator[None]:
    """Starts `sandbox/` on ARP_SANDBOX_URL's port, calling `api_origin`, unless something already answers there. A
    sandbox that already answers sends its tool calls to its own ARP_API_URL, so it must be the one that serves this
    process's tokens; stop it to let this command start its own."""
    if _answers(settings.sandbox_url):
        yield
        return
    npm = shutil.which("npm")
    if npm is None:
        raise RuntimeError(f"nothing answers at {settings.sandbox_url} and npm is not installed to start sandbox/")
    if not (SANDBOX_DIR / "node_modules").is_dir():
        subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=SANDBOX_DIR, check=True, capture_output=True)
    subprocess.run([npm, "run", "build"], cwd=SANDBOX_DIR, check=True, capture_output=True)
    port = urlparse(settings.sandbox_url).port or 8790
    # An empty environment apart from PATH and HOME, as e2e_stack.sh starts it, so no secret reaches it.
    env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""), "ARP_API_URL": api_origin,
           "ARP_SANDBOX_PORT": str(port)}
    proc = subprocess.Popen(["node", "server.mjs"], cwd=SANDBOX_DIR, env=env, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    try:
        _wait(settings.sandbox_url, "sandbox/")
        yield
    finally:
        proc.terminate()
        proc.wait(10)
