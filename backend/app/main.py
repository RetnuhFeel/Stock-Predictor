from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque

from fastapi import Depends, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import config
from .cache import TTLCache
from .data import DataUnavailable, InvalidSymbol, Provider, YahooProvider, normalize_symbol
from .forecast import InsufficientData, forecast

log = logging.getLogger("stock-api")
app = FastAPI(title="Stock Predictor API", version="1.0.0",
              description="Educational stock data & experimental forecasts. " + config.DISCLAIMER)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["GET"],
                   allow_headers=["*"], allow_credentials=False)

cache = TTLCache()
_provider: Provider = YahooProvider()


def get_provider() -> Provider:
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
                return JSONResponse({"error": "rate_limited", "detail": "Too many requests, slow down."},
                                    status_code=429, headers={"Retry-After": str(retry)})
            q.append(now)
            if len(_hits) > 10_000:  # bound memory
                for k in [k for k, v in _hits.items() if not v]:
                    _hits.pop(k, None)
    return await call_next(request)


class ApiError(Exception):
    def __init__(self, status: int, error: str, detail: str):
        self.status, self.error, self.detail = status, error, detail


@app.exception_handler(ApiError)
async def _api_error(_: Request, exc: ApiError):
    return JSONResponse({"error": exc.error, "detail": exc.detail}, status_code=exc.status)


@app.exception_handler(InvalidSymbol)
async def _invalid_symbol(_: Request, exc: InvalidSymbol):
    return JSONResponse({"error": "invalid_symbol", "detail": str(exc)}, status_code=400)


@app.exception_handler(DataUnavailable)
async def _unavailable(_: Request, exc: DataUnavailable):
    log.warning("data unavailable: %s", exc)
    return JSONResponse({"error": "data_unavailable", "detail": str(exc)}, status_code=502)


@app.exception_handler(InsufficientData)
async def _insufficient(_: Request, exc: InsufficientData):
    return JSONResponse({"error": "insufficient_data", "detail": str(exc)}, status_code=422)


def _history(provider: Provider, symbol: str, period: str):
    return cache.get_or_set(("hist", symbol, period), config.HISTORY_TTL_S, lambda: provider.history(symbol, period))


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/search")
def search(q: str = Query(..., min_length=1, max_length=40), provider: Provider = Depends(get_provider)):
    results = cache.get_or_set(("search", q.lower()), 3600, lambda: provider.search(q))
    return {"results": results}


@app.get("/api/quote/{symbol}")
def quote(symbol: str, provider: Provider = Depends(get_provider)):
    sym = normalize_symbol(symbol)
    df = cache.get_or_set(("quote", sym), config.QUOTE_TTL_S, lambda: provider.history(sym, "5d"))
    close = df["Close"].dropna()
    if len(close) < 2:
        raise ApiError(502, "data_unavailable", "Not enough recent data")
    price, prev = float(close.iloc[-1]), float(close.iloc[-2])
    return {
        "symbol": sym, "price": round(price, 4), "previous_close": round(prev, 4),
        "change": round(price - prev, 4), "change_percent": round((price / prev - 1) * 100, 4),
        "as_of": close.index[-1].strftime("%Y-%m-%d"),
        "note": "Daily data; may be delayed. Not suitable for trading decisions.",
    }


@app.get("/api/history/{symbol}")
def history(symbol: str, range: str = Query("6mo"), provider: Provider = Depends(get_provider)):
    sym = normalize_symbol(symbol)
    if range not in config.RANGES:
        raise ApiError(400, "invalid_range", f"range must be one of {sorted(config.RANGES)}")
    df = _history(provider, sym, config.RANGES[range])
    pts = [{"date": d.strftime("%Y-%m-%d"), "close": round(float(r.Close), 4), "volume": int(r.Volume or 0)}
           for d, r in df.iterrows()]
    return {"symbol": sym, "range": range, "points": pts}


@app.get("/api/forecast/{symbol}")
def forecast_endpoint(symbol: str, horizon: int = Query(5, ge=1, le=config.MAX_HORIZON),
                      provider: Provider = Depends(get_provider)):
    sym = normalize_symbol(symbol)

    def build():
        df = _history(provider, sym, "5y")
        return {"symbol": sym, **forecast(df["Close"], horizon)}

    result = cache.get_or_set(("fc", sym, horizon), config.FORECAST_TTL_S, build)
    return {**result, "disclaimer": config.DISCLAIMER}
