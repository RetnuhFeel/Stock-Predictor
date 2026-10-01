import type { Metadata } from "next";
import { Page } from "@/components/Prose";

export const metadata: Metadata = { title: "Privacy — Stock Predictor" };

export default function Privacy() {
  return (
    <Page title="Privacy Notice">
      <p>Last updated: 2026-10-01. <strong>Draft — this notice still needs review by a qualified lawyer</strong> before you rely on it or operate this service publicly.</p>
      <h2>Summary</h2>
      <ul>
        <li>No accounts, sign-in or cookies, and no advertising, fingerprinting or third-party analytics trackers.</li>
        <li>Your named lists of tickers (and which list you last viewed), price alerts, theme choice and last-seen data are stored only on your device (<code>localStorage</code>) and are never sent to a server.</li>
        <li>The server keeps anonymous, aggregate usage counters in memory and short-lived technical logs without IP addresses (details below).</li>
      </ul>
      <h2>What is stored on your device</h2>
      <ul>
        <li>Your lists (names and ticker symbols) and the last-selected list, price alerts (symbol, direction, target price, whether it triggered), theme and your acknowledgement of the disclaimer.</li>
        <li>A copy of the most recent data you viewed (quotes, charts, forecasts, headlines) so the app can show it, labelled as possibly outdated, when you are offline or the server is slow.</li>
        <li>A service worker caches the app&apos;s own pages and static files for offline use. It does not cache API responses or errors.</li>
      </ul>
      <p>Clear your browser&apos;s site data to delete all of this. Price alerts only work while the app is open; there is no push server, and if you enable browser notifications the permission stays on your device.</p>
      <h2>What the servers see and keep</h2>
      <ul>
        <li><strong>Requests:</strong> viewing a symbol sends the ticker symbol (or search text, or the horizon/range options) to the API.</li>
        <li><strong>Application logs (structured JSON):</strong> a random request ID, HTTP method, route path, status code and duration. We do not log IP addresses, user agents, query strings or cookies.</li>
        <li><strong>Aggregate counters</strong> (in memory, reset on restart): request counts by route and status, error counts, latency summaries. No per-user data. They are readable only with an administrator token, and are disabled unless the operator sets one.</li>
        <li><strong>Rate limiting:</strong> the limiter briefly holds a client network address in memory to count requests per minute; it is not written to logs or stored.</li>
        <li><strong>Hosting provider:</strong> your host (for example Render) and its network may keep their own logs, including IP addresses, under their own policies.</li>
      </ul>
      <h2>Error reports (optional, off by default)</h2>
      <p>If the operator enables it, the app may send a small error report when something breaks: the error message, a stack trace and the page path. It contains no lists, alerts, IP address or other personal data, is limited in size and frequency, and is written to the server log. If the operator configures an optional error-tracking service (Sentry), reports go to that service under its own privacy policy.</p>
      <h2>Third parties</h2>
      <p>The API retrieves market data and headlines from Yahoo Finance (via the open-source <code>yfinance</code> library). Only ticker symbols and search terms are sent upstream, not information about you, but the provider sees the API server&apos;s requests. News headlines link out to third-party sites, which have their own privacy practices.</p>
      <h2>Cookies</h2>
      <p>No cookies are set.</p>
      <h2>Operators</h2>
      <p>If you deploy this app and add logging, analytics or accounts beyond what is described here, you must update this notice and comply with the privacy laws that apply to you.</p>
    </Page>
  );
}
