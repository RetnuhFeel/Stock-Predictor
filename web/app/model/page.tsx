import type { Metadata } from "next";
import Link from "next/link";
import { ModelExplorer } from "@/components/ModelExplorer";
import { ModelReport } from "@/components/ModelReport";
import { Page } from "@/components/Prose";

export const metadata: Metadata = {
  title: "Model report — Stock Predictor",
  description: "How the experimental forecast model works, and a live backtest report card showing where it does and does not beat a naive baseline.",
};

export default function Model() {
  return (
    <Page title="Model report" draft={false}>
      <p role="note" className="rounded-md border border-amber-300 bg-amber-50 p-3 text-amber-950 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-100">
        <strong>Experimental, educational, not financial advice.</strong> Predictions are frequently wrong. This page exists to show how
        weak the model is, not to sell it.
      </p>
      <h2>What the model does</h2>
      <p>
        For each ticker it turns daily adjusted closing prices into a few simple features (recent returns, volatility, RSI, MACD, distance
        from the 50-day average) and trains a small, regularised gradient-boosting regressor to guess the price change over the next
        <em> N</em> trading days. The 80% range shown with each forecast is built by <strong>split conformal prediction</strong>: recent volatility scaled to the horizon, stretched or shrunk by how wrong forecasts of this kind were on past data, using only what was known at the time. We then <em>replay that recipe through history</em> to measure how often the real price landed inside the range, and show that number (and how uncertain it is) next to the forecast. It is used only where the history holds enough independent test periods to check it (at least 8) and the replay did not show clear under-coverage. For 120 to about 200 days the API fetches ten years of prices for this purpose. Where the check is not possible (for example 256 days, or 60 days with five years of data) the range falls back to the older method and is labelled <em>coverage not verified</em>, or, from 120 days on, <em>not backtest-calibrated</em> (a plain volatility range around today&apos;s price). The model&apos;s point estimate is for reference only at long horizons.
      </p>
      <h2>How we test it, honestly</h2>
      <ul>
        <li><strong>Walk-forward:</strong> the model is trained only on the past and tested on the period right after, repeatedly (6 folds). It never sees the future.</li>
        <li><strong>Embargo:</strong> a gap of at least <em>N</em> days between training and test data, because an <em>N</em>-day label overlaps the following days.</li>
        <li><strong>Baseline:</strong> every result is compared with &ldquo;the price stays where it is&rdquo;. If the model can&apos;t beat that, it has no skill.</li>
        <li><strong>Uncertainty:</strong> overlapping windows make tests correlated, so a block bootstrap gives a 90% range for the skill score, and we only say &ldquo;better&rdquo; when that whole range is above zero.</li>
      </ul>
      <h2>Long horizons (up to 256 trading days)</h2>
      <p>
        Horizons from 5 to 256 trading days are available. The same walk-forward test and embargo (at least <em>N</em> days) apply, but five years of
        data hold only about 9 independent 60-day periods and about 1 independent 256-day period. With fewer than 5 independent periods a model can
        never be called &ldquo;better&rdquo;, and every forecast of 60 days or more is labelled highly uncertain. Treat these as a sense of scale, not a prediction.
      </p>
      <h2>Risk models: EWMA, HAR and GJR-GARCH</h2>
      <p>
        The risk panel estimates how <em>big</em> moves will be (not which way). The headline estimate is EWMA (recent days weighted more heavily), chosen before we looked at any results.
        HAR-style regression and <strong>GJR-GARCH(1,1)</strong> are shown as alternatives. GARCH is a fitted model in which volatility drifts back toward its long-run level and down days raise
        expected volatility more than up days. Every risk model is judged on the same walk-forward test with the same rules: first against &ldquo;the next period is as jumpy as the last 21 days&rdquo;, and
        the alternatives also against the EWMA headline. In our checks on 12 liquid US tickers GARCH was often clearly closer than EWMA at 20 and 60 days, but not always (it was clearly worse on NVDA at 5 and 20 days),
        and at 120 days there are too few independent periods to call anything &ldquo;better&rdquo;. That is a backtest on one window of history, not a promise, so the headline stays EWMA.
      </p>
      <h2>Limits</h2>
      <ul>
        <li>Short-horizon returns are close to random. Expect &ldquo;not better&rdquo; or &ldquo;inconclusive&rdquo; most of the time, and a few &ldquo;better&rdquo; results are expected by chance alone.</li>
        <li>No transaction costs, no survivorship correction, no news or earnings awareness. Unofficial, possibly delayed data.</li>
        <li>A good past result is not a promise: markets change.</li>
      </ul>
      <h2>Experimental: spike scenario</h2>
      <p>
        The forecast view has an optional, off-by-default <strong>Spike scenario</strong> panel. It runs a jump-diffusion Monte Carlo (2,000 seeded paths)
        calibrated from the ticker&apos;s own last ~2 years: days that move more than 2.5 robust standard deviations count as jumps (up and down counted
        separately, so asymmetry is kept) and the simulation resamples those historical jump sizes. Jumps are compensated so they add spikes, not extra trend.
        Every simulated price is then <strong>clamped</strong> to the standard forecast&apos;s normal 80% range for that day, and the panel reports how often that happened.
      </p>
      <ul>
        <li><strong>Simulated, not predicted:</strong> it does not know when a spike will occur or its direction.</li>
        <li><strong>Backtest:</strong> same walk-forward folds and embargo as above. It compares how often the real move landed inside each range, a combined width-and-miss score (Winkler interval score) with a bootstrap 90% range, and the accuracy of the median path. We only say &ldquo;better&rdquo; for a change of at least 2% whose 90% range excludes zero. In our checks on SPY, AAPL, MSFT, NVDA and TSLA (5 and 20 days) the median path was never clearly more accurate than the standard forecast. Because of the clamp the spike range is never wider than the standard band; in most of our checks it was narrower and contained fewer real outcomes, so a better interval score there mostly reflects a narrower range, not a safer one. See the docs for the numbers.</li>
        <li><strong>Not scored:</strong> it is never part of the live track record&apos;s logged predictions.</li>
      </ul>
      <ModelReport />
      <ModelExplorer />
      <p>
        Backtests look at the past. For results recorded <em>before</em> the outcome was known, see the <Link href="/track-record" className="text-blue-800 underline dark:text-blue-300">live track record</Link>.
      </p>
    </Page>
  );
}
