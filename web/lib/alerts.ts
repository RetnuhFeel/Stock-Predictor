"use client";
import { useSyncExternalStore } from "react";

// Price alerts live only in this browser's localStorage. No accounts, no server, no push service:
// they are evaluated while the app is open (see AlertsChecker).

export type Alert = {
  id: string;
  symbol: string;
  dir: "above" | "below";
  price: number;
  createdAt: number;
  triggeredAt?: number;
  triggeredPrice?: number;
};

const KEY = "alerts.v1";
export const MAX_ALERTS = 20;
const listeners = new Set<() => void>();
let cached: { raw: string | null; value: Alert[] } | null = null;
const EMPTY: Alert[] = [];

function valid(a: unknown): a is Alert {
  const x = a as Alert;
  return !!x && typeof x.id === "string" && typeof x.symbol === "string" && (x.dir === "above" || x.dir === "below") &&
    typeof x.price === "number" && Number.isFinite(x.price) && x.price > 0 && typeof x.createdAt === "number";
}

function read(): Alert[] {
  let raw: string | null = null;
  try {
    raw = localStorage.getItem(KEY);
  } catch {
    return EMPTY;
  }
  if (cached && cached.raw === raw) return cached.value; // stable reference for useSyncExternalStore
  let value = EMPTY;
  try {
    const parsed = raw ? JSON.parse(raw) : [];
    if (Array.isArray(parsed)) value = parsed.filter(valid).slice(0, MAX_ALERTS);
  } catch {
    /* corrupted: start empty */
  }
  cached = { raw, value };
  return value;
}

function write(list: Alert[]) {
  try {
    localStorage.setItem(KEY, JSON.stringify(list));
  } catch {
    /* storage blocked/full */
  }
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

export function useAlerts(): Alert[] {
  return useSyncExternalStore(subscribe, read, () => EMPTY);
}

export type AddResult = { ok: true } | { ok: false; reason: string };

export function addAlert(symbol: string, dir: "above" | "below", price: number): AddResult {
  if (!Number.isFinite(price) || price <= 0) return { ok: false, reason: "Enter a price greater than zero." };
  const list = read();
  if (list.length >= MAX_ALERTS) return { ok: false, reason: `You can have up to ${MAX_ALERTS} alerts.` };
  if (list.some((a) => a.symbol === symbol && a.dir === dir && a.price === price && !a.triggeredAt))
    return { ok: false, reason: "That alert already exists." };
  write([...list, { id: crypto.randomUUID(), symbol, dir, price, createdAt: Date.now() }]);
  return { ok: true };
}

export const removeAlert = (id: string) => write(read().filter((a) => a.id !== id));

export const rearmAlert = (id: string) =>
  write(read().map((a) => (a.id === id ? { ...a, triggeredAt: undefined, triggeredPrice: undefined } : a)));

export function markTriggered(hits: { id: string; price: number }[]) {
  if (!hits.length) return;
  const byId = new Map(hits.map((h) => [h.id, h.price]));
  write(read().map((a) => (byId.has(a.id) ? { ...a, triggeredAt: Date.now(), triggeredPrice: byId.get(a.id) } : a)));
}

/** Pure: which active (not yet triggered) alerts are crossed by the given latest prices. */
export function evaluateAlerts(alerts: Alert[], prices: Record<string, number>): { alert: Alert; price: number }[] {
  const hits: { alert: Alert; price: number }[] = [];
  for (const a of alerts) {
    const p = prices[a.symbol];
    if (a.triggeredAt || p == null || !Number.isFinite(p)) continue;
    if ((a.dir === "above" && p >= a.price) || (a.dir === "below" && p <= a.price)) hits.push({ alert: a, price: p });
  }
  return hits;
}

export const describeAlert = (a: Pick<Alert, "symbol" | "dir" | "price">) => `${a.symbol} ${a.dir} $${a.price.toFixed(2)}`;
