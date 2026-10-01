"use client";
import { useCallback, useEffect, useState } from "react";
import { ApiRequestError, type Failure, toFailure } from "./errors";
import { readLastGood, writeLastGood } from "./lastGood";
import { clearSlow, markSlow } from "./serverStatus";

export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

const ATTEMPT_TIMEOUT_MS = 60_000; // one request (a cold start can take ~1 minute)
const WAKE_WINDOW_MS = 90_000; // keep auto-retrying network-level failures this long
const SLOW_AFTER_MS = 6_000; // a cheap request still pending after this => probably waking up

export async function apiGet<T>(path: string, signal?: AbortSignal, timeoutMs = ATTEMPT_TIMEOUT_MS): Promise<T> {
  const timeout = new AbortController();
  const timer = setTimeout(() => timeout.abort(), timeoutMs);
  const onAbort = () => timeout.abort();
  signal?.addEventListener("abort", onAbort);
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { signal: timeout.signal });
  } catch (e) {
    if (signal?.aborted) throw e; // caller cancelled: not an error
    if (timeout.signal.aborted) throw new ApiRequestError("TIMEOUT", "Request timed out", true, true);
    if (typeof navigator !== "undefined" && navigator.onLine === false) throw new ApiRequestError("OFFLINE", "Offline", true);
    // TypeError from fetch: DNS/connection failure, or a proxy error page without CORS headers
    throw new ApiRequestError("NETWORK", "Network error", true, true);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  }

  if (!res.ok) {
    let body: { error?: { code?: string; message?: string; retryable?: boolean; retry_after?: number } } | null = null;
    try {
      body = await res.json();
    } catch {
      /* non-JSON error body, e.g. an HTML 502/503 from the hosting proxy while the app boots */
    }
    const err = body?.error;
    if (err?.code) {
      throw new ApiRequestError(err.code, err.message ?? "Request failed", err.retryable ?? false, false, err.retry_after);
    }
    // No structured error: treat gateway-style failures as "server is starting up"
    const waking = res.status >= 500;
    throw new ApiRequestError(waking ? "SERVER_ERROR" : "HTTP_" + res.status, `HTTP ${res.status}`, true, waking);
  }
  return res.json() as Promise<T>;
}

const sleep = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve) => {
    const t = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => { clearTimeout(t); resolve(); }, { once: true });
  });

type State<T> = {
  path: string | null;
  data?: T;
  /** where `data` came from: this session's live response, or a copy saved on this device earlier */
  source?: "live" | "saved";
  savedAt?: number;
  failure?: Failure;
  loading: boolean;
};

/**
 * Fetch `path`. Keeps showing the last good data (live or saved on this device) when a refresh fails,
 * auto-retries network-level failures for ~90s (free-tier cold start), and exposes `retry`.
 * `cheap` marks quick endpoints whose slowness signals a sleeping server.
 */
export function useApi<T>(path: string | null, opts: { cheap?: boolean } = {}) {
  const cheap = opts.cheap ?? true;
  const [state, setState] = useState<State<T>>({ path: null, loading: false });
  const [attempt, setAttempt] = useState(0);
  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  useEffect(() => {
    if (!path) return;
    const ctrl = new AbortController();
    const id = Symbol(path);
    let slowTimer: ReturnType<typeof setTimeout> | undefined;

    (async () => {
      await Promise.resolve(); // state updates below happen after the effect has run
      if (ctrl.signal.aborted) return;
      const saved = readLastGood<T>(path);
      setState({ path, data: saved?.data, source: saved ? "saved" : undefined, savedAt: saved?.at, loading: true });
      if (cheap) slowTimer = setTimeout(() => markSlow(id), SLOW_AFTER_MS);

      const started = Date.now();
      for (let n = 0; ; n++) {
        try {
          const data = await apiGet<T>(path, ctrl.signal);
          if (ctrl.signal.aborted) return;
          writeLastGood(path, data);
          setState({ path, data, source: "live", loading: false });
          return;
        } catch (e) {
          if (ctrl.signal.aborted) return;
          const wakeable = e instanceof ApiRequestError && e.wakeable;
          if (wakeable && Date.now() - started < WAKE_WINDOW_MS) {
            markSlow(id);
            await sleep(Math.min(3000 + n * 1500, 8000), ctrl.signal);
            if (ctrl.signal.aborted) return;
            continue;
          }
          setState((s) => ({ ...s, path, failure: toFailure(e), loading: false }));
          return;
        }
      }
    })().finally(() => {
      clearTimeout(slowTimer);
      clearSlow(id);
    });

    return () => {
      ctrl.abort();
      clearTimeout(slowTimer);
      clearSlow(id);
    };
  }, [path, attempt, cheap]);

  // refresh as soon as connectivity returns
  useEffect(() => {
    if (!path) return;
    const onOnline = () => retry();
    window.addEventListener("online", onOnline);
    return () => window.removeEventListener("online", onOnline);
  }, [path, retry]);

  const current = state.path === path && path !== null;
  const data = current ? state.data : undefined;
  return {
    data,
    failure: current ? state.failure : undefined,
    loading: path !== null && (!current || state.loading),
    /** data is a saved copy from an earlier visit (live refresh hasn't succeeded) */
    fromSaved: current && state.source === "saved",
    savedAt: current ? state.savedAt : undefined,
    retry,
  };
}
