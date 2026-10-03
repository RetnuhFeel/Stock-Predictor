#!/usr/bin/env python3
"""Builds docs/FINDINGS.md from analysis/findings_template.md and the saved results (results/*.csv, tables.md).

Every number in the prose and every table is filled in from the results that run_analysis.py wrote, so the
write-up cannot drift from the data. Edit the wording in findings_template.md, then run:

    python analysis/build_findings.py          # rewrites docs/FINDINGS.md
    python analysis/build_findings.py --check  # exits 1 if docs/FINDINGS.md is out of date (used by a test)

Needs only pandas (no matplotlib, no network).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "docs" / "FINDINGS.md"


def pc(x: float) -> str:
    return f"{x * 100:.0f}%"


def spc(x: float, d: int = 1) -> str:
    return f"{x * 100:+.{d}f}%"


def tables(text: str) -> dict[str, str]:
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"<!-- table: (\w+) -->\n(.*?)(?=\n\n<!-- table:|\Z)", text, re.S)}


def render() -> str:
    r = HERE / "results"
    meta = json.loads((r / "summary.json").read_text())
    p = pd.read_csv(r / "point_models.csv")
    v = pd.read_csv(r / "vol_models.csv")
    c = pd.read_csv(r / "conformal_vs_normal.csv")
    leak = pd.read_csv(r / "leakage.csv")
    tabs = tables((r / "tables.md").read_text())
    n_tickers = len(meta["tickers"])
    assert n_tickers == 20, "the prose below says 20 tickers; update findings_template.md if you change the list"

    vals: dict[str, str] = {}
    cand = p[p.model != "naive"]
    vals["better_point"], vals["n_point"] = str(int((cand.verdict == "better").sum())), str(len(cand))
    g = p[p.model == "gbm"]
    vals["gbm_neg"] = str(int((g[g.horizon == 20].skill <= 0).sum()))
    for h in (5, 20, 60):
        s = g[g.horizon == h]
        vals[f"hit{h}"], vals[f"up{h}"] = pc(s.hit_rate.median()), pc(s.up_rate.median())
        vals[f"gbm{h}"] = spc(s.skill.median())
    vals["drift60"] = spc(p[(p.model == "drift") & (p.horizon == 60)].skill.median())
    gv = v[v.model == "garch"]
    for h in (5, 20, 60):
        s = gv[gv.horizon == h]
        vals[f"g{h}b"] = str(int((s.verdict_vs_ewma == "better").sum()))
        vals[f"g{h}w"] = str(int((s.verdict_vs_ewma == "not_better").sum()))
        if h > 5:
            vals[f"garch{h}"] = f"{s.skill_vs_ewma.median() * 100:.0f}%"
    vals["h5b"] = str(int(((v.model == "har") & (v.horizon == 5) & (v.verdict_vs_ewma == "better")).sum()))
    for h in (5, 20, 120, 180):
        s = c[c.horizon == h]
        vals[f"cov{h}"], vals[f"ncov{h}"] = pc(s.conformal_cov.median()), pc(s.normal_cov.median())
    s20 = c[c.horizon == 20]
    vals["cmin20"], vals["cmax20"] = pc(s20.conformal_cov.min()), pc(s20.conformal_cov.max())
    lc = list(leak.columns[1:])
    vals["leak_leaky"], vals["leak_honest"] = spc(leak[lc[0]].median()), spc(leak[lc[2]].median())
    vals["leak_honest_n"] = str(int((leak[lc[2]] > 0).sum()))
    vals["commit"], vals["seconds"] = meta["git_commit"], str(meta["seconds"])

    text = (HERE / "findings_template.md").read_text()
    text = re.sub(r"\{\{table:(\w+)\}\}", lambda m: tabs[m.group(1)], text)
    text = re.sub(r"\{\{(\w+)\}\}", lambda m: vals[m.group(1)], text)
    return text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    text = render()
    if a.check:
        if not OUT.exists() or OUT.read_text() != text:
            print("docs/FINDINGS.md is out of date: run python analysis/build_findings.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
