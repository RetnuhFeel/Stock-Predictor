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
import { type RowExtra, Watchlist } from "./Watchlist";
import { useLists } from "@/lib/lists";
import { TRENDING_ID } from "@/lib/listsCore";
import { ListSwitcher } from "./ListSwitcher";
import { TrendingStatus, useTrending } from "./TrendingList";

type View = "stock" | "compare";

export function App() {
  const { state, actions, isTrending } = useLists();
  const trending = useTrending();
  const [picked, setPicked] = useState<string | null>(null);
  const [view, setView] = useState<View>("stock");
  const [notice, setNotice] = useState("");
  const announce = (m: string) => setNotice(m);

  const userList = state.lists.find((l) => l.id === state.selectedId) ?? null;
  const items = trending.data?.items ?? [];
  const symbols = isTrending ? items.map((i) => i.symbol) : (userList?.symbols ?? []);
  const selected = picked && symbols.includes(picked) ? picked : (symbols[0] ?? null);
  const tab = (v: View) =>
    `rounded-t px-3 py-1.5 text-sm font-medium ${view === v ? "bg-blue-700 text-white" : "bg-slate-200 text-slate-900 dark:bg-slate-800 dark:text-slate-100"}`;

  // A symbol searched/added while the built-in list is showing goes to the last-used user list (created if none).
  function addFromSearch(sym: string) {
    let targetId = userList?.id ?? state.lastUserListId;
    if (!targetId || !state.lists.some((l) => l.id === targetId)) {
      const made = actions.create("My watchlist");
      announce(made.ok ? made.message ?? "" : made.reason);
      const fresh = made.ok ? made.state.lists.at(-1)?.id : undefined;
      if (!fresh) return;
      targetId = fresh;
    }
    const res = actions.addSymbol(targetId, sym);
    announce(res.ok ? res.message ?? "" : res.reason);
    if (res.ok) { actions.select(targetId); setPicked(sym.trim().toUpperCase()); setView("stock"); }
  }

  function addFromTrending(sym: string, listId: string) {
    let target = listId;
    if (!target) {
      const made = actions.create("My watchlist");
      if (!made.ok) { announce(made.reason); return; }
      target = made.state.lists.at(-1)?.id ?? "";
      actions.select(TRENDING_ID); // stay on Trending; creating a list selects it by default
    }
    const res = actions.addSymbol(target, sym);
    announce(res.ok ? res.message ?? "" : res.reason);
  }

  const extras: Record<string, RowExtra> = {};
  if (isTrending) {
    for (const it of items) {
      extras[it.symbol] = {
        badge: `${it.return_percent >= 0 ? "+" : ""}${it.return_percent.toFixed(1)}% 3d`,
        badgeLabel: `#${it.rank} trending, ${it.return_percent.toFixed(1)} percent over 3 days`,
        addTargets: state.lists.map((l) => ({ id: l.id, name: l.name })),
        onAdd: (listId) => addFromTrending(it.symbol, listId),
      };
    }
  }

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
        <p role="status" aria-live="polite" className="sr-only">{notice}</p>
        <div className="grid gap-6 md:grid-cols-[280px_1fr]">
          <aside className="space-y-4" aria-label="Lists, watchlist and alerts">
            <SearchBox onPick={(s) => addFromSearch(s)} />
            <ListSwitcher state={state} actions={actions} announce={announce} />
            {notice && <p className="text-xs text-slate-700 dark:text-slate-300" aria-hidden="true">{notice}</p>}
            {isTrending && <TrendingStatus t={trending} />}
            <Watchlist
              label={isTrending ? "Trending (3-day), read-only" : `${userList?.name ?? "Watchlist"} tickers`}
              symbols={symbols}
              selected={selected}
              onSelect={(s) => { setPicked(s); setView("stock"); }}
              onRemove={!isTrending && userList ? (s) => { const r = actions.removeSymbol(userList.id, s); announce(r.ok ? r.message ?? "" : r.reason); if (picked === s) setPicked(null); } : undefined}
              extras={extras}
              emptyText={isTrending ? (trending.loading ? "" : "No trending tickers to show right now.") : "This list is empty. Search for a symbol above to add it."}
            />
            <AlertsPanel symbol={selected} />
          </aside>
          <main id="main" tabIndex={-1} className="min-w-0 outline-none">
            <div className="mb-4 flex gap-1 border-b border-slate-300 dark:border-slate-700" role="group" aria-label="View">
              <button className={tab("stock")} aria-pressed={view === "stock"} onClick={() => setView("stock")}>Forecast</button>
              <button className={tab("compare")} aria-pressed={view === "compare"} onClick={() => setView("compare")}>Compare</button>
            </div>
            {view === "compare" ? (
              <ComparePanel watchlist={symbols} />
            ) : selected ? (
              <StockPanel key={selected} symbol={selected} />
            ) : (
              <p className="text-slate-700 dark:text-slate-300">{isTrending && trending.loading ? "Loading…" : "Select or search for a symbol."}</p>
            )}
          </main>
        </div>
      </div>
    </>
  );
}
