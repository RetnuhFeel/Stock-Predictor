"use client";
import { useApi } from "@/lib/api";
import { friendlyMessage } from "@/lib/errors";
import type { Quote } from "@/lib/types";

function Row({ symbol, active, onSelect, onRemove }: { symbol: string; active: boolean; onSelect: () => void; onRemove: () => void }) {
  const { data, failure, loading, fromSaved } = useApi<Quote>(`/api/quote/${encodeURIComponent(symbol)}`);
  const up = (data?.change ?? 0) >= 0;
  return (
    <li className={`flex items-center rounded-md border ${active ? "border-blue-500 bg-blue-50 dark:bg-blue-950" : "border-slate-200 dark:border-slate-800"}`}>
      <button onClick={onSelect} aria-pressed={active} aria-label={`${symbol}${data ? `, $${data.price.toFixed(2)}, ${up ? "up" : "down"} ${Math.abs(data.change_percent).toFixed(2)} percent${fromSaved || data.stale ? ", may be outdated" : ""}` : ""}`} className="flex flex-1 items-center justify-between px-3 py-2 text-left">
        <span className="font-semibold">{symbol}</span>
        <span className="text-right text-sm" aria-hidden="true">
          {loading && !data && <span className="text-slate-600 dark:text-slate-300">…</span>}
          {failure && !data && <span className="text-red-700 dark:text-red-300" title={friendlyMessage(failure)}>n/a</span>}
          {data && (
            <>
              <span className="block">${data.price.toFixed(2)}{(fromSaved || data.stale) && <span title="May be outdated" aria-label="may be outdated"> 🕒</span>}</span>
              <span className={up ? "text-green-800 dark:text-green-300" : "text-red-700 dark:text-red-300"}>
                {up ? "▲ +" : "▼ "}{data.change_percent.toFixed(2)}%
              </span>
            </>
          )}
        </span>
      </button>
      <button onClick={onRemove} aria-label={`Remove ${symbol} from watchlist`} className="px-3 text-slate-600 hover:text-red-700 dark:text-slate-300 dark:hover:text-red-300">✕</button>
    </li>
  );
}

export function Watchlist(props: { symbols: string[]; selected: string | null; onSelect: (s: string) => void; onRemove: (s: string) => void }) {
  if (props.symbols.length === 0) return <p className="text-sm text-slate-700 dark:text-slate-300">Your watchlist is empty. Search for a symbol above.</p>;
  return (
    <ul className="space-y-2" aria-label="Watchlist">
      {props.symbols.map((s) => (
        <Row key={s} symbol={s} active={s === props.selected} onSelect={() => props.onSelect(s)} onRemove={() => props.onRemove(s)} />
      ))}
    </ul>
  );
}
