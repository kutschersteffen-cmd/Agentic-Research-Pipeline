"""Notes on a company (spec `stewardship-priority-worklist`): comments and remarks, kept across quarters, add-only.

The log is `notes/notes.jsonl`; no route edits or deletes a note, and notes change no score.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from arp.schemas.common import new_id
from arp.storage.jsonl_io import read_jsonl

MAX = 2000
PREVIEW = 120


class NoteLog:
    def __init__(self, root: Path) -> None:
        self.path = root / "notes" / "notes.jsonl"

    def add(self, company_id: str, text: str, by: str, scope: str) -> dict:
        text = text.strip()
        if not 1 <= len(text) <= MAX:
            raise ValueError("A note needs 1 to 2,000 characters")
        note = {"note_id": new_id("note"), "company_id": company_id, "text": text, "by": by, "at": datetime.now(UTC).isoformat(), "scope": scope}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(note, ensure_ascii=False) + "\n")
        return note

    def notes(self, company_id: str) -> list[dict]:
        """The company's notes, last appended first."""
        return [n for n in reversed(read_jsonl(self.path)) if n["company_id"] == company_id]

    def summary(self) -> dict[str, dict]:
        """company_id -> {"count", "latest": {"text" (first 120 characters), "by", "at"}} for companies with notes."""
        out: dict[str, dict] = {}
        for n in read_jsonl(self.path):
            s = out.setdefault(n["company_id"], {"count": 0})
            s["count"] += 1
            s["latest"] = {"text": n["text"][:PREVIEW], "by": n["by"], "at": n["at"]}
        return out
