"use client";
import { useEffect, useId, useState } from "react";
import { apiGet } from "@/lib/api";
import type { SearchResult } from "@/lib/types";

/** Search field implemented as an ARIA 1.2 combobox (editable, list autocomplete): the input keeps focus, arrow
 *  keys move through the options (aria-activedescendant), Enter picks the highlighted option (or the typed symbol),
 *  Escape closes the list, and the number of suggestions is announced politely. */
export function SearchBox({ onPick }: { onPick: (symbol: string) => void }) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [active, setActive] = useState(-1);
  const [open, setOpen] = useState(false);
  const listId = useId();

  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) return;
    const ctrl = new AbortController();
    const t = setTimeout(() => {
      apiGet<{ results: SearchResult[] }>(`/api/search?q=${encodeURIComponent(term)}`, ctrl.signal)
        .then((r) => { setResults(r.results); setActive(-1); setOpen(true); })
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
    setActive(-1);
    setOpen(false);
  }

  const shown = q.trim().length >= 2 ? results : [];
  const expanded = open && shown.length > 0;
  const optionId = (i: number) => `${listId}-opt-${i}`;

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown" && shown.length > 0) {
      e.preventDefault();
      setOpen(true);
      setActive((a) => (a + 1) % shown.length);
    } else if (e.key === "ArrowUp" && shown.length > 0) {
      e.preventDefault();
      setOpen(true);
      setActive((a) => (a <= 0 ? shown.length - 1 : a - 1));
    } else if (e.key === "Escape" && expanded) {
      e.preventDefault();
      setOpen(false);
      setActive(-1);
    } else if (e.key === "Home" && expanded && active >= 0) {
      e.preventDefault();
      setActive(0);
    } else if (e.key === "End" && expanded && active >= 0) {
      e.preventDefault();
      setActive(shown.length - 1);
    }
  }

  return (
    <form
      className="relative"
      onSubmit={(e) => {
        e.preventDefault();
        if (expanded && active >= 0 && shown[active]) pick(shown[active].symbol);
        else if (q.trim()) pick(q.trim().toUpperCase());
      }}
    >
      <input
        role="combobox"
        aria-expanded={expanded}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={expanded && active >= 0 ? optionId(active) : undefined}
        autoComplete="off"
        value={q}
        onChange={(e) => { setQ(e.target.value); setOpen(true); }}
        onKeyDown={onKeyDown}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder="Search symbol or company (Enter to open)"
        aria-label="Search symbol"
        maxLength={40}
        className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
      />
      <p className="sr-only" role="status" aria-live="polite">
        {expanded ? `${shown.length} suggestion${shown.length === 1 ? "" : "s"} available. Use the up and down arrow keys, then Enter.` : ""}
      </p>
      <ul
        id={listId}
        role="listbox"
        aria-label="Search suggestions"
        hidden={!expanded}
        className="absolute z-20 mt-1 max-h-64 w-full overflow-auto rounded-md border border-slate-200 bg-white shadow-lg dark:border-slate-700 dark:bg-slate-900"
      >
        {expanded && shown.map((r, i) => (
          <li
            key={r.symbol}
            id={optionId(i)}
            role="option"
            aria-selected={i === active}
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => pick(r.symbol)}
            className={`flex w-full cursor-pointer justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-slate-100 dark:hover:bg-slate-800 ${i === active ? "bg-slate-100 dark:bg-slate-800" : ""}`}
          >
            <span className="font-semibold">{r.symbol}</span>
            <span className="truncate text-slate-700 dark:text-slate-300">{r.name} {r.exchange && `· ${r.exchange}`}</span>
          </li>
        ))}
      </ul>
    </form>
  );
}
