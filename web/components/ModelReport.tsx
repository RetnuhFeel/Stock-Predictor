"use client";
import { useApi } from "@/lib/api";
import type { ModelReport as Report, ReportRow } from "@/lib/types";
import { ErrorNotice, OutdatedLabel } from "./Notices";

const pct = (x: number, d = 1) => `${x >= 0 ? "+" : ""}${(x * 100).toFixed(d)}%`;
const VERDICT: Record<ReportRow["verdict"], { icon: string; label: string; tone: string }> = {
  better: { icon: "✔", label: "Better than guessing (in the past)", tone: "text-green-900 dark:text-green-300" },
  inconclusive: { icon: "≈", label: "Inconclusive", tone: "text-amber-900 dark:text-amber-300" },
  not_better: { icon: "✖", label: "Not better than guessing", tone: "text-red-900 dark:text-red-300" },
};

export function ModelReport() {
  const rep = useApi<Report>("/api/model-report", { cheap: false });
  const d = rep.data;
  return (
    <section aria-labelledby="report-title" className="space-y-3">
      <h2 id="report-title">Live report card</h2>
      <p>
        Computed by the API from real price history for a fixed set of well-known tickers, using the same code and settings as the
        forecast feature. It refreshes about every six hours.
      </p>
      {rep.loading && !d && <p role="status">Running backtests… the first load can take up to a minute.</p>}
      {rep.failure && !d && <ErrorNotice failure={rep.failure} onRetry={rep.retry} what="Report card" />}
      {d && (
        <>
          <OutdatedLabel fromSaved={rep.fromSaved} savedAt={rep.savedAt} stale={d.stale} delayed={d.is_delayed} asOf={d.data_as_of} refreshing={rep.loading} onRetry={rep.retry} />
          <p className="rounded border border-slate-300 p-3 dark:border-slate-700" role="status">
            <strong>Result:</strong> out of {d.summary.total} tickers, the model was clearly better than guessing for{" "}
            <strong>{d.summary.better}</strong>, inconclusive for <strong>{d.summary.inconclusive}</strong>, and not better for{" "}
            <strong>{d.summary.not_better}</strong> (horizon: {d.horizon_days} trading days; data as of {d.data_as_of}).
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <caption className="mb-1 text-left text-xs text-slate-700 dark:text-slate-300">
                {d.horizon_days}-day backtest per ticker. Skill = how much lower the model&apos;s typical error was than &ldquo;price stays flat&rdquo; (negative = worse).
              </caption>
              <thead>
                <tr className="border-b border-slate-300 dark:border-slate-700">
                  <th scope="col" className="py-1 pr-2">Ticker</th>
                  <th scope="col" className="pr-2">Verdict</th>
                  <th scope="col" className="pr-2 text-right">Skill vs. flat</th>
                  <th scope="col" className="pr-2 text-right">90% range</th>
                  <th scope="col" className="pr-2 text-right">Right direction</th>
                  <th scope="col" className="pr-2 text-right">&ldquo;Always up&rdquo;</th>
                  <th scope="col" className="text-right">Tests (independent)</th>
                </tr>
              </thead>
              <tbody>
                {d.rows.map((r) => {
                  const v = VERDICT[r.verdict];
                  return (
                    <tr key={r.symbol} className="border-b border-slate-200 dark:border-slate-800">
                      <th scope="row" className="py-1 pr-2 font-semibold">{r.symbol}</th>
                      <td className={`pr-2 font-medium ${v.tone}`}><span aria-hidden="true">{v.icon} </span>{v.label}{r.small_sample ? " (small sample)" : ""}</td>
                      <td className="pr-2 text-right">{pct(r.skill_vs_baseline)}</td>
                      <td className="pr-2 text-right">{pct(r.skill_ci_90[0])} to {pct(r.skill_ci_90[1])}</td>
                      <td className="pr-2 text-right">{r.hit_rate == null ? "—" : `${(r.hit_rate * 100).toFixed(0)}%`}</td>
                      <td className="pr-2 text-right">{(r.up_rate * 100).toFixed(0)}%</td>
                      <td className="text-right">{r.n_test_points} ({r.n_independent_tests})</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {d.failed.length > 0 && (
            <p role="status" className="text-xs">Couldn&apos;t compute: {d.failed.map((f) => f.symbol).join(", ")}. Showing the rest.</p>
          )}
          <p className="text-xs"><strong>How to read this:</strong> &ldquo;Better&rdquo; is only claimed when the whole 90% range is above zero. Test windows overlap, so the number of
            <em> independent</em> tests is roughly tests ÷ horizon. A model that is right about direction 55% of the time while stocks rose 56% of the time has no edge.</p>
          <p className="text-xs font-medium">{d.disclaimer}</p>
        </>
      )}
    </section>
  );
}
