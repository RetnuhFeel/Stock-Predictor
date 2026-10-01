"use client";
import { type Failure, friendlyMessage } from "@/lib/errors";
import { useServerWaking } from "@/lib/serverStatus";

/** Shown while any request is slow / being auto-retried: typically a free-tier server waking up. */
export function WakingBanner() {
  const waking = useServerWaking();
  if (!waking) return null;
  return (
    <div role="status" className="rounded-md border border-blue-300 bg-blue-50 px-3 py-2 text-sm text-blue-900 dark:border-blue-800 dark:bg-blue-950/50 dark:text-blue-200">
      <span aria-hidden="true">⏳ </span>
      <strong>Waking up the server…</strong> this can take up to a minute on the first visit. Hang tight — it will load automatically.
    </div>
  );
}

export function ErrorNotice({ failure, onRetry, what }: { failure: Failure; onRetry: () => void; what: string }) {
  return (
    <div role="alert" className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-900 dark:border-red-800 dark:bg-red-950/40 dark:text-red-200">
      <span>
        <span aria-hidden="true">⚠ </span>
        <strong>{what} unavailable.</strong> {friendlyMessage(failure)}
      </span>
      <button onClick={onRetry} className="rounded border border-red-400 px-3 py-1 font-medium hover:bg-red-100 dark:border-red-700 dark:hover:bg-red-900/50">
        Try again
      </button>
    </div>
  );
}

function savedLabel(at: number): string {
  return new Date(at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

/**
 * "May be outdated" label. Shown when the data is a copy saved on this device (live refresh failed or is
 * pending), or the server says the data is stale/delayed. Rendered as text, not just colour.
 */
export function OutdatedLabel(props: { fromSaved?: boolean; savedAt?: number; stale?: boolean; delayed?: boolean; asOf?: string; refreshing?: boolean; onRetry?: () => void }) {
  const { fromSaved, savedAt, stale, delayed, asOf, refreshing, onRetry } = props;
  if (!fromSaved && !stale && !delayed) return null;
  const reasons: string[] = [];
  if (fromSaved) reasons.push(`showing a copy saved ${savedAt ? "on " + savedLabel(savedAt) : "earlier"}${refreshing ? " while refreshing…" : ""}`);
  if (stale) reasons.push("the data provider hasn't updated recently");
  else if (delayed && asOf) reasons.push(`latest price is from ${asOf}`);
  return (
    <p role="status" className="flex flex-wrap items-center gap-2 rounded border border-amber-300 bg-amber-50 px-2 py-1 text-xs text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
      <span><span aria-hidden="true">🕒 </span><strong>May be outdated:</strong> {reasons.join("; ")}.</span>
      {onRetry && !refreshing && <button onClick={onRetry} className="underline">Refresh</button>}
    </p>
  );
}
