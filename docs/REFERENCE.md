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
| `MODELS_TTL_S` | backend | Cache lifetime of model comparison / volatility / spike results (default 3600) |
| `TRENDING_TTL_S` | backend | Cache lifetime of `GET /api/trending` (default 1200 = 20 min). Also `TRENDING_MIN_COVERAGE` (default 0.5), `TRENDING_MAX_DAYS` (10), `TRENDING_MAX_LIMIT` (10) |
| `HEAVY_RATE_PER_MIN` | backend | Per-client limit for `/api/trending`, `/api/compare-models`, `/api/volatility` and `/api/spikes` (default 20, on top of the global limit) |
| `NEXT_PUBLIC_SUPPORT_URL` | web (build time) | Optional `https://` URL for a "Support this project" footer link. Unset = nothing is shown |
| `NEXT_PUBLIC_ERROR_REPORTING` | web (build time) | `true` makes the browser POST sanitised error reports (message, stack, path) to the API. Needs `CLIENT_ERROR_LOGGING=true` on the API |

## API endpoints

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness + active provider |
| `GET /api/quote/{symbol}` | Latest daily close and change |
| `GET /api/history/{symbol}?range=1mo\|3mo\|6mo\|1y\|2y\|5y` | Daily closes |
| `GET /api/forecast/{symbol}?horizon=1..256` | Experimental forecast + per-horizon backtest |
| `GET /api/timeline/{symbol}?range=1mo\|3mo\|6mo\|1y\|2y\|5y` | History for the main chart (default 6mo; replaces the separate timeline panel) sliced from the one cached 5y download, downsampled to ≤400 points (first, last, high and low always kept); `summary` (period return, high/low with dates, worst drawdown) is computed on the full data. Freshness fields included; `INVALID_RANGE` for other ranges |
| `GET /api/compare?symbols=A,B&range=` | 2–5 symbols, normalised % change |
| `GET /api/news/{symbol}` | Headlines (link-out only) |
| `GET /api/model-report` | Cached backtest report card for SPY, AAPL, MSFT, NVDA, TSLA at 5 days (fixed list, no user input, own rate limit) |
| `GET /api/compare-models/{symbol}?horizon=1..256` | Naive, drift, EWMA, ridge-AR and gradient boosting, each walk-forward (+ embargo) vs. naive: error, skill with 90% bootstrap range, direction hit rate, n tests. Cached, own rate limit |
| `GET /api/volatility/{symbol}?horizon=1..256` | Realised-volatility forecast (EWMA headline, HAR-style, vs. "recent 21-day vol"), annualised vol, 1-sigma risk range, backtest coverage |
| `GET /api/trending?days=3&limit=5` | Top gainers by close-to-close return over the last `days` trading days (1–10, default 3) from the fixed universe in `backend/app/universe.py`. Returns `items[{rank, symbol, name, return_percent, last_close, as_of}]`, `universe_size`, `evaluated`, `method`, `note`, `disclaimer` and the usual freshness fields. One batched provider download, cached 20 min, stale-if-error; tickers that fail or lag behind the latest trading day are skipped; too little coverage gives `503 DATA_UNAVAILABLE` (retryable). Own (heavy) rate limit |
| `GET /api/spikes/{symbol}?horizon=1..256` | **Experimental.** Jump-diffusion spike scenario clamped inside the standard forecast band, with a walk-forward backtest against the standard interval. Cached, heavy rate limit, never logged to the prediction log |
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
- **Forecast horizon**: `GET /api/forecast/{symbol}?horizon=N`, `N` in 1–256 trading days (`422 INVALID_REQUEST` otherwise). The UI offers 5/10/20/60/120/180/256. Backtest and verdict are computed **per horizon** with an embargo of at least `N` days (reported as `embargo_days`). Longer horizons give wider intervals and far fewer independent test periods, which the UI says plainly.
  - **Long horizons (limits):** with the 5 years of data we fetch (~1,250 bars) a 60-day horizon has ~9 independent test periods, 120-day ~4, 180-day ~2 and 256-day ~1. A response with fewer than 5 independent periods is flagged `too_few_independent` and **can never get a "better" verdict** (forecast, model comparison and volatility); every forecast at ≥60 days carries a "highly uncertain" note and the UI shows a prominent warning. The walk-forward embargo is always at least the horizon. A ticker with too little history (roughly under 260 bars for 60d, 350 for 120d, 470 for 180d, 630 for 256d) gets `422 INSUFFICIENT_DATA` with a message naming the horizon; the spike backtest is reported as unavailable when it has fewer than 10 evaluation points (typical at ≥120 days), and then says there is no evidence either way. The prediction log is unchanged: fixed 5-day horizon.
  - **Cost:** compute is the same order at any horizon (about 0.4–0.7 s per endpoint locally, cached per symbol/horizon/day); the spike response grows with horizon (256 daily rows, ~80 kB).
- **News** (`GET /api/news/{symbol}`): headline, source, link and time only (via the active provider; Yahoo for `yfinance`, nothing for providers without news). Article text is never fetched. Shown as "context, not a signal"; an empty list is a normal response.

- **Lists and Trending** (web + `GET /api/trending`): the default list, "Trending (3-day)", is read-only and filled from the endpoint; it shows loading, error and "may be outdated" states and falls back to the last copy saved on the device. User lists are stored in `localStorage` (`lists.v2`, versioned; the old `watchlist.v1` is migrated once into "My watchlist" and left untouched). Limits: 20 lists, 50 tickers per list, 40-character names; symbols are upper-cased and validated; corrupt or oversized saved data falls back to defaults, and a full/blocked storage shows a warning instead of crashing.
  - **Universe:** a static, curated list of ~106 liquid US large caps in `backend/app/universe.py` (edit it and redeploy to change it). Stocks outside it can never appear in Trending.
  - **Limitations:** it ranks only past 3-day price change, so it is a momentum screen and **not a recommendation, signal or prediction**; gains often partly reverse. Data comes from Yahoo via `yfinance`, which is unofficial, can be delayed or rate-limited (then you get cached/stale data or a clear error). The server cache is in-memory, per instance and lost on restart, so the first request after a cold start can take several seconds. The ranking ignores splits/dividends beyond what adjusted closes provide.

- **Experimental spike scenario** (web + `GET /api/spikes/{symbol}?horizon=1..256`, code in `backend/app/spikes.py`): a jump-diffusion Monte Carlo around the standard forecast. It is **off by default** in the UI, labelled *Experimental*, and is **never used by, or written to, the live prediction log** (the logged model is unchanged).
  - **Calibration** (past data only): the last ~504 daily log returns; a day is a *jump* if it is more than 2.5 robust sigmas (1.4826 × MAD) from the median; up and down jumps are counted separately (asymmetry kept); diffusion volatility is estimated from the non-jump days; jump sizes are the historical jump returns, resampled. Needs ≥120 returns and ≥250 bars (`422 INSUFFICIENT_DATA` otherwise). Few jumps (<5) is flagged in the response.
  - **Simulation:** 2,000 paths, fixed seed (42), so the same inputs always give the same output. The drift is set so the average path follows the standard forecast (jumps are compensated: spikes, not extra trend).
  - **Bounds = clamping.** Each simulated daily price is clipped to the standard forecast's normal 80% band for that day (`path[].low/high`). Clamping, rather than rejection/conditioning, keeps every path and lets the response report how often it happened (`clamping.fraction_of_path_days_clamped`, `fraction_of_paths_touching_band`, `terminal_at_high/low`; typically ~15–22% of path-days). The unclamped process keeps running underneath.
  - **Response:** per day the normal band, simulated median/mean, 10–90% simulated range, typical spike-up/spike-down level (median × mean historical jump, clamped), cumulative probability of a jump so far (up/down) and of touching the top/bottom of the band, plus a few example paths, the calibration (jump counts, frequencies, mean sizes) and the freshness/disclaimer fields.
  - **Backtest** (same walk-forward folds and embargo as the standard forecast; baseline band quantiles from earlier folds only, jump calibration from data up to each origin; origins at least `horizon` days apart): empirical coverage of the real h-day return, the Winkler interval score (width + miss penalty, lower is better) with a bootstrap 90% range, and RMSE of the median path vs. the standard point forecast. "better"/"worse" need a change of ≥2% **and** a 90% range that excludes zero.
  - **Results (live yfinance, 5y history, run 2026-10-01).** Coverage = how often the real move landed inside the range (target 80%): standard band / unclamped jump / clamped spike. Interval-score change vs. the standard band (positive = better).

| Ticker | Horizon (d) | Origins | Coverage (std / jump / clamped) | Jump range, score change (verdict) | Clamped range, score change (verdict) | Median-path RMSE vs standard (verdict) |
|---|---|---|---|---|---|---|
| SPY | 5 | 100 | 80% / 91% / 80% | -9.3% (worse) | +0.0% (inconclusive) | 0.0198 vs 0.0198 (inconclusive) |
| SPY | 20 | 26 | 73% / 88% / 73% | +0.5% (inconclusive) | +0.0% (inconclusive) | 0.0404 vs 0.0402 (inconclusive) |
| AAPL | 5 | 100 | 77% / 86% / 77% | +1.4% (inconclusive) | +1.5% (inconclusive) | 0.0390 vs 0.0389 (inconclusive) |
| AAPL | 20 | 26 | 88% / 100% / 88% | -10.3% (inconclusive) | +1.7% (inconclusive) | 0.0523 vs 0.0528 (inconclusive) |
| MSFT | 5 | 100 | 77% / 85% / 77% | -2.4% (inconclusive) | +0.0% (inconclusive) | 0.0462 vs 0.0462 (inconclusive) |
| MSFT | 20 | 26 | 69% / 85% / 69% | +6.0% (inconclusive) | +0.0% (inconclusive) | 0.0832 vs 0.0832 (inconclusive) |
| NVDA | 5 | 100 | 90% / 93% / 89% | -5.9% (worse) | +2.1% (better) | 0.0614 vs 0.0614 (inconclusive) |
| NVDA | 20 | 26 | 92% / 92% / 92% | -4.7% (inconclusive) | +1.4% (inconclusive) | 0.1168 vs 0.1164 (inconclusive) |
| TSLA | 5 | 100 | 83% / 88% / 80% | +1.5% (inconclusive) | +2.4% (better) | 0.0781 vs 0.0782 (inconclusive) |
| TSLA | 20 | 26 | 85% / 88% / 81% | +23.3% (better) | +15.4% (better) | 0.1424 vs 0.1400 (inconclusive) |

  - **Reading it honestly:** the typical (median) spike path was **never** clearly more accurate than the standard forecast (differences in the 4th decimal; all "inconclusive"). The unclamped jump range had higher coverage (it is wider) but a worse or indistinguishable interval score, except TSLA at 20 days (+23%, one ticker, 26 origins, one of 10 ticker-horizon comparisons, so it may well be chance). The clamped range can never be wider than the standard band: it is identical for some tickers, and where it is narrower its better score came with lower coverage (e.g. TSLA 20d: 81% vs 85%). "Better" for NVDA 5d and TSLA 5d is +2.1% and +2.4%, barely above the 2% materiality line and from 10 ticker-horizon comparisons, so we do not claim it improves accuracy. It is an illustration of possible spikiness, not a better forecast.
  - **Limitations:** spikes are simulated from past frequencies, not predicted; earnings/news events are not modelled; jump sizes come from a short sample; clamping squeezes the tails so it cannot represent a move larger than the normal band (real ones happen); results are for 5 tickers and 2 horizons only and the backtest origins are few at long horizons.

- **Chart history range** (web + `GET /api/timeline/{symbol}?range=6mo`): the forecast chart has 1M/3M/6M/1Y/2Y/5Y buttons (default 6M, saved in `localStorage` as `chart.range.v1`; an unknown or corrupt value falls back to 6M). The range sets how much history is drawn left of the forecast; the forecast and 80% interval always join at the last close on the right edge. The summary (return, high, low with dates, worst drop from a peak) is computed on the full range. "% change from the start of the range" scales history, forecast and interval from the same first close. A table lists every plotted point plus the forecast path, and the chart has loading, error and "may be outdated" (saved copy) states. `GET /api/history/{symbol}` is unchanged (all bars with volume, same six ranges) for backward compatibility. The spike scenario chart and model comparison are separate panels that cover the forecast horizon only, so they do not use the history range. Prices are split- and dividend-adjusted closes from the active provider (Yahoo via `yfinance` by default; unofficial and possibly delayed). Past performance does not predict future results.

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

