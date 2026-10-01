"""Yahoo Finance via yfinance: no API key, unofficial, may rate-limit or break at any time."""
from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlparse

import pandas as pd

from .. import config
from ..errors import DataUnavailable, RateLimited, UpstreamTimeout
from ..symbols import SYMBOL_RE
from .base import COLUMNS, BaseProvider, with_retries


def _translate(exc: Exception, symbol: str) -> Exception:
    """Map yfinance/network exceptions onto our typed errors."""
    name, text = type(exc).__name__, str(exc).lower()
    if name == "YFRateLimitError" or "too many requests" in text or "rate limit" in text:
        return RateLimited("Yahoo Finance is rate-limiting requests. Please try again shortly.")
    if "timeout" in name.lower() or "timed out" in text:
        return UpstreamTimeout()
    if name in {"YFTickerMissingError", "YFPricesMissingError", "YFInvalidPeriodError"}:
        return DataUnavailable(f"No data found for '{symbol}' (unknown or delisted symbol).")
    return DataUnavailable("The market-data provider returned an error.", retryable=True)


class YahooProvider(BaseProvider):
    name = "yfinance"

    def _download(self, symbol: str, period: str) -> pd.DataFrame:
        import yfinance as yf

        return yf.Ticker(symbol).history(period=period, interval="1d", auto_adjust=True,
                                         timeout=config.UPSTREAM_TIMEOUT_S)

    def history(self, symbol: str, period: str) -> pd.DataFrame:
        def once() -> pd.DataFrame:
            try:
                df = self._download(symbol, period)
            except Exception as exc:  # yfinance raises many exception types
                raise _translate(exc, symbol) from exc
            if df is None or df.empty or "Close" not in df:
                raise DataUnavailable(f"No data found for '{symbol}' (unknown symbol or provider unavailable).")
            df = df[COLUMNS].dropna(subset=["Close"])
            df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
            return df

        return with_retries(once)

    def search(self, query: str) -> list[dict]:
        def once() -> list[dict]:
            try:
                import yfinance as yf

                quotes = yf.Search(query, max_results=8, timeout=config.UPSTREAM_TIMEOUT_S).quotes
            except Exception as exc:
                raise _translate(exc, query) from exc
            out = []
            for q in quotes:
                sym = str(q.get("symbol") or "").upper()
                if SYMBOL_RE.match(sym):
                    out.append({"symbol": sym, "name": q.get("shortname") or q.get("longname") or "",
                                "exchange": q.get("exchDisp") or q.get("exchange") or ""})
            return out

        return with_retries(once)

    def news(self, symbol: str) -> list[dict]:
        def once() -> list[dict]:
            try:
                import yfinance as yf

                raw = yf.Ticker(symbol).news
            except Exception as exc:
                raise _translate(exc, symbol) from exc
            return parse_news(raw or [])

        return with_retries(once)


def _safe_url(url: object) -> str | None:
    if not isinstance(url, str):
        return None
    parts = urlparse(url.strip())
    return url.strip()[:500] if parts.scheme in {"http", "https"} and parts.netloc else None


def parse_news(raw: list) -> list[dict]:
    """Normalise yfinance news items (new nested format and the older flat one). Link-out data only."""
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        c = item.get("content") if isinstance(item.get("content"), dict) else item
        title = str(c.get("title") or "").strip()
        link = c.get("canonicalUrl") or c.get("clickThroughUrl") or {}
        url = _safe_url(link.get("url") if isinstance(link, dict) else None) or _safe_url(c.get("link"))
        prov = c.get("provider")
        source = (prov.get("displayName") if isinstance(prov, dict) else None) or c.get("publisher") or ""
        published = c.get("pubDate")
        if not published and isinstance(c.get("providerPublishTime"), int | float):
            published = datetime.fromtimestamp(c["providerPublishTime"], UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        if not title or not url or not published:
            continue
        out.append({"headline": title[:300], "source": str(source)[:80], "url": url, "published_at": str(published)})
    out.sort(key=lambda x: x["published_at"], reverse=True)
    return out
