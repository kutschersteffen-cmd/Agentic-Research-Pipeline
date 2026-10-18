from __future__ import annotations

from datetime import date


def today() -> date:
    """The one clock for run dates and ages; tests monkeypatch it."""
    return date.today()
