"use client";
import { useEffect } from "react";
import { reportError } from "@/lib/report";

export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => reportError(error), [error]);
  return (
    <main id="main" tabIndex={-1} className="mx-auto max-w-lg space-y-3 px-4 py-12 text-center">
      <h1 className="text-xl font-bold">Something went wrong</h1>
      <p className="text-sm">The page hit an unexpected error. Your watchlist and alerts are stored on this device and are not affected.</p>
      <button onClick={reset} className="rounded bg-blue-700 px-4 py-2 font-semibold text-white hover:bg-blue-800">Try again</button>
    </main>
  );
}
