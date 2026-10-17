"""Primary scheduler for the prediction log (Render cron job, every 20 minutes, schedule in UTC).

Calls the token-protected ``POST /api/_tasks/run-prediction-log`` on the API, but only inside the logging window
(New York time, decided here so DST does not matter):

  * evening: a NYSE trading day from 16:30 until midnight (the API logs that day's close after 16:10);
  * morning: 00:00-09:10 the morning after a trading day (the API logs the previous session's close).

Outside the window it exits 0 without any network call. Inside it:

  * connection errors, timeouts, HTTP 429 and 5xx (e.g. a free-tier cold start) are retried with backoff;
  * HTTP 200 with the expected batch complete (logged now or ALREADY_LOGGED earlier) is success, and so is a
    SESSION_IN_PROGRESS answer (the API refuses to log during market hours: nothing to do);
  * HTTP 401/404 (token mismatch / task disabled) and an unexpected response are failures (exit 1);
  * an incomplete batch (e.g. DATA_NOT_UPDATED) or a transient outage before the deadline exits 0 with a warning:
    the next run 20 minutes later tries again;
  * from 08:50 NY on a morning run, a batch that is still missing after this attempt exits 1 (missing-batch alarm;
    Render emails on cron failures when failure notifications are enabled).

Env: API_BASE_URL (e.g. https://stock-predictor-api-2dnn.onrender.com) and LOG_TASK_TOKEN (same value as on the
API). The token is never printed. Standard library plus the repo's NYSE calendar (app.marketcal) only.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/, for app.marketcal

from app.marketcal import is_trading_day  # noqa: E402

NY = ZoneInfo("America/New_York")
EVENING_START = dtime(16, 30)
MORNING_END = dtime(9, 10)
DEADLINE = dtime(8, 50)
TASK_PATH = "/api/_tasks/run-prediction-log"
BACKOFF_S = (15, 30, 60, 90)   # waits between attempts: 5 attempts in total, about 3 min plus request time
TIMEOUT_S = 120                # a cold start on the free tier can take about a minute


@dataclass(frozen=True)
class Window:
    open: bool
    kind: str           # "evening", "morning" or "closed"
    reason: str
    deadline: bool = False


def window(now: datetime) -> Window:
    """Whether ``now`` (any tz-aware time; converted to New York) is inside the logging window."""
    now = now.astimezone(NY)
    t, d = now.time(), now.date()
    if t >= EVENING_START:
        if is_trading_day(d):
            return Window(True, "evening", f"after the {d} close")
        return Window(False, "closed", f"{d} is not a trading day")
    if t < MORNING_END:
        prev = d - timedelta(days=1)
        if is_trading_day(prev):
            return Window(True, "morning", f"morning after the {prev} session", deadline=t >= DEADLINE)
        return Window(False, "closed", f"{prev} (yesterday) was not a trading day")
    return Window(False, "closed", "between 09:10 and 16:30 New York time")


@dataclass(frozen=True)
class Outcome:
    code: int        # process exit code
    message: str


def judge(status: int | None, body: dict | None, deadline: bool, detail: str = "") -> Outcome:
    """Turn the final HTTP result into an exit code and message. ``status`` None = no response at all."""
    if status in (401, 404):
        return Outcome(1, f"ERROR: task rejected (HTTP {status}): check LOG_TASK_TOKEN on the API and this cron job.")
    if status != 200:
        what = f"HTTP {status}" if status else f"no response ({detail or 'connection failed'})"
        if deadline:
            return Outcome(1, f"MISSING BATCH: the API could not be reached ({what}) and it is past 08:50 New York "
                              "time. Run the workflow manually before the 09:30 open.")
        return Outcome(0, f"WARNING: API unavailable ({what}); the next run retries.")
    if not isinstance(body, dict) or not isinstance(body.get("skipped"), list):
        return Outcome(1, "ERROR: unexpected response shape from the task.")
    reasons = sorted({s.get("reason") for s in body["skipped"] if s.get("reason") != "ALREADY_LOGGED"})
    batch = body.get("expected_batch")
    if not isinstance(batch, dict):
        return Outcome(1, "ERROR: response has no expected_batch (API too old?).")
    base, missing = batch.get("base_date"), batch.get("missing") or []
    summary = f"base={base} logged={len(body.get('logged') or [])} missing={missing} other_skips={reasons or 'none'}"
    if not missing:
        return Outcome(0, f"OK: batch complete. {summary}")
    if reasons == ["SESSION_IN_PROGRESS"]:
        return Outcome(0, f"OK: market is open, nothing to log. {summary}")
    if deadline:
        return Outcome(1, f"MISSING BATCH for {base} at the 08:50 New York deadline: {summary}. Run the workflow "
                          "manually before the 09:30 open; if the close cannot be logged it becomes a gap (add it to "
                          "MISSED_SESSIONS, never back-fill).")
    return Outcome(0, f"WARNING: batch incomplete, the next run retries. {summary}")


def call_task(url: str, token: str, sleep=time.sleep, opener=urllib.request.urlopen):
    """POST with retries. Returns (status | None, body | None, detail)."""
    status, body, detail = None, None, ""
    for attempt, wait in enumerate((*BACKOFF_S, None), start=1):
        req = urllib.request.Request(url, method="POST", data=b"",
                                     headers={"Authorization": f"Bearer {token}", "User-Agent": "render-cron"})
        try:
            with opener(req, timeout=TIMEOUT_S) as resp:
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read() or b""
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            status, raw, detail = None, b"", type(exc).__name__
        print(f"attempt {attempt}: {'HTTP ' + str(status) if status else 'no response (' + detail + ')'}")
        try:
            body = json.loads(raw) if raw else None
        except ValueError:
            body = None
        retryable = status is None or status == 429 or status >= 500
        if not retryable or wait is None:
            return status, body, detail
        sleep(wait)
    return status, body, detail  # pragma: no cover


def main(now: datetime | None = None, env=os.environ, sleep=time.sleep, opener=urllib.request.urlopen) -> int:
    now = (now or datetime.now(NY)).astimezone(NY)
    w = window(now)
    if not w.open:
        print(f"{now:%Y-%m-%d %H:%M %Z}: outside the logging window ({w.reason}); nothing to do.")
        return 0
    base_url, token = env.get("API_BASE_URL", "").strip(), env.get("LOG_TASK_TOKEN", "").strip()
    if not base_url or not token:
        print("ERROR: API_BASE_URL and/or LOG_TASK_TOKEN is not set.")
        return 1
    print(f"{now:%Y-%m-%d %H:%M %Z}: {w.kind} run ({w.reason}){', deadline check' if w.deadline else ''}.")
    status, body, detail = call_task(base_url.rstrip("/") + TASK_PATH, token, sleep=sleep, opener=opener)
    out = judge(status, body, w.deadline, detail)
    print(out.message)
    return out.code


if __name__ == "__main__":
    sys.exit(main())
