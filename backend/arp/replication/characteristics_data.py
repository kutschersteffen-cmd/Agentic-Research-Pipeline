from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from arp.replication._wide_csv import read_wide_csv


@dataclass
class CharacteristicPanel:
    """A ticker x month-end panel of one cross-sectional fundamental/
    characteristic (e.g. book-to-market), the input a characteristic-based
    signal (SignalType.VALUE and, later, quality/size/etc.) scores on --
    the counterpart to PricePanel for signals that aren't computed from
    price history alone.

    Unlike PricePanel, values here are levels (a ratio, a ranking variable
    -- whatever the paper's own characteristic is), not returns: there is
    no index-0-is-always-None convention, since a characteristic doesn't
    need a prior period to be defined.
    """

    period_ends: list[str]
    values: dict[str, list[float | None]]
    source: str

    def tickers(self) -> list[str]:
        return list(self.values.keys())


class CsvCharacteristicSource:
    """Reads a wide CSV: a `date` column (ISO, one row per period-end,
    typically the same monthly grid as the price panel it's paired with --
    a fundamental reported less often, e.g. annually, is expected to
    already be forward-filled onto that grid by whoever prepared the file)
    plus one column per ticker holding the raw characteristic level (e.g.
    book-to-market ratio). No return derivation, no shifting -- this is a
    plain lookup table.
    """

    name = "csv"

    def __init__(self, path: Path) -> None:
        self.path = path

    def get_values(self, tickers: list[str], start: str, end: str) -> CharacteristicPanel:
        dates, columns = read_wide_csv(self.path)
        wanted = set(tickers)
        missing = wanted - set(columns)
        if missing:
            raise ValueError(f"{self.path}: no column(s) for {sorted(missing)}")

        keep_idx = [i for i, d in enumerate(dates) if start <= d <= end]
        period_ends = [dates[i] for i in keep_idx]
        values = {t: [columns[t][i] for i in keep_idx] for t in tickers}
        return CharacteristicPanel(period_ends=period_ends, values=values, source=self.name)
