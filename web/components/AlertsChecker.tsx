"use client";
import { useEffect, useRef, useState } from "react";
import { apiGet } from "@/lib/api";
import { type Alert, describeAlert, evaluateAlerts, markTriggered, useAlerts } from "@/lib/alerts";
import type { Quote } from "@/lib/types";

const CHECK_EVERY_MS = 60_000;

type Notice = { id: string; text: string };

/**
 * Checks active alerts against fresh quotes while the app is open (on load, every minute, when the tab becomes
 * visible again and when the connection returns). There is no server or push service: if the app is closed,
 * nothing is checked. Shows an in-app notice and, only if the user granted permission, a browser notification.
 */
export function AlertsChecker() {
  const alerts = useAlerts();
  const [notices, setNotices] = useState<Notice[]>([]);
  const ref = useRef<Alert[]>(alerts);
  useEffect(() => {
    ref.current = alerts;
  }, [alerts]);
  const activeKey = alerts.filter((a) => !a.triggeredAt).map((a) => a.id).sort().join(",");

  useEffect(() => {
    if (!activeKey) return;
    let cancelled = false;
    const ctrl = new AbortController();

    const check = async () => {
      const active = ref.current.filter((a) => !a.triggeredAt);
      const symbols = [...new Set(active.map((a) => a.symbol))];
      if (!symbols.length || (typeof navigator !== "undefined" && !navigator.onLine)) return;
      const prices: Record<string, number> = {};
      await Promise.all(
        symbols.map(async (s) => {
          try {
            const q = await apiGet<Quote>(`/api/quote/${encodeURIComponent(s)}`, ctrl.signal, 20_000);
            if (!q.stale) prices[s] = q.price; // never fire on data flagged as stale
          } catch {
            /* transient: try again at the next check */
          }
        }),
      );
      if (cancelled) return;
      const hits = evaluateAlerts(ref.current, prices);
      if (!hits.length) return;
      markTriggered(hits.map((h) => ({ id: h.alert.id, price: h.price })));
      setNotices((n) => [
        ...n,
        ...hits.map((h) => ({ id: h.alert.id, text: `Alert: ${describeAlert(h.alert)} — latest price $${h.price.toFixed(2)}` })),
      ]);
      if ("Notification" in window && Notification.permission === "granted") {
        for (const h of hits) {
          try {
            new Notification("Price alert", { body: `${describeAlert(h.alert)} — now $${h.price.toFixed(2)}`, tag: h.alert.id, icon: "/icon-192.png" });
          } catch {
            /* some browsers only allow notifications via a service worker */
          }
        }
      }
    };

    void check();
    const timer = setInterval(() => void check(), CHECK_EVERY_MS);
    const onVisible = () => document.visibilityState === "visible" && void check();
    const onOnline = () => void check();
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("online", onOnline);
    return () => {
      cancelled = true;
      ctrl.abort();
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("online", onOnline);
    };
  }, [activeKey]);

  return (
    <div aria-live="polite" role="region" aria-label="Alert notices" className="fixed inset-x-0 bottom-0 z-40 mx-auto flex max-w-md flex-col gap-2 p-3">
      {notices.map((n) => (
        <div key={n.id} className="flex items-start justify-between gap-3 rounded-md border border-blue-700 bg-blue-50 px-3 py-2 text-sm text-blue-950 shadow-lg dark:border-blue-400 dark:bg-blue-950 dark:text-blue-100">
          <span><span aria-hidden="true">🔔 </span>{n.text}</span>
          <button onClick={() => setNotices((l) => l.filter((x) => x.id !== n.id))} className="rounded px-2 font-semibold underline" aria-label={`Dismiss: ${n.text}`}>Dismiss</button>
        </div>
      ))}
    </div>
  );
}
