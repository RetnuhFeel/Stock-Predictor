"""Structured errors, freshness flags, stale-cache fallback, retries."""
import time
from datetime import date

import pytest

from app import cache as cache_mod
from app import config, main
from app.errors import DataUnavailable, RateLimited, UpstreamTimeout
from app.freshness import describe
from app.providers.base import with_retries


def test_fresh_data_flags(client):
    body = client.get("/api/quote/AAPL").json()
    assert body["stale"] is False and body["is_delayed"] is False and body["warnings"] == []
    assert body["data_as_of"] == body["as_of"] and body["fetched_at"].endswith("Z")


@pytest.mark.parametrize("exc,status,code,retryable", [
    (DataUnavailable("nope"), 502, "DATA_UNAVAILABLE", False),
    (UpstreamTimeout(), 504, "UPSTREAM_TIMEOUT", True),
    (RateLimited("slow", retry_after=7), 429, "RATE_LIMITED", True),
])
def test_error_codes(client, fake, exc, status, code, retryable):
    fake.fail_with = exc
    r = client.get("/api/history/AAPL?range=1mo")
    err = r.json()["error"]
    assert r.status_code == status and err["code"] == code and err["retryable"] is retryable
    if code == "RATE_LIMITED":
        assert err["retry_after"] == 7 and r.headers["retry-after"] == "7"


def test_serves_stale_cache_when_provider_fails(client, fake, monkeypatch):
    assert client.get("/api/history/AAPL?range=1mo").json()["stale"] is False
    monkeypatch.setattr(config, "HISTORY_TTL_S", -1)  # force the cached entry to be expired
    main.cache._data = {k: (0, v[1], v[2]) for k, v in main.cache._data.items()}
    fake.fail_with = UpstreamTimeout()
    r = client.get("/api/history/AAPL?range=1mo")
    body = r.json()
    assert r.status_code == 200 and body["stale"] is True
    assert body["warnings"][0]["code"] == "STALE_DATA" and len(body["points"]) > 0


def test_stale_cache_too_old_is_not_served(client, fake, monkeypatch):
    client.get("/api/history/AAPL?range=1mo")
    main.cache._data = {k: (0, time.time() - 10_000, v[2]) for k, v in main.cache._data.items()}
    monkeypatch.setattr(config, "STALE_MAX_AGE_S", 60)
    fake.fail_with = UpstreamTimeout()
    assert client.get("/api/history/AAPL?range=1mo").status_code == 504


def test_forecast_uses_stale_history(client, fake):
    client.get("/api/forecast/AAPL?horizon=5")
    main.cache._data = {k: (0, v[1], v[2]) for k, v in main.cache._data.items()}
    fake.fail_with = DataUnavailable("down", retryable=True)
    body = client.get("/api/forecast/AAPL?horizon=5").json()
    assert body["stale"] is True and body["disclaimer"]


def test_describe_delayed_and_stale():
    today = date(2026, 10, 1)  # Thursday
    import app.freshness as f
    orig = f.today_ny
    f.today_ny = lambda: today
    try:
        assert describe(date(2026, 9, 30), time.time(), False)["is_delayed"] is False
        d = describe(date(2026, 9, 28), time.time(), False)  # Monday: 3 business days
        assert d["is_delayed"] is True and d["stale"] is False
        old = describe(date(2026, 9, 17), time.time(), False)
        assert old["stale"] is True and old["warnings"][0]["code"] == "STALE_DATA"
        assert describe(date(2026, 9, 30), time.time(), True)["stale"] is True
    finally:
        f.today_ny = orig


def test_retries_are_bounded_and_only_for_retryable():
    calls = []

    def flaky():
        calls.append(1)
        raise UpstreamTimeout()

    with pytest.raises(UpstreamTimeout):
        with_retries(flaky, retries=2, sleep=lambda s: None)
    assert len(calls) == 3

    calls.clear()

    def permanent():
        calls.append(1)
        raise DataUnavailable("unknown symbol")  # retryable=False

    with pytest.raises(DataUnavailable):
        with_retries(permanent, retries=2, sleep=lambda s: None)
    assert len(calls) == 1


def test_retry_recovers():
    state = {"n": 0}

    def fn():
        state["n"] += 1
        if state["n"] < 3:
            raise UpstreamTimeout()
        return "ok"

    assert with_retries(fn, retries=2, sleep=lambda s: None) == "ok"


def test_cache_ttl_hit_and_expiry():
    c = cache_mod.TTLCache()
    n = {"v": 0}

    def f():
        n["v"] += 1
        return n["v"]

    assert c.fetch("k", 60, f).value == 1 and c.fetch("k", 60, f).value == 1
    assert c.fetch("k2", -1, f).value == 2 and c.fetch("k2", -1, f).value == 3
