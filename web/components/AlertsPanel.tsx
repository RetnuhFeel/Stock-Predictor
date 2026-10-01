"use client";
import { useId, useState, useSyncExternalStore } from "react";
import { addAlert, describeAlert, MAX_ALERTS, rearmAlert, removeAlert, useAlerts } from "@/lib/alerts";

const noop = () => () => undefined;
const permission = () => (typeof Notification === "undefined" ? "unsupported" : Notification.permission);

export function AlertsPanel({ symbol }: { symbol: string | null }) {
  const alerts = useAlerts();
  const [dir, setDir] = useState<"above" | "below">("above");
  const [price, setPrice] = useState("");
  const [error, setError] = useState("");
  const [, bump] = useState(0);
  const perm = useSyncExternalStore(noop, permission, () => "unsupported");
  const priceId = useId();
  const dirId = useId();

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!symbol) return;
    const res = addAlert(symbol, dir, Number(price));
    if (res.ok) {
      setPrice("");
      setError("");
    } else setError(res.reason);
  }

  async function enableNotifications() {
    try {
      await Notification.requestPermission();
    } finally {
      bump((n) => n + 1);
    }
  }

  return (
    <section aria-labelledby="alerts-title" className="space-y-3 rounded-md border border-slate-300 p-3 dark:border-slate-700">
      <h2 id="alerts-title" className="font-semibold">Price alerts</h2>
      <p className="text-xs text-slate-600 dark:text-slate-300">
        Alerts are saved only on this device and <strong>only fire while this app is open</strong> (checked about once a minute).
        There is no push server, so you won&apos;t be notified when it&apos;s closed.
      </p>

      {symbol ? (
        <form onSubmit={onSubmit} className="space-y-2" aria-label={`Add alert for ${symbol}`}>
          <div className="flex flex-wrap items-end gap-2">
            <div>
              <label htmlFor={dirId} className="block text-xs font-medium">{symbol} is</label>
              <select id={dirId} value={dir} onChange={(e) => setDir(e.target.value as "above" | "below")} className="rounded border border-slate-400 bg-white px-2 py-1 text-sm dark:border-slate-600 dark:bg-slate-900">
                <option value="above">at or above</option>
                <option value="below">at or below</option>
              </select>
            </div>
            <div className="min-w-24 flex-1">
              <label htmlFor={priceId} className="block text-xs font-medium">Price (USD)</label>
              <input id={priceId} inputMode="decimal" type="number" step="0.01" min="0.01" value={price} onChange={(e) => setPrice(e.target.value)}
                className="w-full rounded border border-slate-400 bg-white px-2 py-1 text-sm dark:border-slate-600 dark:bg-slate-900" required />
            </div>
            <button type="submit" className="rounded bg-blue-700 px-3 py-1.5 text-sm font-semibold text-white hover:bg-blue-800">Add alert</button>
          </div>
          {error && <p role="alert" className="text-xs text-red-700 dark:text-red-300">{error}</p>}
        </form>
      ) : (
        <p className="text-xs">Select a symbol to add an alert.</p>
      )}

      {alerts.length > 0 && (
        <ul className="space-y-1 text-sm" aria-label="Your alerts">
          {alerts.map((a) => (
            <li key={a.id} className="flex items-center justify-between gap-2 rounded bg-slate-100 px-2 py-1 dark:bg-slate-800">
              <span>
                {describeAlert(a)}
                {a.triggeredAt ? <strong className="ml-2 text-green-800 dark:text-green-300">✓ Triggered at ${a.triggeredPrice?.toFixed(2)}</strong> : <span className="ml-2 text-slate-600 dark:text-slate-300">(waiting)</span>}
              </span>
              <span className="flex gap-2 text-xs">
                {a.triggeredAt && <button onClick={() => rearmAlert(a.id)} className="underline">Re-arm</button>}
                <button onClick={() => removeAlert(a.id)} className="underline" aria-label={`Remove alert ${describeAlert(a)}`}>Remove</button>
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="text-xs text-slate-600 dark:text-slate-300">{alerts.length}/{MAX_ALERTS} alerts used.</p>

      {perm === "default" && (
        <button onClick={enableNotifications} className="rounded border border-slate-400 px-2 py-1 text-xs hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-800">
          Enable browser notifications (optional)
        </button>
      )}
      {perm === "granted" && <p className="text-xs">Browser notifications are on (while the app is open).</p>}
      {perm === "denied" && <p className="text-xs">Browser notifications are blocked; you&apos;ll see in-app notices only.</p>}
    </section>
  );
}
