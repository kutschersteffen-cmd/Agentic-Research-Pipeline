from __future__ import annotations

import csv
import io
from datetime import date, datetime

import openpyxl

from arp.schemas.reporting import ColumnKind, DatasetColumn, QuantitativeDataset


def _infer_kind(name: str, sample_values: list) -> ColumnKind:
    lname = name.lower()
    non_null = [v for v in sample_values if v not in (None, "")]
    if not non_null:
        return ColumnKind.CATEGORY
    if "%" in lname or "pct" in lname or "percent" in lname:
        return ColumnKind.PERCENT
    if all(isinstance(v, (date, datetime)) for v in non_null):
        return ColumnKind.DATE
    numeric = 0
    for v in non_null:
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            numeric += 1
            continue
        try:
            float(str(v).replace(",", ""))
            numeric += 1
        except ValueError:
            pass
    if numeric == len(non_null):
        return ColumnKind.NUMBER
    return ColumnKind.CATEGORY


def _coerce_row_value(kind: ColumnKind, value):
    if value in (None, ""):
        return None
    if kind in (ColumnKind.NUMBER, ColumnKind.PERCENT) and not isinstance(value, (int, float)):
        try:
            return float(str(value).replace(",", "").replace("%", ""))
        except ValueError:
            return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _build_dataset(name: str, header: list[str], raw_rows: list[list]) -> QuantitativeDataset:
    columns_data: dict[str, list] = {h: [row[i] if i < len(row) else None for row in raw_rows] for i, h in enumerate(header)}
    columns = [DatasetColumn(name=h, kind=_infer_kind(h, columns_data[h])) for h in header]
    kind_by_col = {c.name: c.kind for c in columns}
    rows = [{h: _coerce_row_value(kind_by_col[h], row[i] if i < len(row) else None) for i, h in enumerate(header)} for row in raw_rows]
    return QuantitativeDataset(name=name, columns=columns, rows=rows)


def parse_csv_dataset(name: str, content: bytes) -> QuantitativeDataset:
    text = content.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return QuantitativeDataset(name=name, columns=[], rows=[])
    header, data_rows = rows[0], rows[1:]
    return _build_dataset(name, header, data_rows)


def parse_xlsx_dataset(name: str, content: bytes) -> QuantitativeDataset:
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    try:
        header = [str(h) if h is not None else "" for h in next(rows_iter)]
    except StopIteration:
        return QuantitativeDataset(name=name, columns=[], rows=[])
    data_rows = [list(r) for r in rows_iter]
    return _build_dataset(name, header, data_rows)


def parse_tabular_upload(filename: str, content: bytes, name: str | None = None) -> QuantitativeDataset:
    """Parses an uploaded CSV/XLSX into a QuantitativeDataset with
    deterministic column-kind inference (never LLM-guessed) -- the Content
    Planner only ever sees the resulting `.summary()` text, not the raw
    file, so accepted formats stay purely a matter of what this function
    can read."""
    dataset_name = name or filename.rsplit(".", 1)[0]
    lower = filename.lower()
    if lower.endswith(".xlsx") or lower.endswith(".xlsm"):
        return parse_xlsx_dataset(dataset_name, content)
    return parse_csv_dataset(dataset_name, content)
