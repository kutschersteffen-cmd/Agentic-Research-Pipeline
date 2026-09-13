from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from arp.replication._wide_csv import read_wide_csv


@dataclass
class PricePanel:
    """A ticker x month-end panel of simple (non-log) periodic returns,
    the common input every signal/backtest function in this package
    consumes -- deliberately the only shape a PriceDataSource has to
    produce, so a new data vendor is a new adapter here, never a change to
    signals.py/backtest_engine.py.

    `returns[ticker][i]` is the simple return from `period_ends[i-1]` to
    `period_ends[i]` (index 0 is always None -- there's no prior period to
    return from). A ticker missing data for a period holds None there
    rather than 0.0, so the backtest engine can tell "no data" from "flat".
    """

    period_ends: list[str]
    returns: dict[str, list[float | None]]
    source: str

    def tickers(self) -> list[str]:
        return list(self.returns.keys())


class PriceDataSource(ABC):
    """Pluggable market-data adapter. The backtest engine only ever talks
    to this interface, never a vendor SDK directly -- see README's data
    source discussion: start free (CsvPriceSource, YFinancePriceSource),
    swap in a paid point-in-time vendor later without touching signals.py,
    backtest_engine.py, or the pipeline that calls them.
    """

    name: str

    @abstractmethod
    def get_monthly_returns(self, tickers: list[str], start: str, end: str) -> PricePanel:
        """Simple monthly returns for `tickers` over [start, end] (ISO
        dates). Tickers with no data anywhere in the window may be omitted
        entirely rather than included as all-None columns."""
        raise NotImplementedError


class CsvPriceSource(PriceDataSource):
    """Reads a wide CSV: a `date` column (ISO, one row per period-end) plus
    one column per ticker. Values are prices by default (returns are
    derived period-over-period); pass `kind=\"return\"` if the CSV already
    holds periodic returns (e.g. exported from a vendor that only shares
    returns, not raw prices). Free, no network, no API key -- the default
    adapter, and the only one covered by this project's no-network unit
    tests.
    """

    name = "csv"

    def __init__(self, path: Path, kind: str = "price") -> None:
        if kind not in ("price", "return"):
            raise ValueError(f"kind must be 'price' or 'return', got {kind!r}")
        self.path = path
        self.kind = kind

    def get_monthly_returns(self, tickers: list[str], start: str, end: str) -> PricePanel:
        dates, columns = read_wide_csv(self.path)
        wanted = set(tickers)
        missing = wanted - set(columns)
        if missing:
            raise ValueError(f"{self.path}: no column(s) for {sorted(missing)}")

        keep_idx = [i for i, d in enumerate(dates) if start <= d <= end]
        period_ends = [dates[i] for i in keep_idx]
        returns: dict[str, list[float | None]] = {}
        for t in tickers:
            series = [columns[t][i] for i in keep_idx]
            if self.kind == "return":
                returns[t] = series
                if returns[t]:
                    returns[t][0] = None
                continue
            rets: list[float | None] = [None]
            for i in range(1, len(series)):
                prev, cur = series[i - 1], series[i]
                rets.append((cur / prev - 1.0) if (prev not in (None, 0) and cur is not None) else None)
            returns[t] = rets
        return PricePanel(period_ends=period_ends, returns=returns, source=self.name)


class YFinancePriceSource(PriceDataSource):
    """Free real-market adapter backed by Yahoo Finance via the `yfinance`
    package (opt-in extra: `pip install -e \".[replication]\"`). Adjusted
    close, resampled to month-end. No survivorship-bias handling and no
    point-in-time index-membership reconstruction -- see
    docs/STRATEGY_REPLICATION_METHODOLOGY.md for exactly what this does and
    doesn't correct for; a paid point-in-time vendor is a straightforward
    second PriceDataSource implementation when that matters.
    """

    name = "yfinance"

    def __init__(self) -> None:
        try:
            import yfinance  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "YFinancePriceSource requires the 'yfinance' package: pip install -e '.[replication]'"
            ) from exc

    def get_monthly_returns(self, tickers: list[str], start: str, end: str) -> PricePanel:
        import yfinance as yf

        data = yf.download(
            tickers, start=start, end=end, interval="1mo", auto_adjust=True, progress=False, group_by="ticker"
        )
        if data is None or len(data) == 0:
            return PricePanel(period_ends=[], returns={t: [] for t in tickers}, source=self.name)

        period_ends = [d.strftime("%Y-%m-%d") for d in data.index]
        returns: dict[str, list[float | None]] = {}
        for t in tickers:
            try:
                closes = data[(t, "Close")] if len(tickers) > 1 else data["Close"]
            except KeyError:
                returns[t] = [None] * len(period_ends)
                continue
            series = [float(v) if v == v else None for v in closes.tolist()]  # v == v filters NaN
            rets: list[float | None] = [None]
            for i in range(1, len(series)):
                prev, cur = series[i - 1], series[i]
                rets.append((cur / prev - 1.0) if (prev not in (None, 0) and cur is not None) else None)
            returns[t] = rets
        return PricePanel(period_ends=period_ends, returns=returns, source=self.name)
