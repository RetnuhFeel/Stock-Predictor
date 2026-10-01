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
        <em> N</em> trading days. The 80% range shown with each forecast comes from how wrong the model was on data it had not seen.
      </p>
      <h2>How we test it, honestly</h2>
      <ul>
        <li><strong>Walk-forward:</strong> the model is trained only on the past and tested on the period right after, repeatedly (6 folds). It never sees the future.</li>
        <li><strong>Embargo:</strong> a gap of at least <em>N</em> days between training and test data, because an <em>N</em>-day label overlaps the following days.</li>
        <li><strong>Baseline:</strong> every result is compared with &ldquo;the price stays where it is&rdquo;. If the model can&apos;t beat that, it has no skill.</li>
        <li><strong>Uncertainty:</strong> overlapping windows make tests correlated, so a block bootstrap gives a 90% range for the skill score, and we only say &ldquo;better&rdquo; when that whole range is above zero.</li>
      </ul>
      <h2>Limits</h2>
      <ul>
        <li>Short-horizon returns are close to random. Expect &ldquo;not better&rdquo; or &ldquo;inconclusive&rdquo; most of the time, and a few &ldquo;better&rdquo; results are expected by chance alone.</li>
        <li>No transaction costs, no survivorship correction, no news or earnings awareness. Unofficial, possibly delayed data.</li>
        <li>A good past result is not a promise: markets change.</li>
      </ul>
      <ModelReport />
      <ModelExplorer />
      <p>
        Backtests look at the past. For results recorded <em>before</em> the outcome was known, see the <Link href="/track-record" className="text-blue-800 underline dark:text-blue-300">live track record</Link>.
      </p>
    </Page>
  );
}
