"""Test stand-ins: with ARP_STANDINS_DIR set, web search, source fetches and model calls are answered
from fixture files in that folder instead of the network (docs/superpowers/specs/2026-10-25-test-stand-ins-design.md).
Files are read on every call so a test can rewrite them between requests; every call is logged to calls.jsonl."""

from __future__ import annotations

import asyncio
import fcntl
import json
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from arp.config import get_settings
from arp.discovery.site_finder import SearchResult, WebSearchClient
from arp.llm.base import LLMUsage

T = TypeVar("T", bound=BaseModel)

_MISSING = object()


def active_dir() -> Path | None:
    return get_settings().standins_dir


def _record(folder: Path, entry: dict[str, Any]) -> None:
    line = (json.dumps(entry) + "\n").encode("utf-8")
    with open(folder / "calls.jsonl", "ab") as f:
        fcntl.flock(f, fcntl.LOCK_EX)  # one whole line per call, even across worker processes
        f.write(line)


def _read(path: Path) -> Any:
    """The file's JSON, or _MISSING when it does not exist. Raises ValueError when it is not valid JSON."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _MISSING
    return json.loads(text)


async def _delay(entry: Any) -> None:
    if isinstance(entry, dict) and entry.get("delay_seconds"):
        await asyncio.sleep(float(entry["delay_seconds"]))


class StandInLLMClient:
    def __init__(self, folder: Path) -> None:
        self._folder = folder

    async def complete_structured(
        self,
        *,
        system: str,
        prompt: str,
        output_model: type[T],
        max_validation_retries: int = 2,
        temperature: float = 0.0,
        max_tokens: int = 8192,
        images: list[bytes] | None = None,
    ) -> tuple[T, LLMUsage]:
        name = output_model.__name__
        _record(self._folder, {"kind": "model", "name": name, "system": system, "prompt": prompt})
        try:
            entry = _read(self._folder / "model" / f"{name}.json")
        except ValueError:
            raise RuntimeError(f"stand-in model/{name}.json is not valid JSON") from None
        if entry is _MISSING:
            raise RuntimeError(f"no stand-in for {name}")
        await _delay(entry)
        if isinstance(entry, dict) and "error" in entry:
            raise RuntimeError(str(entry["error"]))
        try:
            output = output_model.model_validate(entry.get("output") if isinstance(entry, dict) else None)
        except ValidationError as exc:
            first = exc.errors()[0]
            where = ".".join(str(p) for p in first["loc"]) or "(root)"
            raise RuntimeError(f"stand-in model/{name}.json does not match {name}: {where}: {first['msg']}") from None
        return output, LLMUsage(provider="stand-in", model="stand-in")


class StandInSearchClient(WebSearchClient):
    def __init__(self, folder: Path) -> None:
        self._folder = folder

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        _record(self._folder, {"kind": "search", "query": query})
        try:
            entry = _read(self._folder / "search.json")
        except ValueError:
            raise RuntimeError("stand-in search.json is not valid JSON") from None
        if entry is _MISSING:
            raise RuntimeError("no stand-in for web search")
        await _delay(entry)
        if isinstance(entry, dict) and "error" in entry:
            raise RuntimeError(str(entry["error"]))
        try:
            return [SearchResult.model_validate(r) for r in entry.get("results", [])]  # max_results ignored by design
        except (AttributeError, TypeError, ValidationError):
            raise RuntimeError("stand-in search.json does not match {\"results\": [{\"title\", \"url\", \"snippet\"}]}") from None


async def fetch_text(folder: Path, url: str) -> str | None:
    """The fetch.json `text` for `url`, or None for anything a real fetch would fail on."""
    _record(folder, {"kind": "fetch", "url": url})
    try:
        entries = _read(folder / "fetch.json")
    except ValueError:
        return None
    entry = entries.get(url) if isinstance(entries, dict) else None
    await _delay(entry)
    if not isinstance(entry, dict) or not isinstance(entry.get("text"), str):
        return None
    return entry["text"]
