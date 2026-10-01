// Plain (server-safe) module: imported by both the server layout and client components.
// The gate text lives here so the acknowledgement version is derived from it:
// editing any line automatically re-prompts every user.
export const GATE_POINTS = [
  "This app is educational and experimental. Nothing here is financial, investment, legal or tax advice.",
  "Predictions are frequently wrong, and past performance does not predict future results. You can lose money by acting on them.",
  "No personalized advice is given. We don't hold, trade or manage anyone's money, and there is no warranty of any kind.",
] as const;

function hash(s: string): string {
  let h = 5381;
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0;
  return (h >>> 0).toString(36);
}

export const ACK_KEY = "disclaimer-ack";
export const ACK_VERSION = `v1-${hash(GATE_POINTS.join("|"))}`;

/** Inline script run before first paint: marks <html data-ack="1"> if already acknowledged. */
export const ackBootScript = `try{if(localStorage.getItem(${JSON.stringify(ACK_KEY)})===${JSON.stringify(ACK_VERSION)})document.documentElement.dataset.ack="1"}catch(e){}`;
