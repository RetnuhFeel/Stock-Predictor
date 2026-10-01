"use client";
import { useState } from "react";
import { SearchBox } from "./SearchBox";
import { StockPanel } from "./StockPanel";
import { ThemeToggle } from "./ThemeToggle";
import { Watchlist } from "./Watchlist";
import { useWatchlist } from "@/lib/watchlist";

export function App() {
  const { list, add, remove } = useWatchlist();
  const [picked, setPicked] = useState<string | null>(null);
  const selected = picked ?? list[0] ?? null;

  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      <header className="mb-6 flex items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">📈 Stock Predictor <span className="text-xs font-normal text-slate-500">experimental</span></h1>
        <ThemeToggle />
      </header>
      <div className="grid gap-6 md:grid-cols-[280px_1fr]">
        <aside className="space-y-4">
          <SearchBox onPick={(s) => { add(s); setPicked(s); }} />
          <Watchlist symbols={list} selected={selected} onSelect={setPicked} onRemove={(s) => { remove(s); if (picked === s) setPicked(null); }} />
        </aside>
        <main>{selected ? <StockPanel key={selected} symbol={selected} /> : <p className="text-slate-500">Select or search for a symbol.</p>}</main>
      </div>
    </div>
  );
}
