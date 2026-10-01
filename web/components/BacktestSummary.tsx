import type { Backtest } from "@/lib/types";

const pct = (x: number, d = 0) => `${(x * 100).toFixed(d)}%`;

type Verdict = { icon: string; label: string; tone: string; text: string };

function verdict(b: Backtest): Verdict {
  const ci = b.skill_ci_90;
  const sig = b.beats_baseline;
  if (sig) {
    return {
      icon: "✔", label: "Better than guessing — in the past",
      tone: "border-green-300 bg-green-50 text-green-900 dark:border-green-800 dark:bg-green-950/40 dark:text-green-200",
      text: "In past tests the model did better than guessing, and the gap was bigger than random noise would usually produce. That is no promise it will keep doing so.",
    };
  }
  if (b.skill_vs_baseline > 0 && ci && ci[0] <= 0) {
    return {
      icon: "≈", label: "Inconclusive",
      tone: "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200",
      text: "The model's error was a little lower, but the difference is small enough to be luck. Don't read it as a real edge.",
    };
  }
  return {
    icon: "✖", label: "Not better than guessing",
    tone: "border-red-300 bg-red-50 text-red-900 dark:border-red-800 dark:bg-red-950/40 dark:text-red-200",
    text: "In past tests the model did no better than simply assuming the price stays where it is. Treat its forecast as noise.",
  };
}

export function BacktestSummary({ backtest: b, horizon }: { backtest: Backtest; horizon: number }) {
  const v = verdict(b);
  const diff = Math.abs(b.skill_vs_baseline);
  const lower = b.skill_vs_baseline >= 0;
  const hit = b.model.directional_accuracy;
  const upRate = b.up_rate ?? b.naive_baseline.directional_accuracy;
  const nIndep = b.n_independent_tests;

  return (
    <section aria-labelledby="bt-title" className="space-y-3 rounded-md border border-slate-200 p-4 dark:border-slate-800">
      <h3 id="bt-title" className="font-semibold">How good is this model, really? <span className="font-normal text-slate-600 dark:text-slate-300">({horizon}-trading-day forecasts)</span></h3>

      <div role="status" className={`rounded-md border px-3 py-2 text-sm ${v.tone}`}>
        <p className="font-semibold"><span aria-hidden="true">{v.icon} </span>{v.label}</p>
        <p className="mt-1">{v.text}</p>
      </div>

      {b.small_sample && (
        <p role="note" className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
          <span aria-hidden="true">⚠ </span>
          <strong>Small sample.</strong> The {horizon}-day tests overlap, so the {b.n_test_points} test days are only worth about {nIndep ?? "few"} independent
          tests. Results from this few are easily down to chance.
        </p>
      )}

      <ul className="space-y-2 text-sm">
        <li>
          <strong>Accuracy:</strong> across {b.n_test_points} past test days (about {nIndep ?? "?"} independent {horizon}-day periods), the model&apos;s
          average error was{" "}
          <strong>{pct(diff, 1)} {lower ? "lower" : "higher"}</strong> than simply guessing &ldquo;the price stays the same.&rdquo;
          {b.skill_ci_90 && (
            <> The plausible range is {pct(b.skill_ci_90[0], 1)} to {pct(b.skill_ci_90[1], 1)}{b.skill_ci_90[0] <= 0 && b.skill_ci_90[1] >= 0 ? " — which includes zero, i.e. no real difference" : ""}.</>
          )}
        </li>
        <li>
          <strong>Direction:</strong>{" "}
          {hit == null ? "the model had no up/down view in the tests." : (
            <>the model called up-or-down correctly <strong>{pct(hit)}</strong> of the time (a coin flip is 50%)
              {upRate != null && <>; the price actually rose in {pct(upRate)} of periods, so always guessing &ldquo;up&rdquo; would have scored {pct(upRate)}</>}.</>
          )}
        </li>
      </ul>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">Model versus naive baseline error and direction accuracy</caption>
          <thead><tr className="text-left text-slate-700 dark:text-slate-300"><th scope="col" className="py-1 pr-2">Measure</th><th scope="col" className="pr-2">Model</th><th scope="col">&ldquo;Stays the same&rdquo; guess</th></tr></thead>
          <tbody>
            <tr className="border-t border-slate-100 dark:border-slate-800"><th scope="row" className="py-1 pr-2 text-left font-normal">Typical error ({horizon}-day move)</th><td className="pr-2">{pct(b.model.rmse, 2)}</td><td>{pct(b.naive_baseline.rmse, 2)}</td></tr>
            <tr className="border-t border-slate-100 dark:border-slate-800"><th scope="row" className="py-1 pr-2 text-left font-normal">Direction right</th><td className="pr-2">{hit == null ? "—" : pct(hit)}</td><td>{upRate == null ? "—" : `${pct(upRate)} (always “up”)`}</td></tr>
          </tbody>
        </table>
      </div>

      <details className="text-sm">
        <summary className="cursor-pointer font-medium">What this means &amp; its limits</summary>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-slate-700 dark:text-slate-300">
          <li>The test replays history: the model is trained only on data from before each test period, then asked to predict what came next. It never sees the answer.</li>
          <li>&ldquo;Guessing the price stays the same&rdquo; is a hard baseline to beat for stocks. A forecast is only interesting if it clearly does better.</li>
          <li>Past tests are not future results. Markets change, and big surprises (earnings, news, crashes) are not in the model.</li>
          <li>Even a model that beats the baseline can be wrong on any given day. The range shown around the forecast is an estimate, and outcomes fall outside it regularly.</li>
          <li>Technical details: {b.method}. {b.note}</li>
        </ul>
      </details>
    </section>
  );
}
