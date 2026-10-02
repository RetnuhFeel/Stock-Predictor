"use client";
import { useApi } from "@/lib/api";
import type { Volatility } from "@/lib/types";
import { ErrorNotice, OutdatedLabel } from "./Notices";

const pct = (x: number, d = 1) => `${x >= 0 ? "+" : ""}${(x * 100).toFixed(d)}%`;

function verdictText(v: Volatility): { icon: string; label: string; text: string } {
  if (v.verdict === "better")
    return { icon: "✔", label: "Better than a simple guess — in the past", text: "In past tests this risk estimate was closer to the realised size of moves than just assuming the next period looks like the last 21 days." };
  if (v.verdict === "inconclusive")
    return { icon: "≈", label: "Inconclusive", text: "The estimate was a little closer than the simple guess, but not by enough to rule out luck." };
  return { icon: "✖", label: "Not better than a simple guess", text: "In past tests this estimate was no closer than assuming the next period looks like the last 21 days." };
}

export function VolatilityPanel({ symbol, horizon }: { symbol: string; horizon: number }) {
  const vol = useApi<Volatility>(`/api/volatility/${encodeURIComponent(symbol)}?horizon=${horizon}`, { cheap: false });
  const d = vol.data;
  return (
    <section aria-labelledby="vol-title" className="space-y-3 rounded-md border border-slate-200 p-4 dark:border-slate-800">
      <h3 id="vol-title" className="font-semibold">Expected range / risk <span className="font-normal text-slate-700 dark:text-slate-300">({horizon}-trading-day)</span></h3>
      <p className="text-xs text-slate-700 dark:text-slate-300">How big a move to expect — <strong>not which direction</strong>. Size of moves is much more predictable than direction, but still not certain.</p>
      {vol.loading && !d && <p role="status" className="text-sm text-slate-700 dark:text-slate-300">Estimating risk…</p>}
      {vol.failure && !d && <ErrorNotice failure={vol.failure} onRetry={vol.retry} what="Risk estimate" />}
      {d && (() => {
        const v = verdictText(d);
        const tone = d.verdict === "better" ? "border-green-300 bg-green-50 text-green-950 dark:border-green-800 dark:bg-green-950/40 dark:text-green-100"
          : d.verdict === "inconclusive" ? "border-amber-300 bg-amber-50 text-amber-950 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-100"
          : "border-red-300 bg-red-50 text-red-950 dark:border-red-800 dark:bg-red-950/40 dark:text-red-100";
        return (
          <>
            <OutdatedLabel fromSaved={vol.fromSaved} savedAt={vol.savedAt} stale={d.stale} delayed={d.is_delayed} asOf={d.data_as_of} refreshing={vol.loading} onRetry={vol.retry} />
            <p className="text-sm">
              Typical move over {d.horizon_days} trading days: about <strong>±{d.risk_range.one_sigma_pct.toFixed(1)}%</strong>, i.e. roughly{" "}
              <strong>${d.risk_range.low.toFixed(2)} – ${d.risk_range.high.toFixed(2)}</strong> from ${d.last_close.toFixed(2)} (1-sigma range).
              Annualised volatility ≈ <strong>{(d.annualized_vol * 100).toFixed(0)}%</strong>.
            </p>
            <p className="text-xs">
              In the backtest, the actual move stayed inside this kind of range <strong>{(d.risk_range.backtest_coverage * 100).toFixed(0)}%</strong> of the time (about {(d.risk_range.nominal_coverage * 100).toFixed(0)}% is the textbook target).
              Moves outside it happen, and big ones cluster in stressful markets.
            </p>
            <div className={`rounded border p-3 text-sm ${tone}`} role="note">
              <p className="font-semibold"><span aria-hidden="true">{v.icon} </span>{v.label}</p>
              <p className="mt-1">{v.text} (skill {pct(d.skill_vs_naive)}, 90% range {pct(d.skill_ci_90[0])} to {pct(d.skill_ci_90[1])}; backtest, {d.n_test_points} test days, about {d.n_independent_tests} independent{d.small_sample ? " — small sample" : ""}.)</p>
            </div>
            {d.garch?.available && d.garch.vs_headline && (
              <p className="text-xs" data-testid="garch-alt">
                <strong>Alternative view (GJR-GARCH):</strong> about ±{(d.garch.one_sigma_pct ?? 0).toFixed(1)}% over {d.horizon_days} trading days
                (annualised ≈ {((d.garch.annualized_vol ?? 0) * 100).toFixed(0)}%), versus ±{d.risk_range.one_sigma_pct.toFixed(1)}% for the headline estimate above.
                In the backtest it was{" "}
                {d.garch.vs_headline.verdict === "better" ? "closer than" : d.garch.vs_headline.verdict === "inconclusive" ? "not clearly different from" : "no closer than"}{" "}
                the headline (error change {pct(d.garch.vs_headline.skill)}, 90% range {pct(d.garch.vs_headline.skill_ci_90[0])} to {pct(d.garch.vs_headline.skill_ci_90[1])}).
                The headline stays EWMA because it was chosen before looking at results.
              </p>
            )}
            <details className="text-sm">
              <summary className="cursor-pointer font-medium">Compare volatility models</summary>
              <div className="mt-2 overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <caption className="sr-only">Volatility models for {d.symbol}, backtested against recent realised volatility</caption>
                  <thead><tr className="border-b border-slate-300 dark:border-slate-700"><th scope="col" className="py-1 pr-2">Model</th><th scope="col" className="pr-2 text-right">Annualised</th><th scope="col" className="pr-2 text-right">Skill vs. recent vol</th><th scope="col" className="pr-2 text-right">Typical error</th><th scope="col" className="text-right">Vs. EWMA</th></tr></thead>
                  <tbody>
                    {d.models.map((m) => (
                      <tr key={m.model} className="border-b border-slate-200 dark:border-slate-800">
                        <th scope="row" className="py-1 pr-2 text-left font-medium">{m.label}{m.model === d.headline_model ? " (shown above)" : ""}</th>
                        <td className="pr-2 text-right">{(m.annualized_vol * 100).toFixed(0)}%</td>
                        <td className="pr-2 text-right">{m.verdict === "baseline" ? "baseline" : `${pct(m.skill_vs_naive)} (${m.verdict === "better" ? "better" : m.verdict === "inconclusive" ? "inconclusive" : "not better"})`}</td>
                        <td className="pr-2 text-right">{m.typical_error_pct.toFixed(0)}%</td>
                        <td className="text-right">{m.vs_headline ? `${pct(m.vs_headline.skill)} (${m.vs_headline.verdict === "better" ? "better" : m.vs_headline.verdict === "inconclusive" ? "inconclusive" : "not better"})` : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-1 text-xs text-slate-700 dark:text-slate-300">The headline model was chosen in advance, not by looking at these results.</p>
            </details>
            <ul className="list-disc pl-5 text-xs text-slate-700 dark:text-slate-300">{d.notes.map((n) => (<li key={n}>{n}</li>))}</ul>
          </>
        );
      })()}
    </section>
  );
}
