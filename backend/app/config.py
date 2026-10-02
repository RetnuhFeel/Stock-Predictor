"""Runtime configuration, read from environment variables."""
import os

DISCLAIMER = (
    "Educational/experimental output only. Not financial advice and no warranty of any kind. "
    "Predictions are frequently wrong and past performance does not predict future results. "
    "No personalised advice is given, and this service does not hold or trade money."
)

# Comma-separated list of allowed browser origins, e.g. "https://app.example.com,http://localhost:3000"
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
RATE_LIMIT_PER_MIN = int(os.getenv("RATE_LIMIT_PER_MIN", "60"))
# Only set when running behind trusted reverse proxies. The client address is then read from X-Forwarded-For,
# counting TRUSTED_PROXY_HOPS entries from the RIGHT (each trusted proxy appends the address it saw). Entries to the
# left of that are client-controlled and are never used. 1 = one trusted proxy in front of the app. If the header
# has fewer entries than expected, the socket peer address is used instead (never a spoofable value).
TRUST_PROXY = os.getenv("TRUST_PROXY", "").lower() in {"1", "true", "yes"}
TRUSTED_PROXY_HOPS = max(int(os.getenv("TRUSTED_PROXY_HOPS", "1") or "1"), 1)
# Hard cap on distinct limiter keys held in memory (bucket x client). Beyond it, new clients share one
# overflow bucket (same per-minute limit) instead of growing memory.
RATE_LIMIT_MAX_KEYS = int(os.getenv("RATE_LIMIT_MAX_KEYS", "10000"))

QUOTE_TTL_S = int(os.getenv("QUOTE_TTL_S", "60"))
HISTORY_TTL_S = int(os.getenv("HISTORY_TTL_S", "900"))
SEARCH_CACHE_MAX_ITEMS = int(os.getenv("SEARCH_CACHE_MAX_ITEMS", "256"))  # /api/search has its own small cache
FORECAST_TTL_S = int(os.getenv("FORECAST_TTL_S", "3600"))

RANGES = {"1mo": "1mo", "3mo": "3mo", "6mo": "6mo", "1y": "1y", "2y": "2y", "5y": "5y"}
# Chart history (GET /api/timeline): windows sliced from the single cached 5y download, downsampled for payload size
TIMELINE_RANGES = {"1mo": 1, "3mo": 3, "6mo": 6, "1y": 12, "2y": 24, "5y": 60}  # months
TIMELINE_MAX_POINTS = 400
MAX_HORIZON = 256  # trading days (~1 year); the UI offers 5/10/20/60/120/180/256
# From this horizon on, five years of data hold too few independent backtest periods (<= ~4) for the empirical
# backtest-residual interval to mean anything, so the forecast range is a volatility-based cone centred on today's
# price instead, and is labelled as not backtest-calibrated (interval_calibrated=false).
VOL_CONE_MIN_HORIZON = 120

# Market data provider: "yfinance" (default, no key) or "twelvedata" (needs TWELVEDATA_API_KEY)
DATA_PROVIDER = os.getenv("DATA_PROVIDER", "yfinance")
UPSTREAM_TIMEOUT_S = float(os.getenv("UPSTREAM_TIMEOUT_S", "10"))   # per attempt
UPSTREAM_RETRIES = int(os.getenv("UPSTREAM_RETRIES", "2"))           # extra attempts for transient failures
# If the provider fails, serve a cached copy up to this old (flagged stale) instead of an error
STALE_MAX_AGE_S = int(os.getenv("STALE_MAX_AGE_S", "86400"))

NEWS_TTL_S = int(os.getenv("NEWS_TTL_S", "600"))
MAX_COMPARE_SYMBOLS = 5
# Overall time budget for one /api/compare request (symbols are fetched in parallel). Symbols still running when it
# expires are reported under "failed" (UPSTREAM_TIMEOUT) and the rest are returned; their downloads finish in the
# background and warm the cache.
COMPARE_DEADLINE_S = float(os.getenv("COMPARE_DEADLINE_S", "30"))

# --- observability (all optional / off by default; no IPs, no user data are ever logged) ---
LOG_FORMAT = os.getenv("LOG_FORMAT", "json").lower()  # "json" (default) or "text"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
# Enables GET /api/_stats (Bearer token). Unset/empty = endpoint disabled (404).
MIN_TOKEN_LEN = 16
TOKEN_WARNINGS: list[str] = []


def _token(name: str) -> str:
    """A bearer token from the environment. One shorter than MIN_TOKEN_LEN is guessable, so the endpoint it
    protects stays DISABLED (404) rather than being guarded by a weak secret. A warning is logged (never the value)."""
    value = os.getenv(name, "")
    if value and len(value) < MIN_TOKEN_LEN:
        TOKEN_WARNINGS.append(f"{name} is shorter than {MIN_TOKEN_LEN} characters and was ignored (endpoint disabled).")
        return ""
    return value


ADMIN_TOKEN = _token("ADMIN_TOKEN")
# Enables POST /api/_client-error, which logs sanitized browser error reports. Off by default.
CLIENT_ERROR_LOGGING = os.getenv("CLIENT_ERROR_LOGGING", "").lower() in {"1", "true", "yes"}
CLIENT_ERROR_RATE_PER_MIN = int(os.getenv("CLIENT_ERROR_RATE_PER_MIN", "10"))
CLIENT_ERROR_MAX_BYTES = 4096
# Optional Sentry (backend only): requires `pip install sentry-sdk`; not installed by default.
SENTRY_DSN = os.getenv("SENTRY_DSN", "")

# Public model report card: a fixed, small set of well-known tickers at a fixed horizon (bounded cost).
REPORT_SYMBOLS = ["SPY", "AAPL", "MSFT", "NVDA", "TSLA"]
REPORT_HORIZON = 5
MODEL_REPORT_TTL_S = int(os.getenv("MODEL_REPORT_TTL_S", "21600"))  # 6 h
MODEL_REPORT_RATE_PER_MIN = int(os.getenv("MODEL_REPORT_RATE_PER_MIN", "6"))  # per client, stricter than the default

# --- model comparison / volatility (bounded compute) ---
HEAVY_RATE_PER_MIN = int(os.getenv("HEAVY_RATE_PER_MIN", "20"))  # per client, for compare-models and volatility
MODELS_TTL_S = int(os.getenv("MODELS_TTL_S", "3600"))

# --- trending momentum screen ---
TRENDING_TTL_S = int(os.getenv("TRENDING_TTL_S", "1200"))   # 20 min
TRENDING_MIN_COVERAGE = 0.5   # need data for at least this share of the universe, else treat as unavailable
TRENDING_MAX_DAYS = 10
TRENDING_MAX_LIMIT = 10

# --- live prediction log ---
# Fixed allowlist, logged by a scheduled job only (never per user request), so storage is bounded and nothing
# about any visitor is recorded.
LOG_SYMBOLS = ["SPY", "AAPL", "MSFT", "NVDA", "TSLA"]
LOG_HORIZON = 5
# Protects POST /api/_tasks/run-prediction-log. Unset/empty = endpoint disabled (404).
LOG_TASK_TOKEN = _token("LOG_TASK_TOKEN")
# SQLite file by default; set DATABASE_URL (e.g. a Postgres URL) for storage that survives redeploys.
# On Render's free tier the container disk is EPHEMERAL: a SQLite log is lost on every redeploy/restart.
DATABASE_URL = os.getenv("DATABASE_URL", "")
PREDICTION_LOG_TTL_S = int(os.getenv("PREDICTION_LOG_TTL_S", "120"))
