"""Point-forecast models behind one small interface, all judged by the same walk-forward + embargo test.

Every model predicts the log return over the next ``horizon`` trading days from information available at the
forecast date only. They are compared with the naive baseline "price stays flat" (predicted return = 0).
No heavy or pretrained models here on purpose (see docs: Chronos/TimesFM are an offline follow-up).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .errors import InsufficientData
from .forecast import (
    FEATURES,
    MIN_INDEP_FOR_VERDICT,
    MIN_INDEPENDENT_TESTS,
    MIN_ROWS,
    SEED,
    _metrics,
    _model,
    fold_schedule,
    make_features,
    not_enough_history,
    ratio,
    require_price_variation,
    skill_ci_sq,
)

EWMA_HALFLIFE = 63  # trading days
AR_FEATURES = ["ret_1", "ret_5", "ret_10", "ret_21", "vol_10", "vol_21"]


@dataclass
class Context:
    X: pd.DataFrame      # features for rows whose label is known
    y: pd.Series         # h-day log return label
    ewm_daily: pd.Series  # exponentially weighted mean of daily log returns (past data only)
    horizon: int


class PointModel:
    name = ""
    label = ""
    description = ""

    def predict(self, ctx: Context, train_end: int, test: slice) -> np.ndarray:  # pragma: no cover - interface
        raise NotImplementedError


class Naive(PointModel):
    name, label = "naive", "Naive: price stays flat"
    description = "Predicts no change. The bar every other model has to clear."

    def predict(self, ctx, train_end, test):
        return np.zeros(len(ctx.y.iloc[test]))


class Drift(PointModel):
    name, label = "drift", "Drift: average past return"
    description = "Predicts the average past h-day return seen in training data (a constant)."

    def predict(self, ctx, train_end, test):
        return np.full(len(ctx.y.iloc[test]), float(ctx.y.iloc[:train_end].mean()))


class EwmaMean(PointModel):
    name, label = "ewma", f"EWMA: recent average return (half-life {EWMA_HALFLIFE}d)"
    description = "Predicts the exponentially weighted average of recent daily returns, scaled to the horizon."

    def predict(self, ctx, train_end, test):
        return ctx.ewm_daily.iloc[test].to_numpy() * ctx.horizon


class RidgeAR(PointModel):
    name, label = "ridge_ar", "Ridge AR: shrunk linear model of past returns"
    description = "A heavily regularised linear model of recent returns and volatility (an autoregression-style model)."

    def predict(self, ctx, train_end, test):
        m = make_pipeline(StandardScaler(), Ridge(alpha=300.0, random_state=SEED))
        m.fit(ctx.X[AR_FEATURES].iloc[:train_end], ctx.y.iloc[:train_end])
        return m.predict(ctx.X[AR_FEATURES].iloc[test])


class GradientBoosting(PointModel):
    name, label = "gbm", "Gradient boosting (the model behind the forecast)"
    description = "The small boosted-tree model used for the main forecast, on technical features."

    def predict(self, ctx, train_end, test):
        m = _model().fit(ctx.X.iloc[:train_end], ctx.y.iloc[:train_end])
        return m.predict(ctx.X.iloc[test])


MODELS: list[PointModel] = [Naive(), Drift(), EwmaMean(), RidgeAR(), GradientBoosting()]
N_CANDIDATES = len(MODELS) - 1  # everything except the naive baseline


def build_context(close: pd.Series, horizon: int) -> Context:
    close = close.dropna()
    close = close[close > 0]
    if len(close) < MIN_ROWS:
        raise InsufficientData(f"Need at least {MIN_ROWS} daily bars, got {len(close)}")
    require_price_variation(close)
    logp = np.log(close)
    feats = make_features(close)
    ewm = logp.diff().ewm(halflife=EWMA_HALFLIFE, adjust=False).mean().rename("ewm")
    data = feats.assign(target=logp.shift(-horizon) - logp, ewm=ewm).dropna()
    if len(data) < 150:
        raise InsufficientData(not_enough_history(horizon, len(close)))
    return Context(data[FEATURES], data["target"], data["ewm"], horizon)


def compare_models(close: pd.Series, horizon: int, n_folds: int = 6) -> dict:
    """Walk-forward (with embargo) comparison of every model against the naive baseline."""
    ctx = build_context(close, horizon)
    folds = fold_schedule(len(ctx.X), horizon, n_folds)
    if not folds:
        raise InsufficientData(not_enough_history(horizon, len(ctx.X)))
    y_true = np.concatenate([ctx.y.iloc[test].to_numpy() for _, test in folds])
    base_sq = y_true**2
    n_test = int(len(y_true))
    n_indep = max(n_test // horizon, 1)
    up_rate = float(np.mean(y_true > 0))

    rows = []
    for model in MODELS:
        pred = np.concatenate([model.predict(ctx, te, test) for te, test in folds])
        m = _metrics(y_true, pred)
        is_naive = model.name == "naive"
        skill = 0.0 if is_naive else 1 - ratio(m["rmse"], float(np.sqrt(base_sq.mean())))
        ci = (0.0, 0.0) if is_naive else skill_ci_sq((y_true - pred) ** 2, base_sq, horizon)
        too_few = n_indep < MIN_INDEP_FOR_VERDICT
        beats = bool((not is_naive) and skill > 0.02 and ci[0] > 0 and not too_few)
        if is_naive:
            verdict = "baseline"
        elif beats:
            verdict = "better"
        elif skill > 0 and (ci[0] <= 0 or too_few):
            verdict = "inconclusive"
        else:
            verdict = "not_better"
        rows.append({
            "model": model.name, "label": model.label, "description": model.description,
            "rmse": m["rmse"], "mae": m["mae"],
            "hit_rate": None if is_naive else m["directional_accuracy"],
            "skill_vs_naive": float(skill), "skill_ci_90": [ci[0], ci[1]],
            "beats_naive": beats, "verdict": verdict,
        })
    n_better = sum(r["verdict"] == "better" for r in rows)
    return {
        "horizon_days": horizon, "embargo_days": horizon, "n_folds": len(folds),
        "n_test_points": n_test, "n_independent_tests": n_indep,
        "small_sample": bool(n_indep < MIN_INDEPENDENT_TESTS), "up_rate": up_rate,
        "method": f"expanding-window walk-forward, {len(folds)} folds, {horizon}-day embargo",
        "models": rows,
        "any_beats_naive": n_better > 0, "n_candidates": N_CANDIDATES,
        "note": (f"{N_CANDIDATES} models were tested, so one 'win' by luck is likely. A result only means "
                 "something if it holds up over time (see the track record). Overlapping windows make tests "
                 "correlated; the 90% range accounts for that with a block bootstrap."),
    }
