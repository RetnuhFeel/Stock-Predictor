"""Experimental jump-diffusion spike scenario."""

import json

import numpy as np
import pytest

from app import config, main
from app.errors import InsufficientData
from app.forecast import forecast
from app.spikes import calibrate, raw_log_paths, simulate, spike_forecast

from .conftest import synthetic_prices


@pytest.fixture(scope="module")
def series():
    return synthetic_prices(900, seed=1)["Close"]


@pytest.fixture(scope="module")
def base(series):
    return forecast(series, 10)


@pytest.fixture(scope="module")
def result(series, base):
    return spike_forecast(series, 10, base)


def _finite(o):
    if isinstance(o, dict):
        return all(_finite(v) for v in o.values())
    if isinstance(o, (list, tuple)):
        return all(_finite(v) for v in o)
    if isinstance(o, float):
        return np.isfinite(o)
    return True


def test_deterministic_for_same_input(series, base, result):
    again = spike_forecast(series, 10, base)
    assert json.dumps(again, sort_keys=True) == json.dumps(result, sort_keys=True)


def test_paths_and_summaries_stay_inside_the_baseline_band(result):
    assert len(result["path"]) == 10
    for d in result["path"]:
        lo, hi = d["band_low"], d["band_high"]
        for k in ("median", "mean", "sim_low", "sim_high", "spike_up", "spike_down"):
            assert lo - 1e-3 <= d[k] <= hi + 1e-3, (k, d)
        assert d["sim_low"] <= d["median"] <= d["sim_high"]
    for p in result["sample_paths"]:
        for v, d in zip(p, result["path"], strict=True):
            assert d["band_low"] - 1e-3 <= v <= d["band_high"] + 1e-3


def test_no_nan_and_all_floats_finite(result):
    assert _finite(result)


def test_clamping_is_reported_and_probabilities_valid(result):
    c = result["clamping"]
    assert c["method"] == "clip" and 0 <= c["fraction_of_path_days_clamped"] <= 1
    assert c["fraction_of_paths_touching_band"] >= c["fraction_of_path_days_clamped"] - 1e-9
    for d in result["path"]:
        for k in ("p_jump_up", "p_jump_down", "p_touch_high", "p_touch_low"):
            assert 0 <= d[k] <= 1
    ups = [d["p_jump_up"] for d in result["path"]]
    assert ups == sorted(ups)  # cumulative "any jump so far" never decreases


def test_simulate_clamps_to_arbitrary_tight_band():
    r = np.random.default_rng(0).normal(0, 0.01, 400)
    cal = calibrate(r)
    low, high = np.full(5, 99.0), np.full(5, 101.0)
    sim = simulate(cal, 100.0, 5, 0.0, low, high, n_paths=500)
    assert sim["price"].min() >= 99.0 and sim["price"].max() <= 101.0
    assert sim["clamped_fraction"] > 0.2  # tight band is hit a lot, and that is reported


def test_calibration_finds_asymmetric_jumps():
    rng = np.random.default_rng(1)
    r = rng.normal(0, 0.01, 500)
    r[::25] += 0.08  # 20 up jumps
    r[5::100] -= 0.09  # 5 down jumps
    cal = calibrate(r)
    assert len(cal.up_sizes) >= 15 and len(cal.down_sizes) >= 3
    assert cal.p_up > cal.p_down and cal.sigma_diffusion < 0.02  # jumps do not inflate diffusion vol


def test_no_jumps_is_a_plain_random_walk():
    cal = calibrate(np.random.default_rng(3).normal(0, 0.01, 300) * 0 + np.linspace(-0.001, 0.001, 300))
    cum, direction = raw_log_paths(cal, 5, 0.0, 100)
    assert np.isfinite(cum).all() and not direction.any() or cal.p_up + cal.p_down < 0.05


def test_jumps_do_not_add_drift():
    rng = np.random.default_rng(2)
    r = rng.normal(0, 0.01, 500)
    r[::20] += 0.07
    cal = calibrate(r)
    cum, _ = raw_log_paths(cal, 10, 0.02, 20000)
    assert abs(cum[:, -1].mean() - 0.02) < 0.01  # mean follows the standard forecast's point, spikes are compensated


def test_short_history_is_structured_error(base):
    with pytest.raises(InsufficientData):
        spike_forecast(synthetic_prices(100)["Close"], 5, base)
    with pytest.raises(InsufficientData):
        calibrate(np.zeros(10))


def test_backtest_reports_numbers_and_honest_verdict(result):
    bt = result["backtest"]
    assert bt["available"] and bt["n_origins"] >= 10 and bt["embargo_days"] == 10
    for k in ("baseline", "jump_unclamped", "spike_clamped"):
        assert 0 <= bt[k]["coverage"] <= 1 and bt[k]["interval_score"] > 0
    for k in ("jump_unclamped", "spike_clamped"):
        lo, hi = bt[k]["score_gain_ci_90"]
        assert lo <= hi and bt[k]["verdict"] in {"better", "worse", "inconclusive"}
    assert bt["spike_clamped"]["mean_width"] <= bt["baseline"]["mean_width"] + 1e-9  # clamping can only narrow
    assert bt["summary"] and bt["point"]["verdict"] in {"better", "worse", "inconclusive"}
    text = " ".join(result["notes"]).lower()
    assert "not predictions" in text and "not financial advice" in text
    assert result["experimental"] is True


# ---- API ----
def test_endpoint_shape_freshness_cache_and_errors(client, fake):
    r = client.get("/api/spikes/aapl?horizon=5")
    b = r.json()
    assert r.status_code == 200 and b["symbol"] == "AAPL" and b["experimental"] and b["disclaimer"]
    assert b["stale"] is False and b["fetched_at"].endswith("Z") and "data_as_of" in b
    assert b["model"]["bounds"].startswith("clamped") and b["baseline_interval"]["low"] < b["baseline_interval"]["high"]
    calls = fake.calls
    client.get("/api/spikes/AAPL?horizon=5")
    assert fake.calls == calls  # cached
    for bad in ["horizon=0", "horizon=61", "horizon=abc"]:
        assert client.get(f"/api/spikes/AAPL?{bad}").status_code in (400, 422)
    assert client.get("/api/spikes/A$B").json()["error"]["code"] == "INVALID_SYMBOL"
    assert client.get("/api/spikes/FAIL").json()["error"]["code"] == "DATA_UNAVAILABLE"


def test_endpoint_short_history_is_422_not_500(client, fake):
    short = synthetic_prices(120)
    fake.history = lambda symbol, period: short
    r = client.get("/api/spikes/AAPL?horizon=5")
    assert r.status_code == 422 and r.json()["error"]["code"] == "INSUFFICIENT_DATA"


def test_spikes_endpoint_is_rate_limited_as_heavy(client, monkeypatch):
    monkeypatch.setattr(config, "HEAVY_RATE_PER_MIN", 1)
    codes = [client.get("/api/spikes/AAPL?horizon=1").status_code for _ in range(3)]
    assert codes[0] == 200 and codes[1:] == [429, 429]


def test_prediction_log_and_standard_forecast_unchanged_by_spikes(client, store):
    a = client.get("/api/forecast/AAPL?horizon=5").json()
    client.get("/api/spikes/AAPL?horizon=5")
    b = client.get("/api/forecast/AAPL?horizon=5").json()
    assert a["path"] == b["path"] and a["interval_80"] == b["interval_80"]
    assert store.all_rows() == []  # spikes never write to the scored prediction log
    assert "spike" not in open(main.__file__.replace("main.py", "trackrecord.py")).read().lower()


def test_verdict_needs_material_and_significant_change():
    from app.spikes import _verdict

    assert _verdict(0.015, 0.002, 0.03) == "inconclusive"  # significant but tiny
    assert _verdict(0.05, -0.01, 0.1) == "inconclusive"  # big but not significant
    assert _verdict(0.05, 0.01, 0.1) == "better" and _verdict(-0.05, -0.1, -0.01) == "worse"
