# Stock-Predictor

> ⚠️ **Educational/experimental only. Not financial advice. No warranty. Predictions are frequently wrong.** No personalized advice is given, and this project does not hold or trade money. See the [Terms](web/app/terms/page.tsx) and [Privacy](web/app/privacy/page.tsx) pages — they are draft templates; have a lawyer review them before running a public service.

This repo contains two apps:

| Path | What | Stack |
|---|---|---|
| `web/` + `backend/` | **Installable web app (PWA)**: watchlist, charts, experimental forecasts with honest backtests | Next.js 16 (App Router, TypeScript, Tailwind 4) + FastAPI |
| `StockAnalyzerApp/` and root `*.swift` | Original **iOS SwiftUI** app (untouched by the web work) | SwiftUI, Finnhub API |

## Web app

### Architecture

```
Browser (PWA, watchlist in localStorage)
   │  fetch  NEXT_PUBLIC_API_BASE_URL
   ▼
FastAPI  backend/app
   ├─ /api/quote/{symbol}            latest daily close + change
   ├─ /api/history/{symbol}?range=   1mo|3mo|6mo|1y|2y|5y
   ├─ /api/forecast/{symbol}?horizon=1..30
   ├─ /api/search?q=
   └─ /health
   │  app/providers/ (DATA_PROVIDER): yfinance (default, no key) | twelvedata (needs key)
   │  + in-memory TTL cache with stale-if-error, upstream timeouts + bounded retries, per-IP rate limit
```

- **No accounts, no personal data.** The watchlist lives in the browser only.
- The service worker caches the app shell for installability and an offline page; API responses are never cached by it.

### Run locally

Backend (Python 3.12+):
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest                      # tests use synthetic data, no network needed
uvicorn app.main:app --reload --port 8000
```

Web (Node 20.9+, 22 recommended):
```bash
cd web
cp .env.example .env.local   # NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
npm ci
npm run dev                  # http://localhost:3000
npm run lint && npm run typecheck && npm run build
```
The service worker is only registered in production builds (`npm run build && npm start`).

Docker:
```bash
docker compose up --build    # web on :3000, api on :8000
```

### Configuration

| Variable | Where | Meaning |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | web (build time) | Public URL of the API, reachable from the browser |
| `CORS_ORIGINS` | backend | Comma-separated allowed browser origins (must include the web app URL) |
| `RATE_LIMIT_PER_MIN` | backend | Requests per client IP per minute (default 60; 0 disables) |
| `TRUST_PROXY` | backend | Set `true` only behind a proxy that sets `X-Forwarded-For`, so the limiter sees real client IPs |
| `QUOTE_TTL_S`, `HISTORY_TTL_S`, `FORECAST_TTL_S` | backend | Cache lifetimes in seconds |
| `DATA_PROVIDER` | backend | `yfinance` (default) or `twelvedata` |
| `TWELVEDATA_API_KEY` | backend | Required only when `DATA_PROVIDER=twelvedata`. Set it as a secret in your host; never commit it |
| `UPSTREAM_TIMEOUT_S` | backend | Per-attempt timeout for the data provider (default 10) |
| `UPSTREAM_RETRIES` | backend | Extra attempts for transient provider failures (default 2, exponential backoff) |
| `STALE_MAX_AGE_S` | backend | If the provider fails, serve a cached copy up to this old, flagged `stale` (default 86400) |

### Data providers

Providers live in `backend/app/providers/` behind one small interface (`BaseProvider`: `history`, `search`, `quote`), so adding another is one file plus a line in `create_provider`.

| `DATA_PROVIDER` | Needs | Notes |
|---|---|---|
| `yfinance` (default) | nothing | Unofficial Yahoo data. Free, but can rate-limit or break without notice. Dividend- and split-adjusted. |
| `twelvedata` | `TWELVEDATA_API_KEY` | [Twelve Data](https://twelvedata.com) REST API (`/time_series`, `/symbol_search`), key sent in the `Authorization` header. Free tier has daily/per-minute credit limits. Split-adjusted only. Yahoo-only symbols (`^GSPC`, `=F`, `=X`) are not supported. |

> ⚠️ **The Twelve Data provider was implemented from the public documentation and is unit-tested with mocked HTTP responses only. It has _not_ been tested against the live API (no key was available when it was written).** Try it with your own key (`DATA_PROVIDER=twelvedata TWELVEDATA_API_KEY=... uvicorn app.main:app`) and check the free-plan limits and licence terms for your use before relying on it. An invalid or unknown `DATA_PROVIDER`, or a missing key, makes the server fail at first use with a clear message.

### Errors and data freshness

Every non-2xx `/api/*` response has this shape, with codes that are stable (new ones may be added; existing ones won't be renamed):

```json
{"error": {"code": "DATA_UNAVAILABLE", "message": "…", "retryable": false, "retry_after": 30}}
```

| Code | HTTP | Meaning |
|---|---|---|
| `INVALID_SYMBOL`, `INVALID_RANGE`, `INVALID_REQUEST` | 400 / 422 | Bad input |
| `INSUFFICIENT_DATA` | 422 | Not enough history to run a forecast/backtest |
| `DATA_UNAVAILABLE` | 502 | Provider has no data or failed |
| `UPSTREAM_TIMEOUT` | 504 | Provider too slow (after retries) |
| `RATE_LIMITED` | 429 | Our per-IP limit or the provider's limit; includes `Retry-After` |

Successful quote/history/forecast responses include `data_as_of` (date of the latest bar), `fetched_at`, `is_delayed` (latest bar 2+ business days old), `stale`, and `warnings`. If the provider fails but a cached copy younger than `STALE_MAX_AGE_S` exists, that copy is returned with `stale: true` and a `{"code": "STALE_DATA"}` warning instead of an error.

The web app keeps showing the last good data (saved in the browser's `localStorage`) with a "May be outdated" label when a refresh fails, offers a **Try again** button, and shows "Waking up the server…" while a sleeping free-tier host starts (it retries automatically for about 90 seconds).

### How the forecast works (and its honest limits)

1. Daily adjusted closes → features: 1/5/10/21-day returns, 10/21-day volatility, RSI(14), MACD histogram, distance to the 50-day average.
2. Target: log return over the next *h* trading days. Model: a small, regularised gradient-boosting regressor (fixed seed).
3. **Walk-forward validation**: expanding window, chronological, with an *h*-day embargo so training labels never overlap the test block. Results are compared against the **naive persistence baseline** ("price stays flat").
4. The 80% interval is the empirical 10th–90th percentile of the out-of-sample errors. Every forecast response includes the backtest metrics and a `disclaimer` field.
5. The UI turns the backtest into plain language: how much lower/higher the model's error was than "price stays flat" (with a 90% block-bootstrap range that accounts for overlapping windows), how often it got the direction right versus a coin flip and versus "always up", and a clear **"Not better than guessing" / "Inconclusive" / "Better than guessing — in the past"** verdict. "Better" is only claimed when the whole 90% range is above zero. Small samples are flagged.

Limits you should understand:
- Short-horizon stock returns are close to unpredictable. Most of the time the model **does not beat** the naive baseline, and the UI says so when that happens.
- The interval ignores regime changes, earnings, news and crashes; real outcomes fall outside it regularly. Overlapping windows make backtest points correlated, so metrics are indicative only.
- Data is unofficial, daily, possibly delayed, and the upstream provider can rate-limit or break `yfinance` at any time (the API then returns a clear `502 data_unavailable`). For production use, switch to a licensed data provider by implementing the `Provider` protocol in `backend/app/data.py`.
- No transaction-cost or survivorship modelling; this is not a trading system.

### Deploying

You choose the hosting; nothing is deployed by this repo.
- **Web:** any Node host or platform (Vercel, Netlify, Cloudflare, Fly.io, or a container via `web/Dockerfile`). Set `NEXT_PUBLIC_API_BASE_URL` at **build** time. PWAs require HTTPS.
- **API:** any container host (`backend/Dockerfile`: Fly.io, Render, Cloud Run, a VPS). Set `CORS_ORIGINS` to your web origin(s). The cache and rate limiter are in-memory, so run a single instance or move them to Redis before scaling out.
- Before going public: have the Terms/Privacy drafts reviewed by a lawyer, check the data provider's terms for your use case, and update the privacy notice if you add logging or analytics.

#### Live demo on Render (free tier)

- Web: https://stock-predictor-web-ts7p.onrender.com/
- API: https://stock-predictor-api-2dnn.onrender.com/health

Render's free tier **puts services to sleep after ~15 minutes of inactivity**, so the first request after a pause can take a minute or more. The workflow [`.github/workflows/keepalive.yml`](.github/workflows/keepalive.yml) pings both URLs every 10 minutes (with retries) to mitigate this. It is best-effort only: GitHub scheduled runs can be delayed or skipped, and GitHub **disables scheduled workflows after 60 days without repository activity** (re-enable it from the Actions tab). A paid Render instance type is the reliable fix.

## iOS app

A small SwiftUI app that shows a watchlist (AAPL, GOOGL, TSLA) with the latest price and daily % change, plus a 7-day chart, using [Finnhub](https://finnhub.io). Unchanged by the web work. Requires Xcode 14+ / iOS 16+ and a free Finnhub key set in `NetworkManager.swift` (`apiKey`). Do not commit your real key.

Known issue: Swift sources are split between the repo root and `StockAnalyzerApp/`; consolidating them in Xcode is a pending follow-up.

## License

MIT — see [LICENSE](LICENSE).
