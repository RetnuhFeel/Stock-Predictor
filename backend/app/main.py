from __future__ import annotations

import contextvars
import hmac
import json
import logging
import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait

import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import config, conformal, freshness
from .cache import Fetched, TTLCache
from .errors import (
    ApiError,
    DataUnavailable,
    InsufficientData,
    InvalidRange,
    InvalidRequest,
    NotFound,
    PayloadTooLarge,
    Unauthorized,
    UpstreamTimeout,
)
from .forecast import forecast, legacy_view
from .freshness import (
    bar_is_final,
    describe,
    describe_fetch,
    expected_base_session,
    session_in_progress,
)
from .marketcal import trading_days_between
from .models import compare_models
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
from .ratelimit import RateLimiter, client_key
from .spikes import spike_forecast
from .storage import PredictionStore, now_iso
from .symbols import normalize_symbol
from .trackrecord import (
    hash_spec,
    missed_sessions,
    public_row,
    record_from_forecast,
    resolve_pending,
    scorecard,
)
from .volatility import forecast_volatility

log = setup_logging()
init_sentry(config.SENTRY_DSN, log)
for _w in config.TOKEN_WARNINGS:
    log.warning(_w)
app = FastAPI(title="Stock Predictor API", version="1.2.0",
              description="Educational stock data & experimental forecasts. " + config.DISCLAIMER)

cache = TTLCache()
# /api/search has unbounded key space (any user-typed string), so it gets its own small cache: a flood of distinct
# searches can only evict other searches, never price history that the forecast pages depend on.
search_cache = TTLCache(max_items=config.SEARCH_CACHE_MAX_ITEMS)
stats = Stats()
_provider: BaseProvider | None = None


def get_provider() -> BaseProvider:
    global _provider
    if _provider is None:
        _provider = create_provider(config.DATA_PROVIDER)
    return _provider


# --- rate limiting: in-memory sliding window per client (single-process only; see ratelimit.py) ---
limiter = RateLimiter(config.RATE_LIMIT_MAX_KEYS)


def _client_id(request: Request) -> str:
    return client_key(request.client.host if request.client else None, request.headers.get("x-forwarded-for"),
                      config.TRUST_PROXY, config.TRUSTED_PROXY_HOPS)


def _limited(bucket: str, cid: str, limit: int, now: float) -> int | None:
    """Record a hit; return seconds to wait if the client is over ``limit`` per minute, else None."""
    return limiter.hit(bucket, cid, limit, now)


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
        heavy = path.startswith(("/api/compare-models/", "/api/volatility/", "/api/spikes/", "/api/trending"))
        if retry is None and heavy and config.RATE_LIMIT_PER_MIN > 0:
            retry = _limited("heavy", _client_id(request), config.HEAVY_RATE_PER_MIN, time.monotonic())
        if retry is None and path == "/api/model-report" and config.RATE_LIMIT_PER_MIN > 0:
            retry = _limited("report", _client_id(request), config.MODEL_REPORT_RATE_PER_MIN, time.monotonic())
        if retry is not None:
            request.state.error_code = "RATE_LIMITED"
            response: Response = JSONResponse(
                {"error": {"code": "RATE_LIMITED", "message": "Too many requests, slow down.",
                           "retryable": True, "retry_after": retry}},
                status_code=429, headers={"Retry-After": str(retry)})
        else:
            try:
                response = await call_next(request)
            except Exception as exc:  # noqa: BLE001 - last resort; ApiError & validation have their own handlers
                # Handled HERE (inside the CORS middleware) so the 500 still carries CORS headers, the request id,
                # and is counted in stats and the request log, which Starlette's outermost handler would skip.
                request.state.error_code = "INTERNAL_ERROR"
                log.error("unhandled", exc_info=exc, extra={"ctx": {"route": path}})
                response = _internal_error_response()
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


def _internal_error_response() -> JSONResponse:
    return JSONResponse({"error": {"code": "INTERNAL_ERROR", "retryable": True,
                                   "message": "Unexpected server error. Please try again."}}, status_code=500,
                        headers={"X-Request-ID": request_id_var.get()})


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    """Fallback for errors raised outside the observe_and_limit middleware (it handles the normal case itself)."""
    request.state.error_code = "INTERNAL_ERROR"
    log.error("unhandled", exc_info=exc, extra={"ctx": {"route": request.url.path}})
    return _internal_error_response()


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
    # Parallel fetch under ONE overall deadline: before, 5 slow symbols x (timeout x retries) each could keep a worker
    # busy for minutes. Late symbols are reported as failed; their downloads still finish and fill the cache.
    pool = ThreadPoolExecutor(max_workers=len(syms), thread_name_prefix="compare")
    try:
        futures = {sym: pool.submit(contextvars.copy_context().run, _history, provider, sym, config.RANGES[range])
                   for sym in syms}  # copy_context keeps the request id in worker-thread logs
        wait(futures.values(), timeout=config.COMPARE_DEADLINE_S)
        for sym, fut in futures.items():
            if not fut.done():
                exc: ApiError = UpstreamTimeout("Took too long to fetch this symbol; try again in a moment.")
            else:
                try:
                    fetched[sym] = fut.result()
                    continue
                except ApiError as e:
                    exc = e
            first_error = first_error or exc
            failed.append({"symbol": sym, "code": exc.code, "message": exc.message})
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
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


@app.get("/api/_stats", include_in_schema=False)
def get_stats(request: Request):
    _require_admin(request)
    return stats.snapshot()


@app.post("/api/_client-error", include_in_schema=False)
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
    got = search_cache.fetch(("search", provider.name, q.lower()), 3600, lambda: provider.search(q),
                             stale_max_age=86400)
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


def _volume(v) -> int:
    """Volume as an int; missing/NaN/inf (some providers and some instruments have none) becomes 0, not a 500."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0
    return int(f) if np.isfinite(f) and f > 0 else 0


@app.get("/api/history/{symbol}")
def history(symbol: str, range: str = Query("6mo"), provider: BaseProvider = Depends(get_provider)):
    sym = normalize_symbol(symbol)
    if range not in config.RANGES:
        raise InvalidRange(f"range must be one of {sorted(config.RANGES)}")
    got = _history(provider, sym, config.RANGES[range])
    df = got.value
    pts = [{"date": d.strftime("%Y-%m-%d"), "close": round(float(r.Close), 4), "volume": _volume(r.Volume)}
           for d, r in df.iterrows()]
    return {"symbol": sym, "range": range, "points": pts, **_freshness(df, got)}


def _downsample(close: pd.Series, max_points: int) -> pd.Series:
    """Keep at most ~max_points closes: the last close of each equal-sized bucket, plus the first point, the period high
    and the period low (so the chart never hides the extremes quoted in the summary)."""
    n = len(close)
    if n <= max_points:
        return close
    keep = {0, n - 1, int(np.argmax(close.to_numpy())), int(np.argmin(close.to_numpy()))}
    edges = np.linspace(0, n, max_points - 3, dtype=int)
    keep.update(int(e) - 1 for e in edges[1:] if e > 0)
    return close.iloc[sorted(keep)]


@app.get("/api/timeline/{symbol}")
def timeline(symbol: str, range: str = Query("5y"), provider: BaseProvider = Depends(get_provider)):
    """History for the main chart: closes over 1mo/3mo/6mo/1y/2y/5y, downsampled, with period return, high, low and
    worst drawdown computed on the full data. (/api/history keeps returning every bar with volume.)"""
    sym = normalize_symbol(symbol)
    if range not in config.TIMELINE_RANGES:
        raise InvalidRange(f"range must be one of {list(config.TIMELINE_RANGES)}")
    got = _history(provider, sym, "5y")  # one cached download serves every window
    df = got.value
    close = df["Close"].dropna()
    close = close[close > 0]
    start = close.index[-1] - pd.DateOffset(months=config.TIMELINE_RANGES[range])
    window = close[close.index >= start]
    if len(window) < 2:
        raise InsufficientData("Not enough price history to draw a timeline.")
    first, last = float(window.iloc[0]), float(window.iloc[-1])
    hi_i, lo_i = int(np.argmax(window.to_numpy())), int(np.argmin(window.to_numpy()))
    pts = _downsample(window, config.TIMELINE_MAX_POINTS)
    return {
        "symbol": sym, "range": range,
        "points": [{"date": d.strftime("%Y-%m-%d"), "close": round(float(v), 4)} for d, v in pts.items()],
        "n_points_total": int(len(window)), "downsampled": bool(len(pts) < len(window)),
        "summary": {"start_date": window.index[0].strftime("%Y-%m-%d"),
                    "end_date": window.index[-1].strftime("%Y-%m-%d"),
                    "start_close": round(first, 4), "end_close": round(last, 4),
                    "period_return_pct": round((last / first - 1) * 100, 2),
                    "high": round(float(window.iloc[hi_i]), 4), "high_date": window.index[hi_i].strftime("%Y-%m-%d"),
                    "low": round(float(window.iloc[lo_i]), 4), "low_date": window.index[lo_i].strftime("%Y-%m-%d"),
                    "max_drawdown_pct": round(float((window / window.cummax() - 1).min() * 100), 2)},
        "note": "Adjusted closing prices (splits and dividends included). "
                "Past performance does not predict future results.",
        **_freshness(df, got), "disclaimer": config.DISCLAIMER,
    }


def _calibration_history(provider: BaseProvider, sym: str, horizon: int) -> pd.Series | None:
    """Ten years of closes, used ONLY to calibrate the conformal band at long (cone) horizons, where five years hold too
    few independent periods. Best effort under a deadline: on any failure the forecast simply falls back to the
    uncalibrated volatility cone (the response says why). The download keeps running and warms the cache."""
    if horizon < config.VOL_CONE_MIN_HORIZON or not conformal.calibration_feasible(horizon):
        return None
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="calib")
    try:
        fut = pool.submit(contextvars.copy_context().run, _history, provider, sym, "10y")
        return fut.result(timeout=config.CALIB_FETCH_DEADLINE_S).value["Close"]
    except Exception as exc:  # noqa: BLE001 - best effort by design: any failure means "use the uncalibrated cone"
        log_event(log, "calibration_history_unavailable", logging.INFO, symbol=sym, error_class=type(exc).__name__)
        return None
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _forecast_for(provider: BaseProvider, sym: str, horizon: int) -> tuple[dict, pd.DataFrame, Fetched]:
    hist = _history(provider, sym, "5y")  # served from (stale) cache if the provider is failing
    df = hist.value

    def build():
        return {"symbol": sym, **forecast(df["Close"], horizon, _calibration_history(provider, sym, horizon))}

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
    if bt["skill_vs_baseline"] > 0 and ((ci and ci[0] <= 0) or bt.get("too_few_independent")):
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
                "range_tested": bool(result["conformal"]["used"]),
                "range_coverage": result["conformal"]["measured_coverage"],
                "range_independent_tests": result["conformal"]["n_evaluation_independent"],
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


# --- model comparison & volatility (bounded: one symbol, five cheap models, cached) ----------------------
def _volatility_for(provider: BaseProvider, sym: str, horizon: int) -> tuple[dict, pd.DataFrame, Fetched]:
    hist = _history(provider, sym, "5y")
    df = hist.value
    key = ("vol", provider.name, sym, horizon, df.index[-1].date())
    result = cache.fetch(key, config.MODELS_TTL_S,
                         lambda: {"symbol": sym, **forecast_volatility(df["Close"], horizon)}).value
    return result, df, hist


@app.get("/api/compare-models/{symbol}")
def compare_models_endpoint(symbol: str, horizon: int = Query(5, ge=1, le=config.MAX_HORIZON),
                            provider: BaseProvider = Depends(get_provider)):
    """Walk-forward (+ embargo) error of several simple models vs the naive 'price stays flat' baseline.

    ``risk_models`` adds the volatility models (EWMA, HAR, GJR-GARCH) judged the same way on the size of moves;
    it comes from the same cached computation as /api/volatility and is omitted if that cannot be computed."""
    sym = normalize_symbol(symbol)
    hist = _history(provider, sym, "5y")
    df = hist.value
    key = ("models", provider.name, sym, horizon, df.index[-1].date())
    result = cache.fetch(key, config.MODELS_TTL_S,
                         lambda: {"symbol": sym, **compare_models(df["Close"], horizon)}).value
    risk = None
    try:
        vol, _, _ = _volatility_for(provider, sym, horizon)
        risk = {"headline_model": vol["headline_model"], "garch": vol["garch"],
                "models": [{k: m[k] for k in ("model", "label", "description", "typical_error_pct", "skill_vs_naive",
                                              "skill_ci_90", "verdict", "annualized_vol", "vs_headline")
                            if k in m} for m in vol["models"]]}
    except InsufficientData:
        pass  # not enough history for the volatility models: the point-model table is still returned
    return {**result, "risk_models": risk, **_freshness(df, hist), "disclaimer": config.DISCLAIMER}


@app.get("/api/volatility/{symbol}")
def volatility_endpoint(symbol: str, horizon: int = Query(5, ge=1, le=config.MAX_HORIZON),
                        provider: BaseProvider = Depends(get_provider)):
    """Forecast realised volatility and a 1-sigma risk range, judged walk-forward vs 'recent realised vol'."""
    sym = normalize_symbol(symbol)
    result, df, hist = _volatility_for(provider, sym, horizon)
    return {**result, **_freshness(df, hist), "disclaimer": config.DISCLAIMER}


@app.get("/api/spikes/{symbol}")
def spikes_endpoint(symbol: str, horizon: int = Query(5, ge=1, le=config.MAX_HORIZON),
                    provider: BaseProvider = Depends(get_provider)):
    """EXPERIMENTAL: simulated up/down spikes (jump-diffusion Monte Carlo) clamped inside the standard forecast band.

    Separate from /api/forecast and never used by the prediction log. Includes a walk-forward backtest of the
    spike range against the standard interval, reported whichever way it falls.
    """
    sym = normalize_symbol(symbol)
    hist = _history(provider, sym, "5y")
    df = hist.value

    def build():
        base, _, _ = _forecast_for(provider, sym, horizon)
        # the spike scenario was built and validated against the pre-conformal band, so it keeps using that one
        return {"symbol": sym, **spike_forecast(df["Close"], horizon, legacy_view(base))}

    key = ("spikes", provider.name, sym, horizon, df.index[-1].date())
    result = cache.fetch(key, config.MODELS_TTL_S, build).value
    return {**result, **_freshness(df, hist), "disclaimer": config.DISCLAIMER}


# --- live prediction log -------------------------------------------------------------------------------
_store: PredictionStore | None = None
_store_lock = threading.Lock()


def get_store() -> PredictionStore:
    global _store
    with _store_lock:
        if _store is None:
            url = config.DATABASE_URL or "sqlite:///" + os.path.join(tempfile.gettempdir(), "prediction_log.db")
            _store = PredictionStore(url)
        return _store


def _require_task_token(request: Request) -> None:
    if not config.LOG_TASK_TOKEN:
        raise NotFound("Not found.")
    supplied = request.headers.get("authorization", "")
    if not hmac.compare_digest(supplied.encode(), f"Bearer {config.LOG_TASK_TOKEN}".encode()):
        raise Unauthorized("Missing or invalid task token.")


def _refetch_history(provider: BaseProvider, sym: str, period: str) -> Fetched | None:
    """Fetch history straight from the provider, bypassing the TTL cache (whose copy is behind), and cache the result.
    None if the provider fails: the caller then treats the data as not updated."""
    try:
        df = provider.history(sym, period)
    except ApiError as exc:
        log_event(log, "prediction_log_refetch_failed", logging.WARNING, symbol=sym, code=exc.code)
        return None
    return cache.put(("hist", provider.name, sym, period), df, config.HISTORY_TTL_S, config.STALE_MAX_AGE_S)


@app.post("/api/_tasks/run-prediction-log", include_in_schema=False)
def run_prediction_log(request: Request, provider: BaseProvider = Depends(get_provider),
                       store: PredictionStore = Depends(get_store)):
    """Scheduled job (GitHub Actions): log predictions for the fixed allowlist, then resolve old ones.
    Disabled (404) unless LOG_TASK_TOKEN is set. Idempotent: one row per (symbol, horizon, base date).

    Each run knows which session it should be logging (``expected_base``: today's close after 16:10 New York time on a
    trading day, otherwise the previous trading day's close). A symbol is only logged, or counted as already logged,
    for exactly that base. Data that ends earlier is refetched once past the cache; if it is still behind, the symbol
    is skipped as DATA_NOT_UPDATED (an older base is never reported as ALREADY_LOGGED). Between the open and the close
    nothing is logged (SESSION_IN_PROGRESS): the outcome window of the previous close has already started."""
    _require_task_token(request)
    now = freshness.now_ny()  # looked up at call time so tests (and the clock fixture) can pin it
    expected = expected_base_session(now)
    expected_iso = expected.isoformat()
    in_session = session_in_progress(now)
    logged, skipped, results = [], [], []

    def skip(sym: str, reason: str, base=None, **extra) -> None:
        skipped.append({"symbol": sym, "reason": reason, **extra})
        results.append({"symbol": sym, "base_date": base.isoformat() if base else None, "status": reason, **extra})

    for sym in config.LOG_SYMBOLS:
        if in_session:
            skip(sym, "SESSION_IN_PROGRESS")
            continue
        try:
            result, df, hist = _forecast_for(provider, sym, config.LOG_HORIZON)
        except ApiError as exc:
            skip(sym, exc.code)
            continue
        base = df.index[-1].date()
        refetched = False
        if base < expected:
            # The cached copy (or the provider) is behind the session we expect: try once more, bypassing the cache.
            refetched = True
            fresh = _refetch_history(provider, sym, "5y")
            if fresh is not None and fresh.value.index[-1].date() > base:
                try:
                    result, df, hist = _forecast_for(provider, sym, config.LOG_HORIZON)
                except ApiError as exc:
                    skip(sym, exc.code, base, refetched=True)
                    continue
                base = df.index[-1].date()
        if base < expected:
            skip(sym, "DATA_NOT_UPDATED", base, expected_base=expected_iso, refetched=refetched)
            continue
        lag = trading_days_between(base, now.date())
        if hist.stale or lag > 1:
            # Stale data could mean the outcome is already known (hindsight), so it is never logged.
            skip(sym, "STALE_DATA", base)
            continue
        if base > expected or not bar_is_final(base, now):
            # Today's bar before the close is a partial intraday value, not a close: never log a base from it.
            skip(sym, "PARTIAL_BAR", base)
            continue
        if store.add_prediction(record_from_forecast(result)):
            logged.append(sym)
            results.append({"symbol": sym, "base_date": base.isoformat(), "status": "LOGGED"})
        else:
            skip(sym, "ALREADY_LOGGED", base)

    present = store.symbols_with_base(expected_iso, config.LOG_HORIZON)
    batch = {"base_date": expected_iso, "horizon_days": config.LOG_HORIZON,
             "present": [s for s in config.LOG_SYMBOLS if s in present],
             "missing": [s for s in config.LOG_SYMBOLS if s not in present]}
    batch["complete"] = not batch["missing"]

    def history_for(sym: str):
        return _history(provider, sym, "5y").value["Close"]

    resolved = resolve_pending(store, history_for)
    cache.clear_prefix("plog")
    log_event(log, "prediction_log_run", logged=len(logged), skipped=len(skipped), expected_base=expected_iso,
              batch_complete=batch["complete"], **resolved)
    return {"logged": logged, "skipped": skipped, "expected_base": expected_iso, "results": results,
            "expected_batch": batch, **resolved, "ran_at": now_iso()}


@app.get("/api/prediction-log")
def prediction_log(limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0, le=100_000),
                   symbol: str | None = Query(None, max_length=16), status: str | None = Query(None),
                   store: PredictionStore = Depends(get_store)):
    """Public, read-only, paginated live prediction log plus the live scorecard (resolved rows only)."""
    sym = normalize_symbol(symbol) if symbol else None
    if status not in (None, "pending", "resolved"):
        raise InvalidRequest("status must be 'pending' or 'resolved'.")

    def build():
        pg = store.page(limit, offset, sym, status)
        rows = store.all_rows()
        return {"items": [public_row(r) for r in pg.items], "total": pg.total, "limit": limit, "offset": offset,
                "scorecard": scorecard(rows, config.LOG_HORIZON), **store.verify_report(rows),
                "hash_spec": hash_spec(),
                "symbols": config.LOG_SYMBOLS, "horizon_days": config.LOG_HORIZON,
                "missed_sessions": missed_sessions(config.LOG_SYMBOLS),
                "storage": {"backend": store.backend, "durable": store.backend != "sqlite"}}

    got = cache.fetch(("plog", sym, status, limit, offset), config.PREDICTION_LOG_TTL_S, build)
    return {**got.value, **describe_fetch(got.fetched_at, False), "disclaimer": config.DISCLAIMER}



# --- trending momentum screen --------------------------------------------------------------------------
# Concurrent cold requests for the SAME window share one download via the cache's single-flight; this lock only
# keeps requests for DIFFERENT windows from downloading the whole universe at the same moment.
_trending_lock = threading.Lock()


def _compute_trending(provider: BaseProvider, days: int) -> dict:
    from .universe import NAMES, SYMBOLS
    frames = provider.batch_history(SYMBOLS, "1mo")
    rows = []
    for sym, df in frames.items():
        close = df["Close"].dropna()
        if len(close) < days + 1 or float(close.iloc[-1 - days]) <= 0:
            continue
        rows.append({"symbol": sym, "name": NAMES.get(sym, ""), "last_close": float(close.iloc[-1]),
                     "start_close": float(close.iloc[-1 - days]), "as_of": close.index[-1].date()})
    if not rows:
        raise DataUnavailable("No usable price data for the trending screen.", retryable=True)
    as_of = max(r["as_of"] for r in rows)
    rows = [r for r in rows if r["as_of"] == as_of]  # drop tickers whose latest bar is older (halted/lagging)
    if len(rows) < config.TRENDING_MIN_COVERAGE * len(SYMBOLS):
        raise DataUnavailable(f"Only {len(rows)} of {len(SYMBOLS)} tickers had current data.", retryable=True)
    for r in rows:
        r["return_percent"] = round((r["last_close"] / r["start_close"] - 1) * 100, 2)
    rows.sort(key=lambda r: (-r["return_percent"], r["symbol"]))
    return {"rows": rows, "as_of": as_of, "universe_size": len(SYMBOLS), "evaluated": len(rows)}


@app.get("/api/trending")
def trending(days: int = Query(3, ge=1, le=config.TRENDING_MAX_DAYS),
             limit: int = Query(5, ge=1, le=config.TRENDING_MAX_LIMIT),
             provider: BaseProvider = Depends(get_provider)):
    """Top gainers by close-to-close return over the last ``days`` trading days within a fixed, curated
    universe of liquid US large caps. A plain momentum screen: not a recommendation or a prediction."""
    def build():
        with _trending_lock:
            return _compute_trending(provider, days)

    got = cache.fetch(("trending", provider.name, days), config.TRENDING_TTL_S, build,
                      stale_max_age=config.STALE_MAX_AGE_S)
    v = got.value
    items = [{"rank": i, "symbol": r["symbol"], "name": r["name"], "return_percent": r["return_percent"],
              "last_close": round(r["last_close"], 4), "as_of": r["as_of"].isoformat()}
             for i, r in enumerate(v["rows"][:limit], start=1)]
    return {"days": days, "limit": limit, "items": items, "universe_size": v["universe_size"],
            "evaluated": v["evaluated"], "method": f"Close-to-close return over the last {days} trading days, "
            f"ranked within a fixed list of {v['universe_size']} liquid US large-cap stocks.",
            "note": "A plain momentum screen, not a recommendation or a prediction. Past gains do not predict "
                    "future returns, and stocks that jumped recently often give some of it back.",
            **describe(v["as_of"], got.fetched_at, got.stale), "disclaimer": config.DISCLAIMER}
