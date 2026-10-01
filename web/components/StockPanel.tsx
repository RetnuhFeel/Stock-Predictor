"use client";
import { useMemo, useState } from "react";
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useApi } from "@/lib/api";
import type { Forecast, History } from "@/lib/types";

const RANGES = ["1mo", "3mo", "6mo", "1y", "2y"] as const;
const HORIZONS = [1, 5, 10, 20];
const pct = (x: number | null | undefined, d = 2) => (x == null ? "—" : `${(x * 100).toFixed(d)}%`);

type Row = { date: string; close?: number; mid?: number; band?: [number, number] };

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

function Backtest({ f }: { f: Forecast }) {
  const b = f.backtest;
  const rows: [string, string, string][] = [
    ["RMSE (log return)", pct(b.model.rmse), pct(b.naive_baseline.rmse)],
    ["MAE (log return)", pct(b.model.mae), pct(b.naive_baseline.mae)],
    ["Direction hit-rate", pct(b.model.directional_accuracy, 0), pct(b.naive_baseline.directional_accuracy, 0) + " (always up)"],
  ];
  return (
    <section className="rounded-md border border-slate-200 p-4 dark:border-slate-800" aria-label="Backtest accuracy">
      <h3 className="font-semibold">Backtest: model vs. naive baseline</h3>
      <p className={`mt-1 text-sm font-medium ${b.beats_baseline ? "text-green-600 dark:text-green-400" : "text-amber-700 dark:text-amber-300"}`}>
        {b.beats_baseline
          ? `Model error was ${(b.skill_vs_baseline * 100).toFixed(1)}% lower than "price stays flat" in the backtest — past results may not repeat.`
          : "The model did not meaningfully beat \"price stays flat\". Treat the forecast as noise."}
      </p>
      <div className="overflow-x-auto">
        <table className="mt-3 w-full text-sm">
          <thead><tr className="text-left text-slate-500"><th className="py-1 pr-2">Metric</th><th className="pr-2">Model</th><th>Naive baseline</th></tr></thead>
          <tbody>{rows.map(([m, a, c]) => (<tr key={m} className="border-t border-slate-100 dark:border-slate-800"><td className="py-1 pr-2">{m}</td><td className="pr-2">{a}</td><td>{c}</td></tr>))}</tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-slate-500">{b.method}; {b.n_test_points} out-of-sample points. {b.note}</p>
    </section>
  );
}

export function StockPanel({ symbol }: { symbol: string }) {
  const [range, setRange] = useState<(typeof RANGES)[number]>("6mo");
  const [horizon, setHorizon] = useState(5);
  const sym = encodeURIComponent(symbol);
  const hist = useApi<History>(`/api/history/${sym}?range=${range}`);
  const fc = useApi<Forecast>(`/api/forecast/${sym}?horizon=${horizon}`);

  const btn = (active: boolean) => `rounded px-2 py-1 text-xs ${active ? "bg-blue-600 text-white" : "bg-slate-200 dark:bg-slate-800"}`;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-xl font-bold">{symbol}</h2>
        <div className="flex gap-1" aria-label="Chart range">{RANGES.map((r) => (<button key={r} className={btn(r === range)} onClick={() => setRange(r)}>{r}</button>))}</div>
      </div>

      {hist.loading && <p className="text-sm text-slate-500">Loading prices…</p>}
      {hist.error && <p role="alert" className="text-sm text-red-600">⚠ {hist.error}</p>}
      {hist.data && <Chart history={hist.data} forecast={fc.data} />}

      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span>Forecast horizon:</span>
        {HORIZONS.map((h) => (<button key={h} className={btn(h === horizon)} onClick={() => setHorizon(h)}>{h}d</button>))}
      </div>

      {fc.loading && <p className="text-sm text-slate-500">Training model & running backtest… (can take a few seconds)</p>}
      {fc.error && <p role="alert" className="text-sm text-red-600">⚠ Forecast unavailable: {fc.error}</p>}
      {fc.data && (
        <>
          <section className="rounded-md border border-amber-300 bg-amber-50 p-4 dark:border-amber-800 dark:bg-amber-950/40">
            <p className="text-sm">
              Experimental {fc.data.horizon_days}-day estimate: <strong>${fc.data.predicted_price.toFixed(2)}</strong>{" "}
              ({fc.data.predicted_return >= 0 ? "+" : ""}{pct(fc.data.predicted_return)}) — 80% interval{" "}
              <strong>${fc.data.interval_80.low.toFixed(2)} – ${fc.data.interval_80.high.toFixed(2)}</strong>
            </p>
            <ul className="mt-2 list-disc pl-5 text-xs text-slate-600 dark:text-slate-300">{fc.data.notes.map((n) => (<li key={n}>{n}</li>))}</ul>
            <p className="mt-2 text-xs font-medium">{fc.data.disclaimer}</p>
          </section>
          <Backtest f={fc.data} />
        </>
      )}
    </div>
  );
}
