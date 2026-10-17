"""Render cron scheduler (backend/scripts/scheduled_log.py): NY-time window gating and response handling.
All HTTP is mocked; dates are pinned (or derived from the conftest calendar helpers), so the tests hold on weekends
and holidays."""
import importlib.util
import io
import json
import sys
import urllib.error
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.marketcal import is_trading_day, previous_trading_day

from .conftest import last_bar_date

NY = ZoneInfo("America/New_York")
_spec = importlib.util.spec_from_file_location(
    "scheduled_log", Path(__file__).resolve().parents[1] / "scripts" / "scheduled_log.py")
sl = importlib.util.module_from_spec(_spec)
sys.modules["scheduled_log"] = sl  # dataclasses look the module up while the script loads
_spec.loader.exec_module(sl)

ENV = {"API_BASE_URL": "https://api.example.test/", "LOG_TASK_TOKEN": "super-secret-token-value"}


def ny(*a):
    return datetime(*a, tzinfo=NY)


def utc(*a):
    return datetime(*a, tzinfo=UTC)


# ---------- window gating ----------

@pytest.mark.parametrize("when, is_open, kind, deadline", [
    (ny(2026, 10, 14, 16, 29), False, "closed", False),   # Wed, before 16:30
    (ny(2026, 10, 14, 16, 30), True, "evening", False),
    (ny(2026, 10, 14, 23, 59), True, "evening", False),
    (ny(2026, 10, 15, 0, 0), True, "morning", False),     # Thu morning after Wed
    (ny(2026, 10, 15, 8, 49), True, "morning", False),
    (ny(2026, 10, 15, 8, 50), True, "morning", True),     # deadline from 08:50
    (ny(2026, 10, 15, 9, 0), True, "morning", True),
    (ny(2026, 10, 15, 9, 10), False, "closed", False),    # window ends 09:10
    (ny(2026, 10, 15, 12, 0), False, "closed", False),    # market hours
    (ny(2026, 10, 17, 6, 0), True, "morning", False),    # Sat morning after Fri session
    (ny(2026, 10, 17, 17, 0), False, "closed", False),    # Sat evening
    (ny(2026, 10, 18, 17, 0), False, "closed", False),    # Sun evening
    (ny(2026, 10, 19, 6, 0), False, "closed", False),     # Mon morning: yesterday was Sunday
    (ny(2026, 11, 26, 17, 0), False, "closed", False),    # Thanksgiving evening
    (ny(2026, 11, 27, 6, 0), False, "closed", False),     # morning after Thanksgiving
    (ny(2026, 11, 27, 17, 0), True, "evening", False),    # day after Thanksgiving (early close) is a trading day
    (ny(2026, 4, 3, 17, 0), False, "closed", False),      # Good Friday
    (ny(2026, 12, 25, 6, 0), False, "closed", False),     # Christmas morning, after the Dec 24 session? see below
])
def test_window(when, is_open, kind, deadline):
    if when.date() == date(2026, 12, 25):  # Dec 24 2026 (Thu) is a trading day, so this morning is open
        is_open, kind = True, "morning"
    w = sl.window(when)
    assert (w.open, w.kind, w.deadline) == (is_open, kind, deadline)


@pytest.mark.parametrize("when, is_open", [
    # EDT (UTC-4) on Fri Oct 30 2026; EST (UTC-5) from Sun Nov 1. The UTC cron fires at the same UTC minutes all year.
    (utc(2026, 10, 30, 20, 20), False), (utc(2026, 10, 30, 20, 40), True),   # 16:20 / 16:40 EDT
    (utc(2026, 11, 2, 21, 20), False), (utc(2026, 11, 2, 21, 40), True),     # 16:20 / 16:40 EST
    (utc(2026, 11, 3, 14, 0), True), (utc(2026, 11, 3, 14, 20), False),      # 09:00 / 09:20 EST
    (utc(2026, 3, 10, 13, 0), True), (utc(2026, 3, 10, 13, 20), False),      # 09:00 / 09:20 EDT (after Mar 8)
    (utc(2026, 3, 6, 21, 20), False), (utc(2026, 3, 6, 21, 40), True),       # Fri before DST: 16:20 / 16:40 EST
])
def test_window_dst_edges(when, is_open):
    assert sl.window(when).open is is_open


def test_deadline_across_dst():
    assert sl.window(utc(2026, 11, 3, 13, 40)).deadline is False   # 08:40 EST
    assert sl.window(utc(2026, 11, 3, 14, 0)).deadline is True     # 09:00 EST
    assert sl.window(utc(2026, 10, 29, 12, 40)).deadline is False  # 08:40 EDT
    assert sl.window(utc(2026, 10, 29, 13, 0)).deadline is True    # 09:00 EDT


def test_window_relative_to_today():
    last = date.fromisoformat(last_bar_date())        # most recent trading day on or before today
    assert sl.window(datetime.combine(last, datetime.min.time(), NY).replace(hour=17)).open
    nxt = last + timedelta(days=1)
    assert sl.window(datetime.combine(nxt, datetime.min.time(), NY).replace(hour=8, minute=55)).deadline
    before = previous_trading_day(last) + timedelta(days=1)
    while is_trading_day(before - timedelta(days=1)):  # find a morning whose previous day is not a session
        before += timedelta(days=1)
    assert not sl.window(datetime.combine(before, datetime.min.time(), NY).replace(hour=6)).open


# ---------- response handling ----------

def body(missing=(), skipped=(), logged=()):
    return {"logged": list(logged), "skipped": [{"symbol": s, "reason": r} for s, r in skipped],
            "expected_batch": {"base_date": "2026-10-14", "missing": list(missing), "present": [],
                               "complete": not missing}}


@pytest.mark.parametrize("status, b, deadline, code, word", [
    (200, body(logged=["SPY"]), False, 0, "OK"),
    (200, body(skipped=[("SPY", "ALREADY_LOGGED")]), True, 0, "OK"),
    (200, body(missing=["SPY"], skipped=[("SPY", "SESSION_IN_PROGRESS")]), True, 0, "market is open"),
    (200, body(missing=["SPY"], skipped=[("SPY", "DATA_NOT_UPDATED")]), False, 0, "WARNING"),
    (200, body(missing=["SPY"], skipped=[("SPY", "DATA_NOT_UPDATED")]), True, 1, "MISSING BATCH"),
    (200, {"logged": [], "skipped": []}, False, 1, "expected_batch"),
    (200, None, False, 1, "unexpected"),
    (401, None, False, 1, "rejected"),
    (404, None, False, 1, "rejected"),
    (503, None, False, 0, "WARNING"),
    (None, None, False, 0, "WARNING"),
    (None, None, True, 1, "MISSING BATCH"),
])
def test_judge(status, b, deadline, code, word):
    out = sl.judge(status, b, deadline)
    assert out.code == code and word in out.message


class Resp(io.BytesIO):
    def __init__(self, status, payload):
        super().__init__(json.dumps(payload).encode())
        self.status = status


def opener_from(seq, seen):
    seq = list(seq)

    def opener(req, timeout):
        seen.append(req)
        item = seq.pop(0)
        if isinstance(item, Exception):
            raise item
        status, payload = item
        if status != 200:
            raise urllib.error.HTTPError(req.full_url, status, "err", {}, io.BytesIO(json.dumps(payload).encode()))
        return Resp(status, payload)
    return opener


def test_main_retries_cold_start_then_succeeds(capsys):
    seen, waits = [], []
    op = opener_from([urllib.error.URLError("refused"), (502, {}), (200, body(logged=["SPY"]))], seen)
    code = sl.main(ny(2026, 10, 14, 18, 0), ENV, sleep=waits.append, opener=op)
    out = capsys.readouterr().out
    assert code == 0 and "OK" in out and waits == [15, 30]
    assert seen[0].full_url == "https://api.example.test/api/_tasks/run-prediction-log"
    assert seen[0].get_method() == "POST" and seen[0].get_header("Authorization") == "Bearer " + ENV["LOG_TASK_TOKEN"]
    assert ENV["LOG_TASK_TOKEN"] not in out


def test_main_gives_up_after_retries_and_alarms_at_deadline(capsys):
    seen, waits = [], []
    op = opener_from([(503, {})] * 5, seen)
    assert sl.main(ny(2026, 10, 15, 9, 0), ENV, sleep=waits.append, opener=op) == 1
    assert len(seen) == 5 and waits == list(sl.BACKOFF_S)
    assert "MISSING BATCH" in capsys.readouterr().out


def test_main_does_not_retry_auth_errors():
    seen = []
    assert sl.main(ny(2026, 10, 14, 18, 0), ENV, sleep=lambda s: None, opener=opener_from([(401, {})], seen)) == 1
    assert len(seen) == 1


def test_main_outside_window_makes_no_call(capsys):
    def boom(*a, **k):
        raise AssertionError("no HTTP call outside the window")
    assert sl.main(ny(2026, 10, 17, 17, 0), ENV, opener=boom) == 0           # Saturday evening
    assert sl.main(ny(2026, 10, 15, 12, 0), {}, opener=boom) == 0            # market hours, no env needed
    assert "outside the logging window" in capsys.readouterr().out


def test_main_requires_env_inside_window():
    assert sl.main(ny(2026, 10, 14, 18, 0), {}, opener=lambda *a, **k: None) == 1
