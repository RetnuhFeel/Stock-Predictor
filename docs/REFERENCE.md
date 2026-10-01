# Reference

Detailed configuration, API behaviour and operations notes. For the overview see the [README](../README.md); for design rationale see [ARCHITECTURE.md](ARCHITECTURE.md).

> ⚠️ Educational/experimental only. Not financial advice. Predictions are frequently wrong.

## Configuration

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
| `NEWS_TTL_S` | backend | Cache lifetime for headlines (default 600) |
| `LOG_FORMAT`, `LOG_LEVEL` | backend | `json` (default) or `text`; log level (default `INFO`) |
| `ADMIN_TOKEN` | backend | Enables `GET /api/_stats` (send `Authorization: Bearer <token>`). **Unset = endpoint returns 404.** Use a long random value; set it as a secret |
| `CLIENT_ERROR_LOGGING` | backend | `true` enables `POST /api/_client-error` (default off → 404) |
| `CLIENT_ERROR_RATE_PER_MIN` | backend | Client error reports accepted per minute, globally (default 10; reports are also capped at 4096 bytes) |
| `SENTRY_DSN` | backend | Optional. Only used if you also `pip install sentry-sdk` (not in `requirements.txt`); no PII is sent |
| `MODEL_REPORT_TTL_S` | backend | Cache lifetime of the public `/api/model-report` (default 21600 = 6 h) |
| `MODEL_REPORT_RATE_PER_MIN` | backend | Stricter per-client limit for `/api/model-report` (default 6) |
| `LOG_TASK_TOKEN` | backend | Enables `POST /api/_tasks/run-prediction-log` (send `Authorization: Bearer <token>`). **Unset = endpoint returns 404.** Use a long random value; set it as a secret |
| `DATABASE_URL` | backend | Storage for the prediction log. Unset = SQLite file in the temp dir (**erased on every redeploy/restart on Render's free tier**). Set a Postgres URL (`postgresql://…`) for durable storage |
| `PREDICTION_LOG_TTL_S` | backend | Cache lifetime of `GET /api/prediction-log` (default 120) |
| `MODELS_TTL_S` | backend | Cache lifetime of model comparison / volatility results (default 3600) |
| `TRENDING_TTL_S` | backend | Cache lifetime of `GET /api/trending` (default 1200 = 20 min). Also `TRENDING_MIN_COVERAGE` (default 0.5), `TRENDING_MAX_DAYS` (10), `TRENDING_MAX_LIMIT` (10) |
| `HEAVY_RATE_PER_MIN` | backend | Per-client limit for `/api/trending`, `/api/compare-models` and `/api/volatility` (default 20, on top of the global limit) |
| `NEXT_PUBLIC_SUPPORT_URL` | web (build time) | Optional `https://` URL for a "Support this project" footer link. Unset = nothing is shown |
| `NEXT_PUBLIC_ERROR_REPORTING` | web (build time) | `true` makes the browser POST sanitised error reports (message, stack, path) to the API. Needs `CLIENT_ERROR_LOGGING=true` on the API |

## API endpoints

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness + active provider |
| `GET /api/quote/{symbol}` | Latest daily close and change |
| `GET /api/history/{symbol}?range=1mo\|3mo\|6mo\|1y\|2y\|5y` | Daily closes |
| `GET /api/forecast/{symbol}?horizon=1..60` | Experimental forecast + per-horizon backtest |
| `GET /api/compare?symbols=A,B&range=` | 2–5 symbols, normalised % change |
| `GET /api/news/{symbol}` | Headlines (link-out only) |
| `GET /api/model-report` | Cached backtest report card for SPY, AAPL, MSFT, NVDA, TSLA at 5 days (fixed list, no user input, own rate limit) |
| `GET /api/compare-models/{symbol}?horizon=1..60` | Naive, drift, EWMA, ridge-AR and gradient boosting, each walk-forward (+ embargo) vs. naive: error, skill with 90% bootstrap range, direction hit rate, n tests. Cached, own rate limit |
| `GET /api/volatility/{symbol}?horizon=1..60` | Realised-volatility forecast (EWMA headline, HAR-style, vs. "recent 21-day vol"), annualised vol, 1-sigma risk range, backtest coverage |
| `GET /api/trending?days=3&limit=5` | Top gainers by close-to-close return over the last `days` trading days (1–10, default 3) from the fixed universe in `backend/app/universe.py`. Returns `items[{rank, symbol, name, return_percent, last_close, as_of}]`, `universe_size`, `evaluated`, `method`, `note`, `disclaimer` and the usual freshness fields. One batched provider download, cached 20 min, stale-if-error; tickers that fail or lag behind the latest trading day are skipped; too little coverage gives `503 DATA_UNAVAILABLE` (retryable). Own (heavy) rate limit |
| `GET /api/prediction-log?limit=&offset=&symbol=&status=` | Public, paginated, cached live prediction log + live scorecard (resolved rows only) |
| `POST /api/_tasks/run-prediction-log` | Scheduled job: log predictions for the fixed ticker list, resolve old ones. Needs `LOG_TASK_TOKEN` (disabled otherwise) |
| `GET /api/search?q=` | Symbol search |
| `GET /api/_stats`, `POST /api/_client-error` | Opt-in observability (disabled unless configured) |

Interactive docs: `/docs` (Swagger UI) on any running API.

## Prediction log (live track record)

- **What is recorded:** once per weekday (GitHub Actions cron, 22:30 UTC, after the US close) the API stores its 5-day forecast for a **fixed ticker list** (`SPY, AAPL, MSFT, NVDA, TSLA`): prediction time, last price, predicted return, 80% interval and a snapshot of the backtest verdict. Forecasts served to visitors are **never** logged, so storage is bounded and nothing about any visitor is recorded. Stale data is never logged (it could already contain the outcome).
- **Immutability:** a row is inserted once per (symbol, horizon, base date); only its outcome fields are filled in later, once. Each row stores a SHA-256 hash chained to the previous row, and `/api/prediction-log` reports `chain_ok`. This is tamper-*evidence*, not proof: whoever controls the database could rebuild the chain.
- **Resolution:** when `horizon` trading days have passed, the realised log return is computed from the same adjusted price series for both ends.
- **Scorecard:** live results only (never mixed with backtests): skill vs. "flat" (one score per forecast date so same-day tickers aren't counted as independent), direction hit rate vs. "always up", 80% interval coverage. No verdict is given below 30 independent periods ("too early"), which takes months.
- **Storage and data loss:** SQLite by default. **Render's free tier has an ephemeral disk: the SQLite log is erased on every redeploy or restart**, and the track-record page says so. For a durable record set `DATABASE_URL` to a Postgres URL (e.g. a free Render Postgres, which has its own expiry limits on the free plan, or Neon/Supabase). Only SQLite is covered by automated tests; the Postgres path uses the same SQLAlchemy code but is untested here.
- **Scheduler setup (you must do this):** in the GitHub repo, add the secret **`LOG_TASK_TOKEN`** (Settings → Secrets and variables → Actions → Secrets) and the variable **`API_BASE_URL`** (… → Variables), e.g. `https://stock-predictor-api-2dnn.onrender.com`. Set the *same* `LOG_TASK_TOKEN` value as an env var on the Render API service. Until both exist the workflow exits with a notice and the endpoint returns 404. You can also run it by hand from the Actions tab (*Log and resolve predictions → Run workflow*).
- **Privacy:** the log contains only market forecasts for public tickers; no visitor data. The privacy page needed no change.

## Models and volatility

- **Point-forecast models** (`backend/app/models.py`, one small interface): naive (flat), drift (average past return), EWMA mean, ridge autoregression on past returns/volatility, gradient boosting (the main forecast). All are judged by the same expanding-window walk-forward with a gap of at least `horizon` days, by RMSE skill vs. naive with a block-bootstrap 90% range. "Better" needs the whole range above zero. Because several models are tried, a single "win" can be luck; the response says so and the live track record is the real test.
- **Volatility** (`backend/app/volatility.py`): target is realised volatility over the horizon. Naive = trailing 21-day vol; EWMA (RiskMetrics λ=0.94, headline model fixed in advance); HAR-style regression of log future vol on 5/22/66-day trailing vol. Errors are on the log scale. The "risk range" is 1-sigma (about 68% if returns were normal); the backtest coverage shows how often reality stayed inside. No GARCH: `arch`/`statsmodels` were skipped to keep the image light.
- **Compute on the free tier:** each request is one symbol with cheap models (about 0.5 s locally), cached per symbol/horizon/day, with its own rate limit.
- **Not included on purpose:** neural or pretrained time-series models (e.g. Chronos, TimesFM) are too heavy for the API. Evaluate them offline with the same walk-forward + embargo harness (`compare_models` accepts any object with a `predict(ctx, train_end, test)` method), and add one here only if it beats the baselines in a log you can show.

## Extras

- **Price alerts** (web): per symbol, "at or above / at or below" a price. Stored only in this browser's `localStorage` (max 20), no accounts. They are checked on load, about once a minute, when the tab becomes visible and when you come back online — **only while the app is open**; there is no push server, so a closed app notifies nothing. An in-app notice is always shown; a browser notification is shown only if you grant permission. Alerts never fire on data flagged `stale`.
- **Compare** (web + `GET /api/compare?symbols=AAPL,MSFT&range=6mo`): 2–5 symbols, normalised to % change from the first common date. Symbols that fail are listed in `failed` and the rest are still returned. The chart uses different dash patterns (not colour alone) and has a data table.
- **Forecast horizon**: `GET /api/forecast/{symbol}?horizon=N`, `N` in 1–60 trading days (`422 INVALID_REQUEST` otherwise). Backtest and verdict are computed **per horizon** with an embargo of at least `N` days (reported as `embargo_days`). Longer horizons give wider intervals and far fewer independent test periods, which the UI says plainly.
- **News** (`GET /api/news/{symbol}`): headline, source, link and time only (via the active provider; Yahoo for `yfinance`, nothing for providers without news). Article text is never fetched. Shown as "context, not a signal"; an empty list is a normal response.

- **Lists and Trending** (web + `GET /api/trending`): the default list, "Trending (3-day)", is read-only and filled from the endpoint; it shows loading, error and "may be outdated" states and falls back to the last copy saved on the device. User lists are stored in `localStorage` (`lists.v2`, versioned; the old `watchlist.v1` is migrated once into "My watchlist" and left untouched). Limits: 20 lists, 50 tickers per list, 40-character names; symbols are upper-cased and validated; corrupt or oversized saved data falls back to defaults, and a full/blocked storage shows a warning instead of crashing.
  - **Universe:** a static, curated list of ~106 liquid US large caps in `backend/app/universe.py` (edit it and redeploy to change it). Stocks outside it can never appear in Trending.
  - **Limitations:** it ranks only past 3-day price change, so it is a momentum screen and **not a recommendation, signal or prediction**; gains often partly reverse. Data comes from Yahoo via `yfinance`, which is unofficial, can be delayed or rate-limited (then you get cached/stale data or a clear error). The server cache is in-memory, per instance and lost on restart, so the first request after a cold start can take several seconds. The ranking ignores splits/dividends beyond what adjusted closes provide.

## Observability and privacy

- Structured JSON logs (one line per request: request ID, method, route path, status, duration). **No IP addresses, user agents or query strings.** Every response carries `X-Request-ID` (a caller-supplied value is accepted only if it is a short harmless token).
- `GET /api/_stats` (admin token required): in-memory aggregate counters by route/status/error code and latency summaries; reset on restart; no per-user data.
- `POST /api/_client-error` (opt-in): accepts `{message, stack, route}`, scrubs URLs/emails/tokens, truncates, rate-limits and writes one log line. Returns 204.
- Sentry: backend support is optional (`SENTRY_DSN` + `pip install sentry-sdk`). **Web-side Sentry (`NEXT_PUBLIC_SENTRY_DSN`) is intentionally not included**: `@sentry/nextjs` adds a large dependency and build plugin. Use the built-in reporter above, or add it as a follow-up.
- No cookies and no fingerprinting. The `/privacy` page describes this; it is a **draft that still needs lawyer review**.

## Offline and accessibility

- The service worker caches the app shell and static assets and serves them offline; the watchlist shows the last data saved on the device with an "offline / may be outdated" label. API requests are never cached by the service worker and error responses are never stored.
- Accessibility: skip link, keyboard-operable controls with visible focus, `aria-pressed`/labels, text tables for charts, reduced-motion support, light/dark contrast. Automated axe-core checks (light and dark, main views) run in CI via `web/e2e/smoke.mjs` against a mocked API. `web/e2e/run.mjs` is a fuller optional script against a real backend (alerts, offline, error handling; needs network access to Yahoo data). Automated checks don't replace testing with real assistive technology.

## Data providers

Providers live in `backend/app/providers/` behind one small interface (`BaseProvider`: `history`, `search`, `quote`), so adding another is one file plus a line in `create_provider`.

| `DATA_PROVIDER` | Needs | Notes |
|---|---|---|
| `yfinance` (default) | nothing | Unofficial Yahoo data. Free, but can rate-limit or break without notice. Dividend- and split-adjusted. |
| `twelvedata` | `TWELVEDATA_API_KEY` | [Twelve Data](https://twelvedata.com) REST API (`/time_series`, `/symbol_search`), key sent in the `Authorization` header. Free tier has daily/per-minute credit limits. Split-adjusted only. Yahoo-only symbols (`^GSPC`, `=F`, `=X`) are not supported. |

> ⚠️ **The Twelve Data provider was implemented from the public documentation and is unit-tested with mocked HTTP responses only. It has _not_ been tested against the live API (no key was available when it was written).** Try it with your own key (`DATA_PROVIDER=twelvedata TWELVEDATA_API_KEY=... uvicorn app.main:app`) and check the free-plan limits and licence terms for your use before relying on it. An invalid or unknown `DATA_PROVIDER`, or a missing key, makes the server fail at first use with a clear message.

## Errors and data freshness

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

## Custom domain (Render)

Docs only; nothing here is configured by the repo.
1. Render dashboard → the **web** service → *Settings → Custom Domains → Add Custom Domain*, enter e.g. `app.example.com`, and create the DNS record Render shows (a `CNAME` to the `onrender.com` host; apex domains use the `A`/`ALIAS` values Render lists). Wait for verification and the automatic TLS certificate.
2. On the **API** service, set `CORS_ORIGINS` to include the new web origin (exact scheme + host, no trailing slash), e.g. `https://app.example.com,https://stock-predictor-web-ts7p.onrender.com`. Saving triggers a redeploy.
3. Optionally give the API a domain too (`api.example.com`, same steps). Then set `NEXT_PUBLIC_API_BASE_URL` on the web service to it and **rebuild** the web service (it's inlined at build time).
4. Check: open the app on the new domain, confirm data loads (a CORS mistake shows up as "Couldn't reach the server"), and keep the old origin in `CORS_ORIGINS` until you're done migrating. Update the Privacy page if the operator identity changes.

## Deploying

You choose the hosting; nothing is deployed by this repo.
- **Web:** any Node host or platform (Vercel, Netlify, Cloudflare, Fly.io, or a container via `web/Dockerfile`). Set `NEXT_PUBLIC_API_BASE_URL` at **build** time. PWAs require HTTPS.
- **API:** any container host (`backend/Dockerfile`: Fly.io, Render, Cloud Run, a VPS). Set `CORS_ORIGINS` to your web origin(s). The cache and rate limiter are in-memory, so run a single instance or move them to Redis before scaling out.
- Before going public: have the Terms/Privacy drafts reviewed by a lawyer, check the data provider's terms for your use case, and update the privacy notice if you add logging or analytics.

### Live demo on Render (free tier)

- Web: https://stock-predictor-web-ts7p.onrender.com/
- API: https://stock-predictor-api-2dnn.onrender.com/health

Render's free tier **puts services to sleep after ~15 minutes of inactivity**, so the first request after a pause can take a minute or more. The workflow [`.github/workflows/keepalive.yml`](.github/workflows/keepalive.yml) pings both URLs every 10 minutes (with retries) to mitigate this. It is best-effort only: GitHub scheduled runs can be delayed or skipped, and GitHub **disables scheduled workflows after 60 days without repository activity** (re-enable it from the Actions tab). A paid Render instance type is the reliable fix.

