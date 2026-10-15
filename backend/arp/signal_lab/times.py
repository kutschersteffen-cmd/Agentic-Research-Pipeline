from __future__ import annotations

import calendar
import hashlib
from datetime import UTC, date, datetime

_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _end_of_day(d: date) -> str:
    return f"{d.isoformat()}T23:59:59Z"


def normalise_time(value: str) -> str:
    """Canonical UTC-to-the-second string. Date-only means end of that day, conservatively."""
    if len(value) == 10:
        return _end_of_day(date.fromisoformat(value))
    parsed = datetime.fromisoformat(value.upper())
    if parsed.tzinfo is None:
        raise ValueError(f"time without an offset is ambiguous: {value!r}")
    return parsed.astimezone(UTC).strftime(_FORMAT)


def month_end_time(period_end: str) -> str:
    """The last second of the calendar month containing the ISO date."""
    d = date.fromisoformat(period_end)
    return _end_of_day(d.replace(day=calendar.monthrange(d.year, d.month)[1]))


def content_hash_of(title: str, body: str) -> str:
    return hashlib.sha256(f"{title}\n{body}".encode()).hexdigest()
