"""Twelve Data (https://twelvedata.com) provider: licensed market data with a free tier.

Implemented from the public docs (https://twelvedata.com/docs): GET /time_series and
GET /symbol_search, authenticated with ``Authorization: apikey <key>``. Errors come back as
{"code": <http-like code>, "message": ..., "status": "error"}, sometimes inside an HTTP 200.

NOTE: unit-tested with mocked HTTP only; NOT verified against the live API (no key was available).
Set DATA_PROVIDER=twelvedata and TWELVEDATA_API_KEY. Prices are split-adjusted (not dividend-adjusted),
so they differ slightly from the yfinance default.
"""
from __future__ import annotations

import httpx
import pandas as pd

from .. import config
from ..errors import DataUnavailable, RateLimited, UpstreamTimeout
from .base import COLUMNS, PERIOD_BARS, BaseProvider, with_retries

BASE_URL = "https://api.twelvedata.com"


class TwelveDataProvider(BaseProvider):
    name = "twelvedata"

    def __init__(self, api_key: str, client: httpx.Client | None = None):
        if not api_key:
            raise ValueError("TWELVEDATA_API_KEY is required when DATA_PROVIDER=twelvedata")
        self._client = client or httpx.Client(base_url=BASE_URL, timeout=config.UPSTREAM_TIMEOUT_S)
        self._headers = {"Authorization": f"apikey {api_key}"}  # header keeps the key out of URLs/logs

    @staticmethod
    def _to_provider_symbol(symbol: str) -> str:
        # Twelve Data uses dots for share classes (BRK.B); Yahoo-style tickers use dashes (BRK-B).
        # Yahoo-only symbols (indices ^GSPC, futures =F, FX =X) are not supported here.
        return symbol.replace("-", ".")

    def _get(self, path: str, params: dict) -> dict:
        try:
            resp = self._client.get(path, params=params, headers=self._headers)
        except httpx.TimeoutException as exc:
            raise UpstreamTimeout() from exc
        except httpx.HTTPError as exc:
            raise DataUnavailable("Could not reach the market-data provider.", retryable=True) from exc

        try:
            body = resp.json()
        except ValueError:
            body = None
        code = body.get("code") if isinstance(body, dict) and body.get("status") == "error" else None
        status = int(code) if isinstance(code, int | str) and str(code).isdigit() else resp.status_code

        if status == 429:
            raise RateLimited("The data provider's request limit was reached. Please try again shortly.",
                              retry_after=_retry_after(resp))
        if status in (401, 403):
            # a configuration problem, not the user's: don't expose details or invite retries
            raise DataUnavailable("The data provider rejected the server's credentials or plan.")
        if status in (400, 404):
            raise DataUnavailable(str(body.get("message", "No data found")) if body else "No data found")
        if status >= 500:
            raise DataUnavailable("The market-data provider had an internal error.", retryable=True)
        if status >= 400 or not isinstance(body, dict):
            raise DataUnavailable("Unexpected response from the market-data provider.", retryable=True)
        return body

    def history(self, symbol: str, period: str) -> pd.DataFrame:
        params = {"symbol": self._to_provider_symbol(symbol), "interval": "1day", "order": "asc",
                  "outputsize": PERIOD_BARS.get(period, 253)}

        def once() -> pd.DataFrame:
            body = self._get("/time_series", params)
            values = body.get("values") or []
            if not values:
                raise DataUnavailable(f"No data found for '{symbol}'.")
            df = pd.DataFrame(values)
            df["datetime"] = pd.to_datetime(df["datetime"]).dt.normalize()
            df = df.set_index("datetime").sort_index()
            for col in ("open", "high", "low", "close", "volume"):
                df[col] = pd.to_numeric(df.get(col), errors="coerce")  # missing volume -> NaN
            df = df.rename(columns=str.capitalize)[COLUMNS]
            df["Volume"] = df["Volume"].fillna(0)
            df = df.dropna(subset=["Close"])
            if df.empty:
                raise DataUnavailable(f"No data found for '{symbol}'.")
            return df

        return with_retries(once)

    def search(self, query: str) -> list[dict]:
        body = with_retries(lambda: self._get("/symbol_search", {"symbol": query, "outputsize": 8}))
        return [{"symbol": str(r["symbol"]).upper(), "name": r.get("instrument_name", ""),
                 "exchange": r.get("exchange", "")} for r in body.get("data", []) if r.get("symbol")]


def _retry_after(resp: httpx.Response) -> int:
    try:
        return max(int(resp.headers.get("Retry-After", "30")), 1)
    except ValueError:
        return 30
