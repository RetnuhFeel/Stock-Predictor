"use client";
import { useId, useState } from "react";
import { ModelComparison } from "./ModelComparison";

const SYMBOLS = ["SPY", "AAPL", "MSFT", "NVDA", "TSLA"];
const HORIZONS = [5, 10, 20];

/** Model comparison for one of the report-card tickers on /model. */
export function ModelExplorer() {
  const [symbol, setSymbol] = useState("SPY");
  const [horizon, setHorizon] = useState(5);
  const sid = useId();
  const hid = useId();
  const sel = "ml-2 rounded border border-slate-400 bg-white px-2 py-1 text-sm dark:border-slate-600 dark:bg-slate-900";
  return (
    <section aria-labelledby="explorer-title" className="space-y-3">
      <h2 id="explorer-title">Model comparison</h2>
      <p>
        The forecast above is one model. Here it is next to simpler ones (average return, recent trend, a linear model), all graded the same
        way against &ldquo;price stays flat&rdquo;. This is the honest way to ask whether the fancy model earns its complexity.
      </p>
      <div className="flex flex-wrap gap-4 text-sm">
        <label htmlFor={sid}>Ticker<select id={sid} value={symbol} onChange={(e) => setSymbol(e.target.value)} className={sel}>{SYMBOLS.map((s) => <option key={s}>{s}</option>)}</select></label>
        <label htmlFor={hid}>Horizon<select id={hid} value={horizon} onChange={(e) => setHorizon(Number(e.target.value))} className={sel}>{HORIZONS.map((h) => <option key={h} value={h}>{h} trading days</option>)}</select></label>
      </div>
      <ModelComparison key={`${symbol}-${horizon}`} symbol={symbol} horizon={horizon} />
    </section>
  );
}
