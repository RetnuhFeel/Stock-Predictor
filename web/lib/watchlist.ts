"use client";
import { useSyncExternalStore } from "react";

const KEY = "watchlist.v1";
const DEFAULT = ["AAPL", "MSFT", "NVDA"];
const listeners = new Set<() => void>();
let cached: { raw: string | null; value: string[] } | null = null;

function read(): string[] {
  const raw = localStorage.getItem(KEY);
  if (cached && cached.raw === raw) return cached.value; // stable reference for useSyncExternalStore
  let value = DEFAULT;
  try {
    const parsed = raw ? JSON.parse(raw) : null;
    if (Array.isArray(parsed)) value = parsed.filter((s) => typeof s === "string").slice(0, 50);
  } catch {
    /* corrupted storage: fall back to default */
  }
  cached = { raw, value };
  return value;
}

function write(list: string[]) {
  localStorage.setItem(KEY, JSON.stringify(list));
  listeners.forEach((l) => l());
}

function subscribe(cb: () => void) {
  listeners.add(cb);
  window.addEventListener("storage", cb);
  return () => {
    listeners.delete(cb);
    window.removeEventListener("storage", cb);
  };
}

const SERVER: string[] = [];

export function useWatchlist() {
  const list = useSyncExternalStore(subscribe, read, () => SERVER);
  return {
    list,
    add: (s: string) => {
      const sym = s.trim().toUpperCase();
      if (sym && !read().includes(sym)) write([...read(), sym]);
    },
    remove: (s: string) => write(read().filter((x) => x !== s)),
  };
}
