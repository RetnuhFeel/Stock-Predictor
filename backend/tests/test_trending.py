"""Trending momentum screen: ranking, partial failures, caching, error shape (no network)."""
import numpy as np
import pandas as pd
import pytest

from app import config, main
from app.errors import DataUnavailable, RateLimited
from app.freshness import today_ny
from app.providers.yahoo import split_batch
from app.universe import NAMES, SYMBOLS, UNIVERSE

from .conftest import FakeProvider


def frame(closes, end=None):
    end = pd.Timestamp(end) if end is not None else pd.Timestamp(today_ny())
    idx = pd.bdate_range(end=end, periods=len(closes))
    c = np.array(closes, dtype=float)
    return pd.DataFrame({"Open": c, "High": c, "Low": c, "Close": c, "Volume": 1000}, index=idx)


def flat(n=30):
    return [100.0] * n


def with_last(ret_pct, days=3, n=30):
    """Series that ends ``ret_pct`` % above its close ``days`` bars earlier."""
    s = flat(n)
    s[-1] = 100 * (1 + ret_pct / 100)
    for i in range(1, days):
        s[-1 - i] = 100.0
    return s


class BatchProvider(FakeProvider):
    """Fake provider with a controllable batch_history."""

    def __init__(self, returns: dict[str, float], missing=(), stale=()):
        super().__init__()
        self.returns, self.missing, self.stale_syms, self.batch_calls = returns, set(missing), set(stale), 0

    def batch_history(self, symbols, period):
        self.batch_calls += 1
        if self.fail_with:
            raise self.fail_with
        out = {}
        for s in symbols:
            if s in self.missing:
                continue
            end = pd.Timestamp(today_ny()) - pd.offsets.BDay(4) if s in self.stale_syms else None
            out[s] = frame(with_last(self.returns.get(s, 0.5)), end)
        return out


@pytest.fixture
def trend(client, monkeypatch):
    def use(provider):
        main.app.dependency_overrides[main.get_provider] = lambda: provider
        return provider
    return use


def test_universe_is_curated_and_valid():
    assert 90 <= len(UNIVERSE) <= 130 and len(SYMBOLS) == len(set(SYMBOLS))
    from app.symbols import SYMBOL_RE
    assert all(SYMBOL_RE.match(s) for s in SYMBOLS) and all(NAMES[s] for s in SYMBOLS)


def test_ranking_top5_by_return(client, trend):
    rets = {"NVDA": 9.1, "AAPL": 7.0, "MSFT": 5.5, "AMZN": 4.4, "META": 3.3, "TSLA": 3.2, "GOOGL": -5.0}
    trend(BatchProvider(rets))
    b = client.get("/api/trending").json()
    assert [i["symbol"] for i in b["items"]] == ["NVDA", "AAPL", "MSFT", "AMZN", "META"]
    assert [i["rank"] for i in b["items"]] == [1, 2, 3, 4, 5]
    top = b["items"][0]
    assert top["return_percent"] == 9.1 and top["name"] == "NVIDIA" and top["last_close"] == pytest.approx(109.1)
    assert b["days"] == 3 and b["limit"] == 5 and b["universe_size"] == len(SYMBOLS) and b["evaluated"] == len(SYMBOLS)
    assert "not a recommendation" in b["note"] and "do not predict" in b["note"] and b["disclaimer"]
    assert b["stale"] is False and b["fetched_at"].endswith("Z") and b["data_as_of"] == today_ny().isoformat()


def test_limit_days_and_ties(client, trend):
    trend(BatchProvider({"AAPL": 2.0, "MSFT": 2.0}, ))
    b = client.get("/api/trending?limit=3").json()
    assert len(b["items"]) == 3
    tied = [i["symbol"] for i in b["items"] if i["return_percent"] == 2.0]
    assert tied == sorted(tied)  # deterministic tie-break by symbol
    b2 = client.get("/api/trending?days=5&limit=1").json()
    assert b2["days"] == 5 and len(b2["items"]) == 1


def test_return_uses_requested_window(client, trend):
    class P(BatchProvider):
        def batch_history(self, symbols, period):
            s = flat()
            s[-4], s[-1] = 100.0, 110.0   # +10% over 3 days
            s[-5], s[-2] = 50.0, 100.0    # irrelevant older/inner moves
            return {sym: frame(s) for sym in symbols[:1]} | {sym: frame(flat()) for sym in symbols[1:]}
    trend(P({}))
    assert client.get("/api/trending?days=3&limit=1").json()["items"][0]["return_percent"] == 10.0
    assert client.get("/api/trending?days=4&limit=1").json()["items"][0]["return_percent"] == 120.0  # 110 vs 50


def test_partial_failures_are_skipped(client, trend):
    missing = SYMBOLS[-20:]
    trend(BatchProvider({"NVDA": 8.0}, missing=missing))
    b = client.get("/api/trending").json()
    assert b["evaluated"] == len(SYMBOLS) - 20 and b["items"][0]["symbol"] == "NVDA"
    assert not {i["symbol"] for i in b["items"]} & set(missing)


def test_lagging_tickers_do_not_win_with_old_bars(client, trend):
    trend(BatchProvider({"NVDA": 50.0}, stale=["NVDA"]))
    b = client.get("/api/trending").json()
    assert "NVDA" not in [i["symbol"] for i in b["items"]]  # latest bar older than the others: excluded


def test_too_few_tickers_is_structured_error(client, trend):
    trend(BatchProvider({}, missing=SYMBOLS[: len(SYMBOLS) - 10]))
    r = client.get("/api/trending")
    assert r.status_code == 502 and r.json()["error"]["code"] == "DATA_UNAVAILABLE" and r.json()["error"]["retryable"]


@pytest.mark.parametrize("exc,status,code", [(DataUnavailable("down", retryable=True), 502, "DATA_UNAVAILABLE"),
                                             (RateLimited("slow down"), 429, "RATE_LIMITED")])
def test_provider_failure_never_500(client, trend, exc, status, code):
    p = trend(BatchProvider({}))
    p.fail_with = exc
    r = client.get("/api/trending")
    assert r.status_code == status and r.json()["error"]["code"] == code


def test_cached_and_stale_if_error(client, trend):
    p = trend(BatchProvider({"NVDA": 6.0}))
    client.get("/api/trending")
    client.get("/api/trending?limit=2")  # different limit, same window: still one provider batch
    assert p.batch_calls == 1
    client.get("/api/trending?days=5")
    assert p.batch_calls == 2
    main.cache._data = {k: (0, v[1], v[2]) for k, v in main.cache._data.items()}  # expire
    p.fail_with = DataUnavailable("down", retryable=True)
    b = client.get("/api/trending").json()
    assert b["stale"] is True and b["warnings"][0]["code"] == "STALE_DATA" and b["items"][0]["symbol"] == "NVDA"


@pytest.mark.parametrize("q", ["days=0", "days=11", "limit=0", "limit=11", "days=abc"])
def test_validation(client, trend, q):
    trend(BatchProvider({}))
    r = client.get(f"/api/trending?{q}")
    assert r.status_code in (400, 422) and "code" in r.json()["error"]


def test_uses_one_batch_call_not_per_symbol(client, trend):
    p = trend(BatchProvider({}))
    client.get("/api/trending")
    assert p.batch_calls == 1 and p.calls == 0


def test_default_batch_history_skips_failures():
    class P(FakeProvider):
        pass
    out = P().batch_history(["AAPL", "FAIL", "MSFT"], "1mo")
    assert sorted(out) == ["AAPL", "MSFT"]
    with pytest.raises(DataUnavailable):
        P().batch_history(["FAIL"], "1mo")


def test_split_batch_multiindex_and_failures():
    a, b = frame(flat()), frame(flat())
    raw = pd.concat({"AAA": a, "BBB": b, "CCC": frame(flat()).assign(Close=np.nan)}, axis=1)
    out = split_batch(raw, ["AAA", "BBB", "CCC", "ZZZ"])
    assert sorted(out) == ["AAA", "BBB"] and list(out["AAA"].columns) == ["Open", "High", "Low", "Close", "Volume"]
    with pytest.raises(DataUnavailable):
        split_batch(pd.DataFrame(), ["AAA"])
    with pytest.raises(DataUnavailable):
        split_batch(pd.concat({"CCC": frame(flat()).assign(Close=np.nan)}, axis=1), ["CCC"])
    assert list(split_batch(frame(flat()), ["ONLY"])) == ["ONLY"]  # un-nested single-symbol frame


def test_trending_rate_limited(client, trend, monkeypatch):
    trend(BatchProvider({}))
    monkeypatch.setattr(config, "HEAVY_RATE_PER_MIN", 2)
    assert [client.get("/api/trending").status_code for _ in range(4)] == [200, 200, 429, 429]
