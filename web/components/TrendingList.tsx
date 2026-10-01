"use client";
import { useApi } from "@/lib/api";
import type { Trending } from "@/lib/types";
import { ErrorNotice, OutdatedLabel } from "./Notices";

/** Loads the built-in Trending list. Parent renders the rows; this owns loading/error/stale states. */
export function useTrending() {
  return useApi<Trending>("/api/trending?days=3&limit=5", { cheap: false });
}

export function TrendingStatus({ t }: { t: ReturnType<typeof useTrending> }) {
  const d = t.data;
  return (
    <div className="space-y-2">
      <p className="text-xs text-slate-700 dark:text-slate-300">
        Top 5 gainers over the last 3 trading days among ~{d?.universe_size ?? 100} large US stocks. <strong>A plain momentum screen — not a recommendation or a prediction.</strong>{" "}
        Past gains don&apos;t predict future returns.
      </p>
      {t.loading && !d && <p role="status" className="text-sm text-slate-700 dark:text-slate-300">Finding this week&apos;s movers… (the first load can take a few seconds)</p>}
      {t.failure && !d && <ErrorNotice failure={t.failure} onRetry={t.retry} what="Trending list" />}
      {d && <OutdatedLabel fromSaved={t.fromSaved} savedAt={t.savedAt} stale={d.stale} delayed={d.is_delayed} asOf={d.data_as_of} refreshing={t.loading} onRetry={t.retry} />}
      {d && <p className="text-xs text-slate-700 dark:text-slate-300">Prices as of {d.data_as_of}. Ranked by % change over {d.days} trading days.</p>}
    </div>
  );
}
