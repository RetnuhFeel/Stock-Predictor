from __future__ import annotations

import hmac
import json
import logging
import threading
import time
from collections import defaultdict, deque

import pandas as pd
from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import config
from .cache import Fetched, TTLCache
from .errors import ApiError, InvalidRange, InvalidRequest, NotFound, PayloadTooLarge, Unauthorized
from .forecast import forecast
from .freshness import describe, describe_fetch
from .observability import (
    Stats,
    fingerprint,
    init_sentry,
    log_event,
    new_request_id,
    request_id_var,
    scrub,
    scrub_route,
    setup_logging,
)
from .providers import BaseProvider, create_provider
from .symbols import normalize_symbol

log = setup_logging()
init_sentry(config.SENTRY_DSN, log)
app = FastAPI(title="Stock Predictor API", version="1.2.0",
              description="Educational stock data & experimental forecasts. " + config.DISCLAIMER)

cache = TTLCache()
stats = Stats()
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


def _limited(bucket: str, cid: str, limit: int, now: float) -> int | None:
    """Record a hit; return seconds to wait if the client is over ``limit`` per minute, else None."""
    with _hits_lock:
        q = _hits[f"{bucket}:{cid}"]
        while q and q[0] <= now - 60:
            q.popleft()
        if len(q) >= limit:
            return max(int(60 - (now - q[0])) + 1, 1)
        q.append(now)
        if len(_hits) > 10_000:  # bound memory
            for k in [k for k, v in _hits.items() if not v]:
                _hits.pop(k, None)
    return None


@app.middleware("http")
async def observe_and_limit(request: Request, call_next):
    """Request ID, rate limit, structured access log, aggregate stats. Logs no IPs, UAs or query strings."""
    rid = new_request_id(request.headers.get("x-request-id"))
    token = request_id_var.set(rid)
    started = time.perf_counter()
    path = request.url.path
    request.state.error_code = None
    try:
        retry = None
        if path.startswith("/api/") and config.RATE_LIMIT_PER_MIN > 0:
            retry = _limited("api", _client_id(request), config.RATE_LIMIT_PER_MIN, time.monotonic())
        if retry is None and path == "/api/model-report" and config.RATE_LIMIT_PER_MIN > 0:
            retry = _limited("report", _client_id(request), config.MODEL_REPORT_RATE_PER_MIN, time.monotonic())
        if retry is not None:
            request.state.error_code = "RATE_LIMITED"
            response: Response = JSONResponse(
                {"error": {"code": "RATE_LIMITED", "message": "Too many requests, slow down.",
                           "retryable": True, "retry_after": retry}},
                status_code=429, headers={"Retry-After": str(retry)})
        else:
            response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        if path != "/health":
            route = request.scope.get("route")
            template = getattr(route, "path", None) or "(unmatched)"
            ms = (time.perf_counter() - started) * 1000
            stats.record(f"{request.method} {template}", response.status_code, ms, request.state.error_code)
            log_event(log, "request", method=request.method, route=template, status=response.status_code,
                      ms=round(ms, 1), error_code=request.state.error_code)
        return response
    finally:
        request_id_var.reset(token)


# Added LAST so it is the outermost middleware: every response, including 429s and errors, gets CORS headers.
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["GET", "POST"],
                   allow_headers=["*"], allow_credentials=False, expose_headers=["X-Request-ID", "Retry-After"])


@app.exception_handler(ApiError)
async def _api_error(request: Request, exc: ApiError):
    request.state.error_code = exc.code
    if exc.status >= 500:
        log_event(log, "api_error", logging.WARNING, code=exc.code, message=exc.message)
    headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
    return JSONResponse(exc.body(), status_code=exc.status, headers=headers)


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError):
    request.state.error_code = "INVALID_REQUEST"
    first = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(p) for p in first.get("loc", []) if p != "query")
    return JSONResponse({"error": {"code": "INVALID_REQUEST", "retryable": False,
                                   "message": f"Invalid parameter '{loc}': {first.get('msg', 'invalid value')}"}},
                        status_code=422)


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    request.state.error_code = "INTERNAL_ERROR"
    log.error("unhandled", exc_info=exc, extra={"ctx": {"route": request.url.path}})
    return JSONResponse({"error": {"code": "INTERNAL_ERROR", "retryable": True,
                                   "message": "Unexpected server error. Please try again."}}, status_code=500,
                        headers={"X-Request-ID": request_id_var.get()})


def _history(provider: BaseProvider, symbol: str, period: str) -> Fetched:
    return cache.fetch(("hist", provider.name, symbol, period), config.HISTORY_TTL_S,
                       lambda: provider.history(symbol, period), stale_max_age=config.STALE_MAX_AGE_S)


def _freshness(df: pd.DataFrame, fetched: Fetched) -> dict:
    return describe(df.index[-1].date(), fetched.fetched_at, fetched.stale)


@app.get("/health")
def health():
    return {"status": "ok", "provider": config.DATA_PROVIDER}


@app.get("/api/news/{symbol}")
def news(symbol: str, provider: BaseProvider = Depends(get_provider)):
    """Recent headlines for context. Link-out only (headline, source, URL, time); never article bodies."""
    sym = normalize_symbol(symbol)
    got = cache.fetch(("news", provider.name, sym), config.NEWS_TTL_S, lambda: provider.news(sym),
                      stale_max_age=config.STALE_MAX_AGE_S)
    return {"symbol": sym, "items": got.value[:12], **describe_fetch(got.fetched_at, got.stale),
            "note": "Headlines are context, not a trading signal. They link to third-party sites."}


def _normalised(df: pd.DataFrame) -> pd.Series:
    return df["Close"].dropna()


@app.get("/api/compare")
def compare(symbols: str = Query(..., min_length=1, max_length=120), range: str = Query("6mo"),
            provider: BaseProvider = Depends(get_provider)):
    """Percent change since the first common date, for up to 5 symbols. Partial results are returned
    (with per-symbol failures listed) if some symbols can't be fetched."""
    syms = list(dict.fromkeys(normalize_symbol(s) for s in symbols.split(",") if s.strip()))
    if not 2 <= len(syms) <= config.MAX_COMPARE_SYMBOLS:
        raise InvalidRequest(f"Provide 2 to {config.MAX_COMPARE_SYMBOLS} different symbols, separated by commas.")
    if range not in config.RANGES:
        raise InvalidRange(f"range must be one of {sorted(config.RANGES)}")

    fetched: dict[str, Fetched] = {}
    failed: list[dict] = []
    first_error: ApiError | None = None
    for sym in syms:
        try:
            fetched[sym] = _history(provider, sym, config.RANGES[range])
        except ApiError as exc:
            first_error = first_error or exc
            failed.append({"symbol": sym, "code": exc.code, "message": exc.message})
    if len(fetched) < 2:
        raise first_error or InvalidRequest("Not enough symbols with data to compare.")

    closes = pd.concat({s: _normalised(f.value) for s, f in fetched.items()}, axis=1).sort_index()
    closes = closes.ffill().dropna()  # start where every symbol has a price
    if len(closes) < 2:
        raise InvalidRequest("These symbols have no overlapping price history in this range.")
    pct = (closes / closes.iloc[0] - 1) * 100
    stale = any(f.stale for f in fetched.values())
    fetched_at = min(f.fetched_at for f in fetched.values())
    series = [{"symbol": s, "start_price": round(float(closes[s].iloc[0]), 4),
               "end_price": round(float(closes[s].iloc[-1]), 4),
               "change_percent": round(float(pct[s].iloc[-1]), 2),
               "points": [round(float(v), 3) for v in pct[s]]} for s in pct.columns]
    return {"range": range, "dates": [d.strftime("%Y-%m-%d") for d in pct.index], "series": series,
            "failed": failed, "base": "Percent change since the first common date; not annualised.",
            **describe(closes.index[-1].date(), fetched_at, stale)}


# --- opt-in observability endpoints (disabled unless configured) ---------------------------------
def _require_admin(request: Request) -> None:
    if not config.ADMIN_TOKEN:
        raise NotFound("Not found.")
    supplied = request.headers.get("authorization", "")
    expected = f"Bearer {config.ADMIN_TOKEN}"
    if not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise Unauthorized("Missing or invalid admin token.")


@app.get("/api/_stats")
def get_stats(request: Request):
    _require_admin(request)
    return stats.snapshot()


@app.post("/api/_client-error")
async def client_error(request: Request):
    """Receives sanitized browser error reports (message, stack, route only) and logs them.
    Disabled unless CLIENT_ERROR_LOGGING=true. Size- and rate-limited. Returns 204."""
    if not config.CLIENT_ERROR_LOGGING:
        raise NotFound("Not found.")
    retry = _limited("client-error", _client_id(request), config.CLIENT_ERROR_RATE_PER_MIN, time.monotonic())
    if retry is not None:
        request.state.error_code = "RATE_LIMITED"
        return JSONResponse({"error": {"code": "RATE_LIMITED", "message": "Too many error reports.",
                                       "retryable": True, "retry_after": retry}}, status_code=429,
                            headers={"Retry-After": str(retry)})
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > config.CLIENT_ERROR_MAX_BYTES:
        raise PayloadTooLarge("Error report too large.")
    raw = await request.body()
    if len(raw) > config.CLIENT_ERROR_MAX_BYTES:
        raise PayloadTooLarge("Error report too large.")
    try:
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise ValueError
    except ValueError:
        raise InvalidRequest("Body must be a JSON object.") from None
    message = scrub(str(body.get("message", "")), 300)
    stack = scrub(str(body.get("stack", "")), 2000)
    route = scrub_route(str(body.get("route", "/")))
    stats.record_client_error()
    log_event(log, "client_error", logging.ERROR, route=route, message=message, stack=stack,
              fingerprint=fingerprint(message + stack[:200]))
    return Response(status_code=204)


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


def _forecast_for(provider: BaseProvider, sym: str, horizon: int) -> tuple[dict, pd.DataFrame, Fetched]:
    hist = _history(provider, sym, "5y")  # served from (stale) cache if the provider is failing
    df = hist.value

    def build():
        return {"symbol": sym, **forecast(df["Close"], horizon)}

    # keyed by last bar so a new day's data invalidates the cached forecast
    key = ("fc", provider.name, sym, horizon, df.index[-1].date())
    return cache.fetch(key, config.FORECAST_TTL_S, build).value, df, hist


@app.get("/api/forecast/{symbol}")
def forecast_endpoint(symbol: str, horizon: int = Query(5, ge=1, le=config.MAX_HORIZON),
                      provider: BaseProvider = Depends(get_provider)):
    sym = normalize_symbol(symbol)
    result, df, hist = _forecast_for(provider, sym, horizon)
    return {**result, **_freshness(df, hist), "disclaimer": config.DISCLAIMER}


def _verdict(bt: dict) -> str:
    """Same rule as the web UI's plain-language verdict."""
    if bt["beats_baseline"]:
        return "better"
    ci = bt.get("skill_ci_90")
    if bt["skill_vs_baseline"] > 0 and ci and ci[0] <= 0:
        return "inconclusive"
    return "not_better"


_report_lock = threading.Lock()  # one report build at a time: bounds CPU even under a burst of requests


@app.get("/api/model-report")
def model_report(provider: BaseProvider = Depends(get_provider)):
    """Backtest 'report card' for a small fixed set of tickers at a fixed horizon.

    Cost is bounded: the symbol list and horizon are fixed (not user input), results are cached
    (MODEL_REPORT_TTL_S, and each forecast shares the normal forecast cache), builds are serialised, and the
    endpoint has its own stricter rate limit. A symbol that fails is listed under ``failed``; the rest are shown.
    """
    horizon = config.REPORT_HORIZON

    def build():
        rows, failed, as_of, fetched, stale_in = [], [], [], [], []
        first_error: ApiError | None = None
        for sym in config.REPORT_SYMBOLS:
            try:
                result, df, hist = _forecast_for(provider, sym, horizon)
            except ApiError as exc:
                first_error = first_error or exc
                failed.append({"symbol": sym, "code": exc.code, "message": exc.message})
                continue
            bt = result["backtest"]
            as_of.append(df.index[-1].date())
            fetched.append(hist.fetched_at)
            stale_in.append(hist.stale)
            rows.append({
                "symbol": sym, "verdict": _verdict(bt), "skill_vs_baseline": bt["skill_vs_baseline"],
                "skill_ci_90": bt["skill_ci_90"], "model_rmse": bt["model"]["rmse"],
                "baseline_rmse": bt["naive_baseline"]["rmse"], "hit_rate": bt["model"]["directional_accuracy"],
                "up_rate": bt["up_rate"], "n_test_points": bt["n_test_points"],
                "n_independent_tests": bt["n_independent_tests"], "small_sample": bt["small_sample"],
                "data_as_of": df.index[-1].date().isoformat(),
            })
        if not rows:
            raise first_error or InvalidRequest("No report data available.")
        return {"rows": rows, "failed": failed, "as_of": min(as_of), "fetched_at": min(fetched), "stale": any(stale_in)}

    with _report_lock:
        got = cache.fetch(("report", provider.name, config.REPORT_HORIZON), config.MODEL_REPORT_TTL_S, build,
                          stale_max_age=config.STALE_MAX_AGE_S)
    v = got.value
    return {"horizon_days": horizon, "rows": v["rows"], "failed": v["failed"],
            "method": (f"Expanding-window walk-forward, 6 folds, {horizon}-day embargo, "
                       "vs. a 'price stays flat' baseline."),
            "summary": {"better": sum(r["verdict"] == "better" for r in v["rows"]),
                        "inconclusive": sum(r["verdict"] == "inconclusive" for r in v["rows"]),
                        "not_better": sum(r["verdict"] == "not_better" for r in v["rows"]),
                        "total": len(v["rows"])},
            **describe(v["as_of"], v["fetched_at"], got.stale or v["stale"]), "disclaimer": config.DISCLAIMER}
