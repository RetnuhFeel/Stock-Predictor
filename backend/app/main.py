from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque

import pandas as pd
from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import config
from .cache import Fetched, TTLCache
from .errors import ApiError, InvalidRange
from .forecast import forecast
from .freshness import describe
from .providers import BaseProvider, create_provider
from .symbols import normalize_symbol

log = logging.getLogger("stock-api")
app = FastAPI(title="Stock Predictor API", version="1.1.0",
              description="Educational stock data & experimental forecasts. " + config.DISCLAIMER)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["GET"],
                   allow_headers=["*"], allow_credentials=False)

cache = TTLCache()
_provider: BaseProvider | None = None


def get_provider() -> BaseProvider:
    global _provider
    if _provider is None:
        _provider = create_provider(config.DATA_PROVIDER)
    return _provider


# --- rate limiting: simple in-memory sliding window per client (single-process only) ---
_hits: dict[str, deque] = defaultdict(deque)
_hits_lock = threading.Lock()


def _client_id(request: Request) -> str:
    if config.TRUST_PROXY and (fwd := request.headers.get("x-forwarded-for")):
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if request.url.path.startswith("/api/") and config.RATE_LIMIT_PER_MIN > 0:
        now, cid = time.monotonic(), _client_id(request)
        with _hits_lock:
            q = _hits[cid]
            while q and q[0] <= now - 60:
                q.popleft()
            if len(q) >= config.RATE_LIMIT_PER_MIN:
                retry = max(int(60 - (now - q[0])) + 1, 1)
                body = {"error": {"code": "RATE_LIMITED", "message": "Too many requests, slow down.",
                                  "retryable": True, "retry_after": retry}}
                return JSONResponse(body, status_code=429, headers={"Retry-After": str(retry)})
            q.append(now)
            if len(_hits) > 10_000:  # bound memory
                for k in [k for k, v in _hits.items() if not v]:
                    _hits.pop(k, None)
    return await call_next(request)


@app.exception_handler(ApiError)
async def _api_error(_: Request, exc: ApiError):
    if exc.status >= 500:
        log.warning("%s: %s", exc.code, exc.message)
    headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
    return JSONResponse(exc.body(), status_code=exc.status, headers=headers)


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(p) for p in first.get("loc", []) if p != "query")
    return JSONResponse({"error": {"code": "INVALID_REQUEST", "retryable": False,
                                   "message": f"Invalid parameter '{loc}': {first.get('msg', 'invalid value')}"}},
                        status_code=422)


def _history(provider: BaseProvider, symbol: str, period: str) -> Fetched:
    return cache.fetch(("hist", provider.name, symbol, period), config.HISTORY_TTL_S,
                       lambda: provider.history(symbol, period), stale_max_age=config.STALE_MAX_AGE_S)


def _freshness(df: pd.DataFrame, fetched: Fetched) -> dict:
    return describe(df.index[-1].date(), fetched.fetched_at, fetched.stale)


@app.get("/health")
def health():
    return {"status": "ok", "provider": config.DATA_PROVIDER}


@app.get("/api/search")
def search(q: str = Query(..., min_length=1, max_length=40), provider: BaseProvider = Depends(get_provider)):
    got = cache.fetch(("search", provider.name, q.lower()), 3600, lambda: provider.search(q), stale_max_age=86400)
    return {"results": got.value}


@app.get("/api/quote/{symbol}")
def quote(symbol: str, provider: BaseProvider = Depends(get_provider)):
    sym = normalize_symbol(symbol)
    got = cache.fetch(("quote", provider.name, sym), config.QUOTE_TTL_S, lambda: provider.quote(sym),
                      stale_max_age=config.STALE_MAX_AGE_S)
    q = got.value
    fresh = describe(q["as_of"], got.fetched_at, got.stale)
    return {
        "symbol": sym, "price": round(q["price"], 4), "previous_close": round(q["previous_close"], 4),
        "change": round(q["price"] - q["previous_close"], 4),
        "change_percent": round((q["price"] / q["previous_close"] - 1) * 100, 4),
        "as_of": q["as_of"].isoformat(), **fresh,
        "note": "Daily data; may be delayed. Not suitable for trading decisions.",
    }


@app.get("/api/history/{symbol}")
def history(symbol: str, range: str = Query("6mo"), provider: BaseProvider = Depends(get_provider)):
    sym = normalize_symbol(symbol)
    if range not in config.RANGES:
        raise InvalidRange(f"range must be one of {sorted(config.RANGES)}")
    got = _history(provider, sym, config.RANGES[range])
    df = got.value
    pts = [{"date": d.strftime("%Y-%m-%d"), "close": round(float(r.Close), 4), "volume": int(r.Volume or 0)}
           for d, r in df.iterrows()]
    return {"symbol": sym, "range": range, "points": pts, **_freshness(df, got)}


@app.get("/api/forecast/{symbol}")
def forecast_endpoint(symbol: str, horizon: int = Query(5, ge=1, le=config.MAX_HORIZON),
                      provider: BaseProvider = Depends(get_provider)):
    sym = normalize_symbol(symbol)
    hist = _history(provider, sym, "5y")  # served from (stale) cache if the provider is failing
    df = hist.value

    def build():
        return {"symbol": sym, **forecast(df["Close"], horizon)}

    # keyed by last bar so a new day's data invalidates the cached forecast
    key = ("fc", provider.name, sym, horizon, df.index[-1].date())
    result = cache.fetch(key, config.FORECAST_TTL_S, build).value
    return {**result, **_freshness(df, hist), "disclaimer": config.DISCLAIMER}
