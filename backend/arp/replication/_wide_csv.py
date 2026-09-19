from __future__ import annotations

import csv
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
        reader = csv.DictReader(f)
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
