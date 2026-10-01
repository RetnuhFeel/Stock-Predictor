"use client";
import { useApi } from "@/lib/api";
import type { Quote } from "@/lib/types";

function Row({ symbol, active, onSelect, onRemove }: { symbol: string; active: boolean; onSelect: () => void; onRemove: () => void }) {
  const { data, error, loading } = useApi<Quote>(`/api/quote/${encodeURIComponent(symbol)}`);
  const up = (data?.change ?? 0) >= 0;
  return (
    <li className={`flex items-center rounded-md border ${active ? "border-blue-500 bg-blue-50 dark:bg-blue-950" : "border-slate-200 dark:border-slate-800"}`}>
      <button onClick={onSelect} className="flex flex-1 items-center justify-between px-3 py-2 text-left">
        <span className="font-semibold">{symbol}</span>
        <span className="text-right text-sm">
          {loading && <span className="text-slate-400">…</span>}
          {error && <span className="text-red-500" title={error}>n/a</span>}
          {data && (
            <>
              <span className="block">${data.price.toFixed(2)}</span>
              <span className={up ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}>
                {up ? "+" : ""}{data.change_percent.toFixed(2)}%
              </span>
            </>
          )}
        </span>
      </button>
      <button onClick={onRemove} aria-label={`Remove ${symbol}`} className="px-3 text-slate-400 hover:text-red-500">✕</button>
    </li>
  );
}

export function Watchlist(props: { symbols: string[]; selected: string | null; onSelect: (s: string) => void; onRemove: (s: string) => void }) {
  if (props.symbols.length === 0) return <p className="text-sm text-slate-500">Your watchlist is empty. Search for a symbol above.</p>;
  return (
    <ul className="space-y-2">
      {props.symbols.map((s) => (
        <Row key={s} symbol={s} active={s === props.selected} onSelect={() => props.onSelect(s)} onRemove={() => props.onRemove(s)} />
      ))}
    </ul>
  );
}
