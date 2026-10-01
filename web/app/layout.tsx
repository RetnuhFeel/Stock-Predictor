import type { Metadata, Viewport } from "next";
import "./globals.css";
import { DisclaimerBanner, Footer } from "@/components/Disclaimer";
import { ErrorReporter } from "@/components/ErrorReporter";
import { ServiceWorker } from "@/components/ServiceWorker";
import { ackBootScript } from "@/lib/ackConfig";

export const metadata: Metadata = {
  title: "Stock Predictor (experimental)",
  description: "Educational stock charts and experimental forecasts with honest backtests. Not financial advice.",
  applicationName: "Stock Predictor",
  appleWebApp: { capable: true, title: "Stock Predictor", statusBarStyle: "default" },
  icons: { icon: "/icon-192.png", apple: "/apple-touch-icon.png" },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f8fafc" },
    { media: "(prefers-color-scheme: dark)", color: "#020617" },
  ],
  width: "device-width",
  initialScale: 1,
};

// Runs before first paint to avoid a flash of the wrong theme.
const themeScript = `try{var t=localStorage.getItem('theme');if(t==='dark'||(!t&&matchMedia('(prefers-color-scheme: dark)').matches))document.documentElement.classList.add('dark')}catch(e){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript + ackBootScript }} />
      </head>
      <body>
        <a href="#main" className="skip-link">Skip to main content</a>
        <DisclaimerBanner />
        {children}
        <Footer />
        <ServiceWorker />
        <ErrorReporter />
      </body>
    </html>
  );
}
