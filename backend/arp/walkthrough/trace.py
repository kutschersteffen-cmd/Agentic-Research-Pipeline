from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from arp.llm.base import LLMUsage
from arp.schemas.common import DocumentChunk
from arp.storage.safe_path import safe_id

logger = logging.getLogger(__name__)


def passage(chunk: DocumentChunk) -> dict:
    return {
        "doc_id": chunk.doc_id,
        "char_start": chunk.char_start,
        "char_end": chunk.char_end,
        "section": chunk.section,
    }


def call(usage: LLMUsage | None, answer: BaseModel | None) -> dict | None:
    if answer is None:
        return None
    return {
        "model": usage.model if usage else "",
        "prompt_version": usage.prompt_version if usage else "",
        "answer": answer.model_dump(mode="json"),
    }


def verifier_call(usage: LLMUsage | None, answer: BaseModel | None, *, blind: bool, verdict: BaseModel | None) -> dict | None:
    entry = call(usage, answer)
    if entry is None and verdict is not None:  # a blind re-extraction that failed still has the code's verdict
        entry = {"model": usage.model if usage else "", "prompt_version": usage.prompt_version if usage else "", "answer": None}
    if entry is None:
        return None
    entry["blind"] = blind
    entry["verdict"] = verdict.model_dump(mode="json") if verdict is not None else None
    return entry


def field_entry(
    field_id: str,
    *,
    grouped: bool = False,
    skipped: str | None = None,
    passages: list[dict] = (),
    extractor: dict | None = None,
    verifier: dict | None = None,
    adjudicator: dict | None = None,
    vision: dict | None = None,
    routing: dict | None = None,
) -> dict:
    return {
        "field_id": field_id,
        "grouped": grouped,
        "skipped": skipped,
        "passages": list(passages),
        "extractor": extractor,
        "verifier": verifier,
        "adjudicator": adjudicator,
        "vision": vision,
        "routing": routing,
    }


def trace_path(run_store, run_id: str, company_id: str) -> Path:
    return run_store.run_dir(run_id) / "traces" / f"{safe_id(company_id, label='company id')}.json"


def write_trace(run_store, run_id: str, company_id: str, trace: dict) -> None:
    """Best effort: a trace is a nice-to-have and must never fail a run."""
    if not trace:
        return
    try:
        path = trace_path(run_store, run_id, company_id)
        path.parent.mkdir(exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(trace), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        logger.warning("could not write trace for run %s company %s", run_id, company_id, exc_info=True)
        try:
            run_store.append_event(
                run_id,
                {"type": "trace_write_failed", "company_id": company_id, "at": datetime.now(UTC).isoformat()},
            )
        except Exception:
            logger.warning("could not record trace_write_failed for run %s", run_id, exc_info=True)


def read_trace(run_store, run_id: str, company_id: str) -> dict | None:
    try:
        return json.loads(trace_path(run_store, run_id, company_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
