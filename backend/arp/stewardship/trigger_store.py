"""Stewardship monitoring triggers, kept across monthly runs.

Append-only JSONL: `run` events record what a month's monitoring raised, `transition` events record
a person's decision. The current state is folded from the log; nothing is rewritten."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from arp.schemas.triggers import UnifiedTrigger

STATUSES = ("open", "acknowledged", "resolved")


def trigger_id(issuer_id: str, rule: str) -> str:
    return hashlib.sha256(f"{issuer_id}|{rule}".encode()).hexdigest()[:16]


class TriggerStore:
    def __init__(self, root: Path) -> None:
        self.path = root / "triggers" / "events.jsonl"

    def _append(self, row: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps({**row, "at": datetime.now(UTC).isoformat()}, ensure_ascii=False) + "\n")

    def _fold(self) -> dict[str, UnifiedTrigger]:
        rows = [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()] if self.path.exists() else []
        found: dict[str, UnifiedTrigger] = {}
        runs: dict[str, set[str]] = {}
        for row in rows:
            if row["event"] == "run":
                earlier = [m for m in runs if m < row["month"]]
                prev = runs[max(earlier)] if earlier else set()
                for t in row["triggers"]:
                    tid = trigger_id(t["issuer_id"], t["rule"])
                    # A resolved trigger that comes back after a month without it is open again.
                    if tid in found and tid not in prev and tid not in runs.get(row["month"], ()):
                        found[tid].status = "open"
                    runs.setdefault(row["month"], set()).add(tid)
                    found.setdefault(
                        tid,
                        UnifiedTrigger(
                            trigger_id=tid,
                            source="stewardship",
                            issuer_id=t["issuer_id"],
                            type=t["type"],
                            theme=t["theme"],
                            severity=t["severity"],
                            reason=t["reason"],
                            first_seen_month=row["month"],
                        ),
                    )
            elif row["trigger_id"] in found:
                found[row["trigger_id"]].status = row["status"]
        months = sorted(runs)
        latest, prev = (runs[months[-1]], runs[months[-2]] if len(months) > 1 else set()) if months else (set(), set())
        for tid in latest - prev:
            found[tid].is_new = True
        return found

    def record_run(self, month: str, triggers: list[dict]) -> list[UnifiedTrigger]:
        if any(not t.get("issuer_id") or not t.get("rule") for t in triggers):
            raise ValueError("Every trigger needs issuer_id and rule")
        self._append({"event": "run", "month": month, "triggers": triggers})
        found = self._fold()
        return [found[trigger_id(t["issuer_id"], t["rule"])] for t in triggers]

    def list_triggers(self, status: str | None = None) -> list[UnifiedTrigger]:
        return [t for t in self._fold().values() if status is None or t.status == status]

    def transition(self, trigger_id: str, status: str, decided_by: str, reason: str = "") -> UnifiedTrigger:
        if status not in STATUSES:
            raise ValueError(f"Unknown status {status!r}")
        if not decided_by.strip():
            raise ValueError("A trigger transition needs decided_by")
        if trigger_id not in self._fold():
            raise KeyError(trigger_id)
        self._append(
            {"event": "transition", "trigger_id": trigger_id, "status": status, "decided_by": decided_by, "reason": reason}
        )
        return self._fold()[trigger_id]
