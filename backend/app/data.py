"""Market-data access. Uses yfinance (no API key). Everything above this module only
sees a DataFrame, so tests can swap in a fake provider."""
from __future__ import annotations

import re
from typing import Protocol

import pandas as pd

SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-=^]{0,14}$")


class InvalidSymbol(ValueError):
    pass


class DataUnavailable(RuntimeError):
    """Upstream data could not be fetched (network, rate limit, unknown symbol...)."""


def normalize_symbol(raw: str) -> str:
    symbol = raw.strip().upper()
    if not SYMBOL_RE.match(symbol):
        raise InvalidSymbol(f"'{raw[:20]}' is not a valid ticker symbol")
    return symbol


class Provider(Protocol):
    def history(self, symbol: str, period: str) -> pd.DataFrame: ...
    def search(self, query: str) -> list[dict]: ...


class YahooProvider:
    """Daily OHLCV bars from Yahoo Finance via yfinance. Unofficial; may be rate limited."""

    def history(self, symbol: str, period: str) -> pd.DataFrame:
        try:
            import yfinance as yf

            df = yf.Ticker(symbol).history(period=period, interval="1d", auto_adjust=True)
        except Exception as exc:  # yfinance raises many exception types
            raise DataUnavailable(f"Market data provider error: {exc}") from exc
        if df is None or df.empty or "Close" not in df:
            raise DataUnavailable(f"No data found for '{symbol}' (unknown symbol or provider unavailable)")
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
        return df

    def search(self, query: str) -> list[dict]:
        try:
            import yfinance as yf

            quotes = yf.Search(query, max_results=8).quotes
        except Exception as exc:
            raise DataUnavailable(f"Search unavailable: {exc}") from exc
        out = []
        for q in quotes:
            sym = q.get("symbol")
            if sym and SYMBOL_RE.match(str(sym).upper()):
                out.append({"symbol": sym.upper(), "name": q.get("shortname") or q.get("longname") or "",
                            "exchange": q.get("exchDisp") or q.get("exchange") or ""})
        return out
