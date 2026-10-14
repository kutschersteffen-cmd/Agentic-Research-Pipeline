from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError, field_validator


class ModelCutoff(BaseModel):
    cutoff: str
    source: str

    # Cutoffs are compared as strings against period ends, so only YYYY-MM-DD orders correctly; "2024" would fail open.
    @field_validator("cutoff")
    @classmethod
    def _iso_date(cls, v: str) -> str:
        try:
            ok = datetime.date.fromisoformat(v).isoformat() == v
        except ValueError:
            ok = False
        if not ok:
            raise ValueError(f"cutoff must be a YYYY-MM-DD date, got {v!r}")
        return v


class CutoffTable(BaseModel):
    entries: dict[str, ModelCutoff]

    def cutoff_for(self, model: str) -> str | None:
        entry = self.entries.get(model)
        return entry.cutoff if entry else None


def load_cutoff_table(path: Path) -> CutoffTable:
    if not path.exists():
        return CutoffTable(entries={})
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: malformed JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected an object mapping model name to cutoff entry")
    entries: dict[str, ModelCutoff] = {}
    for model, entry in raw.items():
        try:
            entries[model] = ModelCutoff.model_validate(entry)
        except ValidationError as exc:
            raise ValueError(f"{path}: invalid cutoff entry for model {model!r}: {exc}") from exc
    return CutoffTable(entries=entries)


def period_window(
    model: str | None, period_end: str, table: CutoffTable
) -> Literal["in_window", "post_cutoff"]:
    if model is None:
        return "post_cutoff"
    cutoff = table.cutoff_for(model)
    # Unknown cutoff: assume the model may have seen the period, so it never counts as evidence.
    if cutoff is None:
        return "in_window"
    return "post_cutoff" if period_end > cutoff else "in_window"
