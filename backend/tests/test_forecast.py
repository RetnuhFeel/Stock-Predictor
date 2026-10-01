import numpy as np
import pytest

from app.forecast import InsufficientData, forecast, make_features, rsi
from tests.conftest import synthetic_prices


def test_rsi_bounds():
    r = rsi(synthetic_prices()["Close"])
    assert r.between(0, 100).all()


def test_features_have_no_lookahead():
    close = synthetic_prices()["Close"]
    full = make_features(close)
    truncated = make_features(close.iloc[:-50])
    # features at time t must not change when future data is removed
    assert np.allclose(full.iloc[:-50].dropna().to_numpy(), truncated.dropna().to_numpy())


def test_forecast_structure_and_honesty():
    out = forecast(synthetic_prices()["Close"], horizon=5)
    assert out["interval_80"]["low"] < out["predicted_price"] < out["interval_80"]["high"]
    assert len(out["path"]) == 5
    bt = out["backtest"]
    assert bt["model"]["rmse"] > 0 and bt["naive_baseline"]["rmse"] > 0
    assert "embargo" in bt["method"]
    # a random walk has nothing to learn: the model must not claim a big edge
    assert bt["skill_vs_baseline"] < 0.15


def test_forecast_is_deterministic():
    c = synthetic_prices()["Close"]
    assert forecast(c, 5)["predicted_return"] == forecast(c, 5)["predicted_return"]


def test_insufficient_data():
    with pytest.raises(InsufficientData):
        forecast(synthetic_prices(n=100)["Close"], 5)
