"""Volatility ("risk") forecast for the next ``horizon`` trading days, judged walk-forward vs a naive baseline.

Target: realized volatility over the next h days = sqrt(mean of squared daily log returns), in daily units.
Models (all use only past data at the forecast date):
  naive    recent realized vol: trailing 21-day volatility (the baseline to beat)
  ewma     RiskMetrics EWMA, lambda = 0.94 (no fitting)
  har      HAR-style regression of log future vol on log trailing vol over 5/22/66 days (fitted, with embargo)
  garch    GJR-GARCH(1,1) (garch.py): fitted by quasi-maximum likelihood on past returns only; its forecast mean-reverts
           to the long-run level and reacts more to down days. Judged against the naive baseline AND against the
           headline EWMA, with the same metrics; the headline model stays EWMA (fixed in advance).
Errors are measured on log(forecast / realized), so a tiny stock and a huge one are treated alike.
Volatility is far more predictable than direction (it clusters), but "more predictable" is still not "certain":
the 1-sigma range below is exceeded regularly, and the backtest measures how often.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

from . import config, garch
from .conformal import ewma_vol_series
from .errors import InsufficientData
from .forecast import (
    MIN_INDEP_FOR_VERDICT,
    MIN_INDEPENDENT_TESTS,
    MIN_ROWS,
    fold_schedule,
    not_enough_history,
    ratio,
    require_price_variation,
    skill_ci_sq,
)

LAMBDA = 0.94
HEADLINE = "ewma"  # fixed in advance: not chosen by looking at backtest results
FLOOR = 1e-5
TRADING_DAYS = 252

LABELS = {
    "naive": ("Naive: recent 21-day volatility", "Assumes the next period is as jumpy as the last 21 days."),
    "ewma": ("EWMA (RiskMetrics, λ=0.94)", "Weights recent days more heavily; no fitting."),
    "har": ("HAR-style regression", "Fitted blend of 5-, 22- and 66-day trailing volatility."),
    "garch": ("GJR-GARCH(1,1)", "Fitted model where down days raise expected volatility more than up days, and "
                                "volatility drifts back toward its long-run level."),
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


def ewma_daily_vol(close: pd.Series) -> float:
    """Latest RiskMetrics EWMA daily log-return volatility (lambda 0.94). Cheap: no walk-forward fit."""
    return float(ewma_vol_series(close).iloc[-1])


def _verdict(skill: float, ci_lo: float, too_few: bool, baseline: bool = False) -> tuple[bool, str]:
    """(beats, verdict): "better" needs >2% skill, a bootstrap range above zero and enough independent periods."""
    beats = bool((not baseline) and skill > 0.02 and ci_lo > 0 and not too_few)
    if baseline:
        return False, "baseline"
    if beats:
        return True, "better"
    return False, "inconclusive" if skill > 0 and (ci_lo <= 0 or too_few) else "not_better"


def _garch_walk_forward(close: pd.Series, data: pd.DataFrame, folds, horizon: int, budget_s: float):
    """Out-of-sample GJR-GARCH forecasts for the same test rows as the other models.

    For each fold the parameters are fitted on returns up to the first test origin (nothing later), then the variance
    filter runs forward with those fixed parameters, using each origin's own past only. No labels are involved, so no
    embargo is needed beyond that. Returns (predictions or None, number of failed fits, last fit)."""
    r = (np.log(close).diff() * 100).dropna()
    deadline = time.monotonic() + budget_s
    parts, failures, fit = [], 0, None
    for _, test in folds:
        origin = data.index[test.start]
        try:
            remaining = max(deadline - time.monotonic(), 0.05)
            fit = garch.fit_gjr(r.loc[:origin].to_numpy(), remaining)
        except garch.GarchUnavailable:
            failures += 1
            if fit is None:
                return None, failures, None  # no earlier fit to fall back on: report GARCH as unavailable
        hv = pd.Series(garch.horizon_vol(fit, r.to_numpy(), horizon), index=r.index)
        parts.append(hv.reindex(data.index[test]).to_numpy())
    out = np.concatenate(parts)
    if not np.all(np.isfinite(out)):
        return None, failures, None
    return out, failures, fit


def forecast_volatility(close: pd.Series, horizon: int, n_folds: int = 6) -> dict:
    close = close.dropna()
    close = close[close > 0]
    if len(close) < MIN_ROWS:
        raise InsufficientData(f"Need at least {MIN_ROWS} daily bars, got {len(close)}")
    require_price_variation(close)
    feats, label = _dataset(close, horizon)
    data = feats.join(label).dropna()
    if len(data) < 150:
        raise InsufficientData(not_enough_history(horizon, len(close)))
    folds = fold_schedule(len(data), horizon, n_folds)
    if not folds:
        raise InsufficientData(not_enough_history(horizon, len(data)))

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
    g_pred, g_failures, _ = _garch_walk_forward(close, data, folds, horizon, config.GARCH_DEADLINE_S)
    if g_pred is not None:
        preds["garch"] = g_pred

    log_actual = np.log(actual)
    base_sq = (np.log(preds["naive"]) - log_actual) ** 2
    n_test = int(len(actual))
    n_indep = max(n_test // horizon, 1)

    ewma_sq = (np.log(preds[HEADLINE]) - log_actual) ** 2
    too_few = n_indep < MIN_INDEP_FOR_VERDICT
    rows = []
    for name, p in preds.items():
        sq = (np.log(p) - log_actual) ** 2
        is_naive = name == "naive"
        skill = 0.0 if is_naive else 1 - ratio(float(np.sqrt(sq.mean())), float(np.sqrt(base_sq.mean())))
        ci = (0.0, 0.0) if is_naive else skill_ci_sq(sq, base_sq, horizon)
        beats, verdict = _verdict(skill, ci[0], too_few, baseline=is_naive)
        label_, desc = LABELS[name]
        row = {"model": name, "label": label_, "description": desc,
               "typical_error_pct": float(np.mean(np.abs(p / actual - 1)) * 100),
               "one_sigma_coverage": float(np.mean(np.abs(ret_h) <= p * np.sqrt(horizon))),
               "skill_vs_naive": skill, "skill_ci_90": [ci[0], ci[1]], "beats_naive": beats, "verdict": verdict}
        if name != HEADLINE:  # same metric, judged against the headline EWMA instead of the naive baseline
            s_e = 1 - ratio(float(np.sqrt(sq.mean())), float(np.sqrt(ewma_sq.mean())))
            ci_e = skill_ci_sq(sq, ewma_sq, horizon)
            row["vs_headline"] = {"model": HEADLINE, "skill": s_e, "skill_ci_90": [ci_e[0], ci_e[1]],
                                  "verdict": _verdict(s_e, ci_e[0], too_few)[1]}
        rows.append(row)

    # final forecasts from the latest data
    latest = feats.iloc[[-1]]
    tr = data
    beta, *_ = np.linalg.lstsq(_har_X(tr), np.log(tr["fut"].to_numpy()), rcond=None)
    daily = {"naive": float(latest["rv21"].iloc[0]), "ewma": float(latest["ewma"].iloc[0]),
             "har": float(np.exp(_har_X(latest) @ beta)[0])}
    g_info = {"available": False, "reason": ("not enough history or the fit did not finish in time"
                                             if g_pred is None else None)}
    if g_pred is not None:
        try:
            r_all = (np.log(close).diff() * 100).dropna().to_numpy()
            g_fit = garch.fit_gjr(r_all, config.GARCH_DEADLINE_S)
            daily["garch"] = float(garch.horizon_vol(g_fit, r_all, horizon)[-1])
            g_info = {"available": True, "reason": None, "converged": g_fit.converged,
                      "n_failed_fold_fits": g_failures,
                      "params": {"alpha": g_fit.alpha, "gamma": g_fit.gamma, "beta": g_fit.beta,
                                 "persistence": g_fit.persistence, "half_life_days": g_fit.half_life_days,
                                 "long_run_annual_vol": g_fit.long_run_annual_vol,
                                 "asymmetric": bool(g_fit.gamma > 0.02)}}
        except garch.GarchUnavailable:
            rows = [r for r in rows if r["model"] != "garch"]
            g_info = {"available": False, "reason": "the final fit did not finish in time"}
    for r in rows:
        d = daily[r["model"]]
        r["forecast_daily_vol"] = d
        r["annualized_vol"] = d * np.sqrt(TRADING_DAYS)
        r["horizon_vol"] = d * np.sqrt(horizon)

    head = daily[HEADLINE]
    horizon_vol = head * np.sqrt(horizon)
    last = float(close.iloc[-1])
    head_row = next(r for r in rows if r["model"] == HEADLINE)
    cover = float(np.mean(np.abs(ret_h) <= preds[HEADLINE] * np.sqrt(horizon)))
    notes = [
        "The range is a 1-sigma move over the horizon (about 68% if returns were normal). It describes size, "
        "not direction.",
        "Real returns have fat tails: moves beyond the range happen, and big ones cluster in stress.",
        f"The headline model ({HEADLINE.upper()}) was fixed in advance, not picked after looking at the backtest.",
    ]
    g_row = next((r for r in rows if r["model"] == "garch"), None)
    if g_row is not None:
        v = g_row["vs_headline"]
        words = {"better": "was better than", "inconclusive": "was not clearly different from",
                 "not_better": "was not better than"}[v["verdict"]]
        g_info["vs_headline"] = v
        g_info["horizon_vol"] = g_row["horizon_vol"]
        g_info["annualized_vol"] = g_row["annualized_vol"]
        g_info["one_sigma_pct"] = float(np.expm1(g_row["horizon_vol"]) * 100)
        notes.append(
            f"GJR-GARCH {words} the EWMA headline in this backtest (error change {v['skill']:+.1%}, 90% range "
            f"{v['skill_ci_90'][0]:+.1%} to {v['skill_ci_90'][1]:+.1%}). It is shown as an alternative view; the "
            "headline stays EWMA, which was fixed before looking at results.")
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
        "garch": g_info,
        "notes": notes,
    }
