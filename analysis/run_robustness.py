#!/usr/bin/env python3
"""Robustness checks for docs/FINDINGS.md (section 6a). Existing results are NOT re-run or changed.

    python analysis/run_robustness.py                      # real data from Yahoo (yfinance), pinned 2015-2021 window
    python analysis/run_robustness.py --synthetic --quick  # offline smoke run on made-up prices (what CI does)

Two questions, both answered with the same backtest code as the main analysis (run_analysis.py):
  1. ETF-only subset: do the headline results hold on the 5 funds alone (SPY, QQQ, XLE, TLT, GLD), which have no
     single-company survivorship? Computed from the COMMITTED main-window results (results/*.csv), so the numbers
     are exactly the ones behind the existing tables, just filtered.
  2. Another period: the same 20 tickers on 2015-01-02 to 2021-12-31 (about 7 years), whose walk-forward test half
     (mid-2018 to 2021) includes the 2018 sell-off and the 2020 COVID crash. Fresh run, written to results/robustness_*.

The 2015-2021 run still uses today's tickers (survivors), so it tests another regime, not survivorship.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import run_analysis as RA  # noqa: E402  (adds backend/ to sys.path; reuses the same experiments)

ETFS = ["SPY", "QQQ", "XLE", "TLT", "GLD"]
ALT_START, ALT_END = "2015-01-02", "2021-12-31"
POINT_H = (5, 20, 60)
VOL_H = (5, 20, 60)
CONF_H = (5, 20)
SAMPLES = ("main, all 20", "main, ETFs only", "2015-2021, all 20", "2015-2021, ETFs only")


def load_window(tickers, start: str, end: str, cache: Path, synthetic: bool) -> dict[str, pd.Series]:
    if synthetic:
        return {t: RA.synthetic_close(100 + i, n=1760, end=end) for i, t in enumerate(tickers)}
    import yfinance as yf
    cache.mkdir(parents=True, exist_ok=True)
    out = {}
    stop = (pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    for t in tickers:
        f = cache / f"{t}_{start}_{end}.csv"
        if f.exists():
            s = pd.read_csv(f, index_col=0, parse_dates=True)["Close"]
        else:
            d = yf.Ticker(t).history(start=start, end=stop, interval="1d", auto_adjust=True)["Close"]
            d.index = d.index.tz_localize(None).normalize()
            s = d.dropna()
            s.to_frame("Close").to_csv(f)
        out[t] = s[(s.index >= pd.Timestamp(start)) & (s.index <= pd.Timestamp(end))].dropna()
    return out


def med(x: pd.Series, d: int = 1) -> str:
    return RA.pct(x.median(), d) if len(x) else "n/a"


def point_rows(p: pd.DataFrame, sample: str) -> list[dict]:
    rows = []
    for h in sorted(p.horizon.unique()):
        s = p[p.horizon == h]
        g, d = s[s.model == "gbm"], s[s.model == "drift"]
        cand = s[s.model != "naive"]
        rows.append({"sample": sample, "horizon (days)": h, "tickers": len(g),
                     "gradient boosting, median skill": med(g.skill),
                     "gradient boosting better than flat": f"{int((g.verdict == 'better').sum())}/{len(g)}",
                     "drift, median skill": med(d.skill),
                     "any model better than flat": f"{int((cand.verdict == 'better').sum())}/{len(cand)}",
                     "direction right (median) vs \"always up\"":
                         f"{g.hit_rate.median() * 100:.0f}% vs {g.up_rate.median() * 100:.0f}%"})
    return rows


def vol_rows(v: pd.DataFrame, sample: str) -> list[dict]:
    rows = []
    for h in sorted(v.horizon.unique()):
        s = v[v.horizon == h]
        e, g = s[s.model == "ewma"], s[s.model == "garch"]
        rows.append({"sample": sample, "horizon (days)": h,
                     "EWMA, median skill vs recent vol": med(e.skill),
                     "GJR-GARCH, median change vs EWMA": med(g.skill_vs_ewma),
                     "GARCH clearly better / worse than EWMA":
                         f"{int((g.verdict_vs_ewma == 'better').sum())} / {int((g.verdict_vs_ewma == 'not_better').sum())}"
                         f" of {len(g)}"})
    return rows


def conf_rows(c: pd.DataFrame, sample: str) -> list[dict]:
    rows = []
    for h in sorted(c.horizon.unique()):
        s = c[c.horizon == h]
        rows.append({"sample": sample, "horizon (days)": h, "range used": f"{int(s.used.sum())}/{len(s)}",
                     "conformal coverage, median (min-max)": RA.spread(s.conformal_cov),
                     "normal band coverage, median (min-max)": RA.spread(s.normal_cov),
                     "independent test periods (median)": int(s.n_independent.median())})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(HERE), help="output root; writes results/robustness_* under it")
    ap.add_argument("--synthetic", action="store_true", help="made-up prices for 2015-2021, no network (smoke test)")
    ap.add_argument("--quick", action="store_true", help="the 5 ETFs only and fewer horizons (smoke test)")
    a = ap.parse_args()
    out = Path(a.out) / "results"
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # 1. main window, from the committed results (unchanged numbers, just filtered)
    res = HERE / "results"
    p0, v0 = pd.read_csv(res / "point_models.csv"), pd.read_csv(res / "vol_models.csv")
    c0 = pd.read_csv(res / "conformal_vs_normal.csv")
    c0 = c0[c0.horizon.isin(CONF_H)]
    v0 = v0[v0.horizon.isin(VOL_H)]

    # 2. 2015-2021, fresh run
    tickers = ETFS if a.quick else RA.TICKERS
    point_h, vol_h, conf_h = ((5, 20), (5, 20), (5,)) if a.quick else (POINT_H, VOL_H, CONF_H)
    alt = load_window(tickers, ALT_START, ALT_END, HERE / ".cache", a.synthetic)
    p1 = RA.point_models(alt, point_h)
    v1 = RA.vol_models(alt, vol_h)
    c1 = RA.conformal_vs_normal(alt, alt, conf_h)
    for name, df in (("robustness_point", p1), ("robustness_vol", v1), ("robustness_conformal", c1)):
        df.to_csv(out / f"{name}.csv", index=False)

    def etf(df):
        return df[df.ticker.isin(ETFS)]

    frames = {SAMPLES[0]: (p0, v0, c0), SAMPLES[1]: (etf(p0), etf(v0), etf(c0)),
              SAMPLES[2]: (p1, v1, c1), SAMPLES[3]: (etf(p1), etf(v1), etf(c1))}
    if a.quick:  # the quick run only has the ETFs, so "all 20" would be mislabelled
        frames = {k: f for k, f in frames.items() if not k.startswith("2015-2021, all")}
    tabs = {"rob_point": pd.DataFrame([r for k, (p, _, _) in frames.items() for r in point_rows(p, k)]),
            "rob_vol": pd.DataFrame([r for k, (_, v, _) in frames.items() for r in vol_rows(v, k)]),
            "rob_conformal": pd.DataFrame([r for k, (_, _, c) in frames.items() for r in conf_rows(c, k)])}
    (out / "robustness_tables.md").write_text(
        "\n\n".join(f"<!-- table: {k} -->\n{RA.md(df)}" for k, df in tabs.items()) + "\n")
    meta = {"data": "synthetic (smoke test)" if a.synthetic else "Yahoo Finance via yfinance, adjusted daily closes",
            "window": [ALT_START, ALT_END], "tickers": tickers, "etfs": ETFS, "git_commit": RA.git_commit(),
            "python": RA.platform.python_version(), "bars": {t: len(s) for t, s in alt.items()},
            "first_date": {t: str(s.index[0].date()) for t, s in alt.items()},
            "last_date": {t: str(s.index[-1].date()) for t, s in alt.items()}, "seconds": round(time.time() - t0)}
    (out / "robustness_summary.json").write_text(json.dumps(meta, indent=2, default=str) + "\n")
    print(f"done in {meta['seconds']}s -> {out}")
    for k, df in tabs.items():
        print(f"\n[{k}]\n{RA.md(df)}")


if __name__ == "__main__":
    main()
