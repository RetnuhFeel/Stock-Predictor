from __future__ import annotations

import os

from .base import BaseProvider
from .twelvedata import TwelveDataProvider
from .yahoo import YahooProvider

PROVIDERS = ("yfinance", "twelvedata")


def create_provider(name: str | None = None) -> BaseProvider:
    """Build the provider named by DATA_PROVIDER (default: yfinance). Fails fast on bad config."""
    name = (name or os.getenv("DATA_PROVIDER", "yfinance")).strip().lower()
    if name == "yfinance":
        return YahooProvider()
    if name == "twelvedata":
        return TwelveDataProvider(os.getenv("TWELVEDATA_API_KEY", ""))
    raise ValueError(f"Unknown DATA_PROVIDER '{name}'. Supported: {', '.join(PROVIDERS)}")


__all__ = ["BaseProvider", "PROVIDERS", "TwelveDataProvider", "YahooProvider", "create_provider"]
