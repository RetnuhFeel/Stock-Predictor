"""Honest, small-scale forecasting.

Target: the log return over the next ``horizon`` trading days.
Model:  HistGradientBoostingRegressor on simple technical features.
Check:  expanding-window walk-forward validation (chronological, with a ``horizon``-day embargo
        so training labels never overlap the test period), compared with the naive persistence
        baseline "price stays where it is" (predicted return = 0).
Bands:  split-conformal 80% interval (see conformal.py): a volatility-scaled half-width calibrated on past
        out-of-sample errors, with its coverage measured by replaying the procedure through time. It is used only when
        enough independent periods exist and the measured coverage is close to 80%. Otherwise the older bands apply:
        empirical quantiles of the walk-forward errors, or at horizons >= config.VOL_CONE_MIN_HORIZON a volatility
        cone around the last close, labelled uncalibrated.

Daily stock returns are close to unpredictable. In most cases this model will NOT beat the
baseline by a meaningful margin, and the response says so explicitly.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from . import config, conformal
from .errors import InsufficientData
from .marketcal import trading_days_after

SEED = 42
FEATURES = ["ret_1", "ret_5", "ret_10", "ret_21", "vol_10", "vol_21", "rsi_14", "macd_hist", "dist_sma50"]
MIN_INDEP_FOR_VERDICT = 5  # fewer independent backtest periods than this can never earn a "better" verdict
LONG_HORIZON = 60  # at or beyond this many trading days the response carries an explicit uncertainty note
MIN_ROWS = 250  # ~1 year of daily bars needed for a meaningful backtest


MIN_INDEPENDENT_TESTS = 30  # below this many non-overlapping test windows, the backtest is labelled "small sample"
N_BOOT = 300
Z80 = 1.2815515655446004  # standard-normal 90th percentile: half-width of a nominal 80% band in sigmas


def ratio(num: float, den: float) -> float:
    """num/den that cannot divide by zero: with no baseline error to compare against, report "no difference" (1.0)."""
    return float(num) / float(den) if den > 1e-12 else 1.0


def require_price_variation(close: pd.Series) -> None:
    """A series whose price never changes has nothing to forecast or backtest (every error and baseline is 0)."""
    r = np.log(close.dropna()[lambda c: c > 0]).diff().dropna()
    if len(r) and float(r.abs().max()) < 1e-9:
        raise InsufficientData("This price series is constant (no price changes), so there is nothing to forecast.")


def not_enough_history(horizon: int, n_bars: int) -> str:
    return (f"Not enough price history for a {horizon}-trading-day forecast with a backtest (this ticker has {n_bars} "
            "daily bars). Longer horizons need more history; try a shorter horizon.")


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


def fold_schedule(n: int, horizon: int, n_folds: int = 6) -> list[tuple[int, slice]]:
    """Expanding-window folds as (train_end, test_slice). Rows < train_end are used for training.

    The embargo: a row's label looks ``horizon`` days into the future, so training stops ``horizon``
    rows before the test block starts and no training label overlaps the test period.
    """
    start = max(int(n * 0.5), 120)
    step = max((n - start) // n_folds, 1)
    folds = []
    for t in range(start, n, step):
        train_end = t - horizon
        if train_end < 60:
            continue
        folds.append((train_end, slice(t, min(t + step, n))))
    return folds


def walk_forward(X: pd.DataFrame, y: pd.Series, horizon: int, n_folds: int = 6) -> WalkForward:
    """Expanding-window walk-forward: train on [0, t - horizon), predict the block [t, t + step)."""
    trues, preds, folds = [], [], 0
    for train_end, test in fold_schedule(len(X), horizon, n_folds):
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


def skill_ci_sq(err_model_sq: np.ndarray, err_base_sq: np.ndarray, block: int,
                level: float = 0.90) -> tuple[float, float]:
    """Moving-block bootstrap CI for 1 - RMSE_model / RMSE_baseline, from per-test squared errors."""
    rng = np.random.default_rng(SEED)
    n = len(err_model_sq)
    block = max(min(block, n), 1)
    starts_max = n - block + 1
    n_blocks = int(np.ceil(n / block))
    skills = np.empty(N_BOOT)
    for i in range(N_BOOT):
        idx = (rng.integers(0, starts_max, n_blocks)[:, None] + np.arange(block)).ravel()[:n]
        skills[i] = 1 - ratio(np.sqrt(err_model_sq[idx].mean()), np.sqrt(err_base_sq[idx].mean()))
    lo, hi = np.quantile(skills, [(1 - level) / 2, 1 - (1 - level) / 2])
    return float(lo), float(hi)


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
        skills[i] = 1 - ratio(np.sqrt(err_m[idx].mean()), np.sqrt(err_b[idx].mean()))
    lo, hi = np.quantile(skills, [(1 - level) / 2, 1 - (1 - level) / 2])
    return float(lo), float(hi)


def build_path(last: float, bdays, horizon: int, centre: float, q_lo: float, q_hi: float) -> list[dict]:
    """Dated mid/low/high prices; the band widens like sqrt(time), an approximation of the cone."""
    out = []
    for i, d in enumerate(bdays, start=1):
        frac = np.sqrt(i / horizon)
        mid = centre * i / horizon
        out.append({
            "date": d.strftime("%Y-%m-%d"),
            "mid": round(last * float(np.exp(mid)), 4),
            "low": round(last * float(np.exp(mid + q_lo * frac)), 4),
            "high": round(last * float(np.exp(mid + q_hi * frac)), 4),
        })
    return out


def legacy_view(result: dict) -> dict:
    """The forecast with its pre-conformal band (walk-forward residual percentiles, or the volatility cone).

    The live prediction log and the experimental spike scenario were built and validated on that band, so they keep
    using it: changing it would silently change what the track record measures."""
    lb = result.get("legacy_band")
    if not lb:
        return result
    dates = pd.to_datetime([p["date"] for p in result["path"]])
    path = build_path(float(result["last_close"]), dates, result["horizon_days"], lb["centre"], lb["q_lo"], lb["q_hi"])
    return {**result, "path": path, "interval_80": {"low": lb["low"], "high": lb["high"]}}


def conformal_scores_oos(wf: WalkForward, folds: list[tuple[int, slice]], index: pd.Index, sig: pd.Series,
                         horizon: int) -> np.ndarray:
    """Volatility-normalised absolute errors of the out-of-sample walk-forward predictions, oldest first."""
    pos = np.concatenate([np.arange(t.start, t.stop) for _, t in folds])
    if len(pos) != len(wf.y_true) or (len(pos) > 1 and not np.all(np.diff(pos) == 1)):
        return np.array([])  # not consecutive origins: the embargo bookkeeping would be wrong, so do not calibrate
    scale = sig.reindex(index[pos]).to_numpy() * np.sqrt(horizon)
    return np.abs(wf.y_true - wf.y_pred) / scale


def conformal_scores_cone(close: pd.Series, horizon: int) -> np.ndarray:
    """Normalised absolute h-day returns around zero (the cone's centre), oldest first. Needs no fitted model, so every
    origin with a known outcome counts, not only the second half of the history."""
    logp = np.log(close)
    y = (logp.shift(-horizon) - logp).to_numpy()
    sig = conformal.ewma_vol_series(close).to_numpy()
    lo, hi = conformal.BURN_IN, len(close) - horizon
    if hi <= lo:
        return np.array([])
    return np.abs(y[lo:hi]) / (sig[lo:hi] * np.sqrt(horizon))


def forecast(close: pd.Series, horizon: int, calib_close: pd.Series | None = None) -> dict:
    """``calib_close``: optional longer price history, used only to calibrate the conformal band at cone horizons."""
    close = close.dropna()
    close = close[close > 0]
    if len(close) < MIN_ROWS:
        raise InsufficientData(f"Need at least {MIN_ROWS} daily bars, got {len(close)}")
    require_price_variation(close)

    feats = make_features(close)
    target = np.log(close).shift(-horizon) - np.log(close)  # future h-day log return
    data = feats.assign(target=target)
    train_df = data.dropna()  # rows whose label is known
    if len(train_df) < 150:
        raise InsufficientData(not_enough_history(horizon, len(close)))

    X, y = train_df[FEATURES], train_df["target"]
    folds = fold_schedule(len(X), horizon)
    wf = walk_forward(X, y, horizon)

    model_m = _metrics(wf.y_true, wf.y_pred)
    base_m = _metrics(wf.y_true, np.zeros_like(wf.y_true))
    # Fraction of baseline error removed (positive = better than naive). Usually ~0 or negative.
    skill = 1 - ratio(model_m["rmse"], base_m["rmse"])
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
    bdays = trading_days_after(last_date, horizon)  # skips weekends AND NYSE holidays

    # Older bands. Short/medium horizons: the empirical 10th-90th percentile of out-of-sample errors, centred on the
    # model's point estimate. At long horizons five years of data hold only a handful of independent windows, so those
    # residual quantiles are not a trustworthy 80% band and the point estimate is mostly noise: the band is then a plain
    # volatility cone centred on today's price, labelled uncalibrated.
    cone = horizon >= config.VOL_CONE_MIN_HORIZON
    sig = conformal.ewma_vol_series(close)
    daily = float(sig.iloc[-1])
    if cone:
        if not np.isfinite(daily) or daily <= 0:
            daily = float(np.log(close).diff().std())
        q_lo, q_hi, centre = -Z80 * daily * np.sqrt(horizon), Z80 * daily * np.sqrt(horizon), 0.0
    else:
        q_lo, q_hi, centre = q10, q90, point
    legacy_band = {"centre": centre, "q_lo": q_lo, "q_hi": q_hi,
                   "low": round(last * float(np.exp(centre + q_lo)), 4),
                   "high": round(last * float(np.exp(centre + q_hi)), 4)}

    # Split-conformal band: calibrated on past forecasts only; used only if its measured coverage supports it.
    if cone:
        scores = conformal_scores_cone(calib_close.dropna()[lambda c: c > 0] if calib_close is not None else close,
                                       horizon)
    else:
        scores = conformal_scores_oos(wf, folds, X.index, sig, horizon)
    cal = conformal.calibrate(scores, horizon)
    use_conformal = bool(cal.supported and np.isfinite(daily) and daily > 0)
    if use_conformal:
        half = cal.multiplier * daily * np.sqrt(horizon)
        q_lo, q_hi = -half, half
    fallback = "volatility_cone" if cone else "walk_forward_residuals"
    conformal_info = conformal.describe(cal, use_conformal, fallback)

    path = build_path(last, bdays, horizon, centre, q_lo, q_hi)

    # "Beats" requires a meaningful gain AND a bootstrap interval that excludes zero.
    too_few = n_independent < MIN_INDEP_FOR_VERDICT
    beats = bool(skill > 0.02 and ci_lo > 0 and not too_few)
    why = f" A conformal calibration was tried but not used: {cal.reason}." if cal.reason else ""
    if use_conformal:
        notes = [
            f"80% range: a split-conformal band scaled by recent volatility, calibrated only on past forecasts. "
            f"Replaying that recipe through the history, the real outcome landed inside the range "
            f"{cal.measured_coverage:.0%} of the time (target 80%; about {cal.n_evaluation_independent} independent "
            "periods, so this has real uncertainty). Outcomes fall outside it regularly, more so in market stress.",
        ]
    elif cone:
        notes = [
            f"Horizons of {config.VOL_CONE_MIN_HORIZON}+ trading days: the range is a volatility cone around today's "
            "price (EWMA volatility, normal approximation, nominally 80%), NOT a backtest-calibrated interval. "
            "There are too few independent backtest periods to calibrate one, and the model's point estimate is "
            "shown for reference only. Real outcomes can fall outside this range, especially in market stress." + why,
        ]
    else:
        notes = [
            "Interval is the empirical 10th-90th percentile of out-of-sample walk-forward errors "
            "(an ~80% band); its coverage could not be verified, and real outcomes fall outside it regularly, "
            "especially in market stress." + why,
        ]
    if horizon >= LONG_HORIZON:
        plural = "" if n_independent == 1 else "s"
        notes.append(f"Long horizon ({horizon} trading days): this is highly uncertain. The range is very wide, "
                     f"five years of data hold only about {n_independent} independent backtest period{plural}, "
                     "and the point estimate is mostly noise.")
    if too_few and skill > 0.02 and ci_lo > 0:
        notes.append(f"With only about {n_independent} independent backtest period{'' if n_independent == 1 else 's'} "
                     "the apparent edge cannot be told apart from luck, so it is not counted as better than guessing.")
    elif not beats:
        notes.append("The model did NOT meaningfully beat the naive 'price stays flat' baseline in the "
                     "backtest. Treat the point forecast as noise.")

    return {
        "horizon_days": horizon,
        "last_close": round(last, 4),
        "last_date": last_date.strftime("%Y-%m-%d"),
        "predicted_return": point,
        "predicted_price": round(last * float(np.exp(point)), 4),
        "interval_80": {"low": round(last * float(np.exp(centre + q_lo)), 4),
                        "high": round(last * float(np.exp(centre + q_hi)), 4)},
        "interval_calibrated": bool(use_conformal or not cone),
        "interval_method_name": ("split_conformal" if use_conformal else "volatility_cone" if cone
                                 else "walk_forward_residuals"),
        "interval_method": ("split_conformal: point estimate (zero at cone horizons) +/- a multiplier x EWMA daily "
                            "volatility x sqrt(horizon); the multiplier is the conformal 80% quantile of past "
                            "normalised errors (outcome known at the time only)"
                            if use_conformal else
                            "volatility_cone: EWMA (lambda 0.94) daily volatility x sqrt(horizon), centred on the "
                            "last close, nominal 80% under a normal approximation; not backtest-calibrated"
                            if cone else
                            "walk_forward_residuals: 10th-90th percentile of out-of-sample errors around the point "
                            "estimate"),
        "conformal": conformal_info,
        "legacy_band": legacy_band,
        "path": path,
        "backtest": {
            "method": f"expanding-window walk-forward, {wf.n_folds} folds, {horizon}-day embargo",
            "embargo_days": horizon,
            "horizon_days": horizon,
            "n_test_points": n_test,
            "n_independent_tests": n_independent,
            "small_sample": bool(n_independent < MIN_INDEPENDENT_TESTS),
            "up_rate": up_rate,
            "skill_ci_90": [ci_lo, ci_hi],
            "model": model_m,
            "naive_baseline": base_m,
            "skill_vs_baseline": float(skill),
            "beats_baseline": beats,
            "too_few_independent": bool(too_few),
            "note": "Overlapping multi-day windows make test points correlated; the 90% interval accounts "
                    "for that with a block bootstrap. Metrics are indicative only.",
        },
        "notes": notes,
    }
