"use client";
import Link from "next/link";
import { useApi } from "@/lib/api";
import type { ModelComparison as MC, ModelRow } from "@/lib/types";
import { ErrorNotice, OutdatedLabel } from "./Notices";

const pct = (x: number, d = 1) => `${x >= 0 ? "+" : ""}${(x * 100).toFixed(d)}%`;
const V: Record<ModelRow["verdict"], { icon: string; label: string; tone: string }> = {
  baseline: { icon: "●", label: "The bar to beat", tone: "text-slate-800 dark:text-slate-200" },
  better: { icon: "✔", label: "Better (in the past)", tone: "text-green-900 dark:text-green-300" },
  inconclusive: { icon: "≈", label: "Inconclusive", tone: "text-amber-900 dark:text-amber-300" },
  not_better: { icon: "✖", label: "Not better", tone: "text-red-900 dark:text-red-300" },
};

const riskVerdict: Record<string, string> = {
  baseline: "The bar to beat",
  better: "Better (in the past)",
  inconclusive: "Inconclusive",
  not_better: "Not better",
};

function RiskModels({ d }: { d: NonNullable<MC["risk_models"]> }) {
  const g = d.garch;
  return (
    <div className="space-y-1">
      <h4 className="text-sm font-semibold">Risk models <span className="font-normal text-slate-700 dark:text-slate-300">(how big the moves are, not which way)</span></h4>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <caption className="mb-1 text-left text-xs text-slate-700 dark:text-slate-300">
            Same walk-forward test, but judged on how close each estimate of volatility was to the size of moves that followed. Skill is measured against &ldquo;the next period is as jumpy as the last 21 days&rdquo;.
            The headline risk estimate (EWMA) was fixed in advance; the others are alternatives.
          </caption>
          <thead>
            <tr className="border-b border-slate-300 dark:border-slate-700">
              <th scope="col" className="py-1 pr-2">Model</th>
              <th scope="col" className="pr-2">Result</th>
              <th scope="col" className="pr-2 text-right">Skill vs. recent vol</th>
              <th scope="col" className="text-right">Compared with EWMA</th>
            </tr>
          </thead>
          <tbody>
            {d.models.map((m) => (
              <tr key={m.model} className="border-b border-slate-200 dark:border-slate-800">
                <th scope="row" className="py-1 pr-2 text-left font-medium">
                  {m.label}{m.model === d.headline_model ? " (headline)" : ""}
                  <span className="block text-xs font-normal text-slate-700 dark:text-slate-300">{m.description}</span>
                </th>
                <td className="pr-2">{riskVerdict[m.verdict]}</td>
                <td className="pr-2 text-right">{m.verdict === "baseline" ? "—" : `${pct(m.skill_vs_naive)} (${pct(m.skill_ci_90[0])} to ${pct(m.skill_ci_90[1])})`}</td>
                <td className="text-right">
                  {m.vs_headline ? `${pct(m.vs_headline.skill)}: ${riskVerdict[m.vs_headline.verdict].toLowerCase()}` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!g.available && <p className="text-xs text-slate-700 dark:text-slate-300">GJR-GARCH was not run for this ticker: {g.reason ?? "not enough history"}.</p>}
      {g.available && g.params && (
        <p className="text-xs text-slate-700 dark:text-slate-300">
          GJR-GARCH lets volatility drift back toward its long-run level (here about {(g.params.long_run_annual_vol * 100).toFixed(0)}% a year; shocks fade with a half-life of{" "}
          {g.params.half_life_days == null ? "n/a" : `${g.params.half_life_days.toFixed(0)} days`}) and, {g.params.asymmetric ? "for this ticker, reacts more to down days than up days" : "for this ticker, shows little extra reaction to down days"}.
          It is an alternative view, not a replacement: being better in a backtest is not a promise.
        </p>
      )}
    </div>
  );
}

export function ModelComparison({ symbol, horizon }: { symbol: string; horizon: number }) {
  const mc = useApi<MC>(`/api/compare-models/${encodeURIComponent(symbol)}?horizon=${horizon}`, { cheap: false });
  const d = mc.data;
  return (
    <section aria-labelledby={`mc-title-${symbol}`} className="space-y-3 rounded-md border border-slate-200 p-4 dark:border-slate-800">
      <h3 id={`mc-title-${symbol}`} className="font-semibold">
        Model comparison <span className="font-normal text-slate-700 dark:text-slate-300">({symbol}, {horizon}-trading-day forecasts)</span>
      </h3>
      <p className="text-xs text-slate-700 dark:text-slate-300">
        Several simple models, all tested the same way on past data they hadn&apos;t seen, against &ldquo;the price stays flat&rdquo;. Backtest results only — not live results.
      </p>
      {mc.loading && !d && <p role="status" className="text-sm text-slate-700 dark:text-slate-300">Comparing models…</p>}
      {mc.failure && !d && <ErrorNotice failure={mc.failure} onRetry={mc.retry} what="Model comparison" />}
      {d && (
        <>
          <OutdatedLabel fromSaved={mc.fromSaved} savedAt={mc.savedAt} stale={d.stale} delayed={d.is_delayed} asOf={d.data_as_of} refreshing={mc.loading} onRetry={mc.retry} />
          <p role="status" className={`rounded border p-2 text-sm ${d.any_beats_naive ? "border-amber-400 bg-amber-50 text-amber-950 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-100" : "border-red-300 bg-red-50 text-red-950 dark:border-red-800 dark:bg-red-950/40 dark:text-red-100"}`}>
            {d.any_beats_naive ? (
              <>
                <strong>At least one model beat &ldquo;price stays flat&rdquo; in this backtest.</strong> Be careful: with {d.n_candidates} models tried, one can win by luck.
                That is why we keep a separate, live <Link href="/track-record" className="underline">track record</Link>.
              </>
            ) : (
              <>
                <strong>No model clearly beat &ldquo;price stays flat&rdquo;</strong> over this period. That is the normal outcome for short-horizon stock forecasts.
              </>
            )}
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <caption className="mb-1 text-left text-xs text-slate-700 dark:text-slate-300">
                {d.n_test_points} test days (about {d.n_independent_tests} independent {d.horizon_days}-day periods{d.small_sample ? ", a small sample" : ""}); {d.embargo_days}-day gap between training and test data.
                Skill: how much lower the typical error is than &ldquo;flat&rdquo; (negative = worse).
              </caption>
              <thead>
                <tr className="border-b border-slate-300 dark:border-slate-700">
                  <th scope="col" className="py-1 pr-2">Model</th>
                  <th scope="col" className="pr-2">Result</th>
                  <th scope="col" className="pr-2 text-right">Skill vs. flat</th>
                  <th scope="col" className="pr-2 text-right">90% range</th>
                  <th scope="col" className="text-right">Right direction</th>
                </tr>
              </thead>
              <tbody>
                {d.models.map((m) => {
                  const v = V[m.verdict];
                  const base = m.verdict === "baseline";
                  return (
                    <tr key={m.model} className="border-b border-slate-200 dark:border-slate-800">
                      <th scope="row" className="py-1 pr-2 text-left font-medium">
                        {m.label}
                        <span className="block text-xs font-normal text-slate-700 dark:text-slate-300">{m.description}</span>
                      </th>
                      <td className={`pr-2 font-medium ${v.tone}`}><span aria-hidden="true">{v.icon} </span>{v.label}</td>
                      <td className="pr-2 text-right">{base ? "—" : pct(m.skill_vs_naive)}</td>
                      <td className="pr-2 text-right">{base ? "—" : `${pct(m.skill_ci_90[0])} to ${pct(m.skill_ci_90[1])}`}</td>
                      <td className="text-right">{m.hit_rate == null ? "—" : `${(m.hit_rate * 100).toFixed(0)}%`}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {d.risk_models && <RiskModels d={d.risk_models} />}
          <p className="text-xs text-slate-700 dark:text-slate-300">
            &ldquo;Better&rdquo; needs the whole 90% range above zero. Prices rose in {(d.up_rate * 100).toFixed(0)}% of test periods, so a model that just guesses &ldquo;up&rdquo; scores that on direction. {d.note}
          </p>
        </>
      )}
    </section>
  );
}
