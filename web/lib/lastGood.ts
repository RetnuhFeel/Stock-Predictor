"use client";
// Remembers the last successful response per API path on this device, so the UI can keep showing
// (clearly labelled) older data when the server or data provider is unavailable.
// Stored only in localStorage; never sent anywhere. Bounded in count and size.

const PREFIX = "lg1:";
const INDEX = "lg1:index";
const MAX_ENTRIES = 40;
const MAX_BYTES = 300_000;

export type Saved<T> = { at: number; data: T };

export function readLastGood<T>(path: string): Saved<T> | null {
  try {
    const raw = localStorage.getItem(PREFIX + path);
    return raw ? (JSON.parse(raw) as Saved<T>) : null;
  } catch {
    return null;
  }
}

export function writeLastGood<T>(path: string, data: T) {
  try {
    const raw = JSON.stringify({ at: Date.now(), data } satisfies Saved<T>);
    if (raw.length > MAX_BYTES) return;
    localStorage.setItem(PREFIX + path, raw);
    const index: string[] = JSON.parse(localStorage.getItem(INDEX) ?? "[]").filter((p: string) => p !== path);
    index.push(path);
    while (index.length > MAX_ENTRIES) {
      const old = index.shift();
      if (old) localStorage.removeItem(PREFIX + old);
    }
    localStorage.setItem(INDEX, JSON.stringify(index));
  } catch {
    /* storage full/blocked: the feature degrades silently */
  }
}
