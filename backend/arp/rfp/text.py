"""The spec's shared text rules: normalised text, empty or placeholder, has figures, numbers."""

from __future__ import annotations

import re
from datetime import date

_PLACEHOLDER = re.compile(r"^\[[^\[\]]*\]$")
_NUMBER = re.compile(r"\d+(?:[.,'’]\d+)*")


def normalise(text: str) -> str:
    return " ".join(text.casefold().split()).strip(" ?:.;")


def is_placeholder(text: str) -> bool:
    """Empty or placeholder: nothing but whitespace, or one bracketed span such as `[Response]`."""
    stripped = text.strip()
    return not stripped or bool(_PLACEHOLDER.match(stripped))


def has_figures(text: str) -> bool:
    return bool(re.search(r"\d", text))


def numbers(text: str) -> set[str]:
    return {re.sub(r"[,'’]", "", m) for m in _NUMBER.findall(text)}


def plus_12_months(d: date) -> date:
    try:
        return d.replace(year=d.year + 1)
    except ValueError:  # 29 February
        return d.replace(year=d.year + 1, day=28)
