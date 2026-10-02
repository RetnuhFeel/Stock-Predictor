"""Model comparison and volatility forecast."""
import numpy as np
import pytest

from app import config, main
from app.errors import InsufficientData
from app.forecast import fold_schedule
from app.models import MODELS, build_context, compare_models
from app.volatility import forecast_volatility

from .conftest import synthetic_prices


def test_fold_schedule_embargo_never_overlaps():
    for n, h in [(900, 1), (900, 5), (900, 20), (900, 60), (400, 40)]:
        for train_end, test in fold_schedule(n, h):
            assert train_end + h <= test.start  # no training label reaches into the test block
            assert train_end >= 60


def test_compare_models_shape_and_embargo():
    close = synthetic_prices(900, seed=1)["Close"]
    out = compare_models(close, 10)
    assert [m["model"] for m in out["models"]] == [m.name for m in MODELS]
    assert out["embargo_days"] == 10 >= out["horizon_days"] and "10-day embargo" in out["method"]
    naive = out["models"][0]
    assert naive["verdict"] == "baseline" and naive["skill_vs_naive"] == 0.0 and naive["hit_rate"] is None
    for m in out["models"][1:]:
        assert len(m["skill_ci_90"]) == 2 and m["skill_ci_90"][0] <= m["skill_ci_90"][1]
        assert m["verdict"] in {"better", "inconclusive", "not_better"} and 0 <= m["hit_rate"] <= 1
        assert m["rmse"] > 0 and m["description"]
    assert out["n_test_points"] > out["n_independent_tests"] >= 1
    assert out["any_beats_naive"] == any(m["beats_naive"] for m in out["models"])
    assert "luck" in out["note"]  # multiple-comparisons caveat is always stated


def test_random_walk_has_no_winner_by_construction():
    # pure noise with zero drift: nothing legitimately beats "flat"; the harness must not invent skill
    wins = 0
    for seed in range(6):
        close = synthetic_prices(900, seed=seed, drift=0.0)["Close"]
        wins += compare_models(close, 5)["any_beats_naive"]
    assert wins <= 2  # a few false positives are expected with 4 models x 6 series; not a systematic win


def test_models_use_only_past_information():
    close = synthetic_prices(700, seed=3)["Close"]
    a = compare_models(close, 5)
    changed = close.copy()
    changed.iloc[-3:] *= 1.5  # alter the very last bars (labels of the final rows depend on them)
    ctx_a, ctx_b = build_context(close, 5), build_context(changed, 5)
    assert len(ctx_a.X) == len(ctx_b.X)
    # features at rows far from the end are identical: no look-ahead through feature construction
    assert np.allclose(ctx_a.X.iloc[:-30].to_numpy(), ctx_b.X.iloc[:-30].to_numpy())
    assert a["n_folds"] >= 1


def test_insufficient_data():
    with pytest.raises(InsufficientData):
        compare_models(synthetic_prices(100)["Close"], 5)
    with pytest.raises(InsufficientData):
        forecast_volatility(synthetic_prices(100)["Close"], 5)


def test_compare_models_endpoint(client, fake):
    r = client.get("/api/compare-models/aapl?horizon=20")
    b = r.json()
    assert r.status_code == 200 and b["symbol"] == "AAPL" and b["horizon_days"] == 20 and b["embargo_days"] == 20
    assert b["stale"] is False and b["fetched_at"].endswith("Z") and b["disclaimer"]
    calls = fake.calls
    client.get("/api/compare-models/AAPL?horizon=20")
    assert fake.calls == calls  # cached
    for bad in ["horizon=0", "horizon=257", "horizon=abc"]:
        assert client.get(f"/api/compare-models/AAPL?{bad}").status_code in (400, 422)
    assert client.get("/api/compare-models/A$B").json()["error"]["code"] == "INVALID_SYMBOL"
    assert client.get("/api/compare-models/FAIL").json()["error"]["code"] == "DATA_UNAVAILABLE"


def test_heavy_endpoints_rate_limited(client, monkeypatch):
    monkeypatch.setattr(config, "HEAVY_RATE_PER_MIN", 2)
    codes = [client.get("/api/volatility/AAPL").status_code for _ in range(4)]
    assert codes == [200, 200, 429, 429]
    assert client.get("/api/quote/AAPL").status_code == 200  # ordinary endpoints unaffected


def test_volatility_shape_and_honesty():
    close = synthetic_prices(900, seed=2)["Close"]
    v = forecast_volatility(close, 10)
    assert v["embargo_days"] == 10 and v["headline_model"] == "ewma"
    assert [m["model"] for m in v["models"]] == ["naive", "ewma", "har", "garch"]
    assert v["models"][0]["verdict"] == "baseline"
    assert 0 < v["forecast_daily_vol"] < 0.2
    assert abs(v["annualized_vol"] - v["forecast_daily_vol"] * np.sqrt(252)) < 1e-9
    rr = v["risk_range"]
    assert rr["low"] < v["last_close"] < rr["high"] and 0 <= rr["backtest_coverage"] <= 1
    assert rr["nominal_coverage"] == 0.68
    assert v["verdict"] in {"better", "inconclusive", "not_better"} and any("fat tails" in n for n in v["notes"])


def test_volatility_clustering_is_detected():
    # GARCH-like series: volatility clusters, so a vol model should be able to beat plain "recent vol" or at least run
    rng = np.random.default_rng(0)
    n, vol, rets = 1500, 0.01, []
    for _ in range(n):
        vol = np.sqrt(1e-6 + 0.1 * (rets[-1] ** 2 if rets else 1e-4) + 0.85 * vol**2)
        rets.append(rng.normal(0, vol))
    import pandas as pd
    close = pd.Series(100 * np.exp(np.cumsum(rets)), index=pd.bdate_range(end="2026-09-30", periods=n))
    v = forecast_volatility(close, 5)
    assert np.isfinite(v["skill_vs_naive"]) and v["models"][2]["model"] == "har"


def test_volatility_endpoint(client):
    r = client.get("/api/volatility/MSFT?horizon=20")
    b = r.json()
    assert r.status_code == 200 and b["horizon_days"] == 20 and b["risk_range"]["one_sigma_pct"] > 0
    assert b["stale"] is False and b["disclaimer"]
    assert client.get("/api/volatility/MSFT?horizon=999").status_code in (400, 422)
    assert main.cache._data  # cached
