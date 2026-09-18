from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from arp.decision.parsing import load_table
from arp.schemas.common import new_id, now_iso

DatasetSource = str  # "upload" | "transition_plan_run" | "portfolio_snapshot" | "theme_run" | "extraction_run"


class Dataset(BaseModel):
    """One row per entity, one column per indicator, every cell still a
    string -- typing happens in `profiling`, against the values.

    `confidence` is the hook that makes this more than a spreadsheet
    reader: a table built from an extraction run carries a per-cell
    confidence, so the scorer can report how much of an entity's weight
    rests on independently verified values rather than only how much of it
    is present at all.
    """

    dataset_id: str = Field(default_factory=lambda: new_id("ds"))
    name: str
    columns: list[str]
    rows: list[dict[str, str]]
    confidence: dict[str, list[float | None]] = Field(
        default_factory=dict, description="column -> per-row confidence in [0,1], where the source supplies one."
    )
    source: DatasetSource = "upload"
    source_ref: str | None = Field(default=None, description="Run id, snapshot date or file path the table came from.")
    as_of: str | None = Field(default=None, description="The snapshot this table represents, for period-on-period comparison.")
    created_at: str = Field(default_factory=now_iso)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def column_values(self, column: str) -> list[str]:
        return [r.get(column, "") for r in self.rows]

    def confidence_values(self, column: str) -> list[float | None]:
        return self.confidence.get(column) or [None] * len(self.rows)


def build_dataset(name: str, matrix: list[list[str]], **kwargs) -> Dataset:
    """Header row + body -> Dataset. Blank headers are named positionally
    and duplicates are suffixed, so a column is always addressable even
    when the source export is careless."""
    if not matrix:
        raise ValueError("Empty table.")
    header = [str(h).strip() or f"Column {i + 1}" for i, h in enumerate(matrix[0])]
    seen: dict[str, int] = {}
    columns: list[str] = []
    for h in header:
        seen[h] = seen.get(h, 0) + 1
        columns.append(h if seen[h] == 1 else f"{h}_{seen[h]}")
    rows = [{c: (r[i].strip() if i < len(r) and r[i] is not None else "") for i, c in enumerate(columns)} for r in matrix[1:]]
    return Dataset(name=name, columns=columns, rows=rows, **kwargs)


def dataset_from_file(path: Path | str, **kwargs) -> Dataset:
    p = Path(path)
    return build_dataset(p.name, load_table(p), source_ref=str(p), **kwargs)
