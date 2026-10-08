"""Prediction-log task: which session it must log (expected base), refetch of a stale upstream, the morning backup run,
the per-run batch report and the public list of missed sessions."""
import json
import shutil
import subprocess
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app import config, freshness
from app.freshness import expected_base_session, session_in_progress
from app.marketcal import previous_trading_day
from app.trackrecord import MISSED_SESSIONS

from .conftest import synthetic_prices
from .test_prediction_log import rec

NY = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / ".github" / "scripts" / "check-prediction-log-result.sh"


def ny(*a):
    return datetime(*a, tzinfo=NY)


@pytest.fixture
def task(monkeypatch):
    monkeypatch.setattr(config, "LOG_TASK_TOKEN", "task-secret")
    monkeypatch.setattr(config, "LOG_SYMBOLS", ["SPY", "AAPL"])
    return {"Authorization": "Bearer task-secret"}


def pin(monkeypatch, when: datetime) -> None:
    monkeypatch.setattr(freshness, "now_ny", lambda: when)


def serve(fake, *frames):
    """Make the fake provider return these frames in turn (the last one repeats); counts calls."""
    seq = list(frames)
    fake.calls = 0

    def history(symbol, period):
        fake.calls += 1
        return seq[min(fake.calls - 1, len(seq) - 1)]
    fake.history = history


# ---------- calendar rules
@pytest.mark.parametrize("now,expected", [
    (ny(2026, 10, 7, 17, 0), date(2026, 10, 7)),    # Wed after the close: today
    (ny(2026, 10, 7, 16, 10), date(2026, 10, 7)),   # exactly close + buffer
    (ny(2026, 10, 7, 16, 5), date(2026, 10, 6)),    # inside the publishing buffer: still yesterday
    (ny(2026, 10, 7, 11, 0), date(2026, 10, 6)),    # during the session
    (ny(2026, 10, 8, 5, 40), date(2026, 10, 7)),    # morning backup (EDT): the previous session
    (ny(2026, 10, 2, 21, 17), date(2026, 10, 2)),   # the late Friday run that missed 2026-10-02
    (ny(2026, 10, 3, 5, 40), date(2026, 10, 2)),    # Saturday morning backup catches Friday
    (ny(2026, 10, 5, 5, 40), date(2026, 10, 2)),    # Monday morning: Friday
    (ny(2026, 9, 7, 20, 0), date(2026, 9, 4)),      # Labor Day evening: the Friday before
    (ny(2026, 9, 8, 5, 40), date(2026, 9, 4)),      # morning after the holiday
    (ny(2026, 11, 10, 4, 40), date(2026, 11, 9)),   # morning backup in EST (09:40 UTC = 04:40 EST)
    (ny(2026, 11, 27, 17, 30), date(2026, 11, 27)),  # early-close day (13:00): counted after 16:10 like any day
])
def test_expected_base_session(now, expected):
    assert expected_base_session(now) == expected


def test_session_in_progress_and_previous_trading_day():
    assert session_in_progress(ny(2026, 10, 7, 9, 30)) and session_in_progress(ny(2026, 10, 7, 16, 5))
    assert not session_in_progress(ny(2026, 10, 7, 9, 29)) and not session_in_progress(ny(2026, 10, 7, 16, 10))
    assert not session_in_progress(ny(2026, 10, 3, 11, 0)) and not session_in_progress(ny(2026, 9, 7, 11, 0))
    assert previous_trading_day(date(2026, 9, 8)) == date(2026, 9, 4)
    assert previous_trading_day(date(2026, 10, 5)) == date(2026, 10, 2)


def test_backup_cron_runs_before_the_open_in_both_edt_and_est():
    wf = (ROOT / ".github" / "workflows" / "prediction-log.yml").read_text()
    crons = [line.split('"')[1] for line in wf.splitlines() if "cron:" in line]
    assert len(crons) == 2
    morning = [c for c in crons if int(c.split()[1]) < 12][0]
    minute, hour = (int(x) for x in morning.split()[:2])
    assert minute not in (0, 30)  # avoid the busiest scheduling minutes
    for utc_offset in (4, 5):  # EDT, EST: must be before 09:30 New York with a few hours of slack for late starts
        assert (hour - utc_offset) * 60 + minute <= 9 * 60 + 30 - 180
    assert morning.split()[4] == "2-6"  # Tue-Sat mornings: the previous weekday's close


# ---------- the task
def test_after_close_run_logs_todays_close_and_reports_the_batch(client, task, store, fake, monkeypatch):
    serve(fake, synthetic_prices(900, end="2026-10-07"))
    pin(monkeypatch, ny(2026, 10, 7, 18, 30))
    b = client.post("/api/_tasks/run-prediction-log", headers=task).json()
    assert b["expected_base"] == "2026-10-07" and b["logged"] == ["SPY", "AAPL"]
    assert [r["status"] for r in b["results"]] == ["LOGGED", "LOGGED"]
    assert {r["base_date"] for r in b["results"]} == {"2026-10-07"}
    assert b["expected_batch"] == {"base_date": "2026-10-07", "horizon_days": 5, "present": ["SPY", "AAPL"],
                                   "missing": [], "complete": True}
    again = client.post("/api/_tasks/run-prediction-log", headers=task).json()
    assert {s["reason"] for s in again["skipped"]} == {"ALREADY_LOGGED"} and again["expected_batch"]["complete"]


def test_morning_backup_logs_the_previous_close(client, task, store, fake, monkeypatch):
    serve(fake, synthetic_prices(900, end="2026-10-02"))
    pin(monkeypatch, ny(2026, 10, 3, 5, 40))  # Saturday morning
    b = client.post("/api/_tasks/run-prediction-log", headers=task).json()
    assert b["expected_base"] == "2026-10-02" and b["logged"] == ["SPY", "AAPL"]
    assert {r["base_date"] for r in store.all_rows()} == {"2026-10-02"}


def test_the_2026_10_02_incident_is_reported_as_data_not_updated(client, task, store, fake, monkeypatch):
    """Late Friday run, upstream still serving Thursday's bars and Thursday already logged: before the fix this was
    ALREADY_LOGGED (green). Now it refetches once, then skips as DATA_NOT_UPDATED and the batch is incomplete."""
    for sym in ("SPY", "AAPL"):
        store.add_prediction(rec(sym, base_date="2026-10-01"))
    before = store.all_rows()
    serve(fake, synthetic_prices(900, end="2026-10-01"))
    pin(monkeypatch, ny(2026, 10, 2, 21, 17))
    b = client.post("/api/_tasks/run-prediction-log", headers=task).json()
    assert b["expected_base"] == "2026-10-02" and b["logged"] == []
    assert {s["reason"] for s in b["skipped"]} == {"DATA_NOT_UPDATED"}
    assert all(s["refetched"] and s["expected_base"] == "2026-10-02" for s in b["skipped"])
    assert {r["base_date"] for r in b["results"]} == {"2026-10-01"}
    assert b["expected_batch"]["missing"] == ["SPY", "AAPL"] and b["expected_batch"]["complete"] is False
    assert fake.calls == 4  # one cached fetch + one forced refetch per symbol
    assert store.all_rows() == before  # nothing written, chain untouched


def test_stale_cache_is_bypassed_and_the_fresh_close_is_logged(client, task, store, fake, monkeypatch):
    monkeypatch.setattr(config, "LOG_SYMBOLS", ["SPY"])
    serve(fake, synthetic_prices(900, end="2026-10-06"), synthetic_prices(900, end="2026-10-07"))
    pin(monkeypatch, ny(2026, 10, 7, 18, 30))
    b = client.post("/api/_tasks/run-prediction-log", headers=task).json()
    assert b["logged"] == ["SPY"] and b["results"][0]["base_date"] == "2026-10-07" and fake.calls == 2
    # the refetched copy replaced the cached one, so the public forecast now shows the new close too
    assert client.get("/api/forecast/SPY?horizon=5").json()["last_date"] == "2026-10-07" and fake.calls == 2


def test_refetch_failure_counts_as_not_updated(client, task, store, fake, monkeypatch):
    from app.errors import DataUnavailable
    monkeypatch.setattr(config, "LOG_SYMBOLS", ["SPY"])
    old = synthetic_prices(900, end="2026-10-06")
    fake.calls = 0

    def history(symbol, period):
        fake.calls += 1
        if fake.calls > 1:
            raise DataUnavailable("rate limited", retryable=True)
        return old
    fake.history = history
    pin(monkeypatch, ny(2026, 10, 7, 18, 30))
    b = client.post("/api/_tasks/run-prediction-log", headers=task).json()
    assert b["logged"] == [] and b["skipped"][0]["reason"] == "DATA_NOT_UPDATED" and store.all_rows() == []


# ---------- missed sessions (no backfill, no row changes)
def test_missed_sessions_are_listed_publicly_without_touching_the_log(client, store):
    store.add_prediction(rec("SPY", base_date="2026-10-01"))
    before = store.all_rows()
    b = client.get("/api/prediction-log").json()
    m = {x["base_date"]: x for x in b["missed_sessions"]}["2026-10-02"]
    assert m["symbols"] == config.LOG_SYMBOLS and m["backfilled"] is False
    assert "not filled in" in m["note"] and "hindsight" in m["note"]
    assert store.all_rows() == before and b["chain_ok"] is True
    assert all(r["base_date"] != "2026-10-02" for r in b["items"])
    assert [x["base_date"] for x in MISSED_SESSIONS] == ["2026-10-02"]


# ---------- the workflow's result check
def _check(tmp_path, body) -> subprocess.CompletedProcess:
    f = tmp_path / "out.json"
    f.write_text(json.dumps(body))
    return subprocess.run(["bash", str(CHECK), str(f)], capture_output=True, text=True)


needs_jq = pytest.mark.skipif(not shutil.which("jq") or not shutil.which("bash"), reason="needs bash and jq")


def _resp(present, missing, logged=(), skipped=()):
    return {"logged": list(logged), "skipped": list(skipped), "expected_base": "2026-10-02",
            "expected_batch": {"base_date": "2026-10-02", "horizon_days": 5, "present": present, "missing": missing,
                               "complete": not missing}, "resolved": 0, "still_pending": 0}


@needs_jq
def test_check_script_passes_when_the_expected_batch_is_complete(tmp_path):
    ok = _resp(["SPY", "AAPL"], [], logged=["SPY"], skipped=[{"symbol": "AAPL", "reason": "ALREADY_LOGGED"}])
    assert _check(tmp_path, ok).returncode == 0


@needs_jq
def test_check_script_fails_when_the_batch_is_missing_even_if_old_rows_exist(tmp_path):
    bad = _resp([], ["SPY", "AAPL"], skipped=[{"symbol": "SPY", "reason": "DATA_NOT_UPDATED"},
                                               {"symbol": "AAPL", "reason": "DATA_NOT_UPDATED"}])
    r = _check(tmp_path, bad)
    assert r.returncode == 1 and "2026-10-02" in r.stdout and "SPY=DATA_NOT_UPDATED" in r.stdout
    partial = _resp(["SPY"], ["AAPL"], logged=["SPY"], skipped=[{"symbol": "AAPL", "reason": "DATA_NOT_UPDATED"}])
    assert _check(tmp_path, partial).returncode == 1


@needs_jq
def test_check_script_still_understands_an_older_api(tmp_path):
    legacy_ok = {"logged": [], "skipped": [{"symbol": "SPY", "reason": "ALREADY_LOGGED"}]}
    legacy_bad = {"logged": [], "skipped": [{"symbol": "SPY", "reason": "DATA_UNAVAILABLE"}]}
    r = _check(tmp_path, legacy_ok)
    assert r.returncode == 0 and "expected_batch" in r.stdout
    assert _check(tmp_path, legacy_bad).returncode == 1
    assert _check(tmp_path, {"oops": 1}).returncode == 1
