# analysis/

Reproducible analysis behind [`docs/FINDINGS.md`](../docs/FINDINGS.md). It calls the same backtest code the API uses
(`backend/app/forecast.py`, `models.py`, `volatility.py`, `conformal.py`, `garch.py`) on public Yahoo Finance data, so the write-up
cannot say anything the code does not.

| File | What it is |
|---|---|
| `run_analysis.py` | Downloads prices (cached in `analysis/.cache/`, git-ignored), runs every experiment, writes `results/` and `figures/` |
| `build_findings.py` + `findings_template.md` | Fill the prose and tables of `docs/FINDINGS.md` from `results/`, so numbers are never typed by hand |
| `findings.ipynb` | A short, executed notebook that loads the saved results and lets you explore them (per-ticker tables, charts) |
| `results/` | `tables.md`, `summary.json` (data window, tickers, bar counts, commit) and one CSV per experiment |
| `figures/` | The five PNG charts used in the write-up |

## Reproduce

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -c backend/requirements.lock -r analysis/requirements.txt
python analysis/run_analysis.py          # ~3 minutes, needs internet (yfinance); pinned end date 2026-10-01
python analysis/build_findings.py        # rewrite docs/FINDINGS.md from the new results
```

- `--end YYYY-MM-DD` changes the last trading day (the committed results use 2026-10-01, so the window is pinned). Yahoo data is
  unofficial and can be revised, so a re-run later may differ slightly from the committed numbers; `results/summary.json` records
  exactly what produced them. The code itself is deterministic (fixed seeds): re-running on the same prices gives identical tables.
- `--synthetic --quick` runs offline on made-up prices with 2 tickers in about 15 seconds. CI runs this to make sure the script
  still works; its output is meaningless as a finding.
- If you change the ticker list, update the "20 tickers" wording in `findings_template.md` (the builder asserts the count).

## What it computes

1. **Point forecasts** (`compare_models`): naive, drift, EWMA, ridge AR and gradient boosting at 5, 20 and 60 days, skill versus flat,
   verdict counts, direction hit rate versus "always up".
2. **Volatility** (`forecast_volatility`): naive, EWMA, HAR and GJR-GARCH at 5, 20, 60 and 120 days, plus each against the EWMA headline.
3. **Intervals**: measured coverage of the conformal band versus a textbook normal band (EWMA volatility x 1.2816 x sqrt(h)),
   replayed on the same origins, at 5, 20, 60, 120, 180 and 256 days.
4. **Leakage demo**: one model scored with shuffled k-fold, walk-forward without an embargo, and walk-forward with the embargo.
5. **SPY case study**: out-of-sample 20-day volatility forecasts versus what happened.

Not a trading system, not financial advice.
