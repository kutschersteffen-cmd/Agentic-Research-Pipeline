from __future__ import annotations

import csv
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from arp.signal_lab.text_store import TextRecord, make_record

_REQUIRED = ("issuer_key", "event_time", "title", "text")


class TranscriptSource(Protocol):
    def records(self) -> list[TextRecord]: ...


class CsvTranscriptSource:
    def __init__(self, path: Path, *, now: str | None = None) -> None:
        self._path = path
        self._now = now

    def records(self) -> list[TextRecord]:
        now = self._now or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        out: list[TextRecord] = []
        with self._path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            missing = [c for c in _REQUIRED if c not in (reader.fieldnames or [])]
            if missing:
                raise ValueError(f"{self._path.name}: missing column(s) {', '.join(missing)}")
            for n, row in enumerate(reader, start=1):  # data rows are 1-based; header is row 0
                issuer, event_time = row["issuer_key"].strip(), row["event_time"].strip()
                if not issuer or not event_time:
                    raise ValueError(f"{self._path.name} row {n}: issuer_key and event_time are required")
                item_id = (row.get("source_item_id") or "").strip() or hashlib.sha256(
                    f"{issuer}|{event_time}|{row['title']}".encode()
                ).hexdigest()[:16]
                try:
                    out.append(
                        make_record(
                            source="transcript",
                            source_item_id=item_id,
                            company_id=issuer,
                            event_time=event_time,
                            knowledge_time=(row.get("knowledge_time") or "").strip() or now,
                            title=row["title"],
                            body=row["text"],
                        )
                    )
                except ValueError as exc:
                    raise ValueError(f"{self._path.name} row {n}: {exc}") from exc
        return out
