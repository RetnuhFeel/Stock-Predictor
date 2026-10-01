import Link from "next/link";
import { SUPPORT_URL } from "@/lib/support";

export const DISCLAIMER_SHORT =
  "Educational/experimental only — not financial advice. No warranty. Predictions are frequently wrong. " +
  "No personalized advice. We don't hold or trade money.";

export function DisclaimerBanner() {
  return (
    <div role="region" aria-label="Disclaimer" className="sticky top-0 z-30 border-b border-amber-300 bg-amber-100 px-4 py-2 text-center text-xs font-medium text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200">
      ⚠️ {DISCLAIMER_SHORT}{" "}
      <Link href="/terms" className="underline">Terms</Link>
    </div>
  );
}

export function Footer() {
  return (
    <footer className="mt-12 border-t border-slate-200 px-4 py-6 text-center text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400">
      <p className="mx-auto max-w-2xl">{DISCLAIMER_SHORT} Market data is delayed/unofficial and may be inaccurate.</p>
      <p className="mt-2 space-x-4">
        <Link href="/terms" className="underline">Terms</Link>
        <Link href="/model" className="underline">Model report</Link>
        <Link href="/privacy" className="underline">Privacy</Link>
        <a href="https://github.com/RetnuhFeel/Stock-Predictor" className="underline">Source (MIT)</a>
        {SUPPORT_URL && <a href={SUPPORT_URL} target="_blank" rel="noopener noreferrer" className="underline">Support this project<span className="sr-only"> (opens in a new tab)</span></a>}
      </p>
    </footer>
  );
}
