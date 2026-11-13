"""Live prediction log logic: record predictions for a fixed allowlist, resolve outcomes, build the scorecard.

Everything here is LIVE out-of-sample evidence (prediction stored before the outcome existed). Backtest numbers are
stored only as a labelled snapshot and are never mixed into the live scorecard.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from . import config
from .conformal import wilson_interval
from .forecast import MIN_INDEPENDENT_TESTS, ratio, skill_ci_sq
from .freshness import bar_is_final
from .observability import log_event
from .storage import HASH_FIELDS, HASH_FIELDS_V2, HASH_VERSION_CURRENT, RES_FIELDS, PredictionStore

log = logging.getLogger("stock-api")

# Sessions the live log has no predictions for, listed openly instead of being hidden. They are NEVER back-filled:
# recording a forecast for an old session after the fact would use prices that were already known (hindsight), and
# the hash-chained rows are never inserted out of order or edited. Add an entry when a scheduled run is missed.
MISSED_SESSIONS: tuple[dict, ...] = (
    {
        "base_date": "2026-10-02",
        "symbols": None,  # None = every symbol in the allowlist
        "cause": "upstream_data_not_updated",
        "note": ("No predictions were recorded for the close of Friday, Oct 2, 2026. The scheduled job ran that "
                 "evening, but the data provider was still returning Thursday's prices, so there was nothing new to "
                 "record. The gap is not filled in afterwards, because a forecast recorded once the outcome period has "
                 "started would use hindsight."),
        "backfilled": False,
    },
    {
        "base_date": "2026-10-15",
        "symbols": ("SPY",),  # partial day: AAPL, MSFT, NVDA and TSLA were recorded normally
        "cause": "upstream_data_not_updated",
        "note": ("No SPY prediction was recorded for the close of Thursday, Oct 15, 2026. The evening run recorded the "
                 "other four tickers, but the data provider was still returning Wednesday's SPY price, even after a "
                 "fresh request. The morning retry started only after the market had opened, when nothing can be "
                 "recorded any more. The gap is not filled in afterwards, because a forecast recorded once the outcome "
                 "period has started would use hindsight."),
        "backfilled": False,
    },
)


# What the logged 80% range is. It is the pre-conformal band (see record_from_forecast), NOT the conformal range that
# the forecast page shows today, so the scorecard's coverage describes that older band.
INTERVAL_METHOD = ("legacy band: 10th-90th percentile of walk-forward errors around the point forecast "
                   "(the band the log started with; not the conformal range shown on the forecast page)")


def missed_sessions(symbols: list[str]) -> list[dict]:
    """Public list of missed sessions, newest first, with the affected symbols spelled out."""
    out = [{**m, "symbols": list(m["symbols"] or symbols)} for m in MISSED_SESSIONS]
    return sorted(out, key=lambda m: m["base_date"], reverse=True)


BAND_LEGACY = "legacy_band"  # band_method of new rows that still log the legacy band (base date before the cutover)
INTERVAL_METHOD_CONFORMAL = ("the forecast's own 80% range from the cutover on: split conformal when its coverage "
                             "check passes, otherwise the fallback it names (band_method per row)")


def model_version() -> str:
    """Model id plus the deployed code commit, e.g. 'gbm-v1@2499b36da2c1' (or 'gbm-v1@unknown' locally)."""
    return f"{config.MODEL_ID}@{config.CODE_COMMIT or 'unknown'}"


def band_period(row: dict) -> str:
    """'legacy' for rows that logged the legacy band (all v1 rows, v2 rows before the cutover); else 'conformal'."""
    return "legacy" if row.get("band_method") in (None, BAND_LEGACY) else "conformal"


def record_from_forecast(result: dict) -> dict:
    """The row to log (hash rule v2: it also records the model version and which band it logged).

    Before ``config.LOG_CONFORMAL_FROM`` it stores the pre-conformal band (``legacy_band``), the interval the live log
    was started with. From that base date on it stores the forecast's own 80% range (``interval_80``: split conformal
    when its check passes, else the fallback named in ``interval_method_name``). The switch is dated and recorded per
    row, so the scorecard can judge each period against the band it actually logged."""
    bt = result["backtest"]
    if result["last_date"] >= config.LOG_CONFORMAL_FROM:
        band, method = result["interval_80"], result.get("interval_method_name") or "unknown"
    else:
        band, method = result.get("legacy_band") or result["interval_80"], BAND_LEGACY
    return {
        "hash_version": HASH_VERSION_CURRENT, "model_version": model_version(), "band_method": method,
        "symbol": result["symbol"], "horizon_days": result["horizon_days"],
        "base_date": result["last_date"], "base_close": float(result["last_close"]),
        "predicted_return": float(result["predicted_return"]),
        "interval_low": float(band["low"]), "interval_high": float(band["high"]),
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
        except Exception as exc:  # noqa: BLE001 - provider trouble: leave pending, retried next run, but never silent
            log_event(log, "resolve_pending_failed", logging.WARNING, symbol=sym, error_class=type(exc).__name__)
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
        if not bar_is_final(close.index[j].date()):  # today's bar before the close is a partial intraday value
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
    skill = 1 - ratio(float(np.sqrt(m_sq.mean())), float(np.sqrt(b_sq.mean())))
    n_indep = max(len(dates) // h, 1)
    out = {**base, "n_dates": len(dates), "n_independent": n_indep, "horizon_days": h,
           "skill_vs_naive": skill, "model_rmse": float(np.sqrt(np.mean((real - pred) ** 2))),
           "naive_rmse": float(np.sqrt(np.mean(real**2))),
           "hit_rate": float(np.mean(np.sign(pred) == np.sign(real))), "up_rate": float(np.mean(real > 0)),
           "interval_coverage": float(cover), "interval_nominal": 0.8,
           # Plausible range for the coverage, using independent periods (not rows: same-day tickers and overlapping
           # windows are correlated), so a handful of results cannot look like a precise number.
           "interval_coverage_ci_90": list(wilson_interval(float(cover), float(n_indep))),
           "interval_method": INTERVAL_METHOD}
    periods = band_periods(rows, horizon)
    if len(periods) > 1:
        out["interval_method"] = ("mixed: each row is scored against the band it logged; the legacy and conformal "
                                  "periods are reported separately in 'periods'")
    out["periods"] = periods
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


def _in_band(r: dict) -> bool:
    """Did the realised price land inside the band THIS row logged (whatever method that was)?"""
    return bool(r["interval_low"] <= r["base_close"] * np.exp(r["realized_return"]) <= r["interval_high"])


def band_periods(rows: list[dict], horizon: int | None = None) -> list[dict]:
    """The scorecard split by the band each row logged: 'legacy' (the band the log started with) and, from the dated
    cutover, 'conformal'. Each period is judged only on its own rows, against the band those rows stored, so the switch
    never mixes two methods into one coverage number. No verdict per period: the overall verdict rule still applies."""
    out = []
    for name in ("legacy", "conformal"):
        mine = [r for r in rows if band_period(r) == name and (horizon is None or r["horizon_days"] == horizon)]
        if not mine:
            continue
        res = [r for r in mine if r["status"] == "resolved"]
        dates = sorted({r["base_date"] for r in mine if r.get("base_date")}) or [None]
        h = horizon or max(1, int(np.median([r["horizon_days"] for r in mine])))
        p = {"band": name, "interval_method": INTERVAL_METHOD if name == "legacy" else INTERVAL_METHOD_CONFORMAL,
             "first_base_date": dates[0], "last_base_date": dates[-1], "n_resolved": len(res),
             "n_pending": len(mine) - len(res), "band_methods": sorted({r.get("band_method") or "legacy (v1 row)"
                                                                          for r in mine})}
        if name == "conformal":
            p["n_fallback"] = sum(r.get("band_method") != "split_conformal" for r in mine)
        if res:
            res_dates = sorted({r["base_date"] for r in res})
            n_ind = max(len(res_dates) // h, 1)
            cover = float(np.mean([_in_band(r) for r in res]))
            pred = np.array([r["predicted_return"] for r in res])
            real = np.array([r["realized_return"] for r in res])
            by_date = [[i for i, r in enumerate(res) if r["base_date"] == d] for d in res_dates]
            m_sq = np.array([np.mean((real[ix] - pred[ix]) ** 2) for ix in by_date])
            b_sq = np.array([np.mean(real[ix] ** 2) for ix in by_date])
            p.update({"n_dates": len(res_dates), "n_independent": n_ind, "interval_coverage": cover,
                      "interval_coverage_ci_90": list(wilson_interval(cover, float(n_ind))),
                      "hit_rate": float(np.mean(np.sign(pred) == np.sign(real))), "up_rate": float(np.mean(real > 0)),
                      "skill_vs_naive": 1 - ratio(float(np.sqrt(m_sq.mean())), float(np.sqrt(b_sq.mean()))),
                      "interval_mean_width_pct": float(np.mean(
                          [(r["interval_high"] - r["interval_low"]) / r["base_close"] for r in res]) * 100)})
        out.append(p)
    return out


def band_cutover(rows: list[dict]) -> dict:
    """The configured cutover date and the first base date that actually logged a conformal-period band."""
    first = min((r["base_date"] for r in rows if band_period(r) == "conformal"), default=None)
    return {"configured_from": config.LOG_CONFORMAL_FROM, "first_conformal_base_date": first}


PUBLIC_KEYS = ("id", "symbol", "horizon_days", "made_at", "base_date", "base_close", "predicted_return",
               "interval_low", "interval_high", "backtest_skill", "backtest_verdict", "model", "status",
               "resolved_at", "realized_date", "realized_close", "realized_return", "prev_hash", "entry_hash",
               "res_seq", "res_prev_hash", "res_hash", "hash_version", "model_version", "band_method")


def public_row(r: dict) -> dict:
    """Everything needed to recompute both hash chains (see ``hash_spec``) is public."""
    out = {k: r.get(k) for k in PUBLIC_KEYS}
    if r["status"] == "resolved":
        px = r["base_close"] * float(np.exp(r["realized_return"]))
        out["in_interval"] = bool(r["interval_low"] <= px <= r["interval_high"])
        out["direction_correct"] = bool(np.sign(r["predicted_return"]) == np.sign(r["realized_return"]))
    return out


def hash_spec() -> dict:
    """Machine-readable description of how the log's hashes are computed, for third-party verification."""
    return {
        "algorithm": "sha256 (hex)",
        "genesis": "0" * 64,
        "entry_hash": "sha256(prev_hash + json.dumps([row[f] for f in entry_fields], separators=(',',':'), "
                      "default=str)); prev_hash = entry_hash of the previous row by id (genesis for the first)",
        "entry_fields": list(HASH_FIELDS),
        "entry_hash_v2": "rows with hash_version 2: sha256(prev_hash + json.dumps(['v2'] + [row[f] for f in "
                         "entry_fields_v2], separators=(',',':'), default=str)); rows with hash_version null or 1 "
                         "use entry_hash above. Both rules chain through prev_hash, so v1 rows followed by v2 rows "
                         "form one chain",
        "entry_fields_v2": list(HASH_FIELDS_V2),
        "res_hash": "sha256(res_prev_hash + entry_hash + json.dumps([row[f] for f in outcome_fields], "
                    "separators=(',',':'), default=str)); res_seq counts 1,2,3... in resolution order, "
                    "res_prev_hash is the previous sealed outcome's res_hash (genesis for res_seq 1)",
        "outcome_fields": list(RES_FIELDS),
        "note": ("Rows resolved before outcome seals existed have null res_* fields (reported as unsealed_resolved). "
                 "Rows written before the v2 rule (Nov 2026) have null hash_version, model_version and band_method "
                 "and verify with the original rule."),
    }
