"""Split-conformal prediction intervals with a walk-forward (past-only) calibration and a measured coverage check.

Idea (normalised split conformal, symmetric):
  score_i = |outcome_i - centre_i| / (sigma_i * sqrt(h))      sigma_i = EWMA daily volatility known at origin i
  q       = the ceil((n + 1) * 0.8)-th smallest of the n calibration scores   (the finite-sample "conformal" quantile)
  interval at a new origin = centre +/- q * sigma_now * sqrt(h)

Dividing by the volatility known at the time makes the band narrower in calm markets and wider in stressed ones.

How the coverage is *measured* rather than assumed: the same procedure is replayed through time. At every past origin k
the multiplier q_k is computed ONLY from scores whose outcome was already known at k (origin j counts only if
j + h <= k, i.e. an h-day embargo), and we record whether the real outcome landed inside the band that q_k would have
given. The share of hits over all such origins is the measured coverage reported to the user.

Honest limits (also reported in the API response):
  * Overlapping h-day windows are strongly correlated, so n origins are worth only about n / h independent tests.
    The confidence range on the measured coverage uses that effective sample size.
  * The conformal guarantee needs exchangeable data; markets are not. The measured coverage is the real evidence.
  * The interval is used only when enough independent periods were available to check it (MIN_EVAL_INDEPENDENT) and the
    replay did not show clear under-coverage (the 90% plausible range of the measured coverage lies entirely below the
    target). Otherwise the caller falls back to the older interval and says why. The gate is deliberately NOT "measured
    coverage within a few points of 80%": with only a handful of independent periods that would select on noise and
    make the reported number look better than it is. The measured coverage and its plausible range are always shown.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

ALPHA = 0.2                    # miscoverage: an 80% interval
TARGET = 1 - ALPHA
LAMBDA = 0.94                  # RiskMetrics EWMA decay for the volatility scale
FLOOR = 1e-5
BURN_IN = 66                   # EWMA seed + long-window features: rows before this are not used as calibration
MIN_CAL_ROWS = 100             # never calibrate on fewer origins than this ...
MIN_CAL_HORIZONS = 2           # ... or on fewer than this many horizon-lengths of data
MIN_EVAL_INDEPENDENT = 8       # need at least this many independent test periods for the coverage check
CONE_CALIB_BARS = 2500         # ~10 years of daily bars: the longest history requested for cone-horizon calibration
Z90 = 1.6448536269514722


def ewma_vol_series(close: pd.Series) -> pd.Series:
    """RiskMetrics EWMA daily log-return volatility at every date (uses data up to and including that date)."""
    r2 = np.log(close.dropna()[lambda c: c > 0]).diff() ** 2
    return np.sqrt(r2.ewm(alpha=1 - LAMBDA, adjust=False).mean()).clip(lower=FLOOR)


def calibration_feasible(horizon: int, n_bars: int = CONE_CALIB_BARS) -> bool:
    """Could ``n_bars`` of history ever provide enough independent test periods at this horizon? (cheap pre-check, so
    callers do not download a long history that cannot help)"""
    min_cal = max(MIN_CAL_ROWS, MIN_CAL_HORIZONS * horizon)
    rows = n_bars - BURN_IN - horizon
    return (rows - (min_cal + horizon - 1)) // horizon >= MIN_EVAL_INDEPENDENT


def conformal_quantile(scores: np.ndarray, alpha: float = ALPHA) -> float:
    """Finite-sample conformal quantile: the ceil((n+1)(1-alpha))-th smallest score (inf if n is too small)."""
    n = len(scores)
    k = math.ceil((n + 1) * (1 - alpha))
    if n == 0 or k > n:
        return math.inf
    return float(np.partition(scores, k - 1)[k - 1])


def wilson_interval(p: float, n_eff: float, z: float = Z90) -> tuple[float, float]:
    """Wilson score interval for a proportion measured on ``n_eff`` effectively independent trials."""
    n_eff = max(n_eff, 1.0)
    denom = 1 + z * z / n_eff
    centre = (p + z * z / (2 * n_eff)) / denom
    half = z * math.sqrt(p * (1 - p) / n_eff + z * z / (4 * n_eff * n_eff)) / denom
    return max(centre - half, 0.0), min(centre + half, 1.0)


@dataclass
class ConformalCalibration:
    multiplier: float                 # q: half-width in units of sigma * sqrt(h) (a normal band would be 1.2816)
    n_calibration: int                # scores behind the final multiplier
    n_calibration_independent: int
    measured_coverage: float | None   # share of past outcomes inside the band the procedure would have given
    coverage_ci_90: tuple[float, float] | None
    n_evaluation: int
    n_evaluation_independent: int
    supported: bool
    reason: str | None                # why it was not used (None when supported)


def measure_coverage(scores: np.ndarray, horizon: int, min_cal: int | None = None) -> tuple[float | None, int]:
    """Replay the procedure through time. ``scores`` are for consecutive origins, oldest first.

    Returns (coverage, n_evaluated). At origin k only scores j <= k - horizon (outcome known) are used."""
    min_cal = min_cal or max(MIN_CAL_ROWS, MIN_CAL_HORIZONS * horizon)
    hits = n = 0
    for k in range(min_cal + horizon - 1, len(scores)):
        q = conformal_quantile(scores[: k - horizon + 1])
        hits += int(scores[k] <= q)
        n += 1
    return (hits / n if n else None), n


def calibrate(scores: np.ndarray, horizon: int) -> ConformalCalibration:
    """Final multiplier from all past scores + the measured walk-forward coverage + the support decision."""
    scores = scores[np.isfinite(scores)]
    n = len(scores)
    min_cal = max(MIN_CAL_ROWS, MIN_CAL_HORIZONS * horizon)
    q = conformal_quantile(scores) if n else math.inf
    cov, n_eval = measure_coverage(scores, horizon, min_cal)
    n_eval_ind = n_eval // horizon
    ci = wilson_interval(cov, n_eval / horizon) if cov is not None else None
    reason = None
    if not math.isfinite(q) or n < min_cal:
        reason = f"only {n} past forecasts are available to calibrate on (need at least {min_cal})"
    elif n_eval_ind < MIN_EVAL_INDEPENDENT:
        reason = (f"the history holds only about {n_eval_ind} independent {horizon}-day test periods for checking "
                  f"the coverage (need at least {MIN_EVAL_INDEPENDENT})")
    elif cov is None or ci is None or ci[1] < TARGET:
        reason = (f"the replay showed under-coverage (measured {cov:.0%} against a {TARGET:.0%} target, plausible "
                  f"range {ci[0]:.0%} to {ci[1]:.0%})" if cov is not None and ci is not None
                  else "the coverage could not be measured")
    return ConformalCalibration(
        multiplier=q if math.isfinite(q) else float("nan"), n_calibration=n, n_calibration_independent=n // horizon,
        measured_coverage=cov, coverage_ci_90=ci, n_evaluation=n_eval, n_evaluation_independent=n_eval_ind,
        supported=reason is None, reason=reason)


def describe(c: ConformalCalibration, used: bool, fallback: str | None) -> dict:
    """The JSON block returned to clients."""
    return {
        "used": bool(used),
        "method": "split conformal, volatility-scaled and symmetric; calibrated on past forecasts only",
        "target_coverage": TARGET,
        "multiplier": None if not math.isfinite(c.multiplier) else round(float(c.multiplier), 4),
        "normal_multiplier": 1.2816,
        "n_calibration": c.n_calibration,
        "n_calibration_independent": c.n_calibration_independent,
        "measured_coverage": None if c.measured_coverage is None else round(float(c.measured_coverage), 4),
        "measured_coverage_ci_90": None if c.coverage_ci_90 is None else [round(c.coverage_ci_90[0], 4),
                                                                          round(c.coverage_ci_90[1], 4)],
        "n_evaluation": c.n_evaluation,
        "n_evaluation_independent": c.n_evaluation_independent,
        "supported": bool(c.supported),
        "reason_not_used": c.reason if not used else None,
        "fallback": None if used else fallback,
    }
