"use client";
import { useCallback, useSyncExternalStore } from "react";
import { DEFAULT_RANGE, parseRange, RANGE_KEY } from "./chartRange";
import type { TimelineRange } from "./types";

const listeners = new Set<() => void>();
function read(): TimelineRange {
  try {
    return parseRange(localStorage.getItem(RANGE_KEY));
  } catch {
    return DEFAULT_RANGE; // storage blocked
  }
}
function subscribe(cb: () => void) {
  listeners.add(cb);
  const onStorage = (e: StorageEvent) => (e.key === RANGE_KEY || e.key === null) && cb();
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(cb);
    window.removeEventListener("storage", onStorage);
  };
}

/** The chart's history range, remembered on this device (a plain string, so no snapshot-caching trouble). */
export function useChartRange(): [TimelineRange, (r: TimelineRange) => void] {
  const range = useSyncExternalStore(subscribe, read, () => DEFAULT_RANGE);
  const set = useCallback((r: TimelineRange) => {
    try {
      localStorage.setItem(RANGE_KEY, r);
    } catch {
      /* quota/blocked: the choice just isn't remembered */
    }
    listeners.forEach((l) => l());
  }, []);
  return [range, set];
}
