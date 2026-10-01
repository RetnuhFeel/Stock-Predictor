"""Live prediction log logic: record predictions for a fixed allowlist, resolve outcomes, build the scorecard.

Everything here is LIVE out-of-sample evidence (prediction stored before the outcome existed). Backtest numbers are
stored only as a labelled snapshot and are never mixed into the live scorecard.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config
from .forecast import MIN_INDEPENDENT_TESTS, skill_ci_sq
from .storage import PredictionStore


def record_from_forecast(result: dict, base_close_series: pd.Series) -> dict:
    bt = result["backtest"]
    return {
        "symbol": result["symbol"], "horizon_days": result["horizon_days"],
        "base_date": result["last_date"], "base_close": float(result["last_close"]),
        "predicted_return": float(result["predicted_return"]),
        "interval_low": float(result["interval_80"]["low"]), "interval_high": float(result["interval_80"]["high"]),
        "backtest_skill": float(bt["skill_vs_baseline"]),
        "backtest_verdict": "better" if bt["beats_baseline"] else "not_better_or_inconclusive",
        "model": "gbm",
    }


def resolve_pending(store: PredictionStore, history_for) -> dict:
    """Fill outcomes for rows whose horizon has passed. ``history_for(symbol)`` returns a Close series."""
    resolved = still_pending = 0
    cache: dict[str, pd.Series] = {}
    for row in store.pending():
        sym = row["symbol"]
        try:
            if sym not in cache:
                cache[sym] = history_for(sym)
            close = cache[sym].dropna()
        except Exception:  # noqa: BLE001 - provider trouble: leave pending, try again next run
            still_pending += 1
            continue
        dates = [d.strftime("%Y-%m-%d") for d in close.index]
        if row["base_date"] not in dates:
            still_pending += 1
            continue
        i = dates.index(row["base_date"])
        j = i + row["horizon_days"]
        if j >= len(close):
            still_pending += 1
            continue
        # realized return from the SAME (adjusted) series for both ends, so later dividend adjustments cancel out
        ret = float(np.log(close.iloc[j] / close.iloc[i]))
        if store.resolve(row["id"], dates[j], float(close.iloc[j]), ret):
            resolved += 1
    return {"resolved": resolved, "still_pending": still_pending}


def scorecard(rows: list[dict], horizon: int | None = None) -> dict:
    """Live scorecard over resolved predictions (optionally one horizon)."""
    res = [r for r in rows if r["status"] == "resolved" and (horizon is None or r["horizon_days"] == horizon)]
    pending = sum(r["status"] == "pending" for r in rows)
    base = {"n_resolved": len(res), "n_pending": pending, "min_for_verdict": MIN_INDEPENDENT_TESTS}
    if not res:
        return {**base, "verdict": "no_data", "n_dates": 0, "n_independent": 0}
    h = horizon or max(1, int(np.median([r["horizon_days"] for r in res])))
    pred = np.array([r["predicted_return"] for r in res])
    real = np.array([r["realized_return"] for r in res])
    cover = np.mean([r["interval_low"] <= r["base_close"] * np.exp(r["realized_return"]) <= r["interval_high"]
                     for r in res])
    # one score per forecast date (average across symbols) so same-day, correlated tickers don't count as independent
    dates = sorted({r["base_date"] for r in res})
    by_date = {d: [i for i, r in enumerate(res) if r["base_date"] == d] for d in dates}
    m_sq = np.array([np.mean((real[ix] - pred[ix]) ** 2) for ix in by_date.values()])
    b_sq = np.array([np.mean(real[ix] ** 2) for ix in by_date.values()])
    skill = 1 - float(np.sqrt(m_sq.mean() / b_sq.mean()))
    n_indep = max(len(dates) // h, 1)
    out = {**base, "n_dates": len(dates), "n_independent": n_indep, "horizon_days": h,
           "skill_vs_naive": skill, "model_rmse": float(np.sqrt(np.mean((real - pred) ** 2))),
           "naive_rmse": float(np.sqrt(np.mean(real**2))),
           "hit_rate": float(np.mean(np.sign(pred) == np.sign(real))), "up_rate": float(np.mean(real > 0)),
           "interval_coverage": float(cover), "interval_nominal": 0.8}
    if n_indep < MIN_INDEPENDENT_TESTS:
        out.update(verdict="too_early", skill_ci_90=None)
        return out
    lo, hi = skill_ci_sq(m_sq, b_sq, h)
    out["skill_ci_90"] = [lo, hi]
    if skill > 0.02 and lo > 0:
        out["verdict"] = "better"
    else:
        out["verdict"] = "inconclusive" if skill > 0 and lo <= 0 else "not_better"
    return out


def public_row(r: dict) -> dict:
    keys = ("id", "symbol", "horizon_days", "made_at", "base_date", "base_close", "predicted_return", "interval_low",
            "interval_high", "backtest_skill", "model", "status", "resolved_at", "realized_date", "realized_close",
            "realized_return", "entry_hash")
    out = {k: r[k] for k in keys}
    if r["status"] == "resolved":
        px = r["base_close"] * float(np.exp(r["realized_return"]))
        out["in_interval"] = bool(r["interval_low"] <= px <= r["interval_high"])
        out["direction_correct"] = bool(np.sign(r["predicted_return"]) == np.sign(r["realized_return"]))
    return out


def log_symbols() -> list[str]:
    return list(config.LOG_SYMBOLS)
