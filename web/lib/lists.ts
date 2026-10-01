"use client";
import { useCallback, useSyncExternalStore } from "react";
import {
  type ListsState, type Result, TRENDING_ID, addSymbol, createList, deleteList, initialState, load, removeSymbol, renameList,
  selectList, serialize,
} from "./listsCore";

const KEY = "lists.v2";
const LEGACY_KEY = "watchlist.v1"; // read for migration only; left in place so an older build still works
const listeners = new Set<() => void>();
const SERVER: ListsState = { ...initialState(false), lists: [] };
let cache: { raw: string | null; legacy: string | null; value: ListsState } | null = null;

function safeGet(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null; // storage blocked
  }
}

function read(): ListsState {
  const raw = safeGet(KEY);
  const legacy = raw ? null : safeGet(LEGACY_KEY);
  if (cache && cache.raw === raw && cache.legacy === legacy) return cache.value; // stable reference
  const value = load(raw, legacy);
  cache = { raw, legacy, value };
  return value;
}

/** Persist and notify. If storage is full/blocked the in-memory state is still used for this session. */
function commit(next: ListsState): { saved: boolean } {
  let saved = true;
  const raw = serialize(next);
  try {
    localStorage.setItem(KEY, raw);
  } catch {
    saved = false;
  }
  cache = { raw: saved ? raw : safeGet(KEY), legacy: null, value: next };
  if (!saved) memoryOverride = next;
  listeners.forEach((l) => l());
  return { saved };
}

let memoryOverride: ListsState | null = null;
const current = () => (memoryOverride && cache?.value === memoryOverride ? memoryOverride : read());

function subscribe(cb: () => void) {
  listeners.add(cb);
  const onStorage = (e: StorageEvent) => {
    if (e.key === KEY || e.key === null) {
      memoryOverride = null;
      cb();
    }
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(cb);
    window.removeEventListener("storage", onStorage);
  };
}

export type ListActions = {
  create: (name: string) => Result;
  rename: (id: string, name: string) => Result;
  remove: (id: string) => Result;
  select: (id: string) => void;
  addSymbol: (listId: string, symbol: string) => Result;
  removeSymbol: (listId: string, symbol: string) => Result;
};

function apply(fn: (s: ListsState) => Result): Result {
  const res = fn(current());
  if (res.ok && res.state !== current()) {
    const { saved } = commit(res.state);
    if (!saved) return { ...res, message: `${res.message ?? "Done."} (Couldn't save on this device: storage is full or blocked, so this change may be lost when you close the tab.)` };
  }
  return res;
}

export function useLists() {
  const state = useSyncExternalStore(subscribe, current, () => SERVER);
  const select = useCallback((id: string) => {
    const next = selectList(current(), id);
    if (next !== current()) commit(next);
  }, []);
  const actions: ListActions = {
    create: (name) => apply((s) => createList(s, name)),
    rename: (id, name) => apply((s) => renameList(s, id, name)),
    remove: (id) => apply((s) => deleteList(s, id)),
    select,
    addSymbol: (listId, symbol) => apply((s) => addSymbol(s, listId, symbol)),
    removeSymbol: (listId, symbol) => apply((s) => removeSymbol(s, listId, symbol)),
  };
  return { state, actions, isTrending: state.selectedId === TRENDING_ID };
}
