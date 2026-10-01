"""Honest, small-scale forecasting.

Target: the log return over the next ``horizon`` trading days.
Model:  HistGradientBoostingRegressor on simple technical features.
Check:  expanding-window walk-forward validation (chronological, with a ``horizon``-day embargo
        so training labels never overlap the test period), compared with the naive persistence
        baseline "price stays where it is" (predicted return = 0).
Bands:  empirical quantiles of the out-of-sample walk-forward errors (80% interval).

Daily stock returns are close to unpredictable. In most cases this model will NOT beat the
baseline by a meaningful margin, and the response says so explicitly.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from .errors import InsufficientData

SEED = 42
FEATURES = ["ret_1", "ret_5", "ret_10", "ret_21", "vol_10", "vol_21", "rsi_14", "macd_hist", "dist_sma50"]
MIN_ROWS = 250  # ~1 year of daily bars needed for a meaningful backtest


MIN_INDEPENDENT_TESTS = 30  # below this many non-overlapping test windows, the backtest is labelled "small sample"
N_BOOT = 300


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / down.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def make_features(close: pd.Series) -> pd.DataFrame:
    logp = np.log(close)
    r1 = logp.diff()
    ema12, ema26 = close.ewm(span=12, adjust=False).mean(), close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    feats = pd.DataFrame({
        "ret_1": r1,
        "ret_5": logp.diff(5),
        "ret_10": logp.diff(10),
        "ret_21": logp.diff(21),
        "vol_10": r1.rolling(10).std(),
        "vol_21": r1.rolling(21).std(),
        "rsi_14": rsi(close),
        "macd_hist": (macd - macd.ewm(span=9, adjust=False).mean()) / close,
        "dist_sma50": close / close.rolling(50).mean() - 1,
    })
    return feats[FEATURES]


def _model() -> HistGradientBoostingRegressor:
    # Small, heavily regularised model: with this little, noisy data, bigger is only worse.
    return HistGradientBoostingRegressor(max_depth=3, max_iter=80, learning_rate=0.05,
                                         min_samples_leaf=20, l2_regularization=1.0, random_state=SEED)


@dataclass
class WalkForward:
    y_true: np.ndarray
    y_pred: np.ndarray
    n_folds: int


def walk_forward(X: pd.DataFrame, y: pd.Series, horizon: int, n_folds: int = 6) -> WalkForward:
    """Expanding-window walk-forward: train on [0, t - horizon), predict the block [t, t + step)."""
    n = len(X)
    start = max(int(n * 0.5), 120)
    step = max((n - start) // n_folds, 1)
    trues, preds, folds = [], [], 0
    for t in range(start, n, step):
        train_end = t - horizon  # embargo: labels of rows >= train_end look into the test block
        if train_end < 60:
            continue
        test = slice(t, min(t + step, n))
        m = _model().fit(X.iloc[:train_end], y.iloc[:train_end])
        preds.append(m.predict(X.iloc[test]))
        trues.append(y.iloc[test].to_numpy())
        folds += 1
    if not trues:
        raise InsufficientData("Not enough history for walk-forward validation")
    return WalkForward(np.concatenate(trues), np.concatenate(preds), folds)


def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    err = y_true - y_pred
    return {
        "rmse": float(np.sqrt(np.mean(err**2))),
        "mae": float(np.mean(np.abs(err))),
        "directional_accuracy": float(np.mean(np.sign(y_pred) == np.sign(y_true))) if np.any(y_pred) else None,
    }


def skill_ci(y_true: np.ndarray, y_pred: np.ndarray, block: int, level: float = 0.90) -> tuple[float, float]:
    """Moving-block bootstrap CI for skill = 1 - RMSE_model / RMSE_naive.

    Blocks of ``block`` consecutive test points (the forecast horizon) keep the overlap-induced
    autocorrelation of multi-day returns, so the interval is not overconfident.
    """
    rng = np.random.default_rng(SEED)
    n = len(y_true)
    block = max(min(block, n), 1)
    starts_max = n - block + 1
    n_blocks = int(np.ceil(n / block))
    err_m, err_b = (y_true - y_pred) ** 2, y_true**2
    skills = np.empty(N_BOOT)
    for i in range(N_BOOT):
        idx = (rng.integers(0, starts_max, n_blocks)[:, None] + np.arange(block)).ravel()[:n]
        skills[i] = 1 - np.sqrt(err_m[idx].mean()) / np.sqrt(err_b[idx].mean())
    lo, hi = np.quantile(skills, [(1 - level) / 2, 1 - (1 - level) / 2])
    return float(lo), float(hi)


def forecast(close: pd.Series, horizon: int) -> dict:
    close = close.dropna()
    close = close[close > 0]
    if len(close) < MIN_ROWS:
        raise InsufficientData(f"Need at least {MIN_ROWS} daily bars, got {len(close)}")

    feats = make_features(close)
    target = np.log(close).shift(-horizon) - np.log(close)  # future h-day log return
    data = feats.assign(target=target)
    train_df = data.dropna()  # rows whose label is known
    if len(train_df) < 150:
        raise InsufficientData("Not enough usable rows after feature construction")

    X, y = train_df[FEATURES], train_df["target"]
    wf = walk_forward(X, y, horizon)

    model_m = _metrics(wf.y_true, wf.y_pred)
    base_m = _metrics(wf.y_true, np.zeros_like(wf.y_true))
    # Fraction of baseline error removed (positive = better than naive). Usually ~0 or negative.
    skill = 1 - model_m["rmse"] / base_m["rmse"]
    up_rate = float(np.mean(wf.y_true > 0))
    base_m["directional_accuracy"] = up_rate  # hit-rate of "always predict up", for context
    ci_lo, ci_hi = skill_ci(wf.y_true, wf.y_pred, horizon)
    n_test = int(len(wf.y_true))
    n_independent = max(n_test // horizon, 1)  # test windows overlap: roughly this many are independent

    # Final model on all labelled data; predict from the latest feature row.
    final = _model().fit(X, y)
    latest = feats.dropna().iloc[[-1]]
    point = float(final.predict(latest)[0])

    resid = wf.y_true - wf.y_pred
    q10, q90 = (float(np.quantile(resid, 0.10)), float(np.quantile(resid, 0.90)))
    last = float(close.iloc[-1])
    last_date = close.index[-1]
    bdays = pd.bdate_range(last_date, periods=horizon + 1)[1:]

    path = []
    for i, d in enumerate(bdays, start=1):
        frac = np.sqrt(i / horizon)  # widen like sqrt(time); an approximation of the cone
        path.append({
            "date": d.strftime("%Y-%m-%d"),
            "mid": round(last * float(np.exp(point * i / horizon)), 4),
            "low": round(last * float(np.exp(point * i / horizon + q10 * frac)), 4),
            "high": round(last * float(np.exp(point * i / horizon + q90 * frac)), 4),
        })

    # "Beats" requires a meaningful gain AND a bootstrap interval that excludes zero.
    beats = bool(skill > 0.02 and ci_lo > 0)
    notes = [
        "Interval is the empirical 10th-90th percentile of out-of-sample walk-forward errors "
        "(an ~80% band); real outcomes fall outside it regularly, especially in market stress.",
    ]
    if not beats:
        notes.append("The model did NOT meaningfully beat the naive 'price stays flat' baseline in the "
                     "backtest. Treat the point forecast as noise.")

    return {
        "horizon_days": horizon,
        "last_close": round(last, 4),
        "last_date": last_date.strftime("%Y-%m-%d"),
        "predicted_return": point,
        "predicted_price": round(last * float(np.exp(point)), 4),
        "interval_80": {"low": round(last * float(np.exp(point + q10)), 4),
                        "high": round(last * float(np.exp(point + q90)), 4)},
        "path": path,
        "backtest": {
            "method": f"expanding-window walk-forward, {wf.n_folds} folds, {horizon}-day embargo",
            "n_test_points": n_test,
            "n_independent_tests": n_independent,
            "small_sample": bool(n_independent < MIN_INDEPENDENT_TESTS),
            "up_rate": up_rate,
            "skill_ci_90": [ci_lo, ci_hi],
            "model": model_m,
            "naive_baseline": base_m,
            "skill_vs_baseline": float(skill),
            "beats_baseline": beats,
            "note": "Overlapping multi-day windows make test points correlated; the 90% interval accounts "
                    "for that with a block bootstrap. Metrics are indicative only.",
        },
        "notes": notes,
    }
