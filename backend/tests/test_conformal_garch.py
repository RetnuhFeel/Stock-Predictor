"""Split-conformal intervals (conformal.py, forecast.py) and the GJR-GARCH volatility model (garch.py)."""
import math
import time

import numpy as np
import pytest

from app import config, conformal, garch, main
from app.conformal import calibrate, conformal_quantile, measure_coverage, wilson_interval
from app.errors import DataUnavailable
from app.forecast import forecast, legacy_view
from app.trackrecord import record_from_forecast
from app.volatility import forecast_volatility

from .conftest import FakeProvider, synthetic_prices


# ---------- conformal building blocks ----------
def test_conformal_quantile_is_the_finite_sample_rank():
    assert conformal_quantile(np.arange(1.0, 10.0)) == 8.0          # n=9: ceil(10 * 0.8) = 8th smallest
    assert conformal_quantile(np.array([3.0, 1.0, 2.0, 5.0, 4.0])) == 5.0  # n=5: ceil(6 * 0.8) = 5th: the max
    assert math.isinf(conformal_quantile(np.array([1.0, 2.0, 3.0])))  # too few points for an 80% guarantee
    assert math.isinf(conformal_quantile(np.array([])))


def test_wilson_interval_is_sane():
    lo, hi = wilson_interval(0.8, 100)
    assert 0.7 < lo < 0.8 < hi < 0.88
    lo2, hi2 = wilson_interval(0.8, 10)
    assert (hi2 - lo2) > (hi - lo)                                   # fewer independent periods: wider range
    assert wilson_interval(1.0, 5)[1] == pytest.approx(1.0) and wilson_interval(0.0, 5)[0] == pytest.approx(0.0)


def test_replay_only_uses_scores_whose_outcome_was_known(monkeypatch):
    """At origin k, only origins j <= k - horizon may be used (the embargo), never the overlapping recent ones."""
    seen = []
    real = conformal.conformal_quantile

    def spy(sc, alpha=conformal.ALPHA):
        seen.append(len(sc))
        return real(sc, alpha)
    monkeypatch.setattr(conformal, "conformal_quantile", spy)
    scores = np.random.default_rng(0).random(400)
    h = 20
    measure_coverage(scores, h, min_cal=100)
    assert seen[0] == 100 and seen[-1] == len(scores) - h and seen == list(range(100, len(scores) - h + 1))


def test_replay_coverage_is_near_target_for_exchangeable_scores():
    scores = np.abs(np.random.default_rng(1).normal(size=4000))
    cov, n = measure_coverage(scores, 5)
    assert n > 3000 and 0.77 < cov < 0.83


def test_calibrate_supported_on_stable_scores_and_refused_on_a_regime_shift():
    rng = np.random.default_rng(2)
    stable = calibrate(np.abs(rng.normal(size=3000)), 5)
    assert stable.supported and stable.reason is None
    assert 0.75 < stable.measured_coverage < 0.85 and stable.n_evaluation_independent > 100
    assert stable.coverage_ci_90[0] < stable.measured_coverage < stable.coverage_ci_90[1]
    # calm history followed by a violent one: the past quantile badly under-covers -> must NOT be used
    shift = calibrate(np.concatenate([np.full(600, 0.5), np.full(600, 3.0)]) + rng.random(1200) * 0.01, 5)
    assert not shift.supported and "under-coverage" in shift.reason


def test_calibrate_refuses_when_the_history_is_too_short_to_check():
    c = calibrate(np.abs(np.random.default_rng(3).normal(size=120)), 5)
    assert not c.supported and "independent" in c.reason
    c0 = calibrate(np.abs(np.random.default_rng(3).normal(size=60)), 5)
    assert not c0.supported and "past forecasts" in c0.reason
    c2 = calibrate(np.abs(np.random.default_rng(3).normal(size=700)), 120)
    assert not c2.supported and "independent" in c2.reason
    assert c2.measured_coverage is not None  # still measured and reported, just not trusted enough to use


def test_calibration_feasible_precheck():
    assert conformal.calibration_feasible(120) and conformal.calibration_feasible(180)
    assert not conformal.calibration_feasible(256)
    assert not conformal.calibration_feasible(120, 1260)             # five years cannot support 120 days


# ---------- forecast(): the interval, its honesty fields and the fallbacks ----------
def test_forecast_uses_conformal_interval_with_measured_coverage():
    f = forecast(synthetic_prices(900, seed=11)["Close"], 5)
    c = f["conformal"]
    assert c["used"] and f["interval_method_name"] == "split_conformal" and f["interval_calibrated"] is True
    assert c["target_coverage"] == 0.8 and c["n_calibration"] > 300 and c["n_evaluation_independent"] >= 8
    assert 0.7 < c["measured_coverage"] < 0.9
    lo, hi = c["measured_coverage_ci_90"]
    assert lo < c["measured_coverage"] < hi and c["reason_not_used"] is None and c["fallback"] is None
    assert f["path"][-1]["low"] == pytest.approx(f["interval_80"]["low"], rel=1e-3)
    assert any("conformal" in n for n in f["notes"])


def test_legacy_band_is_kept_and_reproduced():
    f = forecast(synthetic_prices(900, seed=11)["Close"], 5)
    lb = f["legacy_band"]
    assert lb["low"] < lb["high"]
    v = legacy_view(f)
    assert v["interval_80"] == {"low": lb["low"], "high": lb["high"]}
    assert v["path"][-1]["low"] == pytest.approx(lb["low"], rel=1e-3) and len(v["path"]) == len(f["path"])
    assert [p["date"] for p in v["path"]] == [p["date"] for p in f["path"]]
    assert v["path"][0]["mid"] == f["path"][0]["mid"]


def test_prediction_log_keeps_the_pre_conformal_interval():
    f = {**forecast(synthetic_prices(900, seed=12)["Close"], 5), "symbol": "TST"}
    rec = record_from_forecast(f)
    assert (rec["interval_low"], rec["interval_high"]) == (f["legacy_band"]["low"], f["legacy_band"]["high"])
    assert (rec["interval_low"], rec["interval_high"]) != (f["interval_80"]["low"], f["interval_80"]["high"])


def test_short_history_falls_back_and_says_why():
    f = forecast(synthetic_prices(300, seed=5)["Close"], 5)
    c = f["conformal"]
    assert not c["used"] and c["reason_not_used"] and c["fallback"] == "walk_forward_residuals"
    assert f["interval_method_name"] == "walk_forward_residuals" and f["interval_80"] == {
        "low": f["legacy_band"]["low"], "high": f["legacy_band"]["high"]}
    assert any("could not be verified" in n for n in f["notes"])


def test_cone_horizon_needs_long_history_for_conformal():
    close5 = synthetic_prices(900, seed=7)["Close"]
    f = forecast(close5, 120)                                          # five years: not enough independent periods
    assert not f["conformal"]["used"] and f["interval_method_name"] == "volatility_cone"
    assert f["interval_calibrated"] is False and "independent" in f["conformal"]["reason_not_used"]
    assert f["conformal"]["fallback"] == "volatility_cone"
    long = synthetic_prices(2400, seed=7)["Close"]
    g = forecast(close5, 120, calib_close=long)                        # ten years: enough to check it
    assert g["conformal"]["used"] and g["interval_method_name"] == "split_conformal"
    assert g["interval_calibrated"] is True and g["conformal"]["n_calibration"] > 1500
    assert g["conformal"]["n_evaluation_independent"] >= 8
    assert g["interval_80"] != f["interval_80"]
    assert g["legacy_band"]["centre"] == 0.0                           # the cone stays the legacy band


def test_cone_calibration_uses_only_past_data():
    """Scores at origin t depend on prices up to t+h only; changing prices after the last label changes nothing."""
    close = synthetic_prices(1500, seed=9)["Close"]
    base = forecast(close.iloc[:900], 120, calib_close=close)["conformal"]["multiplier"]
    close2 = close.copy()
    close2.iloc[-5:] *= 3                                               # perturb the very last bars only
    again = forecast(close.iloc[:900], 120, calib_close=close2)["conformal"]["multiplier"]
    assert abs(base - again) < 0.05                                     # last 5 bars hardly matter (they have no label)


# ---------- API wiring ----------
class NoLongHistory(FakeProvider):
    def history(self, symbol, period):
        if period == "10y":
            raise DataUnavailable("no 10y")
        return super().history(symbol, period)


def test_api_forecast_exposes_conformal_block(client):
    d = client.get("/api/forecast/AAPL?horizon=5").json()
    assert d["conformal"]["used"] is True and d["interval_method_name"] == "split_conformal"
    assert {"measured_coverage", "n_calibration", "n_evaluation_independent", "multiplier"} <= set(d["conformal"])


def test_api_long_horizon_uses_ten_year_history_when_available(client):
    d = client.get("/api/forecast/AAPL?horizon=120").json()
    assert d["conformal"]["used"] is True and d["interval_calibrated"] is True


def test_api_long_horizon_falls_back_when_ten_year_download_fails(app_with, monkeypatch):
    c = app_with(NoLongHistory())
    r = c.get("/api/forecast/AAPL?horizon=120")
    assert r.status_code == 200
    d = r.json()
    assert d["interval_method_name"] == "volatility_cone" and d["interval_calibrated"] is False


def test_api_long_horizon_falls_back_when_ten_year_download_is_slow(app_with, monkeypatch):
    class Slow(FakeProvider):
        def history(self, symbol, period):
            if period == "10y":
                time.sleep(5.0)
            return super().history(symbol, period)
    monkeypatch.setattr(config, "CALIB_FETCH_DEADLINE_S", 0.05)
    t = time.monotonic()
    d = app_with(Slow()).get("/api/forecast/AAPL?horizon=120").json()
    assert d["interval_method_name"] == "volatility_cone" and time.monotonic() - t < 4.0


def test_spikes_endpoint_keeps_the_pre_conformal_band(client, monkeypatch):
    seen = {}
    real = main.spike_forecast

    def spy(close, horizon, base):
        seen["base"] = base
        return real(close, horizon, base)
    monkeypatch.setattr(main, "spike_forecast", spy)
    fc = client.get("/api/forecast/AAPL?horizon=5").json()
    assert client.get("/api/spikes/AAPL?horizon=5").status_code == 200
    assert seen["base"]["interval_80"] == {"low": fc["legacy_band"]["low"], "high": fc["legacy_band"]["high"]}


# ---------- GJR-GARCH ----------
def _simulate_gjr(n, alpha, gamma, beta, omega, seed=0):
    rng = np.random.default_rng(seed)
    z = rng.standard_normal(n)
    r = np.empty(n)
    s2 = omega / (1 - alpha - gamma / 2 - beta)
    for t in range(n):
        r[t] = np.sqrt(s2) * z[t]
        s2 = omega + (alpha + gamma * (r[t] < 0)) * r[t] ** 2 + beta * s2
    return r


def test_fit_recovers_a_simulated_gjr_process():
    r = _simulate_gjr(8000, 0.04, 0.10, 0.85, 0.05, seed=3)           # persistence 0.94
    f = garch.fit_gjr(r)
    assert f.converged and abs(f.persistence - 0.94) < 0.03
    assert f.gamma > f.alpha and f.gamma > 0.04                         # the leverage effect is picked up
    assert 0.8 < f.beta < 0.92


def test_variance_filter_matches_a_plain_loop():
    r = np.random.default_rng(4).normal(size=300) * 1.2
    a, g, b, w, s0 = 0.05, 0.08, 0.85, 0.07, 1.4
    fast = garch.next_variance(r, a, g, b, w, s0)
    s2, ref = s0, []
    for x in r:
        s2 = w + (a + g * (x < 0)) * x * x + b * s2
        ref.append(s2)
    assert np.allclose(fast, ref)


def test_horizon_forecast_matches_brute_force_and_reverts_to_long_run():
    r = _simulate_gjr(1500, 0.05, 0.08, 0.85, 0.05, seed=5)
    f = garch.fit_gjr(r)
    nxt = garch.next_variance(r, f.alpha, f.gamma, f.beta, f.omega, f.long_run_var)[-1]
    p, v, h = f.persistence, f.long_run_var, 30
    brute = np.mean([v + p ** (k - 1) * (nxt - v) for k in range(1, h + 1)])
    assert garch.horizon_vol(f, r, h)[-1] == pytest.approx(math.sqrt(brute) / 100)
    assert garch.horizon_vol(f, r, 1)[-1] == pytest.approx(math.sqrt(nxt) / 100)
    far = garch.horizon_vol(f, r, 5000)[-1]
    assert abs(far - math.sqrt(v) / 100) / (math.sqrt(v) / 100) < 0.1   # far horizon -> long-run volatility


def test_garch_forecast_at_t_ignores_the_future():
    r = _simulate_gjr(900, 0.05, 0.08, 0.85, 0.05, seed=6)
    f = garch.fit_gjr(r[:600])
    full = garch.horizon_vol(f, r, 10)
    part = garch.horizon_vol(f, r[:700], 10)
    assert np.allclose(full[:700], part)
    changed = r.copy()
    changed[700:] *= 5
    assert np.allclose(garch.horizon_vol(f, changed, 10)[:700], full[:700])


def test_fit_refuses_bad_input_and_respects_its_time_budget():
    with pytest.raises(garch.GarchUnavailable):
        garch.fit_gjr(np.random.default_rng(0).normal(size=100))
    with pytest.raises(garch.GarchUnavailable):
        garch.fit_gjr(np.zeros(500))
    with pytest.raises(garch.GarchUnavailable, match="time budget"):
        garch.fit_gjr(np.random.default_rng(0).normal(size=600), deadline_s=0.0)


# ---------- volatility + comparison endpoints ----------
def test_volatility_reports_garch_against_the_ewma_headline():
    v = forecast_volatility(synthetic_prices(900, seed=21)["Close"], 20)
    assert v["headline_model"] == "ewma" and v["garch"]["available"] is True
    g = next(m for m in v["models"] if m["model"] == "garch")
    assert set(g["vs_headline"]) == {"model", "skill", "skill_ci_90", "verdict"} and g["vs_headline"]["model"] == "ewma"
    assert g["vs_headline"]["verdict"] in {"better", "inconclusive", "not_better"}
    assert "vs_headline" not in next(m for m in v["models"] if m["model"] == "ewma")
    assert g["horizon_vol"] == pytest.approx(g["forecast_daily_vol"] * math.sqrt(20))
    params = v["garch"]["params"]
    assert 0 < params["persistence"] < 1 and params["long_run_annual_vol"] > 0
    words = {"better": "was better than", "inconclusive": "was not clearly different from",
             "not_better": "was not better than"}[g["vs_headline"]["verdict"]]
    assert any(n.startswith("GJR-GARCH " + words) for n in v["notes"])
    assert v["verdict"] == next(m for m in v["models"] if m["model"] == "ewma")["verdict"]  # headline unchanged


def test_garch_is_omitted_not_faked_when_it_cannot_be_fitted(monkeypatch):
    close = synthetic_prices(300, seed=22)["Close"]                     # too short for a 250-return GARCH fit
    v = forecast_volatility(close, 5)
    assert v["garch"]["available"] is False and v["garch"]["reason"]
    assert [m["model"] for m in v["models"]] == ["naive", "ewma", "har"]
    assert not any("GJR-GARCH" in n for n in v["notes"])
    monkeypatch.setattr(config, "GARCH_DEADLINE_S", 0.0)
    v2 = forecast_volatility(synthetic_prices(900, seed=22)["Close"], 5)
    assert v2["garch"]["available"] is False and "garch" not in [m["model"] for m in v2["models"]]


def test_a_failed_fold_fit_reuses_the_previous_fit_and_says_so(monkeypatch):
    real = garch.fit_gjr
    calls = {"n": 0}

    def flaky(r, deadline_s=None):
        calls["n"] += 1
        if calls["n"] == 3:
            raise garch.GarchUnavailable("boom")
        return real(r, deadline_s)
    monkeypatch.setattr(garch, "fit_gjr", flaky)
    v = forecast_volatility(synthetic_prices(900, seed=23)["Close"], 5)
    assert v["garch"]["available"] and v["garch"]["n_failed_fold_fits"] == 1


def test_garch_cost_is_small():
    close = synthetic_prices(1260, seed=24)["Close"]
    t = time.monotonic()
    forecast_volatility(close, 20)
    assert time.monotonic() - t < 5


def test_compare_models_endpoint_adds_the_risk_models(client):
    d = client.get("/api/compare-models/AAPL?horizon=20").json()
    assert [m["model"] for m in d["models"]] == ["naive", "drift", "ewma", "ridge_ar", "gbm"]  # point models unchanged
    r = d["risk_models"]
    assert r["headline_model"] == "ewma" and [m["model"] for m in r["models"]] == ["naive", "ewma", "har", "garch"]
    assert r["garch"]["available"] and "vs_headline" in r["models"][3]
    calls = client.get("/api/volatility/AAPL?horizon=20").json()      # same cached computation, same numbers
    assert calls["models"][3]["skill_vs_naive"] == r["models"][3]["skill_vs_naive"]


def test_openapi_and_dependencies_stay_light():
    import sys
    assert "statsmodels" not in sys.modules and "arch" not in sys.modules
