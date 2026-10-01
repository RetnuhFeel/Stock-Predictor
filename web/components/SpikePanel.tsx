"use client";
import { useId, useMemo, useState } from "react";
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useApi } from "@/lib/api";
import type { Spikes } from "@/lib/types";
import { ErrorNotice, OutdatedLabel } from "./Notices";

const pct = (x: number, d = 0) => `${(x * 100).toFixed(d)}%`;
const spct = (x: number, d = 1) => `${x >= 0 ? "+" : ""}${(x * 100).toFixed(d)}%`;
const money = (x: number) => `$${x.toFixed(2)}`;

function SpikeChart({ d }: { d: Spikes }) {
  const data = useMemo(() => {
    const first = { date: d.last_date, band: [d.last_close, d.last_close] as [number, number], median: d.last_close, up: d.last_close, down: d.last_close, s0: d.last_close };
    return [first, ...d.path.map((p, i) => ({ date: p.date, band: [p.band_low, p.band_high] as [number, number], median: p.median, up: p.spike_up, down: p.spike_down, s0: d.sample_paths[0]?.[i] }))];
  }, [d]);
  return (
    <div className="h-64 w-full" role="img" aria-label={`Spike scenario chart for ${d.symbol}: simulated median path, typical up and down spike levels and one example path, all inside the normal forecast band. Values are in the table below.`}>
      <ResponsiveContainer>
        <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid strokeOpacity={0.15} />
          <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={30} />
          <YAxis domain={["auto", "auto"]} tick={{ fontSize: 11 }} width={48} />
          <Tooltip formatter={(v) => (Array.isArray(v) ? v.map((n) => Number(n).toFixed(2)).join(" – ") : Number(v).toFixed(2))} />
          <Area dataKey="band" name="Normal 80% range" stroke="none" fill="#f59e0b" fillOpacity={0.2} isAnimationActive={false} />
          <Line dataKey="median" name="Simulated median" stroke="#7c3aed" dot={false} strokeWidth={2} isAnimationActive={false} />
          <Line dataKey="up" name="Typical spike up" stroke="#16a34a" strokeDasharray="2 3" dot={false} strokeWidth={2} isAnimationActive={false} />
          <Line dataKey="down" name="Typical spike down" stroke="#dc2626" strokeDasharray="8 3 2 3" dot={false} strokeWidth={2} isAnimationActive={false} />
          <Line dataKey="s0" name="Example simulated path" stroke="#64748b" dot={{ r: 2 }} strokeWidth={1} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function Legend() {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-700 dark:text-slate-300" aria-label="Chart legend">
      <li><span aria-hidden="true" className="mr-1 inline-block h-2 w-4 rounded-sm bg-amber-400/40" />Normal 80% range (shaded)</li>
      <li><span aria-hidden="true" className="mr-1 font-bold text-violet-700 dark:text-violet-300">━</span>Simulated median (solid)</li>
      <li><span aria-hidden="true" className="mr-1 font-bold text-green-700 dark:text-green-400">┈</span>Typical spike up (dotted)</li>
      <li><span aria-hidden="true" className="mr-1 font-bold text-red-700 dark:text-red-400">╌</span>Typical spike down (dash-dot)</li>
      <li><span aria-hidden="true" className="mr-1 font-bold text-slate-600 dark:text-slate-300">•</span>One example path (dots)</li>
    </ul>
  );
}

function Body({ d, api }: { d: Spikes; api: ReturnType<typeof useApi<Spikes>> }) {
  const bt = d.backtest;
  const c = d.calibration;
  return (
    <>
      <OutdatedLabel fromSaved={api.fromSaved} savedAt={api.savedAt} stale={d.stale} delayed={d.is_delayed} asOf={d.data_as_of} refreshing={api.loading} onRetry={api.retry} />
      <p className="text-xs text-slate-700 dark:text-slate-300">
        From {d.symbol}&apos;s own history: {c.n_jumps_up} sharp up days and {c.n_jumps_down} sharp down days (more than {d.model.jump_threshold_sigma}× a normal day, about ±{c.jump_threshold_pct.toFixed(1)}%) in the last {d.model.calibration_days} trading days.
        {c.few_jumps && <strong> Very few jumps: estimates are unreliable.</strong>}
      </p>
      <SpikeChart d={d} />
      <Legend />
      <p className="text-xs text-slate-700 dark:text-slate-300">
        Every simulated price is <strong>clamped</strong> inside the normal range. That happened on {pct(d.clamping.fraction_of_path_days_clamped)} of simulated path-days
        ({pct(d.clamping.fraction_of_paths_touching_band)} of paths touched an edge at least once), so this is a squeezed version of the simulation, not a bigger range.
      </p>
      <details className="text-sm">
        <summary className="cursor-pointer font-medium">Spike bands as a table</summary>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-right text-sm">
            <caption className="sr-only">Simulated spike scenario for {d.symbol}. Prices in dollars; probabilities are the chance, in the simulation, of a jump so far or of touching the edge of the normal range that day.</caption>
            <thead>
              <tr className="border-b border-slate-300 text-left dark:border-slate-700">
                <th scope="col" className="py-1 pr-2">Date</th><th scope="col" className="pr-2 text-right">Normal range</th><th scope="col" className="pr-2 text-right">Median</th>
                <th scope="col" className="pr-2 text-right">Spike up</th><th scope="col" className="pr-2 text-right">Spike down</th>
                <th scope="col" className="pr-2 text-right">Jump so far (up / down)</th><th scope="col" className="text-right">Touches top / bottom</th>
              </tr>
            </thead>
            <tbody>
              {d.path.map((p) => (
                <tr key={p.date} className="border-b border-slate-200 dark:border-slate-800">
                  <th scope="row" className="py-1 pr-2 text-left font-medium">{p.date}</th>
                  <td className="pr-2">{money(p.band_low)} – {money(p.band_high)}</td><td className="pr-2">{money(p.median)}</td>
                  <td className="pr-2">{money(p.spike_up)}</td><td className="pr-2">{money(p.spike_down)}</td>
                  <td className="pr-2">{pct(p.p_jump_up)} / {pct(p.p_jump_down)}</td><td>{pct(p.p_touch_high)} / {pct(p.p_touch_low)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>

      <div role="note" className="rounded border border-slate-300 bg-slate-50 p-3 text-sm dark:border-slate-700 dark:bg-slate-900">
        <p className="font-semibold">Did it help in past tests?</p>
        {bt.available ? (
          <>
            <p className="mt-1">{bt.summary}</p>
            <p className="mt-1 text-xs text-slate-700 dark:text-slate-300">
              Walk-forward backtest, {bt.n_origins} forecast dates{bt.small_sample ? " (small sample)" : ""}. How often the real {d.horizon_days}-day move landed inside each range (target {pct(bt.nominal_coverage)}):
              standard band {pct(bt.baseline.coverage)}, unclamped jump range {pct(bt.jump_unclamped.coverage)}, clamped spike range {pct(bt.spike_clamped.coverage)}.
              Accuracy of the median path vs. the standard forecast: {bt.point.verdict === "inconclusive" ? "no clear difference" : bt.point.verdict} (skill {spct(bt.point.skill_vs_baseline)}, 90% range {spct(bt.point.skill_ci_90[0])} to {spct(bt.point.skill_ci_90[1])}).
            </p>
          </>
        ) : (
          <p className="mt-1">{bt.reason} There is no evidence either way.</p>
        )}
      </div>
      <ul className="list-disc pl-5 text-xs text-slate-700 dark:text-slate-300">{d.notes.map((n) => (<li key={n}>{n}</li>))}</ul>
    </>
  );
}

export function SpikePanel({ symbol, horizon }: { symbol: string; horizon: number }) {
  const [on, setOn] = useState(false); // off by default: nothing is fetched and the main view stays uncluttered
  const toggleId = useId();
  const api = useApi<Spikes>(on ? `/api/spikes/${encodeURIComponent(symbol)}?horizon=${horizon}` : null, { cheap: false });
  const d = api.data;
  return (
    <section aria-labelledby="spike-title" className="space-y-3 rounded-md border border-dashed border-violet-400 p-4 dark:border-violet-700">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id="spike-title" className="font-semibold">
          Spike scenario <span className="font-normal text-slate-700 dark:text-slate-300">({horizon}-trading-day)</span>{" "}
          <span className="ml-1 rounded bg-violet-100 px-1.5 py-0.5 text-xs font-semibold text-violet-900 dark:bg-violet-900/50 dark:text-violet-100">Experimental</span>
        </h3>
        <label htmlFor={toggleId} className="flex items-center gap-2 text-sm">
          <input id={toggleId} type="checkbox" checked={on} onChange={(e) => setOn(e.target.checked)} className="h-4 w-4" />
          Show spike scenario
        </label>
      </div>
      <p className="text-xs text-slate-700 dark:text-slate-300">
        Adds <strong>simulated</strong> short-term jumps, up and down, to the normal forecast, based on how often and how hard this stock has jumped before. Spikes are
        <strong> simulated, not predicted</strong>: it can&apos;t know when one will happen or which way. Everything is kept inside the normal forecast range. Experimental, not financial advice.
      </p>
      {on && api.loading && !d && <p role="status" className="text-sm text-slate-700 dark:text-slate-300">Simulating spikes and backtesting… (can take several seconds)</p>}
      {on && api.failure && !d && <ErrorNotice failure={api.failure} onRetry={api.retry} what="Spike scenario" />}
      {on && d && <Body d={d} api={api} />}
    </section>
  );
}
