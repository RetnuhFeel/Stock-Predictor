"use client";
import { useSyncExternalStore } from "react";

// Tracks requests that are taking suspiciously long (or being auto-retried after a network-level
// failure), which on a free-tier host usually means the server is waking up from sleep.
const slow = new Set<symbol>();
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

export const markSlow = (id: symbol) => {
  if (!slow.has(id)) {
    slow.add(id);
    emit();
  }
};
export const clearSlow = (id: symbol) => {
  if (slow.delete(id)) emit();
};

export function useServerWaking(): boolean {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => slow.size > 0,
    () => false,
  );
}
