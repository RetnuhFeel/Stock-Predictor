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
        n = {"5d": 5, "1mo": 21, "3mo": 63, "6mo": 126, "1y": 252, "2y": 504, "5y": 900, "10y": 2400}[period]
        if n > len(df):
            df = synthetic_prices(n)
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
def store(tmp_path):
    from app.storage import PredictionStore
    st = PredictionStore(f"sqlite:///{tmp_path / 'log.db'}")
    yield st
    st.close()


@pytest.fixture(autouse=True)
def _log_propagation():
    """The app logger has propagate=False; caplog needs it on. Do it for every test so results never depend on
    which test happened to flip it first."""
    import logging
    lg = logging.getLogger("stock-api")
    old = lg.propagate
    lg.propagate = True
    yield
    lg.propagate = old


@pytest.fixture
def after_close(monkeypatch):
    """Pin 'now' to 17:00 New York today so a bar dated today counts as a final close (tests must not depend on the
    wall clock; synthetic series end today)."""
    from datetime import datetime, time
    from zoneinfo import ZoneInfo

    from app import freshness
    monkeypatch.setattr(freshness, "now_ny", lambda: datetime.combine(
        datetime.now(ZoneInfo("America/New_York")).date(), time(17, 0), tzinfo=ZoneInfo("America/New_York")))


@pytest.fixture
def client(fake, store, monkeypatch, after_close):
    monkeypatch.setattr(config, "RATE_LIMIT_PER_MIN", 1000)
    main.cache.clear()
    main.limiter.clear()
    main.search_cache.clear()
    main.stats.reset()
    main.app.dependency_overrides[main.get_provider] = lambda: fake
    main.app.dependency_overrides[main.get_store] = lambda: store
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


@pytest.fixture
def app_with(store, monkeypatch, after_close):
    """Factory: a test client wired to a specific provider instance (e.g. one that fails for some periods)."""
    monkeypatch.setattr(config, "RATE_LIMIT_PER_MIN", 1000)
    main.cache.clear()
    main.limiter.clear()
    main.search_cache.clear()
    main.stats.reset()

    def make(provider):
        main.app.dependency_overrides[main.get_provider] = lambda: provider
        main.app.dependency_overrides[main.get_store] = lambda: store
        return TestClient(main.app)
    yield make
    main.app.dependency_overrides.clear()
