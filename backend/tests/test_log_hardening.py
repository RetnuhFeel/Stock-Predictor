"""Prediction log hardening: outcome seals, backwards compatibility, safe migration, hindsight guard."""
import logging
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from app import config, main
from app.freshness import bar_is_final
from app.storage import (
    GENESIS,
    HASH_FIELDS,
    NEW_COLUMNS,
    PredictionStore,
    compute_hash,
    compute_res_hash,
)
from app.trackrecord import hash_spec, public_row, resolve_pending

from .conftest import lagged_end, synthetic_prices
from .test_prediction_log import rec


@pytest.fixture
def task_env(monkeypatch):
    monkeypatch.setattr(config, "LOG_TASK_TOKEN", "task-secret")
    monkeypatch.setattr(config, "LOG_SYMBOLS", ["SPY", "AAPL"])
    return {"Authorization": "Bearer task-secret"}

NY = ZoneInfo("America/New_York")

LEGACY_DDL = """
CREATE TABLE predictions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, symbol VARCHAR(16) NOT NULL, horizon_days INTEGER NOT NULL,
  made_at VARCHAR(32) NOT NULL, base_date VARCHAR(10) NOT NULL, base_close FLOAT NOT NULL,
  predicted_return FLOAT NOT NULL, interval_low FLOAT NOT NULL, interval_high FLOAT NOT NULL,
  backtest_skill FLOAT NOT NULL, backtest_verdict VARCHAR(64) NOT NULL, model VARCHAR(32) NOT NULL,
  prev_hash VARCHAR(64) NOT NULL, entry_hash VARCHAR(64) NOT NULL, status VARCHAR(16) NOT NULL,
  resolved_at VARCHAR(32), realized_date VARCHAR(10), realized_close FLOAT, realized_return FLOAT,
  CONSTRAINT uq_prediction UNIQUE (symbol, horizon_days, base_date))
"""


def legacy_db(path, n_pending=3, n_resolved=2):
    """Build a database exactly as the previous release would have left it (no seal columns or indexes)."""
    eng = create_engine(f"sqlite:///{path}")
    prev = GENESIS
    with eng.begin() as c:
        c.execute(text(LEGACY_DDL))
        for i in range(n_pending + n_resolved):
            r = {**rec("SPY", base_date=f"2026-08-{i + 3:02d}"), "made_at": f"2026-08-{i + 3:02d}T21:00:00Z"}
            h = compute_hash(prev, r)
            resolved = i < n_resolved
            c.execute(text(
                "INSERT INTO predictions (symbol,horizon_days,made_at,base_date,base_close,predicted_return,"
                "interval_low,interval_high,backtest_skill,backtest_verdict,model,prev_hash,entry_hash,status,"
                "resolved_at,realized_date,realized_close,realized_return) VALUES (:symbol,:horizon_days,:made_at,"
                ":base_date,:base_close,:predicted_return,:interval_low,:interval_high,:backtest_skill,"
                ":backtest_verdict,:model,:prev,:h,:st,:ra,:rd,:rc,:rr)"),
                {**r, "prev": prev, "h": h, "st": "resolved" if resolved else "pending",
                 "ra": "2026-09-01T21:00:00Z" if resolved else None, "rd": "2026-09-01" if resolved else None,
                 "rc": 101.0 if resolved else None, "rr": 0.0099 if resolved else None})
            prev = h
    eng.dispose()


def snapshot(store):
    return [dict(r) for r in store.all_rows()]


# ---------- old rows still verify; migration is additive and never rewrites rows
def test_old_format_rows_still_verify_and_migration_changes_nothing(tmp_path):
    db = tmp_path / "old.db"
    legacy_db(db)
    raw = create_engine(f"sqlite:///{db}")
    with raw.connect() as c:
        before = [tuple(r) for r in c.execute(text("SELECT * FROM predictions ORDER BY id"))]
    st = PredictionStore(f"sqlite:///{db}")
    st.init()
    with raw.connect() as c:
        cols = [r[1] for r in c.execute(text("PRAGMA table_info(predictions)"))]
        after = [tuple(r)[: len(before[0])] for r in c.execute(text("SELECT * FROM predictions ORDER BY id"))]
    assert all(k in cols for k in NEW_COLUMNS)
    assert after == before  # every pre-existing byte of every pre-existing row is untouched
    rep = st.verify_report()
    assert rep["chain_ok"] is True and st.verify_chain() is True
    assert rep["unsealed_resolved"] == 2 and rep["outcomes_ok"] is True and rep["sealed_resolved"] == 0
    # idempotent
    st._ready = False
    st.init()
    assert st.verify_report() == rep


def test_new_activity_on_a_migrated_legacy_db_chains_correctly(tmp_path):
    db = tmp_path / "old.db"
    legacy_db(db)
    st = PredictionStore(f"sqlite:///{db}")
    assert st.add_prediction(rec("AAPL", base_date="2026-09-02")) is True  # extends the legacy entry chain
    pend = [r for r in st.pending() if r["symbol"] == "SPY"][0]
    assert st.resolve(pend["id"], "2026-09-09", 103.0, 0.03) is True  # first seal is res_seq 1
    rep = st.verify_report()
    assert rep == {"chain_ok": True, "outcomes_ok": True, "unsealed_resolved": 2, "sealed_resolved": 1}
    assert [r["res_seq"] for r in st.all_rows() if r["res_seq"]] == [1]
    st.close()


def test_migration_skips_unique_index_when_existing_data_has_duplicates(tmp_path, caplog):
    db = tmp_path / "dup.db"
    legacy_db(db, 2, 0)
    eng = create_engine(f"sqlite:///{db}")
    with eng.begin() as c:  # a (hypothetical) historical fork: two rows with the same parent
        c.execute(text("UPDATE predictions SET prev_hash = (SELECT prev_hash FROM predictions WHERE id = 1) "
                       "WHERE id = 2"))
    caplog.set_level(logging.WARNING, logger="stock-api")
    st = PredictionStore(f"sqlite:///{db}")
    st.init()  # must not raise, must not touch data
    assert any(r.getMessage() == "storage_index_skipped" for r in caplog.records)
    assert st._ready


# ---------- outcome tamper evidence
def resolved_store(store):
    for d in ("2026-09-01", "2026-09-02", "2026-09-03"):
        store.add_prediction(rec(base_date=d))
    for r in store.pending():
        store.resolve(r["id"], "2026-09-10", 103.0 + r["id"], 0.03)
    return store


def test_resolution_edit_is_detected_but_entry_chain_stays_valid(store):
    resolved_store(store)
    assert store.verify_report() == {"chain_ok": True, "outcomes_ok": True, "unsealed_resolved": 0,
                                     "sealed_resolved": 3}
    with store.engine.begin() as conn:
        conn.execute(text("UPDATE predictions SET realized_return = -0.2 WHERE id = 2"))
    rep = store.verify_report()
    assert rep["chain_ok"] is True and rep["outcomes_ok"] is False  # the old check alone would have missed this


@pytest.mark.parametrize("sql", [
    "UPDATE predictions SET realized_close = 1 WHERE id = 1",
    "UPDATE predictions SET resolved_at = '2030-01-01T00:00:00Z' WHERE id = 3",
    "UPDATE predictions SET res_hash = '" + "a" * 64 + "' WHERE id = 2",
    "UPDATE predictions SET res_seq = 9 WHERE id = 3",
    "UPDATE predictions SET res_hash = NULL, res_seq = NULL, res_prev_hash = NULL WHERE id = 2",  # strip a seal
])
def test_outcome_tampering_variants_are_detected(store, sql):
    resolved_store(store)
    with store.engine.begin() as conn:
        conn.execute(text(sql))
    rep = store.verify_report()
    assert rep["outcomes_ok"] is False or rep["unsealed_resolved"] > 0


def test_pending_row_cannot_carry_a_seal(store):
    store.add_prediction(rec())
    with store.engine.begin() as conn:
        conn.execute(text(f"UPDATE predictions SET res_hash = '{'b' * 64}', res_seq = 1, res_prev_hash = '{GENESIS}'"))
    assert store.verify_report()["outcomes_ok"] is False


def test_public_row_and_endpoint_let_third_parties_recompute_both_chains(client, store):
    resolved_store(store)
    main.cache.clear()
    body = client.get("/api/prediction-log?limit=100").json()
    assert body["chain_ok"] is True and body["outcomes_ok"] is True and body["unsealed_resolved"] == 0
    spec = body["hash_spec"]
    assert spec["entry_fields"] == list(HASH_FIELDS) and "outcome_fields" in spec
    items = sorted(body["items"], key=lambda r: r["id"])
    prev = GENESIS
    for it in items:  # independent recomputation from public fields only
        assert it["prev_hash"] == prev and it["entry_hash"] == compute_hash(prev, it)
        prev = it["entry_hash"]
    res_prev = GENESIS
    for it in sorted(items, key=lambda r: r["res_seq"]):
        assert it["res_prev_hash"] == res_prev and it["res_hash"] == compute_res_hash(res_prev, it["entry_hash"], it)
        res_prev = it["res_hash"]
    assert "backtest_verdict" in items[0] and hash_spec()["genesis"] == GENESIS


def test_public_row_exposes_hashed_fields():
    row = {**rec(), "id": 1, "made_at": "x", "prev_hash": GENESIS, "entry_hash": "e", "status": "pending",
           "resolved_at": None, "realized_date": None, "realized_close": None, "realized_return": None,
           "res_seq": None, "res_prev_hash": None, "res_hash": None}
    out = public_row(row)
    assert set(HASH_FIELDS) <= set(out) and "prev_hash" in out


# ---------- append safety
def test_second_row_with_same_parent_is_refused_by_the_database(store):
    from sqlalchemy.exc import IntegrityError
    store.add_prediction(rec(base_date="2026-09-01"))
    first = store.all_rows()[0]
    with pytest.raises(IntegrityError), store.engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO predictions (symbol,horizon_days,made_at,base_date,base_close,predicted_return,interval_low,"
            "interval_high,backtest_skill,backtest_verdict,model,prev_hash,entry_hash,status) VALUES "
            "('QQQ',5,'t','2026-09-02',1,0,0,1,0,'x','gbm',:p,'h2','pending')"), {"p": GENESIS})
    assert first["prev_hash"] == GENESIS


def test_concurrent_appends_keep_one_linear_chain(store):
    import threading
    errs = []
    store.init()

    def work(i):
        try:
            store.add_prediction(rec(f"S{i}", base_date="2026-09-01"))
        except Exception as e:  # noqa: BLE001
            errs.append(e)
    ts = [threading.Thread(target=work, args=(i,)) for i in range(12)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errs and len(store.all_rows()) == 12 and store.verify_chain()


def test_pg_advisory_lock_is_taken_for_both_chains_on_postgres(store, monkeypatch):
    calls = []
    real = store._pg_lock
    store.init()
    monkeypatch.setattr(store.engine.dialect, "name", "postgresql")  # pretend, only to see the lock statements

    def spy(conn, key):
        calls.append(key)  # do not execute the pg-only SQL on sqlite
    monkeypatch.setattr(store, "_pg_lock", spy)
    store.add_prediction(rec())
    store.resolve(store.pending()[0]["id"], "2026-09-08", 103.0, 0.03)
    from app import storage
    assert calls == [storage.LOCK_ENTRY_CHAIN, storage.LOCK_OUTCOME_CHAIN]
    assert real is not spy


def test_migration_statements_are_additive_and_idempotent_on_postgres(monkeypatch):
    """Widening-migration pattern: fake connection that records SQL; live table already has rows and no seal cols."""
    from app import storage

    class Res:
        def first(self):
            return None  # no duplicate prev_hash / res_seq values

    class Conn:
        def __init__(self):
            self.sql = []

        def execute(self, stmt, params=None):
            self.sql.append(str(stmt))
            return Res()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class Dialect:
        name = "postgresql"

    class Eng:
        conn = Conn()
        dialect = Dialect()

        def begin(self):
            return self.conn

    state = {"cols": [{"name": "id"}, {"name": "entry_hash"}], "idx": []}
    monkeypatch.setattr(storage, "inspect", lambda conn: type("I", (), {
        "get_columns": lambda self, t: state["cols"], "get_indexes": lambda self, t: state["idx"]})())
    st = PredictionStore("sqlite://")
    st.engine = Eng()
    st._migrate_seal()
    sql = st.engine.conn.sql
    joined = "\n".join(sql)
    forbidden = ("UPDATE ", "DELETE ", "DROP ", "TRUNCATE", " NOT NULL,", "DEFAULT", "ALTER COLUMN", "REINDEX")
    assert not any(w in joined.upper() for w in forbidden)  # additive only: no row or column is rewritten
    assert joined.count("ADD COLUMN IF NOT EXISTS") == 3
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_predictions_prev_hash" in joined
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_predictions_res_seq" in joined
    assert sql[0].startswith("SET LOCAL lock_timeout") and "pg_advisory_xact_lock" in sql[1]
    # second run on a fully migrated table: nothing but the lock statements
    state["cols"] += [{"name": n} for n in NEW_COLUMNS]
    state["idx"] = [{"name": "uq_predictions_prev_hash"}, {"name": "uq_predictions_res_seq"}]
    st.engine.conn.sql.clear()
    st._migrate_seal()
    assert len(st.engine.conn.sql) == 2


# ---------- real Postgres (skipped where no embedded server is installed; run ad hoc, see PR notes)
def test_real_postgres_migration_lock_and_concurrency(tmp_path):
    pgserver = pytest.importorskip("pixeltable_pgserver")
    import threading
    srv = pgserver.get_server(tmp_path / "pg")
    try:
        url = srv.get_uri()
        eng = create_engine(url.replace("postgresql://", "postgresql+psycopg://", 1))
        with eng.begin() as c:  # previous release's schema + 5 pending and 2 resolved rows
            c.execute(text(LEGACY_DDL.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")))
            prev = GENESIS
            for i in range(7):
                r = {**rec(base_date=f"2026-08-{i + 3:02d}"), "made_at": f"2026-08-{i + 3:02d}T21:00:00Z"}
                h = compute_hash(prev, r)
                c.execute(text(
                    "INSERT INTO predictions (symbol,horizon_days,made_at,base_date,base_close,predicted_return,"
                    "interval_low,interval_high,backtest_skill,backtest_verdict,model,prev_hash,entry_hash,status)"
                    " VALUES (:symbol,:horizon_days,:made_at,:base_date,:base_close,:predicted_return,:interval_low,"
                    ":interval_high,:backtest_skill,:backtest_verdict,:model,:p,:h,'pending')"),
                    {**r, "p": prev, "h": h})
                prev = h
        eng.dispose()
        st = PredictionStore(url)
        st.init()
        st._ready = False
        st.init()  # idempotent
        assert st.verify_report()["chain_ok"] is True
        # two "instances" (separate stores) appending and resolving concurrently
        stores = [PredictionStore(url) for _ in range(2)]
        errs = []

        def work(s, i):
            try:
                for j in range(5):
                    s.add_prediction(rec(f"T{i}{j}", base_date="2026-09-01"))
                for row in s.pending():
                    s.resolve(row["id"], "2026-09-10", 101.0, 0.01)
            except Exception as e:  # noqa: BLE001
                errs.append(e)
        ts = [threading.Thread(target=work, args=(s, i)) for i, s in enumerate(stores)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        assert not errs, errs
        rep = st.verify_report()
        assert rep["chain_ok"] and rep["outcomes_ok"] and len(st.all_rows()) == 17
        assert rep["sealed_resolved"] + rep["unsealed_resolved"] == 17 and rep["unsealed_resolved"] == 0
        for s in (st, *stores):
            s.close()
    finally:
        srv.cleanup()


# ---------- hindsight guard
def test_bar_is_final_rules():
    d = date(2026, 9, 30)  # Wednesday
    assert bar_is_final(date(2026, 9, 29), datetime(2026, 9, 30, 10, 0, tzinfo=NY))
    assert not bar_is_final(d, datetime(2026, 9, 30, 15, 59, tzinfo=NY))  # market still open: partial bar
    assert not bar_is_final(d, datetime(2026, 9, 30, 16, 5, tzinfo=NY))  # provider still publishing the close
    assert bar_is_final(d, datetime(2026, 9, 30, 16, 10, tzinfo=NY))
    assert not bar_is_final(date(2026, 10, 1), datetime(2026, 9, 30, 20, 0, tzinfo=NY))  # future
    assert bar_is_final(date(2026, 9, 26), datetime(2026, 9, 26, 12, 0, tzinfo=NY))  # Saturday date: no live session
    _ = time


def test_task_refuses_a_partial_intraday_bar(client, task_env, store, monkeypatch):
    from app import freshness
    monkeypatch.setattr(freshness, "now_ny", lambda: datetime.combine(
        datetime.now(NY).date(), time(11, 0), tzinfo=NY))
    if datetime.now(NY).weekday() >= 5:
        pytest.skip("no live session on weekends")
    body = client.post("/api/_tasks/run-prediction-log", headers=task_env).json()
    assert body["logged"] == [] and {s["reason"] for s in body["skipped"]} == {"PARTIAL_BAR"}
    assert store.all_rows() == []


@pytest.mark.parametrize("busdays_old,logged", [(1, True), (2, False), (3, False)])
def test_task_allows_at_most_one_business_day_of_lag(client, task_env, store, fake, monkeypatch, busdays_old, logged):
    monkeypatch.setattr(config, "LOG_SYMBOLS", ["SPY"])
    series = synthetic_prices(900, end=lagged_end(busdays_old))
    fake.history = lambda symbol, period: series
    body = client.post("/api/_tasks/run-prediction-log", headers=task_env).json()
    assert (body["logged"] == ["SPY"]) is logged
    if not logged:
        assert body["skipped"][0]["reason"] == "STALE_DATA"


def test_resolver_does_not_resolve_on_a_partial_bar(store, monkeypatch):
    from app import freshness
    today = freshness.now_ny().date()
    idx = pd.bdate_range(end=pd.Timestamp(today), periods=60)
    s = pd.Series([100.0 + i for i in range(60)], index=idx)
    if idx[-1].date() != today:
        pytest.skip("weekend: no bar dated today")
    monkeypatch.setattr(freshness, "now_ny", lambda: datetime.combine(today, time(11, 0), tzinfo=NY))
    store.add_prediction(rec(base_date=idx[-6].strftime("%Y-%m-%d")))  # horizon 5 lands on today's bar
    assert resolve_pending(store, lambda sym: s) == {"resolved": 0, "still_pending": 1}
    monkeypatch.setattr(freshness, "now_ny", lambda: datetime.combine(today, time(17, 0), tzinfo=NY))
    assert resolve_pending(store, lambda sym: s) == {"resolved": 1, "still_pending": 0}


# ---------- resolve_pending logs instead of swallowing
def test_resolve_pending_logs_provider_failures_without_secrets(store, caplog):
    store.add_prediction(rec())
    caplog.set_level(logging.WARNING, logger="stock-api")

    def boom(sym):
        raise RuntimeError("upstream said token=SECRET123")
    assert resolve_pending(store, boom) == {"resolved": 0, "still_pending": 1}
    recs = [r for r in caplog.records if r.getMessage() == "resolve_pending_failed"]
    assert len(recs) == 1 and recs[0].ctx == {"symbol": "SPY", "error_class": "RuntimeError"}
    assert "SECRET123" not in " ".join(r.getMessage() + repr(getattr(r, "ctx", "")) for r in caplog.records)
