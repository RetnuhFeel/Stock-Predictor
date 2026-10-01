"use client";
import { API_BASE } from "./api";

// Optional, privacy-friendly error reporting. Enabled only when the site is BUILT with
// NEXT_PUBLIC_ERROR_REPORTING=true AND the API has CLIENT_ERROR_LOGGING=true.
// Sends: error message, stack and page path. Never: cookies, storage, watchlist, alerts, IP (server doesn't log it).
export const REPORTING_ENABLED = process.env.NEXT_PUBLIC_ERROR_REPORTING === "true";

const MAX_PER_SESSION = 5;
const seen = new Set<string>();
let sent = 0;

/** Remove query strings/fragments from URLs and emails, then truncate. */
export function sanitize(text: string, limit: number): string {
  return text
    .replace(/(https?:\/\/[^\s?#)"']*)[?#][^\s)"']*/g, "$1")
    .replace(/[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g, "[email]")
    .slice(0, limit);
}

export function reportError(error: unknown) {
  if (!REPORTING_ENABLED || sent >= MAX_PER_SESSION || typeof window === "undefined") return;
  const err = error instanceof Error ? error : new Error(String(error));
  const payload = {
    message: sanitize(err.message || "Error", 300),
    stack: sanitize(err.stack ?? "", 2000),
    route: window.location.pathname,
  };
  const key = payload.message + payload.stack.slice(0, 200);
  if (seen.has(key)) return;
  seen.add(key);
  sent++;
  try {
    void fetch(`${API_BASE}/api/_client-error`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      keepalive: true,
      credentials: "omit",
    }).catch(() => undefined);
  } catch {
    /* reporting must never throw */
  }
}
