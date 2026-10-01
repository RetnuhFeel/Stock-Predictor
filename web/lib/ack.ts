"use client";
import { useSyncExternalStore } from "react";
import { ACK_KEY, ACK_VERSION } from "./ackConfig";

const listeners = new Set<() => void>();
let memoryAck = false; // fallback when localStorage is unavailable (e.g. blocked storage)

function isAcked(): boolean {
  if (memoryAck) return true;
  try {
    return localStorage.getItem(ACK_KEY) === ACK_VERSION;
  } catch {
    return false;
  }
}

function subscribe(cb: () => void) {
  listeners.add(cb);
  window.addEventListener("storage", cb);
  return () => {
    listeners.delete(cb);
    window.removeEventListener("storage", cb);
  };
}

export function acknowledge() {
  memoryAck = true;
  try {
    localStorage.setItem(ACK_KEY, ACK_VERSION);
  } catch {
    /* storage blocked: acknowledgement lasts for this page session only */
  }
  document.documentElement.dataset.ack = "1"; // reveals the gated app (see globals.css)
  listeners.forEach((l) => l());
}

/**
 * true once the current disclaimer version is acknowledged.
 * The server snapshot is `true` so SSR/hydration render no dialog; before hydration the inline
 * script in layout.tsx + CSS keep gated content hidden, so there is no flash and no mismatch.
 */
export function useAcknowledged(): boolean {
  return useSyncExternalStore(subscribe, isAcked, () => true);
}
