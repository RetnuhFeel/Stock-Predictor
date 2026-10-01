"""Market-data provider interface.

A provider turns a ticker into daily OHLCV bars and supports symbol search. Quotes are derived
from the last two daily bars by default (override ``quote`` if a provider has a better source).
Providers must raise the typed errors from ``app.errors`` (DataUnavailable / RateLimited /
UpstreamTimeout) and never leak raw library exceptions.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Callable

import pandas as pd

from .. import config
from ..errors import DataUnavailable, UpstreamTimeout

COLUMNS = ["Open", "High", "Low", "Close", "Volume"]

# yfinance-style period -> approximate number of trading-day bars
PERIOD_BARS = {"5d": 7, "1mo": 22, "3mo": 66, "6mo": 132, "1y": 253, "2y": 506, "5y": 1260}


class BaseProvider(ABC):
    name = "base"

    @abstractmethod
    def history(self, symbol: str, period: str) -> pd.DataFrame:
        """Daily bars, ascending DatetimeIndex (tz-naive dates), columns Open/High/Low/Close/Volume."""

    @abstractmethod
    def search(self, query: str) -> list[dict]:
        """[{"symbol", "name", "exchange"}, ...]"""

    def batch_history(self, symbols: list[str], period: str) -> dict[str, pd.DataFrame]:
        """Daily bars for many symbols; symbols that fail are simply absent from the result.

        Default: one ``history`` call per symbol. Providers with a real batch API should override this.
        Raises an upstream error only if nothing at all could be fetched."""
        out: dict[str, pd.DataFrame] = {}
        first: Exception | None = None
        for s in symbols:
            try:
                out[s] = self.history(s, period)
            except (DataUnavailable, UpstreamTimeout) as exc:
                first = first or exc
        if not out and first:
            raise first
        return out

    def news(self, symbol: str) -> list[dict]:
        """Recent headlines [{"headline", "source", "url", "published_at"(ISO 8601 UTC)}], newest first.

        Optional: providers without a news feed return an empty list."""
        return []

    def quote(self, symbol: str) -> dict:
        df = self.history(symbol, "5d")
        close = df["Close"].dropna()
        if len(close) < 2:
            raise DataUnavailable("Not enough recent data to build a quote", retryable=True)
        price, prev = float(close.iloc[-1]), float(close.iloc[-2])
        return {"price": price, "previous_close": prev, "as_of": close.index[-1].date()}


def with_retries[T](fn: Callable[[], T], *, retries: int | None = None, backoff: float = 0.5,
                 sleep: Callable[[float], None] = time.sleep) -> T:
    """Call ``fn``; retry transient upstream failures (timeouts, 5xx) a bounded number of times."""
    attempts = 1 + (config.UPSTREAM_RETRIES if retries is None else retries)
    for i in range(attempts):
        try:
            return fn()
        except (UpstreamTimeout, DataUnavailable) as exc:
            if not exc.retryable or i == attempts - 1:
                raise
            sleep(backoff * 2**i)
    raise AssertionError("unreachable")
