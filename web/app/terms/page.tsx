import type { Metadata } from "next";
import { Page } from "@/components/Prose";

export const metadata: Metadata = { title: "Terms of Use — Stock Predictor" };

export default function Terms() {
  return (
    <Page title="Terms of Use">
      <p>Last updated: 2026-10-01</p>
      <h2>1. Educational and experimental use only</h2>
      <p>Stock Predictor is an educational, experimental project. It displays market data and statistical model outputs for learning purposes only.</p>
      <h2>2. Not financial advice</h2>
      <p>Nothing here is investment, financial, legal or tax advice, a recommendation, or an offer or solicitation to buy or sell any security. No advice is tailored to your circumstances. Consult a licensed professional before making financial decisions.</p>
      <h2>3. Predictions are frequently wrong</h2>
      <p>Forecasts come from simple statistical models trained on past prices. Markets are noisy and past performance does not predict future results. The backtest shown next to each forecast is itself an estimate and may overstate real-world performance. You may lose money if you act on this information.</p>
      <h2>4. We do not hold or trade money</h2>
      <p>This service does not custody funds, execute trades, broker securities or manage portfolios.</p>
      <h2>5. Data</h2>
      <p>Market data comes from third-party, unofficial sources, may be delayed, incomplete or incorrect, and may be unavailable at any time.</p>
      <h2>6. No warranty; limitation of liability</h2>
      <p>THE SERVICE IS PROVIDED “AS IS” AND “AS AVAILABLE”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED. TO THE MAXIMUM EXTENT PERMITTED BY LAW, THE AUTHORS AND OPERATORS ARE NOT LIABLE FOR ANY LOSS OR DAMAGE ARISING FROM USE OF, OR INABILITY TO USE, THE SERVICE. Some jurisdictions do not allow these limits; they apply only to the extent permitted.</p>
      <h2>7. Open source</h2>
      <p>The source code is released under the MIT License (see the repository).</p>
      <h2>8. Changes</h2>
      <p>These terms may change at any time. Continued use means you accept the current version.</p>
    </Page>
  );
}
