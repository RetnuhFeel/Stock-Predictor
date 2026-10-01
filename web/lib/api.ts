"use client";
import { useEffect, useState } from "react";

export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { signal });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new Error("Cannot reach the server. Check your connection and try again.");
  }
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : detail;
    } catch {
      /* non-JSON error body */
    }
    if (res.status === 429) detail = "Too many requests — please wait a moment.";
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

type State<T> = { path: string | null; data?: T; error?: string };

/** Fetch `path` and keep the result keyed by path, so loading state is derived (no sync setState in effects). */
export function useApi<T>(path: string | null) {
  const [state, setState] = useState<State<T>>({ path: null });

  useEffect(() => {
    if (!path) return;
    const ctrl = new AbortController();
    apiGet<T>(path, ctrl.signal)
      .then((data) => setState({ path, data }))
      .catch((e: Error) => {
        if (e.name !== "AbortError") setState({ path, error: e.message });
      });
    return () => ctrl.abort();
  }, [path]);

  const current = state.path === path && path !== null;
  return {
    data: current ? state.data : undefined,
    error: current ? state.error : undefined,
    loading: path !== null && !current,
  };
}
