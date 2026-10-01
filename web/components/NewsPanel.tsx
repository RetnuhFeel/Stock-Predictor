"use client";
import { useApi } from "@/lib/api";
import type { News } from "@/lib/types";
import { ErrorNotice, OutdatedLabel } from "./Notices";

export function NewsPanel({ symbol }: { symbol: string }) {
  const news = useApi<News>(`/api/news/${encodeURIComponent(symbol)}`, { cheap: false });
  return (
    <section aria-labelledby="news-title" className="space-y-2 rounded-md border border-slate-200 p-4 dark:border-slate-800">
      <h3 id="news-title" className="font-semibold">Recent headlines</h3>
      <p className="text-xs text-slate-600 dark:text-slate-300">Context only — <strong>not a trading signal</strong>. Headlines link to third-party sites; we don&apos;t read or summarise them.</p>
      {news.loading && !news.data && <p role="status" className="text-sm text-slate-600 dark:text-slate-300">Loading headlines…</p>}
      {news.failure && !news.data && <ErrorNotice failure={news.failure} onRetry={news.retry} what="Headlines" />}
      {news.data && (
        <>
          <OutdatedLabel fromSaved={news.fromSaved} savedAt={news.savedAt} stale={news.data.stale} refreshing={news.loading} onRetry={news.retry} />
          {news.data.items.length === 0 ? (
            <p className="text-sm">No recent headlines found for {symbol} right now.</p>
          ) : (
            <ul className="space-y-2">
              {news.data.items.map((n) => (
                <li key={n.url} className="text-sm">
                  <a href={n.url} target="_blank" rel="noopener noreferrer" className="font-medium text-blue-800 underline dark:text-blue-300">
                    {n.headline}<span className="sr-only"> (opens in a new tab)</span>
                  </a>
                  <div className="text-xs text-slate-600 dark:text-slate-300">
                    {n.source && <>{n.source} · </>}
                    <time dateTime={n.published_at}>{new Date(n.published_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</time>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
