"use client";
import { useMemo, useState } from "react";
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useApi } from "@/lib/api";
import { BacktestSummary } from "./BacktestSummary";
import { useOnline } from "@/lib/online";
import { NewsPanel } from "./NewsPanel";
import { ErrorNotice, OutdatedLabel } from "./Notices";
import type { Forecast, History } from "@/lib/types";

const RANGES = ["1mo", "3mo", "6mo", "1y", "2y"] as const;
const HORIZONS = [1, 5, 10, 20, 40, 60]; // trading days; the backend validates 1..60
function ForecastNote() {
  return (
    <p role="note" className="rounded border border-amber-300 bg-amber-50 px-2 py-1 text-xs font-medium text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
      ⚠️ Forecast is experimental and not financial advice — predictions are frequently wrong.
    </p>
  );
}

const pct = (x: number | null | undefined, d = 2) => (x == null ? "—" : `${(x * 100).toFixed(d)}%`);

type Row = { date: string; close?: number; mid?: number; band?: [number, number] };

function ChartTable({ history, forecast }: { history: History; forecast?: Forecast }) {
  const recent = history.points.slice(-10);
  return (
    <details className="text-sm">
      <summary className="cursor-pointer font-medium">View chart data as a table</summary>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">Recent closing prices{forecast ? " and forecast path with 80% interval" : ""} for {history.symbol}</caption>
          <thead><tr className="text-left text-slate-600 dark:text-slate-300"><th scope="col">Date</th><th scope="col">Type</th><th scope="col" className="text-right">Price</th><th scope="col" className="text-right">80% range</th></tr></thead>
          <tbody>
            {recent.map((p) => (<tr key={p.date} className="border-t border-slate-200 dark:border-slate-800"><td>{p.date}</td><td>Close</td><td className="text-right">${p.close.toFixed(2)}</td><td className="text-right">—</td></tr>))}
            {forecast?.path.map((p) => (<tr key={"f" + p.date} className="border-t border-slate-200 dark:border-slate-800"><td>{p.date}</td><td>Forecast</td><td className="text-right">${p.mid.toFixed(2)}</td><td className="text-right">${p.low.toFixed(2)} – ${p.high.toFixed(2)}</td></tr>))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

function Chart({ history, forecast }: { history: History; forecast?: Forecast }) {
  const data = useMemo(() => {
    const rows: Row[] = history.points.map((p) => ({ date: p.date, close: p.close }));
    if (forecast && rows.length) {
      const last = rows[rows.length - 1];
      last.mid = last.close;
      last.band = [last.close!, last.close!];
      forecast.path.forEach((p) => rows.push({ date: p.date, mid: p.mid, band: [p.low, p.high] }));
    }
    return rows;
  }, [history, forecast]);

  return (
    <div className="h-72 w-full" role="img" aria-label={`Price chart for ${history.symbol}${forecast ? " with forecast band" : ""}`}>
      <ResponsiveContainer>
        <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid strokeOpacity={0.15} />
          <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={40} />
          <YAxis domain={["auto", "auto"]} tick={{ fontSize: 11 }} width={48} />
          <Tooltip formatter={(v) => (Array.isArray(v) ? v.map((n) => Number(n).toFixed(2)).join(" – ") : Number(v).toFixed(2))} />
          <Area dataKey="band" name="80% interval" stroke="none" fill="#f59e0b" fillOpacity={0.25} isAnimationActive={false} />
          <Line dataKey="close" name="Close" stroke="#3b82f6" dot={false} strokeWidth={2} isAnimationActive={false} />
          <Line dataKey="mid" name="Forecast" stroke="#f59e0b" strokeDasharray="5 4" dot={false} strokeWidth={2} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function StockPanel({ symbol }: { symbol: string }) {
  const [range, setRange] = useState<(typeof RANGES)[number]>("6mo");
  const [horizon, setHorizon] = useState(5);
  const sym = encodeURIComponent(symbol);
  const online = useOnline();
  const hist = useApi<History>(`/api/history/${sym}?range=${range}`);
  const fc = useApi<Forecast>(`/api/forecast/${sym}?horizon=${horizon}`, { cheap: false });

  const btn = (active: boolean) => `rounded px-2 py-1 text-xs font-medium ${active ? "bg-blue-700 text-white" : "bg-slate-200 text-slate-900 dark:bg-slate-800 dark:text-slate-100"}`;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-xl font-bold">{symbol}</h2>
        <div className="flex gap-1" role="group" aria-label="Chart range">{RANGES.map((r) => (<button key={r} className={btn(r === range)} aria-pressed={r === range} onClick={() => setRange(r)}>{r}</button>))}</div>
      </div>

      {hist.loading && !hist.data && <p role="status" className="text-sm text-slate-700 dark:text-slate-300">Loading prices…</p>}
      {hist.failure && !(hist.data && !online) && <ErrorNotice failure={hist.failure} onRetry={hist.retry} what="Price history" />}
      {hist.data && (
        <>
          <OutdatedLabel fromSaved={hist.fromSaved} savedAt={hist.savedAt} stale={hist.data.stale} delayed={hist.data.is_delayed}
            asOf={hist.data.data_as_of} refreshing={hist.loading} onRetry={hist.retry} />
          <Chart history={hist.data} forecast={fc.data} />
          <ChartTable history={hist.data} forecast={fc.data} />
          {fc.data && <ForecastNote />}
        </>
      )}

      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span id="horizon-label">Forecast horizon (trading days):</span>
        <div className="flex flex-wrap gap-1" role="group" aria-labelledby="horizon-label">
          {HORIZONS.map((h) => (<button key={h} className={btn(h === horizon)} aria-pressed={h === horizon} onClick={() => setHorizon(h)}>{h}d</button>))}
        </div>
        {horizon >= 20 && <span className="text-xs text-slate-600 dark:text-slate-300">Longer horizons mean wider ranges and fewer independent backtests.</span>}
      </div>

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
      <NewsPanel symbol={symbol} />
    </div>
  );
}
