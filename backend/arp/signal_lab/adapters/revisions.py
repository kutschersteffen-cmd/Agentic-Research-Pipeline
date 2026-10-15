from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Protocol

from arp.replication.characteristics_data import CharacteristicPanel
from arp.signal_lab.times import month_end_time, normalise_time

_REQUIRED = ("issuer_key", "event_time", "direction")


class RevisionSource(Protocol):
    def get_panel(
        self, issuer_keys: list[str], period_ends: list[str], *, window_months: int = 3
    ) -> CharacteristicPanel: ...


def _window_start(period_end: str, window_months: int) -> str:
    d = date.fromisoformat(period_end)
    k = d.year * 12 + d.month - 1 - (window_months - 1)  # calendar math, so index 0 may reach before the grid
    return f"{k // 12:04d}-{k % 12 + 1:02d}-01T00:00:00Z"


class CsvRevisionSource:
    """EPS revisions as a net ratio (up - down) / (up + down), event time only."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def _revisions(self) -> list[tuple[str, str, int]]:
        out: list[tuple[str, str, int]] = []
        with self._path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            missing = [c for c in _REQUIRED if c not in (reader.fieldnames or [])]
            if missing:
                raise ValueError(f"{self._path.name}: missing column(s) {', '.join(missing)}")
            for n, row in enumerate(reader, start=1):  # data rows are 1-based; header is row 0
                issuer, when, direction = ((row[c] or "").strip() for c in _REQUIRED)
                if not issuer or not when:
                    raise ValueError(f"{self._path.name} row {n}: issuer_key and event_time are required")
                if direction not in ("up", "down"):
                    raise ValueError(f"{self._path.name} row {n}: direction must be 'up' or 'down', got {direction!r}")
                try:
                    moment = normalise_time(when)
                except ValueError as exc:
                    raise ValueError(f"{self._path.name} row {n}: {exc}") from exc
                out.append((issuer, moment, 1 if direction == "up" else -1))
        return out

    def get_panel(
        self, issuer_keys: list[str], period_ends: list[str], *, window_months: int = 3
    ) -> CharacteristicPanel:
        if window_months < 1:
            raise ValueError("window_months must be >= 1")
        by_issuer: dict[str, list[tuple[str, int]]] = {}
        for issuer, moment, sign in self._revisions():
            by_issuer.setdefault(issuer, []).append((moment, sign))
        windows = [(_window_start(p, window_months), month_end_time(p)) for p in period_ends]
        values: dict[str, list[float | None]] = {}
        for key in issuer_keys:
            col: list[float | None] = []
            for lo, hi in windows:
                signs = [s for m, s in by_issuer.get(key, []) if lo <= m <= hi]
                col.append(sum(signs) / len(signs) if signs else None)
            values[key] = col
        return CharacteristicPanel(period_ends=list(period_ends), values=values, source="analyst_revisions")
