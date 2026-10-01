"use client";
import { useEffect } from "react";
import { REPORTING_ENABLED, reportError } from "@/lib/report";

export function ErrorReporter() {
  useEffect(() => {
    if (!REPORTING_ENABLED) return;
    const onError = (e: ErrorEvent) => reportError(e.error ?? e.message);
    const onRejection = (e: PromiseRejectionEvent) => reportError(e.reason);
    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onRejection);
    return () => {
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onRejection);
    };
  }, []);
  return null;
}
