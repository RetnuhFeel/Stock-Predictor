import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import config, main
from app.errors import DataUnavailable
from app.freshness import today_ny
from app.providers.base import BaseProvider


def synthetic_prices(n=900, seed=0, drift=0.0003, vol=0.012, end=None) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(drift, vol, n)))
    # end on the most recent business day so freshness checks see "current" data
    end = pd.Timestamp(end) if end is not None else pd.Timestamp(today_ny())
    idx = pd.bdate_range(end=end, periods=n)
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99, "Close": close,
                         "Volume": rng.integers(1_000, 5_000, n)}, index=idx)


class FakeProvider(BaseProvider):
    name = "fake"

    def __init__(self):
        self.calls = 0
        self.fail_with = None
        self.fail_news = None

    def history(self, symbol, period):
        self.calls += 1
        if self.fail_with:
            raise self.fail_with
        if symbol == "FAIL":
            raise DataUnavailable("No data found for 'FAIL'")
        df = synthetic_prices()
        n = {"5d": 5, "1mo": 21, "3mo": 63, "6mo": 126, "1y": 252, "2y": 504, "5y": 900}[period]
        return df.tail(n)

    def news(self, symbol):
        if self.fail_news:
            raise self.fail_news
        return [{"headline": "Acme beats estimates", "source": "Wire", "url": "https://example.com/a",
                 "published_at": "2026-09-30T13:00:00Z"}]

    def search(self, query):
        return [{"symbol": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ"}]


@pytest.fixture
def fake():
    return FakeProvider()


@pytest.fixture
def client(fake, monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_PER_MIN", 1000)
    main.cache.clear()
    main._hits.clear()
    main.stats.reset()
    main.app.dependency_overrides[main.get_provider] = lambda: fake
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()
