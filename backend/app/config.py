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
MAX_HORIZON = 30

# Market data provider: "yfinance" (default, no key) or "twelvedata" (needs TWELVEDATA_API_KEY)
DATA_PROVIDER = os.getenv("DATA_PROVIDER", "yfinance")
UPSTREAM_TIMEOUT_S = float(os.getenv("UPSTREAM_TIMEOUT_S", "10"))   # per attempt
UPSTREAM_RETRIES = int(os.getenv("UPSTREAM_RETRIES", "2"))           # extra attempts for transient failures
# If the provider fails, serve a cached copy up to this old (flagged stale) instead of an error
STALE_MAX_AGE_S = int(os.getenv("STALE_MAX_AGE_S", "86400"))
