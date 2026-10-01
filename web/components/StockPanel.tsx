"use client";
import { useId, useMemo, useState } from "react";
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useApi } from "@/lib/api";
import { BacktestSummary } from "./BacktestSummary";
import { useOnline } from "@/lib/online";
import { ModelComparison } from "./ModelComparison";
import { NewsPanel } from "./NewsPanel";
import { ErrorNotice, OutdatedLabel } from "./Notices";
import { SpikePanel } from "./SpikePanel";
import { VolatilityPanel } from "./VolatilityPanel";
import { buildRows, CHART_RANGES, rangeLong } from "@/lib/chartRange";
import { useChartRange } from "@/lib/chartRangeStore";
import type { Forecast, Timeline } from "@/lib/types";

const HORIZONS = [5, 10, 20, 60, 120, 180, 256]; // trading days; the backend validates 1..256
const LONG_HORIZON = 60;
function ForecastNote() {
  return (
    <p role="note" className="rounded border border-amber-300 bg-amber-50 px-2 py-1 text-xs font-medium text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
      ⚠️ Forecast is experimental and not financial advice — predictions are frequently wrong.
    </p>
  );
}

const pct = (x: number | null | undefined, d = 2) => (x == null ? "—" : `${(x * 100).toFixed(d)}%`);
const money = (x: number) => `$${x.toFixed(2)}`;
const spct = (x: number, d = 1) => `${x >= 0 ? "+" : ""}${x.toFixed(d)}%`;

function ChartTable({ history, forecast }: { history: Timeline; forecast?: Forecast }) {
  const base = history.points[0]?.close ?? 1;
  const long = rangeLong(history.range);
  return (
    <details className="text-sm">
      <summary className="cursor-pointer font-medium">View chart data as a table</summary>
      <div className="mt-2 max-h-72 overflow-auto" tabIndex={0} role="region" aria-label={`Scrollable table of ${history.symbol} prices`}>
        <table className="w-full text-sm">
          <caption className="sr-only">Closing prices for {history.symbol} over the past {long}{history.downsampled ? " (sampled)" : ""}{forecast ? ", followed by the forecast path with its 80% interval" : ""}</caption>
          <thead><tr className="text-left text-slate-600 dark:text-slate-300"><th scope="col">Date</th><th scope="col">Type</th><th scope="col" className="text-right">Price</th><th scope="col" className="text-right">80% range</th><th scope="col" className="text-right">Change since start of range</th></tr></thead>
          <tbody>
            {forecast?.path.map((p) => (<tr key={"f" + p.date} className="border-t border-slate-200 dark:border-slate-800"><td>{p.date}</td><td>Forecast</td><td className="text-right">{money(p.mid)}</td><td className="text-right">{money(p.low)} – {money(p.high)}</td><td className="text-right">{spct((p.mid / base - 1) * 100)}</td></tr>))}
            {[...history.points].reverse().map((p) => (<tr key={p.date} className="border-t border-slate-200 dark:border-slate-800"><td>{p.date}</td><td>Close</td><td className="text-right">{money(p.close)}</td><td className="text-right">—</td><td className="text-right">{spct((p.close / base - 1) * 100)}</td></tr>))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

function RangeSummary({ d }: { d: Timeline }) {
  const s = d.summary;
  const up = s.period_return_pct >= 0;
  const box = "rounded border border-slate-200 p-2 dark:border-slate-800";
  const sub = "text-xs text-slate-700 dark:text-slate-300";
  return (
    <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4" aria-label={`Summary for the past ${rangeLong(d.range)}`}>
      <div className={box}><dt className={sub}>Return over {rangeLong(d.range)}</dt>
        <dd className={`font-semibold ${up ? "text-green-800 dark:text-green-300" : "text-red-700 dark:text-red-300"}`}><span aria-hidden="true">{up ? "▲ " : "▼ "}</span>{spct(s.period_return_pct)}</dd>
        <dd className={sub}>{money(s.start_close)} → {money(s.end_close)}</dd></div>
      <div className={box}><dt className={sub}>High</dt><dd className="font-semibold">{money(s.high)}</dd><dd className={sub}>{s.high_date}</dd></div>
      <div className={box}><dt className={sub}>Low</dt><dd className="font-semibold">{money(s.low)}</dd><dd className={sub}>{s.low_date}</dd></div>
      <div className={box}><dt className={sub}>Worst drop from a peak</dt><dd className="font-semibold">{spct(s.max_drawdown_pct)}</dd><dd className={sub}>within this range</dd></div>
    </dl>
  );
}

function Chart({ history, forecast, normalized }: { history: Timeline; forecast?: Forecast; normalized: boolean }) {
  const data = useMemo(() => buildRows(history.points, forecast?.path, normalized), [history, forecast, normalized]);
  const s = history.summary;
  return (
    <div className="h-72 w-full" role="img"
      aria-label={`${normalized ? "Percent change" : "Price"} chart for ${history.symbol} over the past ${rangeLong(history.range)}${forecast ? ` with ${forecast.horizon_days}-day forecast and 80% interval` : ""}: ${spct(s.period_return_pct)} over the range, high ${money(s.high)}, low ${money(s.low)}. A table is available below.`}>
      <ResponsiveContainer>
        <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid strokeOpacity={0.15} />
          <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={40} />
          <YAxis domain={["auto", "auto"]} tick={{ fontSize: 11 }} width={52} tickFormatter={(v) => (normalized ? `${Number(v).toFixed(0)}%` : `$${Number(v).toFixed(0)}`)} />
          <Tooltip formatter={(v) => { const f = (n: unknown) => (normalized ? `${Number(n).toFixed(1)}%` : Number(n).toFixed(2)); return Array.isArray(v) ? v.map(f).join(" – ") : f(v); }} />
          <Area dataKey="band" name="80% interval" stroke="none" fill="#f59e0b" fillOpacity={0.25} isAnimationActive={false} />
          <Line dataKey="close" name="Close" stroke="#3b82f6" dot={false} strokeWidth={2} isAnimationActive={false} />
          <Line dataKey="mid" name="Forecast" stroke="#f59e0b" strokeDasharray="5 4" dot={false} strokeWidth={2} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function StockPanel({ symbol }: { symbol: string }) {
  const [range, setRange] = useChartRange();
  const normToggle = useId();
  const [normalized, setNormalized] = useState(false);
  const [horizon, setHorizon] = useState(5);
  const sym = encodeURIComponent(symbol);
  const online = useOnline();
  const hist = useApi<Timeline>(`/api/timeline/${sym}?range=${range}`);
  const fc = useApi<Forecast>(`/api/forecast/${sym}?horizon=${horizon}`, { cheap: false });

  const btn = (active: boolean) => `rounded px-2 py-1 text-xs font-medium ${active ? "bg-blue-700 text-white" : "bg-slate-200 text-slate-900 dark:bg-slate-800 dark:text-slate-100"}`;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-xl font-bold">{symbol}</h2>
        <div className="flex flex-wrap gap-1" role="group" aria-label="History range shown on the chart">{CHART_RANGES.map((r) => (<button key={r.id} className={btn(r.id === range)} aria-pressed={r.id === range} aria-label={r.long} onClick={() => setRange(r.id)}>{r.label}</button>))}</div>
      </div>

      {hist.loading && !hist.data && <p role="status" className="text-sm text-slate-700 dark:text-slate-300">Loading prices…</p>}
      {hist.failure && !(hist.data && !online) && <ErrorNotice failure={hist.failure} onRetry={hist.retry} what="Price history" />}
      {hist.data && (
        <>
          <OutdatedLabel fromSaved={hist.fromSaved} savedAt={hist.savedAt} stale={hist.data.stale} delayed={hist.data.is_delayed}
            asOf={hist.data.data_as_of} refreshing={hist.loading} onRetry={hist.retry} />
          <RangeSummary d={hist.data} />
          <label htmlFor={normToggle} className="flex items-center gap-2 text-sm">
            <input id={normToggle} type="checkbox" checked={normalized} onChange={(e) => setNormalized(e.target.checked)} className="h-4 w-4" />
            Show as % change from the start of the range (forecast included)
          </label>
          <Chart history={hist.data} forecast={fc.data} normalized={normalized} />
          <p className="text-xs text-slate-700 dark:text-slate-300">
            {hist.data.note} {hist.data.downsampled && `The chart shows ${hist.data.points.length} of ${hist.data.n_points_total} trading days (highs and lows kept); the summary uses all of them.`}
          </p>
          <ChartTable history={hist.data} forecast={fc.data} />
          {fc.data && <ForecastNote />}
        </>
      )}

      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span id="horizon-label">Forecast horizon (trading days):</span>
        <div className="flex flex-wrap gap-1" role="group" aria-labelledby="horizon-label">
          {HORIZONS.map((h) => (<button key={h} className={btn(h === horizon)} aria-pressed={h === horizon} onClick={() => setHorizon(h)}>{h}d</button>))}
        </div>
        {horizon >= 20 && horizon < LONG_HORIZON && <span className="text-xs text-slate-600 dark:text-slate-300">Longer horizons mean wider ranges and fewer independent backtests.</span>}
      </div>
      {horizon >= LONG_HORIZON && (
        <p role="note" className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-950 dark:border-red-800 dark:bg-red-950/40 dark:text-red-100">
          <strong>Long-horizon forecasts ({horizon} trading days, about {Math.round(horizon / 21)} months) are highly uncertain.</strong> The range is very wide, only a handful
          of independent past periods exist in five years of data to test it, and the point estimate is mostly noise. Use it as a sense of scale, not a prediction.
        </p>
      )}

      {fc.loading && !fc.data && <p role="status" className="text-sm text-slate-700 dark:text-slate-300">Training model &amp; running backtest… (can take a few seconds)</p>}
      {fc.failure && !(fc.data && !online) && <ErrorNotice failure={fc.failure} onRetry={fc.retry} what="Forecast" />}
      {fc.data && (
        <>
          <OutdatedLabel fromSaved={fc.fromSaved} savedAt={fc.savedAt} stale={fc.data.stale} delayed={fc.data.is_delayed}
            asOf={fc.data.data_as_of} refreshing={fc.loading} onRetry={fc.retry} />
          <section className="rounded-md border border-amber-300 bg-amber-50 p-4 dark:border-amber-800 dark:bg-amber-950/40">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-amber-800 dark:text-amber-300">
              Experimental · not financial advice
            </p>
            <p className="text-sm">
              Experimental {fc.data.horizon_days}-day estimate: <strong>${fc.data.predicted_price.toFixed(2)}</strong>{" "}
              ({fc.data.predicted_return >= 0 ? "+" : ""}{pct(fc.data.predicted_return)}) — 80% interval{" "}
              <strong>${fc.data.interval_80.low.toFixed(2)} – ${fc.data.interval_80.high.toFixed(2)}</strong>
            </p>
            <ul className="mt-2 list-disc pl-5 text-xs text-slate-600 dark:text-slate-300">{fc.data.notes.map((n) => (<li key={n}>{n}</li>))}</ul>
            <p className="mt-2 text-xs font-medium">{fc.data.disclaimer}</p>
          </section>
          <BacktestSummary backtest={fc.data.backtest} horizon={fc.data.horizon_days} />
        </>
      )}
      <SpikePanel symbol={symbol} horizon={horizon} />
      <VolatilityPanel symbol={symbol} horizon={horizon} />
      <ModelComparison symbol={symbol} horizon={horizon} />
      <NewsPanel symbol={symbol} />
    </div>
  );
}
