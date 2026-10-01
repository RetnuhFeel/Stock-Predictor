"use client";
import { useId, useMemo, useState } from "react";
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useApi } from "@/lib/api";
import type { Timeline, TimelineRange } from "@/lib/types";
import { ErrorNotice, OutdatedLabel } from "./Notices";

const RANGES: { id: TimelineRange; label: string; long: string }[] = [
  { id: "1mo", label: "1M", long: "1 month" },
  { id: "6mo", label: "6M", long: "6 months" },
  { id: "1y", label: "1Y", long: "1 year" },
  { id: "5y", label: "5Y", long: "5 years" },
];
const money = (x: number) => `$${x.toFixed(2)}`;
const spct = (x: number, d = 1) => `${x >= 0 ? "+" : ""}${x.toFixed(d)}%`;

export function PerformanceTimeline({ symbol }: { symbol: string }) {
  const [range, setRange] = useState<TimelineRange>("5y");
  const [normalized, setNormalized] = useState(false);
  const toggleId = useId();
  const api = useApi<Timeline>(`/api/timeline/${encodeURIComponent(symbol)}?range=${range}`, { cheap: false });
  const d = api.data;
  const rangeLong = RANGES.find((r) => r.id === (d?.range ?? range))?.long ?? range;

  const rows = useMemo(() => {
    if (!d) return [];
    const base = d.points[0]?.close ?? 1;
    return d.points.map((p) => ({ date: p.date, close: p.close, pct: (p.close / base - 1) * 100 }));
  }, [d]);

  const btn = (active: boolean) => `rounded px-2 py-1 text-xs font-medium ${active ? "bg-blue-700 text-white" : "bg-slate-200 text-slate-900 dark:bg-slate-800 dark:text-slate-100"}`;
  const s = d?.summary;
  const up = (s?.period_return_pct ?? 0) >= 0;
  const key = normalized ? "pct" : "close";
  return (
    <section aria-labelledby="timeline-title" className="space-y-3 rounded-md border border-slate-200 p-4 dark:border-slate-800">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id="timeline-title" className="font-semibold">Performance timeline <span className="font-normal text-slate-700 dark:text-slate-300">({symbol}, past {rangeLong})</span></h3>
        <div className="flex gap-1" role="group" aria-label="Timeline range">
          {RANGES.map((r) => (<button key={r.id} className={btn(r.id === range)} aria-pressed={r.id === range} aria-label={r.long} onClick={() => setRange(r.id)}>{r.label}</button>))}
        </div>
      </div>
      <label htmlFor={toggleId} className="flex items-center gap-2 text-sm">
        <input id={toggleId} type="checkbox" checked={normalized} onChange={(e) => setNormalized(e.target.checked)} className="h-4 w-4" />
        Show as % change from the start of the period
      </label>

      {api.loading && !d && <p role="status" className="text-sm text-slate-700 dark:text-slate-300">Loading {symbol} history…</p>}
      {api.failure && !d && <ErrorNotice failure={api.failure} onRetry={api.retry} what="Performance timeline" />}
      {d && s && (
        <>
          <OutdatedLabel fromSaved={api.fromSaved} savedAt={api.savedAt} stale={d.stale} delayed={d.is_delayed} asOf={d.data_as_of} refreshing={api.loading} onRetry={api.retry} />
          <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
            <div className="rounded border border-slate-200 p-2 dark:border-slate-800"><dt className="text-xs text-slate-700 dark:text-slate-300">Period return</dt>
              <dd className={`font-semibold ${up ? "text-green-800 dark:text-green-300" : "text-red-700 dark:text-red-300"}`}><span aria-hidden="true">{up ? "▲ " : "▼ "}</span>{spct(s.period_return_pct)}</dd>
              <dd className="text-xs text-slate-700 dark:text-slate-300">{money(s.start_close)} → {money(s.end_close)}</dd></div>
            <div className="rounded border border-slate-200 p-2 dark:border-slate-800"><dt className="text-xs text-slate-700 dark:text-slate-300">High</dt>
              <dd className="font-semibold">{money(s.high)}</dd><dd className="text-xs text-slate-700 dark:text-slate-300">{s.high_date}</dd></div>
            <div className="rounded border border-slate-200 p-2 dark:border-slate-800"><dt className="text-xs text-slate-700 dark:text-slate-300">Low</dt>
              <dd className="font-semibold">{money(s.low)}</dd><dd className="text-xs text-slate-700 dark:text-slate-300">{s.low_date}</dd></div>
            <div className="rounded border border-slate-200 p-2 dark:border-slate-800"><dt className="text-xs text-slate-700 dark:text-slate-300">Worst drop from a peak</dt>
              <dd className="font-semibold">{spct(s.max_drawdown_pct)}</dd><dd className="text-xs text-slate-700 dark:text-slate-300">within this period</dd></div>
          </dl>
          <div className="h-64 w-full" role="img" aria-label={`${symbol} ${normalized ? "percent change" : "closing price"} over the past ${rangeLong}: ${spct(s.period_return_pct)} from ${s.start_date} to ${s.end_date}, high ${money(s.high)} on ${s.high_date}, low ${money(s.low)} on ${s.low_date}. A table is available below.`}>
            <ResponsiveContainer>
              <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                <CartesianGrid strokeOpacity={0.15} />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={50} />
                <YAxis domain={["auto", "auto"]} tick={{ fontSize: 11 }} width={52} tickFormatter={(v) => (normalized ? `${Number(v).toFixed(0)}%` : `$${Number(v).toFixed(0)}`)} />
                <Tooltip formatter={(v) => (normalized ? `${Number(v).toFixed(1)}%` : `$${Number(v).toFixed(2)}`)} />
                <Area dataKey={key} name={normalized ? "% change" : "Close"} stroke="none" fill={up ? "#16a34a" : "#dc2626"} fillOpacity={0.08} isAnimationActive={false} />
                <Line dataKey={key} name={normalized ? "% change" : "Close"} stroke="#3b82f6" dot={false} strokeWidth={2} isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <p className="text-xs text-slate-700 dark:text-slate-300">
            {d.note} {d.downsampled && `The chart shows ${d.points.length} of ${d.n_points_total} trading days (extremes kept); the summary uses all of them.`}
          </p>
          <details className="text-sm">
            <summary className="cursor-pointer font-medium">View timeline data as a table</summary>
            <div className="mt-2 max-h-72 overflow-auto" tabIndex={0} role="region" aria-label={`Scrollable table of ${symbol} closing prices`}>
              <table className="w-full text-right text-sm">
                <caption className="sr-only">Closing prices for {symbol} over the past {rangeLong}{d.downsampled ? ", sampled" : ""}</caption>
                <thead><tr className="text-left"><th scope="col" className="py-1 pr-2">Date</th><th scope="col" className="pr-2 text-right">Close</th><th scope="col" className="text-right">Change since start</th></tr></thead>
                <tbody>
                  {[...rows].reverse().map((r) => (
                    <tr key={r.date} className="border-t border-slate-200 dark:border-slate-800"><th scope="row" className="py-0.5 pr-2 text-left font-normal">{r.date}</th><td className="pr-2">{money(r.close)}</td><td>{spct(r.pct)}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </>
      )}
    </section>
  );
}
