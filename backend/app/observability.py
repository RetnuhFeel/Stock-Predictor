"""Privacy-friendly observability: JSON logs with request IDs, in-memory aggregate counters, optional Sentry.

What is NEVER recorded: IP addresses, user agents, cookies, query strings, request bodies, symbols that a
specific person looked at (only route *templates* are counted). Everything lives in process memory
and is lost on restart.
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import re
import sys
import threading
import time
import uuid
from collections import Counter
from datetime import UTC, datetime

from . import config

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
LATENCY_BUCKETS_MS = [50, 100, 250, 500, 1000, 2500, 5000]


def new_request_id(inbound: str | None) -> str:
    """Accept a caller-supplied ID only if it is a short, harmless token; otherwise generate one."""
    return inbound if inbound and _SAFE_ID.match(inbound) else uuid.uuid4().hex


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {"ts": datetime.fromtimestamp(record.created, UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
               "level": record.levelname, "event": record.getMessage(), "request_id": request_id_var.get()}
        out.update(getattr(record, "ctx", {}))
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)[-1500:]
        return json.dumps(out, default=str)


def disable_server_access_log() -> None:
    """Belt and braces for hosts that start uvicorn with their own command (so the Dockerfile flag is not used):
    uvicorn's access log records the client address and the full URL including the query string. Our own
    ``request`` log event replaces it and carries neither."""
    logging.getLogger("uvicorn.access").disabled = True


def setup_logging() -> logging.Logger:
    disable_server_access_log()
    log = logging.getLogger("stock-api")
    log.setLevel(config.LOG_LEVEL)
    if not log.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(JsonFormatter() if config.LOG_FORMAT == "json"
                       else logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(h)
        log.propagate = False
    return log


def log_event(log: logging.Logger, event: str, level: int = logging.INFO, **ctx) -> None:
    log.log(level, event, extra={"ctx": ctx})


class Stats:
    """Aggregate counters only. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.started = time.time()
            self.requests = 0
            self.by_route: Counter[str] = Counter()
            self.by_status: Counter[str] = Counter()
            self.by_error_code: Counter[str] = Counter()
            self.latency: Counter[str] = Counter()
            self.latency_total_ms = 0.0
            self.client_errors = 0

    def record(self, route: str, status: int, ms: float, error_code: str | None) -> None:
        bucket = next((f"<={b}ms" for b in LATENCY_BUCKETS_MS if ms <= b), f">{LATENCY_BUCKETS_MS[-1]}ms")
        with self._lock:
            self.requests += 1
            self.by_route[route] += 1
            self.by_status[f"{status // 100}xx"] += 1
            self.latency[bucket] += 1
            self.latency_total_ms += ms
            if error_code:
                self.by_error_code[error_code] += 1

    def record_client_error(self) -> None:
        with self._lock:
            self.client_errors += 1

    def snapshot(self) -> dict:
        with self._lock:
            n = self.requests
            return {
                "since": datetime.fromtimestamp(self.started, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "uptime_s": int(time.time() - self.started),
                "requests_total": n,
                "avg_latency_ms": round(self.latency_total_ms / n, 1) if n else None,
                "latency_buckets": dict(self.latency),
                "by_route": dict(self.by_route),
                "by_status": dict(self.by_status),
                "by_error_code": dict(self.by_error_code),
                "client_errors_reported": self.client_errors,
                "note": "In-memory aggregates only (no IPs/PII); reset on restart.",
            }


# --- sanitising browser error reports ---------------------------------------------------------
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL_QS = re.compile(r"(https?://[^\s?#)\"']*)[?#][^\s)\"']*")
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def scrub(text: str, limit: int) -> str:
    """Drop query strings/fragments from URLs, redact emails and control characters, truncate."""
    text = _URL_QS.sub(r"\1", text)
    text = _EMAIL.sub("[email]", text)
    return _CTRL.sub("", text)[:limit]


def scrub_route(route: str) -> str:
    path = route.split("?")[0].split("#")[0]
    return path[:100] if path.startswith("/") else "/"


def init_sentry(dsn: str, log: logging.Logger) -> bool:
    """Optional backend error tracking. Needs `pip install sentry-sdk`; never sends PII or traces."""
    if not dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        log_event(log, "sentry_unavailable", logging.WARNING, hint="SENTRY_DSN is set but sentry-sdk is not installed")
        return False

    def before_send(event, hint):
        event.pop("request", None)  # no URLs/headers/cookies/IPs
        event.pop("user", None)
        return event

    sentry_sdk.init(dsn=dsn, send_default_pii=False, traces_sample_rate=0.0, before_send=before_send)
    return True


def fingerprint(text: str) -> str:
    """Short stable hash to group identical client errors in logs."""
    return hashlib.sha1(text.encode(), usedforsecurity=False).hexdigest()[:10]
