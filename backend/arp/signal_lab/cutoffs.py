from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel


class ModelCutoff(BaseModel):
    cutoff: str
    source: str


class CutoffTable(BaseModel):
    entries: dict[str, ModelCutoff]

    def cutoff_for(self, model: str) -> str | None:
        entry = self.entries.get(model)
        return entry.cutoff if entry else None


def load_cutoff_table(path: Path) -> CutoffTable:
    if not path.exists():
        return CutoffTable(entries={})
    return CutoffTable(entries=json.loads(path.read_text()))


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
