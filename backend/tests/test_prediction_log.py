"""Live prediction log: storage, resolver, scorecard, endpoints, task auth."""
import math

import pandas as pd
import pytest
from sqlalchemy import text

from app import config, main
from app.errors import DataUnavailable
from app.storage import GENESIS, PredictionStore, StorageUnavailable, _normalise_url
from app.trackrecord import resolve_pending, scorecard

from .conftest import lagged_end, synthetic_prices


def rec(symbol="SPY", base_date="2026-09-01", pred=0.01, close=100.0, h=5):
    return {"symbol": symbol, "horizon_days": h, "base_date": base_date, "base_close": close,
            "predicted_return": pred, "interval_low": 95.0, "interval_high": 106.0, "backtest_skill": -0.03,
            "backtest_verdict": "not_better_or_inconclusive", "model": "gbm"}


# ---------- storage
def test_insert_once_and_hash_chain(store):
    assert store.add_prediction(rec()) is True
    assert store.add_prediction(rec()) is False  # same (symbol, horizon, base_date): never duplicated or replaced
    assert store.add_prediction(rec("AAPL")) is True
    rows = store.all_rows()
    assert len(rows) == 2 and rows[0]["prev_hash"] == GENESIS and rows[1]["prev_hash"] == rows[0]["entry_hash"]
    assert rows[0]["made_at"].endswith("Z") and rows[0]["status"] == "pending"
    assert store.verify_chain() is True


def test_tampering_is_detected(store):
    store.add_prediction(rec())
    store.add_prediction(rec("AAPL"))
    with store.engine.begin() as conn:
        conn.execute(text("UPDATE predictions SET predicted_return = 0.5 WHERE symbol = 'SPY'"))
    assert store.verify_chain() is False


def test_resolve_once_and_prediction_fields_untouched(store):
    store.add_prediction(rec())
    row = store.pending()[0]
    assert store.resolve(row["id"], "2026-09-08", 103.0, 0.0296) is True
    assert store.resolve(row["id"], "2026-09-09", 999.0, 5.0) is False  # second resolve ignored
    after = store.all_rows()[0]
    assert after["status"] == "resolved" and after["realized_close"] == 103.0
    assert after["predicted_return"] == row["predicted_return"] and after["entry_hash"] == row["entry_hash"]
    assert store.verify_chain() is True  # entry chain untouched by resolution
    rep = store.verify_report()
    assert rep == {"chain_ok": True, "outcomes_ok": True, "unsealed_resolved": 0, "sealed_resolved": 1}


def test_pagination_filters(store):
    for i in range(7):
        store.add_prediction(rec("SPY" if i % 2 else "AAPL", base_date=f"2026-09-{i + 1:02d}"))
    pg = store.page(3, 0)
    assert pg.total == 7 and len(pg.items) == 3 and pg.items[0]["id"] > pg.items[1]["id"]
    assert len(store.page(3, 6).items) == 1
    assert store.page(10, 0, symbol="SPY").total == 3


def test_url_normalisation_and_sqlite_default():
    assert _normalise_url("postgres://u:p@h/db").startswith("postgresql+psycopg://")
    assert _normalise_url("postgresql://u:p@h/db").startswith("postgresql+psycopg://")
    assert PredictionStore("sqlite://").backend == "sqlite"


def test_storage_failure_is_structured():
    st = PredictionStore("sqlite:////nonexistent-dir/x/y.db")
    with pytest.raises(StorageUnavailable) as e:
        st.add_prediction(rec())
    assert e.value.code == "STORAGE_UNAVAILABLE" and e.value.status == 503 and e.value.retryable


# ---------- resolver
def series(n=60, end="2026-09-30"):
    idx = pd.bdate_range(end=end, periods=n)
    return pd.Series([100 + i for i in range(n)], index=idx, dtype=float)


def test_resolver_waits_for_horizon_then_fills(store):
    s = series()
    base = s.index[-8].strftime("%Y-%m-%d")
    store.add_prediction(rec(base_date=base, close=float(s.iloc[-8])))
    recent = s.index[-3].strftime("%Y-%m-%d")
    store.add_prediction(rec("AAPL", base_date=recent, close=float(s.iloc[-3])))  # horizon not reached yet
    out = resolve_pending(store, lambda sym: s)
    assert out == {"resolved": 1, "still_pending": 1}
    done = [r for r in store.all_rows() if r["status"] == "resolved"][0]
    assert done["realized_date"] == s.index[-3].strftime("%Y-%m-%d")  # exactly 5 trading days after base
    assert done["realized_return"] == pytest.approx(math.log(s.iloc[-3] / s.iloc[-8]))
    assert resolve_pending(store, lambda sym: s) == {"resolved": 0, "still_pending": 1}  # idempotent


def test_resolver_survives_provider_failure(store):
    store.add_prediction(rec())

    def boom(sym):
        raise DataUnavailable("down")
    assert resolve_pending(store, boom) == {"resolved": 0, "still_pending": 1}
    assert store.pending()


# ---------- scorecard
def resolved(i, pred, real, sym="SPY", date=None):
    return {"status": "resolved", "horizon_days": 5, "base_date": date or f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}",
            "predicted_return": pred, "realized_return": real, "base_close": 100.0, "interval_low": 95.0,
            "interval_high": 106.0, "symbol": sym}


def test_scorecard_empty_and_too_early():
    assert scorecard([])["verdict"] == "no_data"
    sc = scorecard([resolved(i, 0.01, 0.02) for i in range(5)] + [{"status": "pending", "horizon_days": 5}])
    assert sc["verdict"] == "too_early" and sc["n_pending"] == 1 and sc["skill_ci_90"] is None
    assert sc["n_resolved"] == 5 and sc["min_for_verdict"] == 30


def test_scorecard_math_and_honest_verdicts():
    import numpy as np
    rng = np.random.default_rng(1)
    real = rng.normal(0, 0.02, 400)
    good = [resolved(i, r * 0.9, r) for i, r in enumerate(real)]            # near-perfect predictions
    bad = [resolved(i, -r * 2, r) for i, r in enumerate(real)]               # anti-correlated
    g, b = scorecard(good), scorecard(bad)
    assert g["verdict"] == "better" and g["skill_vs_naive"] > 0.5 and g["hit_rate"] == 1.0
    assert b["verdict"] == "not_better" and b["skill_vs_naive"] < 0
    assert 0 <= g["interval_coverage"] <= 1 and g["interval_nominal"] == 0.8


def test_scorecard_counts_same_day_symbols_once():
    rows = [resolved(0, 0.01, 0.02, sym=s, date="2026-01-05") for s in ("SPY", "AAPL", "MSFT", "NVDA", "TSLA")]
    assert scorecard(rows)["n_dates"] == 1 and scorecard(rows)["n_resolved"] == 5


# ---------- endpoints
@pytest.fixture
def task(monkeypatch):
    monkeypatch.setattr(config, "LOG_TASK_TOKEN", "task-secret")
    monkeypatch.setattr(config, "LOG_SYMBOLS", ["SPY", "AAPL"])
    return {"Authorization": "Bearer task-secret"}


def test_task_disabled_by_default_and_requires_token(client, monkeypatch):
    monkeypatch.setattr(config, "LOG_TASK_TOKEN", "")
    assert client.post("/api/_tasks/run-prediction-log").status_code == 404
    monkeypatch.setattr(config, "LOG_TASK_TOKEN", "task-secret")
    auth = {"Authorization": "Bearer task-secret"}
    assert client.post("/api/_tasks/run-prediction-log").status_code == 401
    assert client.post("/api/_tasks/run-prediction-log", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/api/_tasks/run-prediction-log", headers=auth).status_code == 405


def test_task_logs_allowlist_only_and_is_idempotent(client, task, store):
    body = client.post("/api/_tasks/run-prediction-log", headers=task).json()
    assert body["logged"] == ["SPY", "AAPL"] and body["skipped"] == []
    rows = store.all_rows()
    assert {r["symbol"] for r in rows} == {"SPY", "AAPL"} and all(r["horizon_days"] == 5 for r in rows)
    again = client.post("/api/_tasks/run-prediction-log", headers=task).json()
    assert again["logged"] == [] and {s["reason"] for s in again["skipped"]} == {"ALREADY_LOGGED"}
    assert len(store.all_rows()) == 2


def test_normal_forecast_requests_never_write_to_the_log(client, store):
    client.get("/api/forecast/AAPL?horizon=5")
    client.get("/api/forecast/ZZZZ?horizon=5")
    assert store.all_rows() == []  # storage is bounded and not driven by visitors


def test_task_skips_failures_and_stale(client, task, store, fake, monkeypatch):
    monkeypatch.setattr(config, "LOG_SYMBOLS", ["SPY", "FAIL"])
    body = client.post("/api/_tasks/run-prediction-log", headers=task).json()
    assert body["logged"] == ["SPY"] and body["skipped"][0] == {"symbol": "FAIL", "reason": "DATA_UNAVAILABLE"}
    # data that is days old could already contain the outcome: never logged
    main.cache.clear()
    old = synthetic_prices(900, end=lagged_end(10))
    fake.history = lambda symbol, period: old
    monkeypatch.setattr(config, "LOG_SYMBOLS", ["AAPL"])
    body = client.post("/api/_tasks/run-prediction-log", headers=task).json()
    # behind the expected session even after a forced refetch: skipped, never logged from old data
    assert body["logged"] == [] and body["skipped"][0]["reason"] == "DATA_NOT_UPDATED"


def test_prediction_log_endpoint_empty_state_and_pagination(client, task, store):
    b = client.get("/api/prediction-log").json()
    assert b["items"] == [] and b["total"] == 0 and b["scorecard"]["verdict"] == "no_data" and b["chain_ok"] is True
    assert b["storage"] == {"backend": "sqlite", "durable": False} and b["stale"] is False and b["disclaimer"]
    for i in range(3):
        store.add_prediction(rec(base_date=f"2026-09-0{i + 1}"))
    main.cache.clear()
    b = client.get("/api/prediction-log?limit=2&offset=0").json()
    assert b["total"] == 3 and len(b["items"]) == 2 and b["limit"] == 2
    row = b["items"][0]
    assert "entry_hash" in row and "prev_hash" in row and row["status"] == "pending"
    assert client.get("/api/prediction-log?limit=0").status_code in (400, 422)
    assert client.get("/api/prediction-log?limit=101").status_code in (400, 422)
    assert client.get("/api/prediction-log?status=weird").json()["error"]["code"] == "INVALID_REQUEST"
    assert client.get("/api/prediction-log?symbol=A$B").json()["error"]["code"] == "INVALID_SYMBOL"


def test_prediction_log_is_cached_and_task_invalidates(client, task, store):
    client.get("/api/prediction-log")
    store.add_prediction(rec())
    assert client.get("/api/prediction-log").json()["total"] == 0  # cached
    client.post("/api/_tasks/run-prediction-log", headers=task)
    assert client.get("/api/prediction-log").json()["total"] >= 1  # cache dropped by the task


def test_public_log_marks_outcomes(client, store):
    store.add_prediction(rec(close=100.0))
    row = store.pending()[0]
    store.resolve(row["id"], "2026-09-08", 103.0, 0.0296)
    main.cache.clear()
    item = client.get("/api/prediction-log").json()["items"][0]
    assert item["status"] == "resolved" and item["in_interval"] is True and item["direction_correct"] is True


# ---------- storage error diagnostics (no credentials in logs) ----------
PG_URL = "postgresql://neon_user:s3cr%40t-P4ss@ep-cool-123.us-east-2.aws.neon.tech/neondb?sslmode=require"


def _records(caplog):
    return [r for r in caplog.records if r.getMessage() == "storage_error"]


def _dump(caplog):
    return " ".join(r.getMessage() + repr(getattr(r, "ctx", {})) + (r.exc_text or "") for r in caplog.records)


def test_redact_removes_password_user_and_url():
    from app.storage import redact
    secrets = [PG_URL, "s3cr%40t-P4ss", "s3cr@t-P4ss", "neon_user"]
    msgs = [
        'connection failed: password authentication failed for user "neon_user"',
        f"could not connect using {PG_URL}",
        "postgresql+psycopg://neon_user:s3cr@t-P4ss@ep-cool-123.us-east-2.aws.neon.tech/neondb refused",
        "conninfo: host=h user=u password=s3cr@t-P4ss dbname=x",
    ]
    for m in msgs:
        out = redact(m, secrets)
        for bad in ("s3cr", "P4ss", "neon_user", "neondb?sslmode"):
            assert bad not in out, (m, out)
    assert "[redacted]" in redact(msgs[3], secrets)
    assert len(redact("x" * 5000, [])) == 300


def test_password_in_exception_message_is_not_logged(monkeypatch, caplog):
    import logging

    from sqlalchemy.exc import OperationalError

    from app import storage
    monkeypatch.setattr(storage, "_sleep", lambda s: None)
    st = PredictionStore(PG_URL)
    assert st.backend == "postgres" and st._host == "ep-cool-123.us-east-2.aws.neon.tech"

    class Boom:
        def connect(self):
            raise OperationalError(
                "SELECT 1", {}, Exception(f"FATAL: password authentication failed; dsn={PG_URL} pw=s3cr@t-P4ss"))
    st.engine = Boom()
    caplog.set_level(logging.DEBUG, logger="stock-api")
    with pytest.raises(StorageUnavailable) as e:
        st.init()
    assert e.value.body() == {"error": {"code": "STORAGE_UNAVAILABLE", "retryable": True, "retry_after": 30,
                                        "message": "The prediction log is temporarily unavailable."}}
    recs = _records(caplog)
    assert len(recs) == storage.CONNECT_ATTEMPTS  # retried, each attempt logged
    ctx = recs[-1].ctx
    assert ctx["backend"] == "postgres" and ctx["host"] == "ep-cool-123.us-east-2.aws.neon.tech"
    assert ctx["phase"] == "connect" and ctx["error_class"] == "OperationalError" and ctx["op"] == "init"
    assert recs[0].levelno == logging.WARNING and recs[-1].levelno == logging.ERROR
    text = _dump(caplog)
    for bad in ("s3cr", "P4ss", "neon_user", "sslmode", PG_URL):
        assert bad not in text
    assert e.value.__cause__ is None and e.value.__suppress_context__


def test_init_retries_then_succeeds_postgres_style(monkeypatch, tmp_path, caplog):
    import logging

    from sqlalchemy.exc import OperationalError

    from app import storage
    sleeps = []
    monkeypatch.setattr(storage, "_sleep", sleeps.append)
    st = PredictionStore(f"sqlite:///{tmp_path / 'r.db'}")
    st.backend = "postgres"  # exercise the retry path with a working engine
    real, calls = st.engine.connect, {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise OperationalError("SELECT 1", {}, Exception("server is waking up"))
        return real()
    monkeypatch.setattr(st.engine, "connect", flaky)
    caplog.set_level(logging.DEBUG, logger="stock-api")
    st.init()
    assert st._ready and calls["n"] >= 3 and sleeps == [1.0, 3.0]  # create_all reconnects too
    assert [r.levelno for r in _records(caplog)] == [logging.WARNING, logging.WARNING]


def test_postgres_connect_args_and_sqlite_unchanged(monkeypatch):
    from app import storage
    seen = {}
    real = storage.create_engine
    monkeypatch.setattr(storage, "create_engine", lambda url, **kw: seen.setdefault("kw", kw) and real("sqlite://"))
    PredictionStore(PG_URL)
    assert seen["kw"]["connect_args"] == {"connect_timeout": storage.CONNECT_TIMEOUT_S == 10 and 10}
    assert seen["kw"]["pool_pre_ping"] is True
    seen.clear()
    PredictionStore("sqlite://")
    assert seen["kw"] == {"connect_args": {"check_same_thread": False}}


def test_sqlite_init_failure_is_single_attempt_and_logged(caplog):
    import logging
    st = PredictionStore("sqlite:////nonexistent-dir/x/y.db")
    caplog.set_level(logging.DEBUG, logger="stock-api")
    with pytest.raises(StorageUnavailable):
        st.init()
    recs = _records(caplog)
    assert len(recs) == 1 and recs[0].ctx["backend"] == "sqlite" and recs[0].ctx["host"] == "file"


def test_query_failure_logged_with_phase_query(store, caplog, monkeypatch):
    import logging

    from sqlalchemy.exc import OperationalError
    store.init()
    caplog.set_level(logging.DEBUG, logger="stock-api")

    class Bad:
        def connect(self):
            raise OperationalError("SELECT", {}, Exception("connection reset by peer"))
        begin = connect
    monkeypatch.setattr(store, "engine", Bad())
    with pytest.raises(StorageUnavailable):
        store.page(5, 0)
    ctx = _records(caplog)[0].ctx
    assert ctx["op"] == "page" and ctx["phase"] == "query" and "connection reset" in ctx["message"]


# ---------- column lengths (SQLite doesn't enforce VARCHAR(n); Postgres does) ----------
def _limits():
    from app.storage import predictions
    return {c.name: c.type.length for c in predictions.columns if getattr(c.type, "length", None)}


def _assert_fits(rows):
    lim = _limits()
    for r in rows:
        for col, n in lim.items():
            v = r.get(col)
            if isinstance(v, str):
                assert len(v) <= n, f"{col}={v!r} ({len(v)}) exceeds VARCHAR({n})"


def test_column_lengths_are_safe():
    lim = _limits()
    assert lim["backtest_verdict"] >= 64 and lim["model"] >= 64 and lim["symbol"] >= 16
    assert lim["entry_hash"] == lim["prev_hash"] == 64  # sha-256 hex, real length
    assert lim["base_date"] == lim["realized_date"] == 10  # YYYY-MM-DD
    assert lim["made_at"] >= 20 and lim["resolved_at"] >= 20  # YYYY-MM-DDTHH:MM:SSZ
    assert lim["status"] >= len("resolved")


def test_every_value_the_logger_writes_fits_its_column(client, task, store, fake):
    """Regression: backtest_verdict 'not_better_or_inconclusive' (26 chars) overflowed VARCHAR(16) on Postgres."""
    from app.trackrecord import record_from_forecast
    # both verdict branches of the logger, via the real record builder
    for beats in (True, False):
        result = {"symbol": "X" * 15, "horizon_days": 5, "last_date": "2026-09-30", "last_close": 1.0,
                  "predicted_return": 0.01, "interval_80": {"low": 0.9, "high": 1.1},
                  "backtest": {"skill_vs_baseline": 0.0, "beats_baseline": beats}}
        _assert_fits([record_from_forecast(result)])
    # end to end: what the scheduled task actually stores, before and after resolution
    client.post("/api/_tasks/run-prediction-log", headers=task)
    rows = store.all_rows()
    assert rows
    _assert_fits(rows)
    longest = max(len(r["backtest_verdict"]) for r in rows)
    assert longest > 16  # the value that used to overflow is really exercised here
    for r in store.pending():
        store.resolve(r["id"], "2026-10-08", 101.0, 0.01)
    _assert_fits(store.all_rows())
    # symbol validator allows up to 15 chars: the longest legal symbol fits too
    from app.symbols import normalize_symbol
    assert len(normalize_symbol("A" * 15)) <= _limits()["symbol"]


def test_plan_widening_only_widens_and_is_idempotent():
    from app.storage import plan_widening
    old = {"symbol": 16, "made_at": 24, "backtest_verdict": 16, "model": 32, "status": 12, "resolved_at": 24,
           "base_date": 10, "realized_date": 10, "prev_hash": 64, "entry_hash": 64, "id": None, "base_close": None}
    plan = dict(plan_widening(old))
    assert plan["backtest_verdict"] == 64 and plan["model"] == 64 and plan["symbol"] == 32
    assert "entry_hash" not in plan and "prev_hash" not in plan and "base_date" not in plan and "id" not in plan
    widened = {**old, **plan}
    assert plan_widening(widened) == []  # second run: nothing to do
    assert plan_widening({**widened, "model": 200}) == []  # never narrows a wider column


def test_postgres_migration_issues_alter_for_short_columns_only(monkeypatch):
    from app import storage

    class Conn:
        def __init__(self):
            self.sql = []

        def execute(self, stmt):
            self.sql.append(str(stmt))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class Eng:
        conn = Conn()

        def begin(self):
            return self.conn

    live = [{"name": "backtest_verdict", "type": type("T", (), {"length": 16})()},
            {"name": "entry_hash", "type": type("T", (), {"length": 64})()},
            {"name": "id", "type": type("T", (), {})()}]
    monkeypatch.setattr(storage, "inspect", lambda conn: type("I", (), {"get_columns": lambda self, t: live})())
    st = PredictionStore("sqlite://")
    st.engine = Eng()
    st._migrate_columns()
    assert st.engine.conn.sql == ['ALTER TABLE predictions ALTER COLUMN "backtest_verdict" TYPE VARCHAR(64)']


def test_migration_only_runs_for_postgres(store, monkeypatch):
    called = []
    monkeypatch.setattr(store, "_migrate_columns", lambda: called.append(1))
    store.init()
    assert called == [] and store._ready  # sqlite: unchanged behaviour
    store.backend = "postgres"
    store._ready = False
    store.init()
    assert called == [1]
