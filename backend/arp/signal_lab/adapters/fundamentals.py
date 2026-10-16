from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Protocol

from arp.replication.characteristics_data import CharacteristicPanel
from arp.signal_lab.times import month_end_time, normalise_time

_REQUIRED = ("issuer_key", "metric", "fiscal_period_end", "available_time", "value")


class FundamentalSource(Protocol):
    def get_panel(self, metric: str, issuer_keys: list[str], period_ends: list[str]) -> CharacteristicPanel: ...


class CsvFundamentalSource:
    """As-reported fundamentals: a restatement replaces a value only from its available_time."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def _rows(self) -> list[tuple[str, str, str, str, float]]:
        out: list[tuple[str, str, str, str, float]] = []
        with self._path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            missing = [c for c in _REQUIRED if c not in (reader.fieldnames or [])]
            if missing:
                raise ValueError(f"{self._path.name}: missing column(s) {', '.join(missing)}")
            for n, row in enumerate(reader, start=1):  # data rows are 1-based; header is row 0
                issuer, metric, period, avail, raw = ((row[c] or "").strip() for c in _REQUIRED)
                if not (issuer and metric and period and avail and raw):
                    raise ValueError(f"{self._path.name} row {n}: all columns are required")
                try:
                    period_m, avail_m = normalise_time(period), normalise_time(avail)
                    value = float(raw)
                except ValueError as exc:
                    raise ValueError(f"{self._path.name} row {n}: {exc}") from exc
                if not math.isfinite(value):
                    raise ValueError(f"{self._path.name} row {n}: value must be finite, got {raw!r}")
                out.append((issuer, metric, period_m, avail_m, value))
        return out

    def get_panel(self, metric: str, issuer_keys: list[str], period_ends: list[str]) -> CharacteristicPanel:
        by_issuer: dict[str, list[tuple[str, str, float]]] = {}
        for issuer, m, period, avail, value in self._rows():  # every row is validated, even other metrics
            if m == metric:
                by_issuer.setdefault(issuer, []).append((period, avail, value))
        values: dict[str, list[float | None]] = {}
        for key in issuer_keys:
            col: list[float | None] = []
            for p in period_ends:
                cutoff = month_end_time(p)
                seen = [r for r in by_issuer.get(key, []) if r[1] <= cutoff]
                # max returns the first maximum, so scan reversed: a full tie goes to the last file row
                best = max(reversed(seen), key=lambda r: (r[0], r[1]), default=None)
                col.append(best[2] if best else None)
            values[key] = col
        return CharacteristicPanel(period_ends=list(period_ends), values=values, source=f"fundamentals:{metric}")
