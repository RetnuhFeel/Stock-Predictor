"""Horizons up to 256 trading days and the 5-year performance timeline."""
import pytest

from app import config
from app.errors import InsufficientData
from app.forecast import forecast
from app.models import compare_models
from app.spikes import spike_forecast
from app.volatility import forecast_volatility

from .conftest import synthetic_prices


def test_max_horizon_is_256_everywhere(client):
    assert config.MAX_HORIZON == 256
    for ep in ("forecast", "compare-models", "volatility", "spikes"):
        assert client.get(f"/api/{ep}/AAPL?horizon=257").status_code == 422
        assert client.get(f"/api/{ep}/AAPL?horizon=0").status_code in (400, 422)
        r = client.get(f"/api/{ep}/AAPL?horizon=256")
        assert r.status_code == 200, (ep, r.text[:200])
        assert r.json()["horizon_days"] == 256


def test_long_horizon_forecast_is_labelled_and_embargoed(client):
    b = client.get("/api/forecast/AAPL?horizon=256").json()
    bt = b["backtest"]
    assert bt["embargo_days"] == 256 and "256-day embargo" in bt["method"] and bt["small_sample"] is True
    assert bt["n_independent_tests"] >= 1
    assert any("highly uncertain" in n for n in b["notes"])
    short = client.get("/api/forecast/AAPL?horizon=5").json()
    assert not any("highly uncertain" in n for n in short["notes"])
    assert len(b["path"]) == 256


@pytest.mark.parametrize("h", [120, 180, 256])
def test_long_horizon_all_models_run_on_five_years(h):
    close = synthetic_prices(1250, seed=2)["Close"]
    base = forecast(close, h)
    assert compare_models(close, h)["embargo_days"] == h
    assert forecast_volatility(close, h)["embargo_days"] == h
    sp = spike_forecast(close, h, base)
    for d in sp["path"]:
        assert d["band_low"] - 1e-3 <= d["median"] <= d["band_high"] + 1e-3
    # at long horizons there are too few origins for a spike backtest: it says so instead of inventing numbers
    if h >= 180:
        assert sp["backtest"]["available"] is False and "too few" in sp["backtest"]["reason"]
        assert any("could not be run" in n for n in sp["notes"])


def test_too_little_history_for_long_horizon_is_structured_error(client, fake):
    short = synthetic_prices(400)
    fake.history = lambda symbol, period: short
    ok = client.get("/api/forecast/AAPL?horizon=60")
    assert ok.status_code == 200
    r = client.get("/api/forecast/AAPL?horizon=256")
    assert r.status_code == 422 and r.json()["error"]["code"] == "INSUFFICIENT_DATA"
    assert "256" in r.json()["error"]["message"] and "shorter horizon" in r.json()["error"]["message"]
    for ep in ("compare-models", "volatility", "spikes"):
        assert client.get(f"/api/{ep}/AAPL?horizon=256").json()["error"]["code"] == "INSUFFICIENT_DATA"
    with pytest.raises(InsufficientData):
        forecast(short["Close"], 256)


def test_prediction_log_is_still_5_day():
    assert config.LOG_HORIZON == 5 and config.LOG_SYMBOLS == ["SPY", "AAPL", "MSFT", "NVDA", "TSLA"]


# ---- timeline ----
def test_timeline_default_5y_summary_and_freshness(client):
    r = client.get("/api/timeline/aapl")
    b = r.json()
    assert r.status_code == 200 and b["symbol"] == "AAPL" and b["range"] == "5y"
    assert b["stale"] is False and b["fetched_at"].endswith("Z") and b["disclaimer"] and "data_as_of" in b
    pts = b["points"]
    assert len(pts) <= config.TIMELINE_MAX_POINTS and b["downsampled"] is True and b["n_points_total"] > len(pts)
    assert [p["date"] for p in pts] == sorted(p["date"] for p in pts)
    s = b["summary"]
    # the summary is computed on the full data and the chart keeps the extremes, first and last point
    closes = [p["close"] for p in pts]
    assert max(closes) == s["high"] and min(closes) == s["low"]
    assert pts[0]["date"] == s["start_date"] and pts[-1]["date"] == s["end_date"]
    assert s["period_return_pct"] == pytest.approx((s["end_close"] / s["start_close"] - 1) * 100, abs=0.01)
    assert s["max_drawdown_pct"] <= 0 and s["low"] <= s["high"]


def test_timeline_ranges_and_validation_and_cache(client, fake):
    sizes = {}
    for rg in ("1mo", "3mo", "6mo", "1y", "2y", "5y"):
        j = client.get(f"/api/timeline/AAPL?range={rg}").json()
        assert j["range"] == rg
        sizes[rg] = j["n_points_total"]
    assert sizes["1mo"] < sizes["3mo"] < sizes["6mo"] < sizes["1y"] < sizes["2y"] < sizes["5y"]
    assert list(config.TIMELINE_RANGES) == ["1mo", "3mo", "6mo", "1y", "2y", "5y"]
    assert fake.calls == 1  # all windows are sliced from one cached 5y download
    small = client.get("/api/timeline/AAPL?range=1mo").json()
    assert small["downsampled"] is False and len(small["points"]) == small["n_points_total"]
    assert client.get("/api/timeline/AAPL?range=10y").json()["error"]["code"] == "INVALID_RANGE"
    assert client.get("/api/timeline/A$B").json()["error"]["code"] == "INVALID_SYMBOL"
    assert client.get("/api/timeline/FAIL").json()["error"]["code"] == "DATA_UNAVAILABLE"


def test_timeline_stale_when_provider_fails(client, fake):
    from app import main
    assert client.get("/api/timeline/AAPL").status_code == 200
    for k, (_, fa, v) in list(main.cache._data.items()):
        main.cache._data[k] = (0, fa, v)  # expire everything
    from app.errors import DataUnavailable
    fake.fail_with = DataUnavailable("down")
    r = client.get("/api/timeline/AAPL")
    assert r.status_code == 200 and r.json()["stale"] is True and r.json()["warnings"][0]["code"] == "STALE_DATA"


def test_timeline_too_short_history(client, fake):
    short = synthetic_prices(900).tail(1)
    fake.history = lambda symbol, period: short
    r = client.get("/api/timeline/AAPL")
    assert r.status_code == 422 and r.json()["error"]["code"] == "INSUFFICIENT_DATA"


def test_too_few_independent_periods_can_never_say_better():
    from app.forecast import MIN_INDEP_FOR_VERDICT
    close = synthetic_prices(1250, seed=4, drift=0.002)["Close"]
    b = forecast(close, 256)["backtest"]
    assert b["n_independent_tests"] < MIN_INDEP_FOR_VERDICT and b["too_few_independent"] is True
    assert b["beats_baseline"] is False
    assert all(m["verdict"] != "better" for m in compare_models(close, 256)["models"])
    assert forecast_volatility(close, 256)["verdict"] != "better"
    five = forecast(close, 5)["backtest"]
    assert five["too_few_independent"] is False  # the logged 5-day horizon is unaffected


def test_history_endpoint_still_accepts_every_chart_range_and_keeps_volume(client):
    # backward compatible: /api/history is unchanged (all bars, with volume) for every range the chart offers
    for rg in ("1mo", "3mo", "6mo", "1y", "2y", "5y"):
        r = client.get(f"/api/history/AAPL?range={rg}")
        assert r.status_code == 200 and "volume" in r.json()["points"][0]
    assert client.get("/api/history/AAPL?range=7y").json()["error"]["code"] == "INVALID_RANGE"


def test_timeline_window_matches_range_and_summary_covers_full_window(client):
    for rg, months in (("3mo", 3), ("2y", 24)):
        b = client.get(f"/api/timeline/AAPL?range={rg}").json()
        import pandas as pd
        span = pd.Timestamp(b["summary"]["end_date"]) - pd.Timestamp(b["summary"]["start_date"])
        assert abs(span.days - months * 30.4) < 8
        closes = [p["close"] for p in b["points"]]
        assert min(closes) == b["summary"]["low"] and max(closes) == b["summary"]["high"]


def test_timeline_unknown_range_is_invalid_range(client):
    for bad in ("max", "10y", "ytd", "", "6MO"):
        r = client.get(f"/api/timeline/AAPL?range={bad}")
        assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_RANGE"
