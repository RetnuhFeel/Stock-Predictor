"use client";
import { useMemo, useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useApi } from "@/lib/api";
import type { Compare } from "@/lib/types";
import { ErrorNotice, OutdatedLabel } from "./Notices";

const RANGES = ["1mo", "3mo", "6mo", "1y", "2y", "5y"] as const;
const MAX = 5;
// Colour AND dash pattern AND marker letter differ per series, so the chart never relies on colour alone.
const STYLE = [
  { color: "#2563eb", dash: "", mark: "A" },
  { color: "#d97706", dash: "6 3", mark: "B" },
  { color: "#059669", dash: "2 3", mark: "C" },
  { color: "#9333ea", dash: "10 3 2 3", mark: "D" },
  { color: "#dc2626", dash: "1 4", mark: "E" },
];
const sgn = (n: number) => `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;

export function ComparePanel({ watchlist }: { watchlist: string[] }) {
  const [range, setRange] = useState<(typeof RANGES)[number]>("6mo");
  const [picked, setPicked] = useState<string[] | null>(null);
  const selected = (picked ?? watchlist.slice(0, 3)).filter((s) => watchlist.includes(s)).slice(0, MAX);
  const path = selected.length >= 2 ? `/api/compare?symbols=${selected.map(encodeURIComponent).join(",")}&range=${range}` : null;
  const cmp = useApi<Compare>(path, { cheap: false });

  function toggle(s: string) {
    const next = selected.includes(s) ? selected.filter((x) => x !== s) : [...selected, s];
    if (next.length <= MAX) setPicked(next);
  }

  const rows = useMemo(
    () => (cmp.data ? cmp.data.dates.map((d, i) => ({ date: d, ...Object.fromEntries(cmp.data!.series.map((s) => [s.symbol, s.points[i]])) })) : []),
    [cmp.data],
  );
  const btn = (active: boolean) => `rounded px-2 py-1 text-xs font-medium ${active ? "bg-blue-700 text-white" : "bg-slate-200 text-slate-900 dark:bg-slate-800 dark:text-slate-100"}`;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-xl font-bold">Compare symbols</h2>
        <div className="flex gap-1" role="group" aria-label="Compare range">
          {RANGES.map((r) => (<button key={r} className={btn(r === range)} aria-pressed={r === range} onClick={() => setRange(r)}>{r}</button>))}
        </div>
      </div>

      <fieldset className="rounded-md border border-slate-300 p-3 dark:border-slate-700">
        <legend className="px-1 text-sm font-medium">Pick 2 to {MAX} symbols from your watchlist</legend>
        <div className="flex flex-wrap gap-3">
          {watchlist.map((s) => {
            const on = selected.includes(s);
            return (
              <label key={s} className="flex items-center gap-1 text-sm">
                <input type="checkbox" checked={on} disabled={!on && selected.length >= MAX} onChange={() => toggle(s)} className="h-4 w-4" />
                {s}
              </label>
            );
          })}
        </div>
        {watchlist.length < 2 && <p className="mt-2 text-sm">Add at least two symbols to your watchlist to compare them.</p>}
      </fieldset>

      {selected.length >= 2 && cmp.loading && !cmp.data && <p role="status" className="text-sm text-slate-600 dark:text-slate-300">Loading comparison…</p>}
      {cmp.failure && <ErrorNotice failure={cmp.failure} onRetry={cmp.retry} what="Comparison" />}
      {cmp.data && (
        <>
          <OutdatedLabel fromSaved={cmp.fromSaved} savedAt={cmp.savedAt} stale={cmp.data.stale} delayed={cmp.data.is_delayed} asOf={cmp.data.data_as_of} refreshing={cmp.loading} onRetry={cmp.retry} />
          {cmp.data.failed.length > 0 && (
            <p role="status" className="rounded border border-amber-400 bg-amber-50 px-2 py-1 text-xs text-amber-950 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-100">
              <span aria-hidden="true">⚠ </span>Couldn&apos;t load: {cmp.data.failed.map((f) => f.symbol).join(", ")}. Showing the rest.
            </p>
          )}
          <div className="h-72 w-full" role="img" aria-label={`Percent change since ${cmp.data.dates[0]}: ${cmp.data.series.map((s) => `${s.symbol} ${sgn(s.change_percent)}`).join(", ")}. A data table follows.`}>
            <ResponsiveContainer>
              <LineChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                <CartesianGrid strokeOpacity={0.2} />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={40} />
                <YAxis tick={{ fontSize: 11 }} width={48} tickFormatter={(v) => `${v}%`} />
                <ReferenceLine y={0} stroke="#64748b" strokeDasharray="2 2" />
                <Tooltip formatter={(v) => `${Number(v).toFixed(2)}%`} />
                {cmp.data.series.map((s, i) => (
                  <Line key={s.symbol} dataKey={s.symbol} stroke={STYLE[i % 5].color} strokeDasharray={STYLE[i % 5].dash} strokeWidth={2} dot={false} isAnimationActive={false} />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>

          <table className="w-full text-sm">
            <caption className="mb-1 text-left text-xs text-slate-600 dark:text-slate-300">{cmp.data.base} From {cmp.data.dates[0]} to {cmp.data.dates[cmp.data.dates.length - 1]}.</caption>
            <thead><tr className="text-left text-slate-600 dark:text-slate-300"><th scope="col" className="py-1">Line</th><th scope="col">Symbol</th><th scope="col" className="text-right">Start</th><th scope="col" className="text-right">End</th><th scope="col" className="text-right">Change</th></tr></thead>
            <tbody>
              {cmp.data.series.map((s, i) => (
                <tr key={s.symbol} className="border-t border-slate-200 dark:border-slate-800">
                  <td className="py-1">
                    <svg width="44" height="12" aria-hidden="true"><line x1="0" y1="6" x2="44" y2="6" stroke={STYLE[i % 5].color} strokeWidth="2" strokeDasharray={STYLE[i % 5].dash} /></svg>
                    <span className="sr-only">Line {i + 1}</span>
                  </td>
                  <th scope="row" className="text-left font-semibold">{s.symbol}</th>
                  <td className="text-right">${s.start_price.toFixed(2)}</td>
                  <td className="text-right">${s.end_price.toFixed(2)}</td>
                  <td className="text-right font-semibold">{s.change_percent >= 0 ? "▲" : "▼"} {sgn(s.change_percent)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-xs text-slate-600 dark:text-slate-300">Past performance does not predict future results. Experimental, not financial advice.</p>
        </>
      )}
    </div>
  );
}
