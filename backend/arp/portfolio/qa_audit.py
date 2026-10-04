"""Append-only audit of every Q&A answer: who asked what, a hash of the answer, and the data vintage behind it."""

from __future__ import annotations

import hashlib
import logging
import threading

from arp.api.auth import Principal
from arp.config import Settings
from arp.schemas.common import now_iso
from arp.storage.jsonl_io import append_jsonl, read_jsonl

logger = logging.getLogger(__name__)
_lock = threading.Lock()  # ponytail: one process-wide lock, enough for a single API process


def _path(settings: Settings):
    return settings.qa_audit_path or settings.portfolios_dir / "qa_audit.jsonl"


def record_answer(
    settings: Settings, *, endpoint: str, principal: Principal, question: str,
    answer_text: str | None, vintage: dict, error: str | None = None,
) -> None:
    row = {
        "at": now_iso(), "endpoint": endpoint, "user_id": principal.user_id, "user_name": principal.name,
        "question": question, "answer_sha256": hashlib.sha256((answer_text or "").encode()).hexdigest(),
        "vintage": vintage, "error": error,
    }
    try:
        with _lock:
            append_jsonl(_path(settings), row)
    except Exception:  # an audit-write failure must neither crash nor mask the answer
        logger.exception("qa audit write failed")


def list_audit(settings: Settings, *, limit: int = 200) -> list[dict]:
    rows = read_jsonl(_path(settings))[::-1][:limit]
    return [{k: v for k, v in r.items() if k != "user_id"} for r in rows]
