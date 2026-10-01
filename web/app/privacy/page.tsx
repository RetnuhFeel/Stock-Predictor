import type { Metadata } from "next";
import { Page } from "@/components/Prose";

export const metadata: Metadata = { title: "Privacy — Stock Predictor" };

export default function Privacy() {
  return (
    <Page title="Privacy Notice">
      <p>Last updated: 2026-10-01</p>
      <h2>Summary</h2>
      <ul>
        <li>No accounts, sign-in, or personal data collected by the app.</li>
        <li>Your watchlist and theme preference are stored only on your device (browser <code>localStorage</code>) and are never sent to a server.</li>
        <li>No advertising or analytics trackers are included.</li>
      </ul>
      <h2>What the servers see</h2>
      <p>When you view a symbol, your browser requests data from the API, which includes the ticker symbol you looked at. Like any web server, the host may log standard technical data (IP address, user agent, timestamp) for security and rate limiting. The built-in rate limiter keeps IP addresses in memory only, briefly. Your hosting provider may keep its own logs; operators should document this.</p>
      <h2>Third parties</h2>
      <p>The API retrieves market data from a third-party provider (Yahoo Finance via the open-source <code>yfinance</code> library). Only ticker symbols and search terms are sent upstream, not information about you, but the provider sees the API server&apos;s requests.</p>
      <h2>Cookies and storage</h2>
      <p>No cookies are set. The service worker caches static app files for offline use.</p>
      <h2>Your choices</h2>
      <p>Clear your browser&apos;s site data to delete your watchlist and preferences.</p>
      <h2>Operators</h2>
      <p>If you deploy this app and add logging, analytics or accounts, you must update this notice and comply with the privacy laws that apply to you.</p>
    </Page>
  );
}
