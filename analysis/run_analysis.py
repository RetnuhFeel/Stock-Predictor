#!/usr/bin/env python3
"""Regenerates every number, table and chart in docs/FINDINGS.md from this repo's own backtest code.

    python analysis/run_analysis.py                      # real data from Yahoo (yfinance), pinned end date
    python analysis/run_analysis.py --synthetic --quick  # offline smoke run on made-up prices (what CI does)

What it does (nothing here is hand-edited; the write-up quotes the outputs):
  1. downloads daily adjusted closes for a fixed ticker list up to a pinned end date (cached locally),
  2. runs the same walk-forward + embargo code the API uses (backend/app/forecast.py, models.py, volatility.py,
     conformal.py, garch.py) for several horizons and every ticker,
  3. runs one extra experiment, a deliberately leaky evaluation, to show why the embargo matters,
  4. writes tables (results/*.csv, results/tables.md, results/summary.json) and charts (figures/*.png).

Yahoo data is unofficial and can be revised after the fact, so a re-run can differ slightly from the committed
numbers; the committed summary.json records exactly which data (tickers, date range, bar counts) produced them.
"""
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "backend"))

import matplotlib
from sklearn.model_selection import KFold

matplotlib.use("Agg")  # headless; must come before pyplot is imported
import matplotlib.pyplot as plt  # isort: skip

from app import conformal  # isort: skip
from app import forecast as F  # isort: skip
from app import volatility as V  # isort: skip
from app.errors import ApiError  # isort: skip
from app.models import compare_models  # isort: skip

warnings.filterwarnings("ignore")

TICKERS = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "JPM",
           "KO", "XOM", "PFE", "JNJ", "PG", "WMT", "UNH", "XLE", "TLT", "GLD"]
POINT_H = (5, 20, 60)                 # point-forecast comparison horizons (trading days)
VOL_H = (5, 20, 60, 120)              # volatility horizons
CONF_H = (5, 20, 60, 120, 180, 256)   # conformal interval horizons
LEAK_H = 20
Z80 = F.Z80
COLORS = {"naive": "#6b7280", "drift": "#a78bfa", "ewma": "#2563eb", "ridge_ar": "#059669", "gbm": "#d97706",
          "har": "#0891b2", "garch": "#dc2626"}
NAMES = {"naive": "Naive (flat)", "drift": "Drift", "ewma": "EWMA", "ridge_ar": "Ridge AR", "gbm": "Gradient boosting",
         "har": "HAR", "garch": "GJR-GARCH"}


# ----------------------------------------------------------------------------------------------- data
def synthetic_close(seed: int, n: int = 2600, end: str = "2026-10-01") -> pd.Series:
    """Made-up prices with volatility clustering (a GARCH-like process). Used only for the offline smoke run."""
    rng = np.random.default_rng(seed)
    r, s2 = np.empty(n), 1e-4
    for t in range(n):
        r[t] = np.sqrt(s2) * rng.standard_normal() + 0.0003
        s2 = 2e-6 + (0.05 + 0.08 * (r[t] < 0)) * (r[t] - 0.0003) ** 2 + 0.88 * s2
    idx = pd.bdate_range(end=end, periods=n)
    return pd.Series(100 * np.exp(np.cumsum(r)), index=idx)


def load_prices(tickers: list[str], end: str, cache: Path, synthetic: bool) -> dict[str, pd.Series]:
    if synthetic:
        return {t: synthetic_close(i, end=end) for i, t in enumerate(tickers)}
    import yfinance as yf
    cache.mkdir(parents=True, exist_ok=True)
    out = {}
    start = (pd.Timestamp(end) - pd.DateOffset(years=10, months=2)).strftime("%Y-%m-%d")
    stop = (pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")  # yfinance end is exclusive
    for t in tickers:
        f = cache / f"{t}_{end}.csv"
        if f.exists():
            s = pd.read_csv(f, index_col=0, parse_dates=True)["Close"]
        else:
            d = yf.Ticker(t).history(start=start, end=stop, interval="1d", auto_adjust=True)["Close"]
            d.index = d.index.tz_localize(None).normalize()
            s = d.dropna()
            s.to_frame("Close").to_csv(f)
        out[t] = s[s.index <= pd.Timestamp(end)].dropna()
    return out


def windows(close_all: pd.Series, end: str) -> tuple[pd.Series, pd.Series]:
    """(5-year series the API forecasts from, 10-year series used to calibrate 120+ day conformal ranges)."""
    e = pd.Timestamp(end)
    return (close_all[close_all.index > e - pd.DateOffset(years=5)],
            close_all[close_all.index > e - pd.DateOffset(years=10)])


# ----------------------------------------------------------------------------------------------- experiments
def point_models(c5: dict[str, pd.Series], horizons) -> pd.DataFrame:
    rows = []
    for t, close in c5.items():
        for h in horizons:
            try:
                r = compare_models(close, h)
            except ApiError:
                continue
            for m in r["models"]:
                rows.append({"ticker": t, "horizon": h, "model": m["model"], "skill": m["skill_vs_naive"],
                             "ci_lo": m["skill_ci_90"][0], "ci_hi": m["skill_ci_90"][1], "verdict": m["verdict"],
                             "hit_rate": m["hit_rate"], "up_rate": r["up_rate"], "n_independent": r["n_independent_tests"]})
    return pd.DataFrame(rows)


def vol_models(c5: dict[str, pd.Series], horizons) -> pd.DataFrame:
    rows = []
    for t, close in c5.items():
        for h in horizons:
            try:
                r = V.forecast_volatility(close, h)
            except ApiError:
                continue
            for m in r["models"]:
                vs = m.get("vs_headline")
                rows.append({"ticker": t, "horizon": h, "model": m["model"], "skill": m["skill_vs_naive"],
                             "verdict": m["verdict"], "one_sigma_cov": m["one_sigma_coverage"],
                             "skill_vs_ewma": None if vs is None else vs["skill"],
                             "ci_vs_ewma_lo": None if vs is None else vs["skill_ci_90"][0],
                             "ci_vs_ewma_hi": None if vs is None else vs["skill_ci_90"][1],
                             "verdict_vs_ewma": None if vs is None else vs["verdict"], "n_independent": r["n_independent_tests"]})
    return pd.DataFrame(rows)


def conformal_scores(close5: pd.Series, close10: pd.Series, h: int) -> np.ndarray:
    """The volatility-normalised errors the API calibrates on (mirrors forecast.forecast(); see that function)."""
    close = close5.dropna()[lambda c: c > 0]
    if h >= F.config.VOL_CONE_MIN_HORIZON:
        return F.conformal_scores_cone(close10.dropna()[lambda c: c > 0], h)
    feats = F.make_features(close)
    data = feats.assign(target=np.log(close).shift(-h) - np.log(close)).dropna()
    X, y = data[F.FEATURES], data["target"]
    folds = F.fold_schedule(len(X), h)
    wf = F.walk_forward(X, y, h)
    return F.conformal_scores_oos(wf, folds, X.index, conformal.ewma_vol_series(close), h)


def conformal_vs_normal(c5, c10, horizons) -> pd.DataFrame:
    """Measured coverage of the conformal band vs the textbook normal band (EWMA vol x 1.2816 x sqrt(h)), replayed on the
    same origins. The normal band needs no calibration, so it is the natural thing to beat."""
    rows = []
    for t in c5:
        for h in horizons:
            try:
                f = F.forecast(c5[t], h, calib_close=c10[t] if h >= F.config.VOL_CONE_MIN_HORIZON else None)
                sc = conformal_scores(c5[t], c10[t], h)
            except ApiError:
                continue
            c = f["conformal"]
            sc = sc[np.isfinite(sc)]
            ks = range(max(conformal.MIN_CAL_ROWS, conformal.MIN_CAL_HORIZONS * h) + h - 1, len(sc))
            normal_cov = float(np.mean([sc[k] <= Z80 for k in ks])) if len(ks) else np.nan
            rows.append({"ticker": t, "horizon": h, "used": c["used"], "conformal_cov": c["measured_coverage"],
                         "ci_lo": (c["measured_coverage_ci_90"] or [np.nan, np.nan])[0],
                         "ci_hi": (c["measured_coverage_ci_90"] or [np.nan, np.nan])[1],
                         "normal_cov": normal_cov, "multiplier": c["multiplier"], "n_independent": c["n_evaluation_independent"],
                         "n_calibration": c["n_calibration"], "reason": c["reason_not_used"]})
    return pd.DataFrame(rows)


def leakage_demo(c5, h: int) -> pd.DataFrame:
    """The same gradient-boosting model scored three ways. Only the last is honest."""
    rows = []
    for t, close in c5.items():
        close = close.dropna()[lambda c: c > 0]
        df = F.make_features(close).assign(target=np.log(close).shift(-h) - np.log(close)).dropna()
        X, y = df[F.FEATURES], df["target"]
        pred = np.empty(len(y))
        for tr, te in KFold(6, shuffle=True, random_state=0).split(X):
            pred[te] = F._model().fit(X.iloc[tr], y.iloc[tr]).predict(X.iloc[te])
        out = {"ticker": t, "shuffled k-fold (leaky)": 1 - F.ratio(np.sqrt(np.mean((y - pred) ** 2)), np.sqrt(np.mean(y ** 2)))}
        for name, emb in (("walk-forward, no embargo", 0), ("walk-forward + embargo (used)", h)):
            wf = F.walk_forward(X, y, emb)
            out[name] = 1 - F.ratio(np.sqrt(np.mean((wf.y_true - wf.y_pred) ** 2)), np.sqrt(np.mean(wf.y_true ** 2)))
        rows.append(out)
    return pd.DataFrame(rows)


def vol_case_study(close: pd.Series, h: int) -> pd.DataFrame:
    """Out-of-sample realised volatility vs the EWMA and GJR-GARCH forecasts for one ticker (the same test rows as the API)."""
    close = close.dropna()[lambda c: c > 0]
    feats, label = V._dataset(close, h)
    data = feats.join(label).dropna()
    folds = F.fold_schedule(len(data), h)
    g, _, _ = V._garch_walk_forward(close, data, folds, h, 30.0)
    idx = data.index[np.concatenate([np.arange(t.start, t.stop) for _, t in folds])]
    ann = np.sqrt(252)
    return pd.DataFrame({"actual": data["fut"].reindex(idx) * ann, "ewma": data["ewma"].reindex(idx) * ann,
                         "garch": g * ann if g is not None else np.nan}, index=idx)


# ----------------------------------------------------------------------------------------------- tables
def md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(str(v) for v in r.values) + " |")
    return "\n".join(lines)


def pct(x, d=0):
    return "n/a" if x is None or pd.isna(x) else f"{x * 100:+.{d}f}%"


def table_point(p: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for h in sorted(p.horizon.unique()):
        for m in ["drift", "ewma", "ridge_ar", "gbm"]:
            s = p[(p.horizon == h) & (p.model == m)]
            rows.append({"horizon (days)": h, "model": NAMES[m], "tickers": len(s), "better than flat": int((s.verdict == "better").sum()),
                         "inconclusive": int((s.verdict == "inconclusive").sum()), "not better": int((s.verdict == "not_better").sum()),
                         "median skill": pct(s.skill.median(), 1), "tickers with skill > 0": f"{int((s.skill > 0).sum())}/{len(s)}"})
    return pd.DataFrame(rows)


def table_direction(p: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for h in sorted(p.horizon.unique()):
        s = p[(p.horizon == h) & (p.model == "gbm")]
        rows.append({"horizon (days)": h, "model right about direction (median)": f"{s.hit_rate.median() * 100:.0f}%",
                     "\"always up\" would score (median)": f"{s.up_rate.median() * 100:.0f}%",
                     "tickers where model beat \"always up\"": f"{int((s.hit_rate > s.up_rate).sum())}/{len(s)}"})
    return pd.DataFrame(rows)


def table_vol(v: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for h in sorted(v.horizon.unique()):
        for m in ["ewma", "har", "garch"]:
            s = v[(v.horizon == h) & (v.model == m)]
            row = {"horizon (days)": h, "model": NAMES[m] if m != "ewma" else "EWMA volatility", "median skill vs recent vol": pct(s.skill.median(), 1),
                   "better than recent vol": f"{int((s.verdict == 'better').sum())}/{len(s)}"}
            if m == "ewma":
                row.update({"better than EWMA": "(headline)", "worse than EWMA": "", "median change vs EWMA": ""})
            else:
                row.update({"better than EWMA": f"{int((s.verdict_vs_ewma == 'better').sum())}/{len(s)}",
                            "worse than EWMA": f"{int((s.verdict_vs_ewma == 'not_better').sum())}/{len(s)}",
                            "median change vs EWMA": pct(s.skill_vs_ewma.median(), 1)})
            rows.append(row)
    return pd.DataFrame(rows)


def spread(x: pd.Series) -> str:
    return f"{x.median() * 100:.0f}% ({x.min() * 100:.0f}-{x.max() * 100:.0f}%)"


def table_conf(c: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for h in sorted(c.horizon.unique()):
        s = c[c.horizon == h]
        rows.append({"horizon (days)": h, "range used": f"{int(s.used.sum())}/{len(s)}",
                     "conformal coverage, median (min-max)": spread(s.conformal_cov),
                     "normal band coverage, median (min-max)": spread(s.normal_cov),
                     "typical multiplier (normal = 1.28)": f"{s.multiplier.median():.2f}",
                     "independent test periods (median)": int(s.n_independent.median())})
    return pd.DataFrame(rows)


def table_leak(L: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for c in L.columns[1:]:
        rows.append({"how the model was scored": c, "median skill vs flat": pct(L[c].median(), 1),
                     "tickers with skill > 0": f"{int((L[c] > 0).sum())}/{len(L)}"})
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------------------------- charts
def style():
    plt.rcParams.update({"figure.dpi": 130, "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
                         "grid.alpha": 0.25, "font.size": 10, "axes.titleweight": "bold"})


def strip(ax, data_by_label: dict, colors: dict, ref=0.0):
    rng = np.random.default_rng(0)
    for i, (lab, vals) in enumerate(data_by_label.items()):
        v = np.asarray([x for x in vals if pd.notna(x)])
        ax.scatter(i + rng.uniform(-0.18, 0.18, len(v)), v, s=22, alpha=0.65, color=colors[lab], edgecolor="white", linewidth=0.4, zorder=3)
        if len(v):
            ax.hlines(np.median(v), i - 0.3, i + 0.3, color="black", linewidth=2, zorder=4)
    ax.axhline(ref, color="black", linewidth=0.8, linestyle="--")
    ax.set_xticks(range(len(data_by_label)))


def fig_point(p: pd.DataFrame, out: Path):
    hs = sorted(p.horizon.unique())
    fig, axes = plt.subplots(1, len(hs), figsize=(4.2 * len(hs), 4.2), sharey=True)
    axes = np.atleast_1d(axes)
    models = ["drift", "ewma", "ridge_ar", "gbm"]
    for ax, h in zip(axes, hs):
        strip(ax, {m: p[(p.horizon == h) & (p.model == m)].skill.values for m in models}, COLORS)
        ax.set_xticklabels([NAMES[m].replace(" ", "\n") for m in models], fontsize=8)
        ax.set_title(f"{h}-day horizon")
    axes[0].set_ylabel("skill vs. \"price stays flat\"\n(above 0 = better than flat; each dot = one ticker)")
    fig.suptitle("Point forecasts: no model reliably beats \"the price stays flat\"", fontweight="bold")
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def fig_leak(L: pd.DataFrame, out: Path, h: int):
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    cols = list(L.columns[1:])
    cmap = {cols[0]: "#dc2626", cols[1]: "#f59e0b", cols[2]: "#2563eb"}
    strip(ax, {c: L[c].values for c in cols}, cmap)
    ax.set_xticklabels([c.replace(", ", ",\n").replace(" (", "\n(") for c in cols], fontsize=8)
    ax.set_ylabel("skill vs. \"price stays flat\"\n(each dot = one ticker, bar = median)")
    ax.set_title(f"Same model, three ways of scoring it ({h}-day horizon)")
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def fig_vol(v: pd.DataFrame, out: Path):
    hs = sorted(v.horizon.unique())
    fig, axes = plt.subplots(1, len(hs), figsize=(3.9 * len(hs), 4.4), sharey=True)
    axes = np.atleast_1d(axes)
    models = ["ewma", "har", "garch"]
    for ax, h in zip(axes, hs):
        strip(ax, {m: v[(v.horizon == h) & (v.model == m)].skill.values for m in models}, COLORS)
        ax.set_xticklabels([NAMES[m] for m in models], fontsize=8)
        ax.set_title(f"{h}-day horizon")
    axes[0].set_ylabel("skill vs. \"as jumpy as the last 21 days\"\n(above 0 = closer to what happened)")
    fig.suptitle("Volatility is partly predictable (unlike direction); the fancier models help more as the horizon grows", fontweight="bold")
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def fig_case(df: pd.DataFrame, ticker: str, h: int, out: Path):
    fig, ax = plt.subplots(figsize=(9, 4.2))
    ax.plot(df.index, df["actual"] * 100, color="black", linewidth=1.6, label=f"What actually happened (next {h} days)")
    ax.plot(df.index, df["ewma"] * 100, color=COLORS["ewma"], linewidth=1.3, label="EWMA forecast")
    ax.plot(df.index, df["garch"] * 100, color=COLORS["garch"], linewidth=1.3, label="GJR-GARCH forecast")
    ax.set_ylabel("annualised volatility (%)")
    ax.set_title(f"{ticker}: {h}-day-ahead volatility, forecasts vs. outcome (out-of-sample rows only)")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def fig_cov(c: pd.DataFrame, out: Path):
    hs = sorted(c.horizon.unique())
    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    x = np.arange(len(hs))
    rng = np.random.default_rng(1)
    for j, (col, lab, colr, off) in enumerate((("normal_cov", "Textbook normal band", "#9ca3af", -0.17), ("conformal_cov", "Conformal band", "#2563eb", 0.17))):
        for i, h in enumerate(hs):
            s = c[c.horizon == h]
            ax.scatter(i + off + rng.uniform(-0.07, 0.07, len(s)), s[col] * 100, s=18, alpha=0.6, color=colr, zorder=3,
                       label=lab if i == 0 else None)
            ax.hlines(s[col].median() * 100, i + off - 0.13, i + off + 0.13, color="black", linewidth=2, zorder=4)
    for i, h in enumerate(hs):  # mark horizons where the API refuses to use the conformal range
        s = c[c.horizon == h]
        if not s.used.any():
            ax.text(i, 31, "not enough\nindependent\nperiods: not used", ha="center", fontsize=7.5, color="#b91c1c")
    ax.axhline(80, color="#16a34a", linestyle="--", linewidth=1.2, label="Target: 80%")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{h} days" for h in hs])
    ax.set_ylim(25, 102)
    ax.set_ylabel("share of past outcomes inside the range (%)")
    ax.set_title("Does the \"80% range\" really contain 80% of outcomes? (replayed on past data)")
    ax.legend(frameon=False, loc="lower left", ncol=3, fontsize=8)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


# ----------------------------------------------------------------------------------------------- main
def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=HERE, text=True).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--end", default="2026-10-01", help="last trading day to include (pins the data window)")
    ap.add_argument("--out", default=str(HERE), help="output root; writes results/ and figures/ under it")
    ap.add_argument("--synthetic", action="store_true", help="made-up prices, no network (smoke test only)")
    ap.add_argument("--quick", action="store_true", help="2 tickers and fewer horizons (smoke test)")
    a = ap.parse_args()
    out = Path(a.out)
    (out / "results").mkdir(parents=True, exist_ok=True)
    (out / "figures").mkdir(parents=True, exist_ok=True)
    style()

    tickers = TICKERS[:2] if a.quick else TICKERS
    point_h, vol_h, conf_h = ((5, 20), (5, 20), (5, 120)) if a.quick else (POINT_H, VOL_H, CONF_H)
    t0 = time.time()
    full = load_prices(tickers, a.end, HERE / ".cache", a.synthetic)
    c5, c10 = {}, {}
    for t, s in full.items():
        c5[t], c10[t] = windows(s, a.end)
    meta = {"data": "synthetic (smoke test)" if a.synthetic else "Yahoo Finance via yfinance, adjusted daily closes",
            "end_date": a.end, "tickers": tickers, "git_commit": git_commit(), "python": platform.python_version(),
            "bars_5y": {t: len(s) for t, s in c5.items()}, "first_date_5y": {t: str(s.index[0].date()) for t, s in c5.items()},
            "last_date": {t: str(s.index[-1].date()) for t, s in c5.items()}}

    p = point_models(c5, point_h)
    v = vol_models(c5, vol_h)
    c = conformal_vs_normal(c5, c10, conf_h)
    L = leakage_demo(c5, point_h[1] if a.quick else LEAK_H)
    case_t = "SPY" if "SPY" in c5 else tickers[0]
    case = vol_case_study(c5[case_t], 20)

    for name, df in (("point_models", p), ("vol_models", v), ("conformal_vs_normal", c), ("leakage", L), ("vol_case_study", case)):
        df.to_csv(out / "results" / f"{name}.csv", index=name == "vol_case_study")
    tabs = {"point": table_point(p), "direction": table_direction(p), "volatility": table_vol(v),
            "conformal": table_conf(c), "leakage": table_leak(L)}
    (out / "results" / "tables.md").write_text("\n\n".join(f"<!-- table: {k} -->\n{md(df)}" for k, df in tabs.items()) + "\n")

    fig_point(p, out / "figures" / "1_point_forecasts_vs_flat.png")
    fig_leak(L, out / "figures" / "2_leakage_demo.png", point_h[1] if a.quick else LEAK_H)
    fig_vol(v, out / "figures" / "3_volatility_models.png")
    fig_case(case, case_t, 20, out / "figures" / "4_volatility_case_study.png")
    fig_cov(c, out / "figures" / "5_interval_coverage.png")

    meta["seconds"] = round(time.time() - t0)
    g = v[(v.model == "garch") & (v.horizon == 20)]
    meta["headline"] = {
        "point_models_better_than_flat": int((p[p.model != "naive"].verdict == "better").sum()),
        "point_model_tests": int(len(p[p.model != "naive"])),
        "garch_vs_ewma_20d_better": int((g.verdict_vs_ewma == "better").sum()), "garch_vs_ewma_20d_tickers": int(len(g)),
    }
    (out / "results" / "summary.json").write_text(json.dumps(meta, indent=2, default=str) + "\n")
    print(f"done in {meta['seconds']}s -> {out}/results, {out}/figures")
    for k, df in tabs.items():
        print(f"\n[{k}]\n{md(df)}")


if __name__ == "__main__":
    main()
