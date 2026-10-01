"use client";
import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import type { SearchResult } from "@/lib/types";

export function SearchBox({ onPick }: { onPick: (symbol: string) => void }) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);

  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) return;
    const ctrl = new AbortController();
    const t = setTimeout(() => {
      apiGet<{ results: SearchResult[] }>(`/api/search?q=${encodeURIComponent(term)}`, ctrl.signal)
        .then((r) => setResults(r.results))
        .catch(() => setResults([]));
    }, 300);
    return () => {
      clearTimeout(t);
      ctrl.abort();
    };
  }, [q]);

  function pick(symbol: string) {
    onPick(symbol);
    setQ("");
    setResults([]);
  }

  const shown = q.trim().length >= 2 ? results : [];

  return (
    <form
      className="relative"
      onSubmit={(e) => {
        e.preventDefault();
        if (q.trim()) pick(q.trim().toUpperCase());
      }}
    >
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Search symbol or company (Enter to open)"
        aria-label="Search symbol"
        maxLength={40}
        className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
      />
      {shown.length > 0 && (
        <ul className="absolute z-20 mt-1 max-h-64 w-full overflow-auto rounded-md border border-slate-200 bg-white shadow-lg dark:border-slate-700 dark:bg-slate-900">
          {shown.map((r) => (
            <li key={r.symbol}>
              <button type="button" onClick={() => pick(r.symbol)} className="flex w-full justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-slate-100 dark:hover:bg-slate-800">
                <span className="font-semibold">{r.symbol}</span>
                <span className="truncate text-slate-500">{r.name} {r.exchange && `· ${r.exchange}`}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </form>
  );
}
