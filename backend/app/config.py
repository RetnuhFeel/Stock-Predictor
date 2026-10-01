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
# Only set when running behind a trusted reverse proxy that overwrites X-Forwarded-For.
TRUST_PROXY = os.getenv("TRUST_PROXY", "").lower() in {"1", "true", "yes"}

QUOTE_TTL_S = int(os.getenv("QUOTE_TTL_S", "60"))
HISTORY_TTL_S = int(os.getenv("HISTORY_TTL_S", "900"))
FORECAST_TTL_S = int(os.getenv("FORECAST_TTL_S", "3600"))

RANGES = {"1mo": "1mo", "3mo": "3mo", "6mo": "6mo", "1y": "1y", "2y": "2y", "5y": "5y"}
MAX_HORIZON = 60  # trading days; the UI offers 1/5/10/20/40/60

# Market data provider: "yfinance" (default, no key) or "twelvedata" (needs TWELVEDATA_API_KEY)
DATA_PROVIDER = os.getenv("DATA_PROVIDER", "yfinance")
UPSTREAM_TIMEOUT_S = float(os.getenv("UPSTREAM_TIMEOUT_S", "10"))   # per attempt
UPSTREAM_RETRIES = int(os.getenv("UPSTREAM_RETRIES", "2"))           # extra attempts for transient failures
# If the provider fails, serve a cached copy up to this old (flagged stale) instead of an error
STALE_MAX_AGE_S = int(os.getenv("STALE_MAX_AGE_S", "86400"))

NEWS_TTL_S = int(os.getenv("NEWS_TTL_S", "600"))
MAX_COMPARE_SYMBOLS = 5

# --- observability (all optional / off by default; no IPs, no user data are ever logged) ---
LOG_FORMAT = os.getenv("LOG_FORMAT", "json").lower()  # "json" (default) or "text"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
# Enables GET /api/_stats (Bearer token). Unset/empty = endpoint disabled (404).
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
# Enables POST /api/_client-error, which logs sanitized browser error reports. Off by default.
CLIENT_ERROR_LOGGING = os.getenv("CLIENT_ERROR_LOGGING", "").lower() in {"1", "true", "yes"}
CLIENT_ERROR_RATE_PER_MIN = int(os.getenv("CLIENT_ERROR_RATE_PER_MIN", "10"))
CLIENT_ERROR_MAX_BYTES = 4096
# Optional Sentry (backend only): requires `pip install sentry-sdk`; not installed by default.
SENTRY_DSN = os.getenv("SENTRY_DSN", "")
