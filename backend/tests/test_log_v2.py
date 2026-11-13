"""Hash rule v2 (model version + band method) and the dated conformal-band cutover, on top of an untouched v1 log."""
import hashlib
import json

import pytest
from sqlalchemy import insert, select, text

from app import config, main
from app.storage import GENESIS, HASH_FIELDS, PredictionStore, compute_hash, predictions
from app.trackrecord import band_cutover, hash_spec, public_row, scorecard

from .test_log_hardening import legacy_db
from .test_prediction_log import rec


def v1_reference(prev: str, row: dict) -> str:
    """The original rule, written out independently (not imported), so a change to compute_hash's v1 path fails."""
    fields = ["symbol", "horizon_days", "made_at", "base_date", "base_close", "predicted_return", "interval_low",
              "interval_high", "backtest_skill", "backtest_verdict", "model"]
    return hashlib.sha256((prev + json.dumps([row[f] for f in fields], separators=(",", ":"),
                                             default=str)).encode()).hexdigest()


def v2(symbol="SPY", base_date="2026-11-16", band="split_conformal", **kw):
    return {**rec(symbol, base_date=base_date, **kw), "hash_version": 2, "model_version": "gbm-v1@abc1234",
            "band_method": band}


def add_v1(store, r, made_at="2026-11-01T21:00:00Z"):
    """Append an old-format row the way the previous release wrote it (new code cannot: it always writes v2)."""
    store.init()
    with store.engine.begin() as conn:
        last = conn.execute(select(predictions.c.entry_hash).order_by(predictions.c.id.desc()).limit(1)).first()
        prev = last[0] if last else GENESIS
        row = {**r, "made_at": made_at}
        conn.execute(insert(predictions).values(**row, prev_hash=prev, entry_hash=v1_reference(prev, row),
                                                status="pending"))


def test_v1_rule_is_byte_for_byte_the_original():
    row = {**rec(), "made_at": "2026-09-01T21:00:00Z"}
    assert list(HASH_FIELDS) == ["symbol", "horizon_days", "made_at", "base_date", "base_close", "predicted_return",
                                 "interval_low", "interval_high", "backtest_skill", "backtest_verdict", "model"]
    want = v1_reference(GENESIS, row)
    assert compute_hash(GENESIS, row) == want
    assert compute_hash(GENESIS, {**row, "hash_version": None}) == want  # migrated rows: NULL column
    assert compute_hash(GENESIS, {**row, "hash_version": 1}) == want
    assert compute_hash(GENESIS, {**row, **v2(), "made_at": row["made_at"]}) != want  # v2 is a different rule


def test_v1_log_still_verifies_after_migration_and_is_not_rewritten(tmp_path):
    db = tmp_path / "old.db"
    legacy_db(db, 4, 3)
    from sqlalchemy import create_engine
    before = [dict(r._mapping) for r in create_engine(f"sqlite:///{db}").connect().execute(
        text("SELECT * FROM predictions ORDER BY id"))]
    st = PredictionStore(f"sqlite:///{db}")
    rows = st.all_rows()
    assert st.verify_report()["chain_ok"] is True
    for b, r in zip(before, rows, strict=True):  # every original column unchanged; new columns NULL
        assert all(r[k] == v for k, v in b.items())
        assert r["hash_version"] is None and r["model_version"] is None and r["band_method"] is None
        assert r["entry_hash"] == v1_reference(r["prev_hash"], r)
    assert st.hash_versions(rows) == {"v1": 7, "v2": 0, "first_v2_id": None, "v1_after_v2": 0}
    st.close()


def test_mixed_chain_v1_rows_then_v2_rows_verifies(tmp_path):
    db = tmp_path / "old.db"
    legacy_db(db, 3, 2)
    st = PredictionStore(f"sqlite:///{db}")
    old = st.all_rows()
    for sym in ("SPY", "AAPL"):
        assert st.add_prediction(v2(sym, base_date="2026-11-13", band="legacy_band")) is True
    assert st.add_prediction(v2("SPY", base_date="2026-11-16")) is True
    rows = st.all_rows()
    assert rows[: len(old)] == [{**o} for o in old]  # the v1 rows are not touched by appending v2 rows
    first_v2 = rows[len(old)]
    assert first_v2["prev_hash"] == old[-1]["entry_hash"]  # v2 links to the last v1 hash like any other row
    assert first_v2["entry_hash"] == compute_hash(first_v2["prev_hash"], first_v2) != v1_reference(
        first_v2["prev_hash"], first_v2)
    rep = st.verify_report()
    assert rep["chain_ok"] is True and rep["outcomes_ok"] is True
    assert st.hash_versions(rows) == {"v1": 5, "v2": 3, "first_v2_id": first_v2["id"], "v1_after_v2": 0}
    pend = [r for r in st.pending() if r["hash_version"] == 2][0]
    assert st.resolve(pend["id"], "2026-11-20", 101.0, 0.01) is True  # outcome seals work the same on v2 rows
    assert st.verify_report()["outcomes_ok"] is True
    st.close()


def _tampered(store, sql):
    with store.engine.begin() as conn:
        conn.execute(text(sql))
    return store.verify_report()["chain_ok"]


@pytest.mark.parametrize("sql", [
    "UPDATE predictions SET model_version = 'gbm-v9@ffffff' WHERE hash_version = 2",
    "UPDATE predictions SET band_method = 'legacy_band' WHERE hash_version = 2",
    "UPDATE predictions SET interval_high = interval_high + 1 WHERE hash_version = 2",
    "UPDATE predictions SET hash_version = NULL WHERE hash_version = 2",   # downgrade to v1: different hash
    "UPDATE predictions SET hash_version = 1 WHERE hash_version = 2",
    "UPDATE predictions SET hash_version = 3 WHERE hash_version = 2",      # unknown rule never verifies
    "UPDATE predictions SET band_method = 'split_conformal' WHERE hash_version IS NULL",  # planted on a v1 row
    "UPDATE predictions SET model_version = 'x' WHERE hash_version IS NULL",
])
def test_tampering_with_a_mixed_chain_is_detected(store, sql):
    add_v1(store, rec("SPY", base_date="2026-11-10"))
    add_v1(store, rec("AAPL", base_date="2026-11-10"))
    store.add_prediction(v2("SPY"))
    store.add_prediction(v2("AAPL"))
    assert store.verify_report()["chain_ok"] is True
    assert _tampered(store, sql) is False


def test_upgrading_a_v1_row_to_v1_explicitly_is_harmless(store):
    add_v1(store, rec())
    assert _tampered(store, "UPDATE predictions SET hash_version = 1") is True  # same rule, same hash


def test_v1_row_after_v2_fails_the_chain_with_a_reason(store):
    add_v1(store, rec("SPY", base_date="2026-11-13"))
    store.add_prediction(v2())
    add_v1(store, rec("AAPL", base_date="2026-11-16"))  # e.g. an older instance writing during a deploy
    store.add_prediction(v2("MSFT"))                     # later rows do not make it valid again
    rows = store.all_rows()
    rep = store.verify_report()
    assert rep["chain_ok"] is False and rep["chain_error"] == {"reason": "v1_after_v2", "row_id": rows[2]["id"]}
    assert rep["outcomes_ok"] is True  # outcome seals are a separate check
    assert store.hash_versions(rows)["v1_after_v2"] == 1
    assert "v1_after_v2" in hash_spec()["chain_errors"]


def test_new_code_always_writes_v2_whatever_the_caller_passes(store):
    store.add_prediction(rec("SPY"))                                  # no hash_version given
    store.add_prediction({**rec("AAPL"), "hash_version": 1})          # an explicit old version is overridden
    store.add_prediction({**rec("MSFT"), "hash_version": None})
    rows = store.all_rows()
    assert [r["hash_version"] for r in rows] == [2, 2, 2]
    assert store.verify_report()["chain_ok"] is True


def test_new_code_appending_to_a_v1_log_never_breaks_it(tmp_path):
    db = tmp_path / "old.db"
    legacy_db(db, 3, 2)
    st = PredictionStore(f"sqlite:///{db}")
    st.add_prediction(rec("AAPL", base_date="2026-11-13"))
    st.add_prediction(rec("MSFT", base_date="2026-11-13"))
    rows = st.all_rows()
    assert [r["hash_version"] for r in rows] == [None] * 5 + [2, 2]
    assert st.verify_report()["chain_ok"] is True and st.verify_report()["chain_error"] is None
    st.close()


@pytest.mark.parametrize("sql,reason", [
    ("UPDATE predictions SET predicted_return = 0.5 WHERE id = 2", "entry_hash_mismatch"),
    ("UPDATE predictions SET prev_hash = 'x' WHERE id = 2", "prev_hash_mismatch"),
    ("UPDATE predictions SET hash_version = 7 WHERE id = 2", "unknown_hash_version"),
    ("UPDATE predictions SET band_method = 'split_conformal' WHERE id = 1", "v1_with_v2_fields"),
])
def test_chain_error_names_the_reason_and_row(store, sql, reason):
    add_v1(store, rec("SPY", base_date="2026-11-10"))
    store.add_prediction(v2("SPY"))
    with store.engine.begin() as conn:
        conn.execute(text(sql))
    rep = store.verify_report()
    assert rep["chain_ok"] is False and rep["chain_error"]["reason"] == reason


def _resolve(store, sym, base_date, close):
    row = [r for r in store.pending() if r["symbol"] == sym and r["base_date"] == base_date][0]
    store.resolve(row["id"], "2026-12-01", close, float(__import__("math").log(close / 100.0)))


def test_scorecard_reports_each_period_against_its_own_band(store):
    # legacy rows: band 95-106. Conformal rows: a narrower 98-102 band. A close of 104 is inside the first only.
    for d in ("2026-11-10", "2026-11-11", "2026-11-12"):
        add_v1(store, rec("SPY", base_date=d))
        _resolve(store, "SPY", d, 104.0)
    for d in ("2026-11-16", "2026-11-17"):
        store.add_prediction({**v2("SPY", base_date=d), "interval_low": 98.0, "interval_high": 102.0})
        _resolve(store, "SPY", d, 104.0)
    store.add_prediction({**v2("SPY", base_date="2026-11-18", band="walk_forward_residuals"),
                          "interval_low": 98.0, "interval_high": 102.0})
    sc = scorecard(store.all_rows(), 5)
    legacy, conf = sc["periods"]
    assert legacy["band"] == "legacy" and legacy["n_resolved"] == 3 and legacy["interval_coverage"] == 1.0
    assert legacy["band_methods"] == ["legacy (v1 row)"] and legacy["last_base_date"] == "2026-11-12"
    assert conf["band"] == "conformal" and conf["n_resolved"] == 2 and conf["interval_coverage"] == 0.0
    assert conf["n_pending"] == 1 and conf["n_fallback"] == 1 and conf["first_base_date"] == "2026-11-16"
    assert conf["band_methods"] == ["split_conformal", "walk_forward_residuals"]
    assert sc["interval_coverage"] == pytest.approx(0.6) and sc["interval_method"].startswith("mixed")
    assert band_cutover(store.all_rows())["first_conformal_base_date"] == "2026-11-16"


def test_scorecard_before_the_cutover_is_unchanged(store):
    for d in ("2026-11-10", "2026-11-11"):
        add_v1(store, rec("SPY", base_date=d))
        _resolve(store, "SPY", d, 104.0)
    sc = scorecard(store.all_rows(), 5)
    assert [p["band"] for p in sc["periods"]] == ["legacy"] and sc["interval_method"].startswith("legacy band")


def test_public_log_exposes_v2_fields_and_cutover(client, store, monkeypatch):
    monkeypatch.setattr(config, "LOG_CONFORMAL_FROM", "2026-11-16")
    add_v1(store, rec("SPY", base_date="2026-11-13"))
    store.add_prediction(v2("SPY"))
    main.cache.clear()
    b = client.get("/api/prediction-log").json()
    assert b["chain_ok"] is True and b["chain_error"] is None and b["band_cutover"] == {"configured_from": "2026-11-16",
                                                           "first_conformal_base_date": "2026-11-16"}
    assert b["hash_versions"]["v2"] == 1 and b["hash_spec"]["entry_fields_v2"][-2:] == ["model_version",
                                                                                         "band_method"]
    newest, oldest = b["items"]
    assert newest["hash_version"] == 2 and newest["band_method"] == "split_conformal"
    assert oldest["hash_version"] is None and oldest["model_version"] is None
    # a third party can recompute both rules from the public rows alone
    prev = GENESIS
    for r in (oldest, newest):
        assert r["prev_hash"] == prev and compute_hash(prev, r) == r["entry_hash"]
        prev = r["entry_hash"]
    assert "v2" in hash_spec()["entry_hash_v2"] and public_row(store.all_rows()[1])["model_version"]
