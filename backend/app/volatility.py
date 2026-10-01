"""Volatility ("risk") forecast for the next ``horizon`` trading days, judged walk-forward vs a naive baseline.

Target: realized volatility over the next h days = sqrt(mean of squared daily log returns), in daily units.
Models (all use only past data at the forecast date):
  naive    recent realized vol: trailing 21-day volatility (the baseline to beat)
  ewma     RiskMetrics EWMA, lambda = 0.94 (no fitting)
  har      HAR-style regression of log future vol on log trailing vol over 5/22/66 days (fitted, with embargo)
Errors are measured on log(forecast / realized), so a tiny stock and a huge one are treated alike.
Volatility is far more predictable than direction (it clusters), but "more predictable" is still not "certain":
the 1-sigma range below is exceeded regularly, and the backtest measures how often.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .errors import InsufficientData
from .forecast import MIN_INDEPENDENT_TESTS, MIN_ROWS, fold_schedule, skill_ci_sq

LAMBDA = 0.94
HEADLINE = "ewma"  # fixed in advance: not chosen by looking at backtest results
FLOOR = 1e-5
TRADING_DAYS = 252

LABELS = {
    "naive": ("Naive: recent 21-day volatility", "Assumes the next period is as jumpy as the last 21 days."),
    "ewma": ("EWMA (RiskMetrics, λ=0.94)", "Weights recent days more heavily; no fitting."),
    "har": ("HAR-style regression", "Fitted blend of 5-, 22- and 66-day trailing volatility."),
}


def _rms(r2: pd.Series, w: int) -> pd.Series:
    return np.sqrt(r2.rolling(w).mean()).clip(lower=FLOOR)


def _har_X(frame: pd.DataFrame) -> np.ndarray:
    return np.column_stack([np.ones(len(frame)), np.log(frame["rv5"]), np.log(frame["rv22"]), np.log(frame["rv66"])])


def _dataset(close: pd.Series, horizon: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    logp = np.log(close)
    r1 = logp.diff()
    r2 = r1**2
    feats = pd.DataFrame({
        "rv5": _rms(r2, 5), "rv22": _rms(r2, 22), "rv66": _rms(r2, 66), "rv21": _rms(r2, 21),
        "ewma": np.sqrt(r2.ewm(alpha=1 - LAMBDA, adjust=False).mean()).clip(lower=FLOOR),
    })
    feats.iloc[:66] = np.nan  # burn-in for the long windows and the EWMA seed
    label = pd.DataFrame({
        "fut": np.sqrt(r2.rolling(horizon).mean().shift(-horizon)).clip(lower=FLOOR),
        "ret_h": logp.shift(-horizon) - logp,
    })
    return feats, label


def forecast_volatility(close: pd.Series, horizon: int, n_folds: int = 6) -> dict:
    close = close.dropna()
    close = close[close > 0]
    if len(close) < MIN_ROWS:
        raise InsufficientData(f"Need at least {MIN_ROWS} daily bars, got {len(close)}")
    feats, label = _dataset(close, horizon)
    data = feats.join(label).dropna()
    if len(data) < 150:
        raise InsufficientData("Not enough usable rows after feature construction")
    folds = fold_schedule(len(data), horizon, n_folds)
    if not folds:
        raise InsufficientData("Not enough history for walk-forward validation")

    actual = np.concatenate([data["fut"].iloc[t].to_numpy() for _, t in folds])
    ret_h = np.concatenate([data["ret_h"].iloc[t].to_numpy() for _, t in folds])
    preds: dict[str, np.ndarray] = {
        "naive": np.concatenate([data["rv21"].iloc[t].to_numpy() for _, t in folds]),
        "ewma": np.concatenate([data["ewma"].iloc[t].to_numpy() for _, t in folds]),
    }
    har_parts = []
    for te, t in folds:  # embargoed: labels of rows >= te look into the test block
        tr = data.iloc[:te]
        beta, *_ = np.linalg.lstsq(_har_X(tr), np.log(tr["fut"].to_numpy()), rcond=None)
        har_parts.append(np.exp(_har_X(data.iloc[t]) @ beta))
    preds["har"] = np.concatenate(har_parts)

    log_actual = np.log(actual)
    base_sq = (np.log(preds["naive"]) - log_actual) ** 2
    n_test = int(len(actual))
    n_indep = max(n_test // horizon, 1)

    rows = []
    for name, p in preds.items():
        sq = (np.log(p) - log_actual) ** 2
        is_naive = name == "naive"
        skill = 0.0 if is_naive else 1 - float(np.sqrt(sq.mean() / base_sq.mean()))
        ci = (0.0, 0.0) if is_naive else skill_ci_sq(sq, base_sq, horizon)
        beats = bool((not is_naive) and skill > 0.02 and ci[0] > 0)
        verdict = ("baseline" if is_naive else "better" if beats
                   else "inconclusive" if skill > 0 and ci[0] <= 0 else "not_better")
        label_, desc = LABELS[name]
        rows.append({"model": name, "label": label_, "description": desc,
                     "typical_error_pct": float(np.mean(np.abs(p / actual - 1)) * 100),
                     "skill_vs_naive": skill, "skill_ci_90": [ci[0], ci[1]], "beats_naive": beats, "verdict": verdict})

    # final forecasts from the latest data
    latest = feats.iloc[[-1]]
    tr = data
    beta, *_ = np.linalg.lstsq(_har_X(tr), np.log(tr["fut"].to_numpy()), rcond=None)
    daily = {"naive": float(latest["rv21"].iloc[0]), "ewma": float(latest["ewma"].iloc[0]),
             "har": float(np.exp(_har_X(latest) @ beta)[0])}
    for r in rows:
        d = daily[r["model"]]
        r["forecast_daily_vol"] = d
        r["annualized_vol"] = d * np.sqrt(TRADING_DAYS)

    head = daily[HEADLINE]
    horizon_vol = head * np.sqrt(horizon)
    last = float(close.iloc[-1])
    head_row = next(r for r in rows if r["model"] == HEADLINE)
    cover = float(np.mean(np.abs(ret_h) <= preds[HEADLINE] * np.sqrt(horizon)))
    return {
        "horizon_days": horizon, "last_close": round(last, 4), "last_date": close.index[-1].strftime("%Y-%m-%d"),
        "headline_model": HEADLINE, "forecast_daily_vol": head, "annualized_vol": head * np.sqrt(TRADING_DAYS),
        "horizon_vol": horizon_vol,
        "risk_range": {"one_sigma_pct": float(np.expm1(horizon_vol) * 100),
                       "low": round(last * float(np.exp(-horizon_vol)), 4),
                       "high": round(last * float(np.exp(horizon_vol)), 4),
                       "nominal_coverage": 0.68, "backtest_coverage": cover},
        "verdict": head_row["verdict"], "skill_vs_naive": head_row["skill_vs_naive"],
        "skill_ci_90": head_row["skill_ci_90"],
        "models": rows, "n_test_points": n_test, "n_independent_tests": n_indep,
        "small_sample": bool(n_indep < MIN_INDEPENDENT_TESTS),
        "embargo_days": horizon,
        "method": f"expanding-window walk-forward, {len(folds)} folds, {horizon}-day embargo, errors on log scale",
        "notes": [
            "The range is a 1-sigma move over the horizon (about 68% if returns were normal). It describes size, "
            "not direction.",
            "Real returns have fat tails: moves beyond the range happen, and big ones cluster in stress.",
            f"The headline model ({HEADLINE.upper()}) was fixed in advance, not picked after looking at the backtest.",
        ],
    }
