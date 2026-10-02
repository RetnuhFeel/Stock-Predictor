"use client";
import { useId, useRef, useState } from "react";
import { MAX_LISTS, TRENDING_ID, TRENDING_NAME, type ListsState, type Result } from "@/lib/listsCore";
import type { ListActions } from "@/lib/lists";

type Mode = "idle" | "create" | "rename" | "delete";

export function ListSwitcher({ state, actions, announce }: { state: ListsState; actions: ListActions; announce: (m: string) => void }) {
  const [mode, setMode] = useState<Mode>("idle");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const selectId = useId();
  const inputId = useId();
  const input = useRef<HTMLInputElement>(null);
  const select = useRef<HTMLSelectElement>(null);
  const focusSelect = () => setTimeout(() => select.current?.focus(), 0);  // the clicked button is unmounted: keep focus in the widget
  const current = state.lists.find((l) => l.id === state.selectedId);

  const reset = () => { setMode("idle"); setName(""); setError(""); };
  const finish = (res: Result) => {
    if (res.ok) { announce(res.message ?? "Done."); reset(); focusSelect(); } else setError(res.reason);
  };
  const open = (m: Mode, initial = "") => { setMode(m); setName(initial); setError(""); setTimeout(() => input.current?.focus(), 0); };

  const btn = "rounded border border-slate-400 px-2 py-1 text-xs hover:bg-slate-100 disabled:opacity-50 dark:border-slate-600 dark:hover:bg-slate-800";
  return (
    <section aria-label="Lists" className="space-y-2">
      <div>
        <label htmlFor={selectId} className="block text-xs font-medium">List</label>
        <select
          id={selectId}
          ref={select}
          value={state.selectedId}
          onChange={(e) => { actions.select(e.target.value); reset(); announce(`Showing ${e.target.value === TRENDING_ID ? TRENDING_NAME : state.lists.find((l) => l.id === e.target.value)?.name ?? "list"}.`); }}
          className="w-full rounded border border-slate-400 bg-white px-2 py-1.5 text-sm dark:border-slate-600 dark:bg-slate-900"
        >
          <option value={TRENDING_ID}>{TRENDING_NAME} · built-in</option>
          {state.lists.map((l) => (<option key={l.id} value={l.id}>{l.name} ({l.symbols.length})</option>))}
        </select>
      </div>

      {mode === "idle" && (
        <div className="flex flex-wrap gap-2">
          <button className={btn} onClick={() => open("create")} disabled={state.lists.length >= MAX_LISTS} title={state.lists.length >= MAX_LISTS ? `Limit of ${MAX_LISTS} lists reached` : undefined}>New list</button>
          {current && <button className={btn} onClick={() => open("rename", current.name)}>Rename</button>}
          {current && <button className={btn} onClick={() => open("delete")}>Delete</button>}
        </div>
      )}

      {(mode === "create" || mode === "rename") && (
        <form
          className="space-y-1"
          onSubmit={(e) => { e.preventDefault(); finish(mode === "create" ? actions.create(name) : actions.rename(state.selectedId, name)); }}
        >
          <label htmlFor={inputId} className="block text-xs font-medium">{mode === "create" ? "Name of the new list" : `New name for ${current?.name}`}</label>
          <input id={inputId} ref={input} value={name} onChange={(e) => setName(e.target.value)} maxLength={60} autoComplete="off"
            aria-invalid={error ? true : undefined} aria-describedby={error ? `${inputId}-err` : undefined}
            onKeyDown={(e) => { if (e.key === "Escape") { reset(); focusSelect(); } }}
            className="w-full rounded border border-slate-400 bg-white px-2 py-1 text-sm dark:border-slate-600 dark:bg-slate-900" />
          {error && <p id={`${inputId}-err`} role="alert" className="text-xs text-red-700 dark:text-red-300">{error}</p>}
          <div className="flex gap-2">
            <button type="submit" className="rounded bg-blue-700 px-3 py-1 text-xs font-semibold text-white hover:bg-blue-800">{mode === "create" ? "Create" : "Save"}</button>
            <button type="button" className={btn} onClick={() => { reset(); focusSelect(); }}>Cancel</button>
          </div>
        </form>
      )}

      {mode === "delete" && current && (
        <div role="alertdialog" aria-label={`Delete ${current.name}?`} className="space-y-2 rounded border border-red-300 bg-red-50 p-2 text-sm text-red-950 dark:border-red-800 dark:bg-red-950/40 dark:text-red-100">
          <p>Delete <strong>{current.name}</strong> and its {current.symbols.length} ticker{current.symbols.length === 1 ? "" : "s"}? This can&apos;t be undone.</p>
          <div className="flex gap-2">
            <button autoFocus className="rounded bg-red-700 px-3 py-1 text-xs font-semibold text-white hover:bg-red-800" onClick={() => finish(actions.remove(current.id))}>Yes, delete</button>
            <button className={btn} onClick={() => { reset(); focusSelect(); }}>Cancel</button>
          </div>
        </div>
      )}
    </section>
  );
}
