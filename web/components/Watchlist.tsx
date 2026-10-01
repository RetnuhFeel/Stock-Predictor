"use client";
import { useApi } from "@/lib/api";
import { friendlyMessage } from "@/lib/errors";
import type { Quote } from "@/lib/types";

export type RowExtra = { badge?: string; badgeLabel?: string; addTargets?: { id: string; name: string }[]; onAdd?: (listId: string) => void };

function Row({ symbol, active, onSelect, onRemove, extra }: { symbol: string; active: boolean; onSelect: () => void; onRemove?: () => void; extra?: RowExtra }) {
  const { data, failure, loading, fromSaved } = useApi<Quote>(`/api/quote/${encodeURIComponent(symbol)}`);
  const up = (data?.change ?? 0) >= 0;
  return (
    <li className={`rounded-md border ${active ? "border-blue-500 bg-blue-50 dark:bg-blue-950" : "border-slate-200 dark:border-slate-800"}`}>
      <div className="flex items-center">
        <button onClick={onSelect} aria-pressed={active} aria-label={`${symbol}${extra?.badgeLabel ? `, ${extra.badgeLabel}` : ""}${data ? `, $${data.price.toFixed(2)}, ${up ? "up" : "down"} ${Math.abs(data.change_percent).toFixed(2)} percent today${fromSaved || data.stale ? ", may be outdated" : ""}` : ""}`} className="flex flex-1 items-center justify-between px-3 py-2 text-left">
          <span className="font-semibold">
            {symbol}
            {extra?.badge && <span className="ml-2 rounded bg-green-100 px-1.5 py-0.5 text-xs font-medium text-green-900 dark:bg-green-900/50 dark:text-green-200">{extra.badge}</span>}
          </span>
          <span className="text-right text-sm" aria-hidden="true">
            {loading && !data && <span className="text-slate-600 dark:text-slate-300">…</span>}
            {failure && !data && <span className="text-red-700 dark:text-red-300" title={friendlyMessage(failure)}>n/a</span>}
            {data && (
              <>
                <span className="block">${data.price.toFixed(2)}{(fromSaved || data.stale) && <span title="May be outdated"> 🕒</span>}</span>
                <span className={up ? "text-green-800 dark:text-green-300" : "text-red-700 dark:text-red-300"}>
                  {up ? "▲ +" : "▼ "}{data.change_percent.toFixed(2)}%
                </span>
              </>
            )}
          </span>
        </button>
        {onRemove && (
          <button onClick={onRemove} aria-label={`Remove ${symbol} from this list`} className="px-3 text-slate-600 hover:text-red-700 dark:text-slate-300 dark:hover:text-red-300">✕</button>
        )}
      </div>
      {extra?.onAdd && (
        <div className="border-t border-slate-200 px-3 py-1 dark:border-slate-800">
          {extra.addTargets && extra.addTargets.length > 0 ? (
            <select
              aria-label={`Add ${symbol} to one of your lists`}
              value=""
              onChange={(e) => e.target.value && extra.onAdd?.(e.target.value)}
              className="w-full rounded border border-slate-400 bg-white px-1 py-1 text-xs dark:border-slate-600 dark:bg-slate-900"
            >
              <option value="">Add to list…</option>
              {extra.addTargets.map((t) => (<option key={t.id} value={t.id}>{t.name}</option>))}
            </select>
          ) : (
            <button onClick={() => extra.onAdd?.("")} className="text-xs underline">Add to a new list</button>
          )}
        </div>
      )}
    </li>
  );
}

export type WatchlistProps = {
  symbols: string[];
  selected: string | null;
  onSelect: (s: string) => void;
  onRemove?: (s: string) => void;
  extras?: Record<string, RowExtra>;
  emptyText?: string;
  label: string;
};

export function Watchlist(props: WatchlistProps) {
  if (props.symbols.length === 0) return <p className="text-sm text-slate-700 dark:text-slate-300">{props.emptyText ?? "This list is empty. Search for a symbol above."}</p>;
  return (
    <ul className="space-y-2" aria-label={props.label}>
      {props.symbols.map((s) => (
        <Row key={s} symbol={s} active={s === props.selected} onSelect={() => props.onSelect(s)} onRemove={props.onRemove ? () => props.onRemove?.(s) : undefined} extra={props.extras?.[s]} />
      ))}
    </ul>
  );
}
