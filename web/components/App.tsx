"use client";
import Link from "next/link";
import { useState } from "react";
import { AlertsChecker } from "./AlertsChecker";
import { AlertsPanel } from "./AlertsPanel";
import { ComparePanel } from "./ComparePanel";
import { DisclaimerGate } from "./DisclaimerGate";
import { OfflineBanner, WakingBanner } from "./Notices";
import { SearchBox } from "./SearchBox";
import { StockPanel } from "./StockPanel";
import { ThemeToggle } from "./ThemeToggle";
import { Watchlist } from "./Watchlist";
import { useWatchlist } from "@/lib/watchlist";

type View = "stock" | "compare";

export function App() {
  const { list, add, remove } = useWatchlist();
  const [picked, setPicked] = useState<string | null>(null);
  const [view, setView] = useState<View>("stock");
  const selected = picked ?? list[0] ?? null;
  const tab = (v: View) =>
    `rounded-t px-3 py-1.5 text-sm font-medium ${view === v ? "bg-blue-700 text-white" : "bg-slate-200 text-slate-900 dark:bg-slate-800 dark:text-slate-100"}`;

  return (
    <>
      <DisclaimerGate />
      <AlertsChecker />
      <div data-gated className="mx-auto max-w-6xl px-4 py-6">
        <header className="mb-6 flex items-center justify-between gap-3">
          <h1 className="text-2xl font-bold">
            <span aria-hidden="true">📈 </span>Stock Predictor <span className="text-xs font-normal text-slate-600 dark:text-slate-300">experimental</span>
          </h1>
          <nav aria-label="Site" className="flex items-center gap-3 text-sm">
            <Link href="/model" className="text-blue-800 underline dark:text-blue-300">Model report</Link>
            <Link href="/track-record" className="text-blue-800 underline dark:text-blue-300">Track record</Link>
            <ThemeToggle />
          </nav>
        </header>
        <div className="mb-4 space-y-2">
          <OfflineBanner />
          <WakingBanner />
        </div>
        <div className="grid gap-6 md:grid-cols-[280px_1fr]">
          <aside className="space-y-4" aria-label="Watchlist and alerts">
            <SearchBox onPick={(s) => { add(s); setPicked(s); setView("stock"); }} />
            <Watchlist
              symbols={list}
              selected={selected}
              onSelect={(s) => { setPicked(s); setView("stock"); }}
              onRemove={(s) => { remove(s); if (picked === s) setPicked(null); }}
            />
            <AlertsPanel symbol={selected} />
          </aside>
          <main id="main" tabIndex={-1} className="min-w-0 outline-none">
            <div className="mb-4 flex gap-1 border-b border-slate-300 dark:border-slate-700" role="group" aria-label="View">
              <button className={tab("stock")} aria-pressed={view === "stock"} onClick={() => setView("stock")}>Forecast</button>
              <button className={tab("compare")} aria-pressed={view === "compare"} onClick={() => setView("compare")}>Compare</button>
            </div>
            {view === "compare" ? (
              <ComparePanel watchlist={list} />
            ) : selected ? (
              <StockPanel key={selected} symbol={selected} />
            ) : (
              <p className="text-slate-700 dark:text-slate-300">Select or search for a symbol.</p>
            )}
          </main>
        </div>
      </div>
    </>
  );
}
