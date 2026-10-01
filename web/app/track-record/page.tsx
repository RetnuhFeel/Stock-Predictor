import type { Metadata } from "next";
import { Page } from "@/components/Prose";
import { TrackRecord } from "@/components/TrackRecord";

export const metadata: Metadata = {
  title: "Track record — Stock Predictor",
  description: "A public, pre-registered log of the model's real forecasts and how they turned out. Educational, not financial advice.",
};

export default function TrackRecordPage() {
  return (
    <Page title="Live track record" draft={false}>
      <p role="note" className="rounded-md border border-amber-300 bg-amber-50 p-3 text-amber-950 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-100">
        <strong>Experimental, educational, not financial advice.</strong> A short or empty record proves nothing. Past results do not predict future ones.
      </p>
      <TrackRecord />
    </Page>
  );
}
