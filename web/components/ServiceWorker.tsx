"use client";
import { useEffect } from "react";

export function ServiceWorker() {
  useEffect(() => {
    if (!("serviceWorker" in navigator) || process.env.NODE_ENV !== "production") return;
    const register = async () => {
      try {
        const reg = await navigator.serviceWorker.register("/sw.js");
        const ready = await navigator.serviceWorker.ready;
        // Let the worker store the static assets this page already loaded, so the first visit works offline too.
        const urls = performance
          .getEntriesByType("resource")
          .map((e) => e.name)
          .filter((n) => n.includes("/_next/static/"));
        (ready.active ?? reg.active)?.postMessage({ type: "CACHE_URLS", urls });
      } catch {
        /* installability / offline are progressive enhancements */
      }
    };
    if (document.readyState === "complete") void register();
    else window.addEventListener("load", () => void register(), { once: true });
  }, []);
  return null;
}
