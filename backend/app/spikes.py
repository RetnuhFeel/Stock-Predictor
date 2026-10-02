"""EXPERIMENTAL spike scenario: a jump-diffusion Monte Carlo around the standard forecast.

What it is
  The standard forecast gives a point path (``mid``) and a "normal" 80% band per day (``low``/``high``).
  This module adds *simulated* short-term jumps, up and down, calibrated from the ticker's own history, and
  keeps every simulated price inside that normal band.

How it works (all deterministic: fixed seed, same inputs -> same output)
  1. Calibration from the last ``CAL_DAYS`` daily log returns (past data only):
     * robust sigma = 1.4826 * MAD, so jumps themselves do not inflate the threshold;
     * a day is a *jump* if its return differs from the median by more than ``JUMP_K`` robust sigmas
       (up and down are counted separately, so asymmetry is kept);
     * diffusion volatility = std of the non-jump days; jump frequency = jump days / days; jump sizes are the
       historical jump returns themselves (resampled), so fat tails and asymmetry are not assumed away.
  2. Simulation: ``N_PATHS`` paths. Each day: drift + diffusion shock + (with the calibrated probabilities) an
     up or down jump drawn from the historical jump sizes. The drift is set so that the *average* log return
     matches the standard forecast's path (jumps are compensated), i.e. jumps add spikes, not extra trend.
  3. Bounds: **clamping**. Each simulated day's price is clipped to that day's normal band. (Rejection or
     conditioning would instead throw away or reweight paths; clipping is simpler and lets us report exactly
     how often the band was hit.) The unclamped process keeps running underneath: clipping is a per-day
     projection, not a path-dependent barrier. ``clamping`` in the response reports how often it happened.

It does NOT predict when a spike happens or its direction. Spikes are simulated from past frequencies.
The walk-forward backtest below measures whether this adds anything over the standard interval, and the response
reports the numbers whichever way they fall.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .errors import InsufficientData
from .forecast import (
    FEATURES,
    MIN_INDEPENDENT_TESTS,
    MIN_ROWS,
    SEED,
    fold_schedule,
    make_features,
    skill_ci_sq,
    walk_forward,
)

CAL_DAYS = 504  # ~2 years of daily returns used for calibration
MIN_CAL_DAYS = 120
JUMP_K = 2.5  # jump = |return - median| > JUMP_K * robust sigma
N_PATHS = 2000
BT_PATHS = 1000
MAX_BT_ORIGINS = 150
N_SAMPLE_PATHS = 3
MIN_BT_POINTS = 10
ALPHA = 0.2  # the standard band is an 80% interval
FLOOR = 1e-4
N_BOOT = 300


@dataclass
class Calibration:
    n_days: int
    robust_sigma: float
    threshold: float
    sigma_diffusion: float
    up_sizes: np.ndarray
    down_sizes: np.ndarray

    @property
    def p_up(self) -> float:
        return len(self.up_sizes) / self.n_days

    @property
    def p_down(self) -> float:
        return len(self.down_sizes) / self.n_days

    @property
    def compensator(self) -> float:
        """Expected jump contribution to the daily log return."""
        up = self.p_up * float(self.up_sizes.mean()) if len(self.up_sizes) else 0.0
        dn = self.p_down * float(self.down_sizes.mean()) if len(self.down_sizes) else 0.0
        return up + dn


def calibrate(returns: np.ndarray) -> Calibration:
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)][-CAL_DAYS:]
    if len(r) < MIN_CAL_DAYS:
        raise InsufficientData(f"Need at least {MIN_CAL_DAYS} daily returns to calibrate jumps, got {len(r)}")
    med = float(np.median(r))
    robust = max(1.4826 * float(np.median(np.abs(r - med))), FLOOR)
    thr = JUMP_K * robust
    up, down = r - med > thr, r - med < -thr
    calm = r[~(up | down)]
    sigma = max(float(calm.std()) if len(calm) > 2 else robust, FLOOR)
    return Calibration(len(r), robust, thr, sigma, r[up], r[down])


def raw_log_paths(
    cal: Calibration, horizon: int, point: float, n_paths: int, seed: int = SEED
) -> tuple[np.ndarray, np.ndarray]:
    """Cumulative simulated log returns, shape (n_paths, horizon), plus a (n_paths, horizon) jump-direction array
    (+1 up jump, -1 down jump, 0 none). Unclamped."""
    rng = np.random.default_rng(seed)
    z = rng.standard_normal((n_paths, horizon))
    u = rng.random((n_paths, horizon))
    up = u < cal.p_up
    down = (u >= cal.p_up) & (u < cal.p_up + cal.p_down)
    jumps = np.zeros((n_paths, horizon))
    if len(cal.up_sizes):
        jumps = np.where(up, rng.choice(cal.up_sizes, (n_paths, horizon)), jumps)
    if len(cal.down_sizes):
        jumps = np.where(down, rng.choice(cal.down_sizes, (n_paths, horizon)), jumps)
    mu = point / horizon - cal.compensator
    inc = mu + cal.sigma_diffusion * z + jumps
    direction = np.where(up & (len(cal.up_sizes) > 0), 1, 0) - np.where(down & (len(cal.down_sizes) > 0), 1, 0)
    return np.cumsum(inc, axis=1), direction


def _q(a: np.ndarray, q: float, axis: int = 0) -> np.ndarray:
    return np.quantile(a, q, axis=axis)


def simulate(
    cal: Calibration,
    last: float,
    horizon: int,
    point: float,
    low: np.ndarray,
    high: np.ndarray,
    n_paths: int = N_PATHS,
    seed: int = SEED,
) -> dict:
    """Simulate and clamp to [low, high] (per-day arrays of the standard band, in price units)."""
    cum, direction = raw_log_paths(cal, horizon, point, n_paths, seed)
    raw = last * np.exp(cum)
    price = np.clip(raw, low[None, :], high[None, :])
    hit_hi, hit_lo = raw >= high[None, :], raw <= low[None, :]
    clamped = hit_hi | hit_lo
    jump_up = (direction == 1).cumsum(axis=1) > 0
    jump_dn = (direction == -1).cumsum(axis=1) > 0
    med = np.median(price, axis=0)
    mean_up = float(cal.up_sizes.mean()) if len(cal.up_sizes) else 0.0
    mean_dn = float(cal.down_sizes.mean()) if len(cal.down_sizes) else 0.0
    spike_up = np.clip(med * np.exp(mean_up), low, high)
    spike_dn = np.clip(med * np.exp(mean_dn), low, high)
    # illustrative paths: prefer ones that actually contain a jump
    has_jump = (direction != 0).any(axis=1)
    order = np.concatenate([np.flatnonzero(has_jump), np.flatnonzero(~has_jump)])[:N_SAMPLE_PATHS]
    return {
        "median": med,
        "mean": price.mean(axis=0),
        "sim_low": _q(price, 0.10),
        "sim_high": _q(price, 0.90),
        "spike_up": spike_up,
        "spike_down": spike_dn,
        "p_jump_up": jump_up.mean(axis=0),
        "p_jump_down": jump_dn.mean(axis=0),
        "p_touch_high": hit_hi.mean(axis=0),
        "p_touch_low": hit_lo.mean(axis=0),
        "samples": price[order],
        "raw": raw,
        "price": price,
        "clamped_fraction": float(clamped.mean()),
        "paths_touched": float(clamped.any(axis=1).mean()),
        "terminal_at_high": float(hit_hi[:, -1].mean()),
        "terminal_at_low": float(hit_lo[:, -1].mean()),
    }


# ---------------------------------------------------------------- walk-forward backtest
def _interval_score(lo: np.ndarray, hi: np.ndarray, y: np.ndarray, alpha: float = ALPHA) -> np.ndarray:
    """Winkler interval score: width plus a penalty (2/alpha) times how far the outcome missed. Lower is better."""
    return (hi - lo) + (2 / alpha) * np.maximum(lo - y, 0) + (2 / alpha) * np.maximum(y - hi, 0)


def _score_gain_ci(new: np.ndarray, base: np.ndarray, level: float = 0.90) -> tuple[float, float, float]:
    """Gain = 1 - mean(new)/mean(base) of per-origin interval scores, with a bootstrap CI (origins are spaced
    >= horizon days apart, so they are close to independent)."""
    rng = np.random.default_rng(SEED)
    n = len(new)
    gain = 1 - new.mean() / base.mean()
    boots = np.empty(N_BOOT)
    for i in range(N_BOOT):
        idx = rng.integers(0, n, n)
        boots[i] = 1 - new[idx].mean() / base[idx].mean()
    lo, hi = np.quantile(boots, [(1 - level) / 2, 1 - (1 - level) / 2])
    return float(gain), float(lo), float(hi)


MIN_GAIN = 0.02  # a change smaller than 2% of the interval score is not treated as meaningful, even if "significant"


def _verdict(gain: float, lo: float, hi: float) -> str:
    """'better'/'worse' need a material change (>= 2%) AND a 90% bootstrap range that excludes zero."""
    return "better" if gain >= MIN_GAIN and lo > 0 else "worse" if gain <= -MIN_GAIN and hi < 0 else "inconclusive"


def origin_row(test: slice, n_rows: int, offset: int) -> int:
    """Row index (into the walk-forward feature table) of the ``offset``-th point of a fold's test block."""
    return range(*test.indices(n_rows))[offset]


def backtest(close: pd.Series, horizon: int) -> dict:
    """Expanding-window walk-forward (same folds and embargo as the standard forecast).

    At each evaluation origin (spaced >= horizon days apart) everything is computed from data up to that date:
    the standard model's point + band (band quantiles from *earlier* folds' out-of-sample errors only) and a jump
    calibration from returns up to that date. Compares, for the h-day return:
      baseline  the standard 80% interval
      jump      the 10-90% range of the simulated jump-diffusion, NOT clamped
      spike     the same range after clamping to the baseline band (what the UI shows)
    """
    close = close.dropna()
    close = close[close > 0]
    feats = make_features(close)
    target = np.log(close).shift(-horizon) - np.log(close)
    train_df = feats.assign(target=target).dropna()
    X, y = train_df[FEATURES], train_df["target"]
    folds = fold_schedule(len(X), horizon)
    wf = walk_forward(X, y, horizon)
    sizes = [len(range(*t.indices(len(X)))) for _, t in folds]
    bounds = np.cumsum([0] + sizes)
    logret = np.log(close).diff().dropna()
    dates = train_df.index

    n_total = int(bounds[-1])  # number of out-of-sample points across all folds
    stride = max(horizon, int(np.ceil(max(n_total, 1) / MAX_BT_ORIGINS)))
    rows = {k: [] for k in ("y", "pred", "blo", "bhi", "jlo", "jhi", "slo", "shi", "smed", "smean", "clamp")}
    for k in range(1, len(folds)):
        resid = wf.y_true[: bounds[k]] - wf.y_pred[: bounds[k]]  # earlier folds only
        q10, q90 = (float(np.quantile(resid, 0.10)), float(np.quantile(resid, 0.90)))
        for j in range(int(bounds[k]), int(bounds[k + 1]), stride):
            pred, truth = float(wf.y_pred[j]), float(wf.y_true[j])
            # j indexes the CONCATENATED test blocks; map it to the real row of ``train_df`` (the origin day) so
            # calibration sees data up to that day and no later (and no less).
            row_i = origin_row(folds[k][1], len(X), j - int(bounds[k]))
            hist = logret.loc[: dates[row_i]].to_numpy()
            if len(hist) < MIN_CAL_DAYS:
                continue
            cal = calibrate(hist)
            cum, _ = raw_log_paths(cal, horizon, pred, BT_PATHS)
            term = cum[:, -1]
            blo, bhi = pred + q10, pred + q90
            clamped = np.clip(term, blo, bhi)
            rows["y"].append(truth)
            rows["pred"].append(pred)
            rows["blo"].append(blo)
            rows["bhi"].append(bhi)
            rows["jlo"].append(float(np.quantile(term, 0.10)))
            rows["jhi"].append(float(np.quantile(term, 0.90)))
            rows["slo"].append(float(np.quantile(clamped, 0.10)))
            rows["shi"].append(float(np.quantile(clamped, 0.90)))
            rows["smed"].append(float(np.median(clamped)))
            rows["smean"].append(float(clamped.mean()))
            rows["clamp"].append(float(np.mean((term < blo) | (term > bhi))))
    n = len(rows["y"])
    if n < MIN_BT_POINTS:
        return {"available": False, "reason": f"Only {n} evaluation points; too few for a meaningful backtest."}
    a = {k: np.asarray(v) for k, v in rows.items()}
    out: dict = {
        "available": True,
        "n_origins": n,
        "horizon_days": horizon,
        "small_sample": bool(n < MIN_INDEPENDENT_TESTS),
        "nominal_coverage": 1 - ALPHA,
        "embargo_days": horizon,
        "method": (
            f"expanding-window walk-forward, {len(folds)} folds, {horizon}-day embargo; baseline band quantiles "
            f"from earlier folds only; jump calibration from data up to each origin; "
            f"{n} origins spaced >= {stride} trading days apart"
        ),
    }
    scores = {}
    for name, lo, hi in (
        ("baseline", a["blo"], a["bhi"]),
        ("jump_unclamped", a["jlo"], a["jhi"]),
        ("spike_clamped", a["slo"], a["shi"]),
    ):
        sc = _interval_score(lo, hi, a["y"])
        scores[name] = sc
        out[name] = {
            "coverage": float(np.mean((a["y"] >= lo) & (a["y"] <= hi))),
            "mean_width": float(np.mean(hi - lo)),
            "interval_score": float(sc.mean()),
        }
    for name in ("jump_unclamped", "spike_clamped"):
        gain, lo, hi = _score_gain_ci(scores[name], scores["baseline"])
        out[name].update(
            {"score_gain_vs_baseline": gain, "score_gain_ci_90": [lo, hi], "verdict": _verdict(gain, lo, hi)}
        )
    e_base, e_spike = (a["y"] - a["pred"]) ** 2, (a["y"] - a["smed"]) ** 2
    skill = 1 - float(np.sqrt(e_spike.mean() / e_base.mean()))
    ci = skill_ci_sq(e_spike, e_base, 1)
    out["point"] = {
        "baseline_rmse": float(np.sqrt(e_base.mean())),
        "spike_median_rmse": float(np.sqrt(e_spike.mean())),
        "naive_rmse": float(np.sqrt(np.mean(a["y"] ** 2))),
        "skill_vs_baseline": skill,
        "skill_ci_90": [ci[0], ci[1]],
        "verdict": "better" if skill > 0.02 and ci[0] > 0 else "worse" if ci[1] < 0 else "inconclusive",
    }
    out["mean_clamped_fraction_at_horizon"] = float(a["clamp"].mean())
    out["summary"] = _summarise(out)
    return out


def _summarise(b: dict) -> str:
    base, jd, sp, pt = b["baseline"], b["jump_unclamped"], b["spike_clamped"], b["point"]
    parts = [
        f"Over {b['n_origins']} past forecast dates the standard 80% band contained the outcome "
        f"{base['coverage']:.0%} of the time; the clamped spike range, which can never be wider, "
        f"{sp['coverage']:.0%}."
    ]
    parts.append(
        "As a risk range the unclamped jump model was "
        + {"better": "better", "worse": "worse", "inconclusive": "not clearly different"}[jd["verdict"]]
        + f" than the standard band (interval-score change {jd['score_gain_vs_baseline']:+.1%}, 90% range "
        f"{jd['score_gain_ci_90'][0]:+.1%} to {jd['score_gain_ci_90'][1]:+.1%})."
    )
    parts.append(
        "The clamped spike range was "
        + {"better": "better", "worse": "worse", "inconclusive": "not clearly different"}[sp["verdict"]]
        + f" ({sp['score_gain_vs_baseline']:+.1%}, {sp['score_gain_ci_90'][0]:+.1%} to "
        f"{sp['score_gain_ci_90'][1]:+.1%})."
    )
    parts.append(
        "Its typical (median) path was "
        + {"better": "more accurate", "worse": "less accurate", "inconclusive": "not clearly different in accuracy"}[
            pt["verdict"]
        ]
        + f" than the standard point forecast (RMSE {pt['spike_median_rmse']:.4f} vs {pt['baseline_rmse']:.4f})."
    )
    if b["small_sample"]:
        parts.append("Small sample: treat these numbers as rough.")
    return " ".join(parts)


# ---------------------------------------------------------------- public entry point
def spike_forecast(close: pd.Series, horizon: int, base: dict) -> dict:
    """``base`` is the standard ``forecast()`` result for the same series and horizon."""
    close = close.dropna()
    close = close[close > 0]
    if len(close) < MIN_ROWS:
        raise InsufficientData(f"Need at least {MIN_ROWS} daily bars, got {len(close)}")
    logret = np.log(close).diff().dropna().to_numpy()
    cal = calibrate(logret)
    last = float(base["last_close"])
    path = base["path"]
    low = np.array([p["low"] for p in path], dtype=float)
    high = np.array([p["high"] for p in path], dtype=float)
    sim = simulate(cal, last, horizon, float(base["predicted_return"]), low, high)

    def r4(x):
        return [round(float(v), 4) for v in x]

    days = []
    for i, p in enumerate(path):
        days.append(
            {
                "date": p["date"],
                "baseline_mid": p["mid"],
                "band_low": p["low"],
                "band_high": p["high"],
                "median": r4(sim["median"])[i],
                "mean": r4(sim["mean"])[i],
                "sim_low": r4(sim["sim_low"])[i],
                "sim_high": r4(sim["sim_high"])[i],
                "spike_up": r4(sim["spike_up"])[i],
                "spike_down": r4(sim["spike_down"])[i],
                "p_jump_up": round(float(sim["p_jump_up"][i]), 4),
                "p_jump_down": round(float(sim["p_jump_down"][i]), 4),
                "p_touch_high": round(float(sim["p_touch_high"][i]), 4),
                "p_touch_low": round(float(sim["p_touch_low"][i]), 4),
            }
        )
    few = len(cal.up_sizes) + len(cal.down_sizes) < 5
    bt = backtest(close, horizon)
    notes = [
        "Spikes are simulated from this stock's own past jump frequency and size. They are not predictions: the model "
        "does not know when a spike will happen or which way it will go.",
        "Every simulated price is clamped to the standard forecast's normal band for that day, so these paths "
        "can never "
        "show a move bigger than the normal range. Real spikes sometimes are.",
        "Experimental. Not financial advice.",
    ]
    if few:
        notes.append(
            "This stock had very few historical jumps in the calibration window, so the spike estimates are "
            "unreliable and the result is close to a plain random walk."
        )
    if bt.get("available"):
        if bt["point"]["verdict"] != "better":
            notes.append(
                "In the walk-forward backtest the typical spike path was NOT more accurate than the standard point "
                "forecast. Treat this as an illustration of possible spikiness, not as a better forecast."
            )
        if bt["spike_clamped"]["coverage"] < bt["baseline"]["coverage"] - 0.02:
            notes.append(
                "The clamped spike range is narrower than the standard band and contained fewer real outcomes in the "
                f"backtest ({bt['spike_clamped']['coverage']:.0%} vs {bt['baseline']['coverage']:.0%}), so a better "
                "interval score does not mean it is safer to rely on."
            )
        if bt["jump_unclamped"]["verdict"] == "worse":
            notes.append(
                "Without the clamp, the jump model's range scored worse than the standard band in the backtest."
            )
    else:
        notes.append(
            "A walk-forward backtest could not be run for this history, so there is no evidence about whether this "
            "model helps."
        )
    return {
        "experimental": True,
        "horizon_days": horizon,
        "last_close": round(last, 4),
        "last_date": base["last_date"],
        "baseline_interval": base["interval_80"],
        "model": {
            "name": "jump-diffusion Monte Carlo (experimental)",
            "n_paths": N_PATHS,
            "seed": SEED,
            "bounds": "clamped: each day's simulated price is clipped to the standard forecast's normal band",
            "jump_threshold_sigma": JUMP_K,
            "calibration_days": cal.n_days,
        },
        "calibration": {
            "robust_sigma_daily": cal.robust_sigma,
            "diffusion_sigma_daily": cal.sigma_diffusion,
            "jump_threshold_pct": float(np.expm1(cal.threshold) * 100),
            "n_jumps_up": int(len(cal.up_sizes)),
            "n_jumps_down": int(len(cal.down_sizes)),
            "jump_freq_up_per_day": cal.p_up,
            "jump_freq_down_per_day": cal.p_down,
            "mean_jump_up_pct": float(np.expm1(cal.up_sizes.mean()) * 100) if len(cal.up_sizes) else None,
            "mean_jump_down_pct": float(np.expm1(cal.down_sizes.mean()) * 100) if len(cal.down_sizes) else None,
            "few_jumps": bool(few),
        },
        "path": days,
        "sample_paths": [r4(s) for s in sim["samples"]],
        "clamping": {
            "method": "clip",
            "fraction_of_path_days_clamped": sim["clamped_fraction"],
            "fraction_of_paths_touching_band": sim["paths_touched"],
            "terminal_at_high": sim["terminal_at_high"],
            "terminal_at_low": sim["terminal_at_low"],
        },
        "backtest": bt,
        "notes": notes,
    }
