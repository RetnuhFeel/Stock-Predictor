"use client";
import Link from "next/link";
import { useEffect, useRef } from "react";
import { acknowledge, useAcknowledged } from "@/lib/ack";
import { GATE_POINTS } from "@/lib/ackConfig";

const FOCUSABLE = 'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** First-visit modal gate. Rendered only on the app page, so /terms and /privacy stay reachable. */
export function DisclaimerGate() {
  const acked = useAcknowledged();
  if (acked) return null;
  return <GateDialog />;
}

function GateDialog() {
  const ref = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const html = document.documentElement;
    const overflow = html.style.overflow;
    html.style.overflow = "hidden";
    button.current?.focus();
    return () => {
      html.style.overflow = overflow;
      previous?.focus?.();
    };
  }, []);

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      e.preventDefault(); // deliberately NOT dismissable
      return;
    }
    if (e.key !== "Tab") return;
    const items = Array.from(ref.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []);
    if (items.length === 0) return;
    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement;
    if (e.shiftKey && (active === first || !ref.current?.contains(active))) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && (active === last || !ref.current?.contains(active))) {
      e.preventDefault();
      first.focus();
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4" onKeyDown={onKeyDown}>
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby="gate-title"
        aria-describedby="gate-desc"
        className="max-h-full w-full max-w-lg overflow-auto rounded-lg bg-white p-6 shadow-xl dark:bg-slate-900"
      >
        <h2 id="gate-title" className="text-xl font-bold">⚠️ Before you continue</h2>
        <div id="gate-desc" className="mt-3 space-y-3 text-sm">
          <p className="font-semibold">Stock Predictor is NOT financial advice.</p>
          <ul className="list-disc space-y-2 pl-5">
            {GATE_POINTS.map((p) => (<li key={p}>{p}</li>))}
          </ul>
          <p>
            Please read the <Link href="/terms" className="text-blue-600 underline dark:text-blue-400">Terms</Link> and{" "}
            <Link href="/privacy" className="text-blue-600 underline dark:text-blue-400">Privacy notice</Link>{" "}
            (you can open them without accepting). No accounts or personal data are collected.
          </p>
        </div>
        <button
          ref={button}
          onClick={acknowledge}
          className="mt-5 w-full rounded-md bg-blue-600 px-4 py-2 font-semibold text-white hover:bg-blue-700 focus:outline-2 focus:outline-offset-2 focus:outline-blue-600"
        >
          I understand
        </button>
      </div>
    </div>
  );
}
