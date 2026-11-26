from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path


def read_wide_csv(path: Path) -> tuple[list[str], dict[str, list[float | None]]]:
    """Shared reader for this package's wide-CSV convention: a `date`
    column (first column, one row per period-end) plus one column per
    ticker. Used by both CsvPriceSource (arp/replication/price_data.py)
    and CsvCharacteristicSource (arp/replication/characteristics_data.py)
    -- the two differ only in what they do with the raw column values
    (derive returns vs. use levels directly), not in how the file is
    parsed.
    """
    with path.open(newline="") as f:
        # Empty lines are not data (check_wide_csv skips them too); a leading one would otherwise be read as the header.
        reader = csv.DictReader(line for line in f if line.strip("\r\n"))
        if reader.fieldnames is None:
            raise ValueError(f"{path}: empty CSV")
        date_col = reader.fieldnames[0]
        tickers = [c for c in reader.fieldnames[1:] if c]
        dates: list[str] = []
        columns: dict[str, list[float | None]] = {t: [] for t in tickers}
        for row in reader:
            dates.append(row[date_col])
            for t in tickers:
                raw = (row.get(t) or "").strip()
                columns[t].append(float(raw) if raw else None)
    return dates, columns


_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _rows(reader):
    """Rows of `reader`; a parser failure (a cell over csv's field limit, a NUL byte) is a reason like any other."""
    try:
        yield from reader
    except csv.Error as exc:
        raise ValueError(f"{exc}.") from None


def _is_calendar_date(text: str) -> bool:
    if not _ISO_DATE.fullmatch(text):
        return False
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


@dataclass
class WideCsvSummary:
    tickers: list[str]
    rows: int
    first_date: str
    last_date: str


def check_wide_csv(data: bytes) -> WideCsvSummary:
    """Check an uploaded file against the layout `read_wide_csv` reads and say what it holds.

    Raises ValueError with the reason (the part after "Not a usable CSV: ") at the first failure, top to bottom
    and left to right. Row numbers are file line numbers counted from 1; empty lines are skipped.
    """
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("not UTF-8 text.") from None
    reader = csv.reader(io.StringIO(text, newline=""))
    header = next((row for row in _rows(reader) if row), None)
    if header is None:
        raise ValueError("the file is empty.")
    if sum(1 for name in header if name) < 2:
        raise ValueError("needs a date column and at least one ticker column.")
    columns = [(i, name) for i, name in enumerate(header) if i > 0 and name]
    dates: list[str] = []
    rows = _rows(reader)
    for row in rows:
        if not row:
            continue
        r = reader.line_num
        day = row[0][:10]
        if not _is_calendar_date(day):
            raise ValueError(f'row {r}: date "{row[0]}" does not start with YYYY-MM-DD.')
        for i, name in columns:
            cell = row[i].strip() if i < len(row) else ""
            if cell:
                try:
                    float(cell)
                except ValueError:
                    raise ValueError(f'row {r}, column {name}: "{cell}" is not a number.') from None
        dates.append(day)
    if not dates:
        raise ValueError("no data rows.")
    return WideCsvSummary(tickers=[name for _, name in columns], rows=len(dates), first_date=dates[0], last_date=dates[-1])
