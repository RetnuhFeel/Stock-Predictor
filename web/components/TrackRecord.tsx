"use client";
import { useState } from "react";
import { useApi } from "@/lib/api";
import type { LogRow, PredictionLog } from "@/lib/types";
import { ErrorNotice, OutdatedLabel } from "./Notices";

const PAGE = 25;
const pct = (x: number, d = 1) => `${x >= 0 ? "+" : ""}${(x * 100).toFixed(d)}%`;
const money = (x: number) => `$${x.toFixed(2)}`;
const day = (iso: string) => iso.slice(0, 10);
const longDay = (iso: string) =>
  new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { weekday: "short", year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });

function Outcome({ r }: { r: LogRow }) {
  if (r.status === "pending") return <span>Waiting (resolves after {r.horizon_days} trading days)</span>;
  return (
    <span>
      {money(r.realized_close ?? 0)} ({pct(Math.expm1(r.realized_return ?? 0))}) ·{" "}
      <span className={r.direction_correct ? "text-green-900 dark:text-green-300" : "text-red-900 dark:text-red-300"}>{r.direction_correct ? "✔ direction right" : "✖ direction wrong"}</span> ·{" "}
      {r.in_interval ? "inside range" : "outside range"}
    </span>
  );
}

export function TrackRecord() {
  const [offset, setOffset] = useState(0);
  const log = useApi<PredictionLog>(`/api/prediction-log?limit=${PAGE}&offset=${offset}`, { cheap: false });
  const d = log.data;
  const sc = d?.scorecard;
  return (
    <div className="space-y-4">
      <section aria-labelledby="prereg" className="space-y-2">
        <h2 id="prereg">Pre-registered, not edited after the fact</h2>
        <p>
          Once a day after the US market closes (with a backup run early the next morning, before the market opens), a scheduled job records the model&apos;s {d?.horizon_days ?? 5}-trading-day forecast for a fixed list of tickers
          {d ? ` (${d.symbols.join(", ")})` : ""}. Each record is stored <strong>before</strong> the outcome exists, and is never changed afterwards: only the realised
          result is filled in once the horizon has passed. Each entry carries a hash chained to the one before it, so a quiet edit of an old row would break the
          chain{d && <> (chain check right now: <strong>{d.chain_ok ? "intact" : "BROKEN"}</strong>
          {d.outcomes_ok !== undefined && <>; outcome seals: <strong>{d.outcomes_ok ? "intact" : "BROKEN"}</strong>{d.unsealed_resolved ? `, ${d.unsealed_resolved} older result${d.unsealed_resolved === 1 ? "" : "s"} predate seals` : ""}</>})</>}.
        </p>
        <p className="text-xs">
          Limits: this is tamper-<em>evidence</em>, not proof — whoever runs the database could rebuild it. Nothing is logged for visitors; only this fixed ticker list is recorded.
        </p>
        <p role="note" className="rounded border border-amber-400 bg-amber-50 p-2 text-sm text-amber-950 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-100">
          <strong>Data-loss caveat:</strong>{" "}
          {d?.storage.durable
            ? "This log is stored in an external database, so it should survive redeploys."
            : "On the free hosting tier this log is kept on a temporary disk, so it is erased whenever the server redeploys or restarts, and the record then starts over. Treat a short history as incomplete, not as a full record."}
        </p>
        <p className="text-xs"><strong>Live results only.</strong> Numbers on this page come from real forecasts that were recorded before the outcome. They are separate from the backtests shown elsewhere in the app, which look at the past.</p>
      </section>

      {log.loading && !d && <p role="status">Loading the track record…</p>}
      {log.failure && !d && <ErrorNotice failure={log.failure} onRetry={log.retry} what="Track record" />}
      {d && sc && (
        <>
          <OutdatedLabel fromSaved={log.fromSaved} savedAt={log.savedAt} stale={d.stale} refreshing={log.loading} onRetry={log.retry} />
          <section aria-labelledby="scorecard" className="space-y-2">
            <h2 id="scorecard">Live scorecard</h2>
            {sc.verdict === "no_data" && (
              <p role="status" className="rounded border border-slate-300 p-3 dark:border-slate-700">
                <strong>No resolved predictions yet.</strong> {d.total === 0 ? "Nothing has been recorded yet" : `${sc.n_pending} predictions are waiting for their ${d.horizon_days}-day horizon to pass`}. Check back after a few weeks;
                a fair verdict needs at least {sc.min_for_verdict} independent periods, which takes months.
              </p>
            )}
            {sc.verdict !== "no_data" && (
              <>
                <p role="status" className="rounded border border-slate-300 p-3 dark:border-slate-700">
                  {sc.verdict === "too_early" && <><strong>Too early to say.</strong> Only about {sc.n_independent} independent {sc.horizon_days}-day periods so far; we don&apos;t give a verdict below {sc.min_for_verdict}. The numbers below are shown for transparency, not as evidence either way.</>}
                  {sc.verdict === "better" && <><strong>Better than &ldquo;price stays flat&rdquo; so far</strong> (90% range entirely above zero). Keep watching: this can change.</>}
                  {sc.verdict === "inconclusive" && <><strong>Inconclusive:</strong> slightly better than &ldquo;flat&rdquo;, but within the range of luck.</>}
                  {sc.verdict === "not_better" && <><strong>Not better than &ldquo;price stays flat&rdquo;</strong> so far.</>}
                </p>
                <table className="w-full text-left text-sm">
                  <caption className="sr-only">Live scorecard over {sc.n_resolved} resolved predictions</caption>
                  <tbody>
                    <tr className="border-b border-slate-200 dark:border-slate-800"><th scope="row" className="py-1 pr-2 font-medium">Resolved / waiting</th><td>{sc.n_resolved} / {sc.n_pending} ({sc.n_dates} forecast dates, about {sc.n_independent} independent)</td></tr>
                    <tr className="border-b border-slate-200 dark:border-slate-800"><th scope="row" className="py-1 pr-2 font-medium">Skill vs. &ldquo;flat&rdquo;</th><td>{pct(sc.skill_vs_naive ?? 0)}{sc.skill_ci_90 ? ` (90% range ${pct(sc.skill_ci_90[0])} to ${pct(sc.skill_ci_90[1])})` : " (no range yet: too few periods)"}</td></tr>
                    <tr className="border-b border-slate-200 dark:border-slate-800"><th scope="row" className="py-1 pr-2 font-medium">Right direction</th><td>{pct(sc.hit_rate ?? 0, 0).replace("+", "")} (prices rose in {pct(sc.up_rate ?? 0, 0).replace("+", "")} of cases)</td></tr>
                    <tr><th scope="row" className="py-1 pr-2 font-medium">80% range contained the result</th><td>{pct(sc.interval_coverage ?? 0, 0).replace("+", "")} (target {pct(sc.interval_nominal ?? 0.8, 0).replace("+", "")})</td></tr>
                  </tbody>
                </table>
              </>
            )}
          </section>

          {(d.missed_sessions?.length ?? 0) > 0 && (
            <section aria-labelledby="missed" className="space-y-2">
              <h2 id="missed">Missed days</h2>
              <p className="text-sm">
                Days with no recorded predictions are listed here rather than hidden. They are not filled in afterwards: a forecast written once its outcome period has
                started would use hindsight.
              </p>
              <ul className="list-disc space-y-1 pl-5 text-sm">
                {d.missed_sessions!.map((m) => (
                  <li key={m.base_date}>
                    <strong>{longDay(m.base_date)}</strong> ({m.symbols.length === d.symbols.length ? "all tickers" : m.symbols.join(", ")}): {m.note}
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section aria-labelledby="log" className="space-y-2">
            <h2 id="log">Prediction log</h2>
            {d.items.length === 0 ? (
              <p>The log is empty. Predictions appear here after the first scheduled run.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <caption className="sr-only">Recorded predictions, newest first</caption>
                  <thead><tr className="border-b border-slate-300 dark:border-slate-700">
                    <th scope="col" className="py-1 pr-2">Ticker</th><th scope="col" className="pr-2">Recorded (UTC)</th><th scope="col" className="pr-2 text-right">Price then</th>
                    <th scope="col" className="pr-2 text-right">Predicted move</th><th scope="col" className="pr-2 text-right">80% range</th><th scope="col">Outcome</th></tr></thead>
                  <tbody>
                    {d.items.map((r) => (
                      <tr key={r.id} className="border-b border-slate-200 align-top dark:border-slate-800">
                        <th scope="row" className="py-1 pr-2 font-semibold">{r.symbol}</th>
                        <td className="pr-2">{day(r.made_at)}<span className="block text-xs text-slate-700 dark:text-slate-300">data as of {r.base_date}</span></td>
                        <td className="pr-2 text-right">{money(r.base_close)}</td>
                        <td className="pr-2 text-right">{pct(Math.expm1(r.predicted_return))}</td>
                        <td className="pr-2 text-right">{money(r.interval_low)} – {money(r.interval_high)}</td>
                        <td><Outcome r={r} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {d.total > PAGE && (
              <nav aria-label="Log pages" className="flex items-center gap-3 text-sm">
                <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))} className="rounded border border-slate-400 px-3 py-1 disabled:opacity-50 dark:border-slate-600">Newer</button>
                <span>{offset + 1}–{Math.min(offset + PAGE, d.total)} of {d.total}</span>
                <button disabled={offset + PAGE >= d.total} onClick={() => setOffset(offset + PAGE)} className="rounded border border-slate-400 px-3 py-1 disabled:opacity-50 dark:border-slate-600">Older</button>
              </nav>
            )}
          </section>
          <p className="text-xs font-medium">{d.disclaimer}</p>
        </>
      )}
    </div>
  );
}
