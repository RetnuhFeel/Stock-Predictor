import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import config, main
from app.data import DataUnavailable


def synthetic_prices(n=900, seed=0, drift=0.0003, vol=0.012) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(drift, vol, n)))
    idx = pd.bdate_range("2021-01-01", periods=n)
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99, "Close": close,
                         "Volume": rng.integers(1_000, 5_000, n)}, index=idx)


class FakeProvider:
    def __init__(self):
        self.calls = 0

    def history(self, symbol, period):
        self.calls += 1
        if symbol == "FAIL":
            raise DataUnavailable("No data found for 'FAIL'")
        df = synthetic_prices()
        n = {"5d": 5, "1mo": 21, "3mo": 63, "6mo": 126, "1y": 252, "2y": 504, "5y": 900}[period]
        return df.tail(n)

    def search(self, query):
        return [{"symbol": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ"}]


@pytest.fixture
def fake():
    return FakeProvider()


@pytest.fixture
def client(fake, monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_PER_MIN", 1000)
    main.cache._data.clear()
    main._hits.clear()
    main.app.dependency_overrides[main.get_provider] = lambda: fake
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()
