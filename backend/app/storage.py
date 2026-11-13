"""Prediction-log storage: a thin abstraction over SQLAlchemy Core (SQLite by default, Postgres via DATABASE_URL).

Rules the code enforces (so the "pre-registered" claim is as strong as software alone can make it):
  * a prediction row is inserted once per (symbol, horizon, base_date) and its prediction fields are never updated;
  * only the outcome fields of a still-pending row can be filled in, once;
  * each row carries a hash chained to the previous row, so edits to old predictions are detectable;
  * outcomes are sealed by a SECOND chain (``res_*`` columns): when a row is resolved, a hash over the previous seal,
    the row's ``entry_hash`` and the outcome fields is stored with a gap-free sequence number, so editing, removing or
    reordering an outcome is detectable too. Rows resolved before this chain existed carry no seal; they are counted
    and reported as ``unsealed_resolved`` rather than silently trusted;
  * appends are serialised across processes (Postgres advisory locks) and the database refuses a second row with
    the same ``prev_hash``, so two instances cannot fork the chain.
All hashes are recomputable from the public API (see docs/REFERENCE.md, "Verifying the log yourself").
This is tamper-*evidence*, not tamper-proofing: whoever controls the database could rebuild the chains.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import quote, unquote

from sqlalchemy import (
    Column,
    Float,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    create_engine,
    func,
    insert,
    inspect,
    select,
    text,
    update,
)
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .errors import ApiError
from .observability import log_event

log = logging.getLogger("stock-api")
CONNECT_TIMEOUT_S = 10   # postgres only: a cold serverless compute (e.g. Neon) can take several seconds to wake
CONNECT_ATTEMPTS = 3     # postgres only: first try + 2 retries
CONNECT_BACKOFF_S = (1.0, 3.0)
_sleep = time.sleep      # replaced in tests

metadata = MetaData()
predictions = Table(
    "predictions", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("symbol", String(32), nullable=False),
    Column("horizon_days", Integer, nullable=False),
    Column("made_at", String(32), nullable=False),        # UTC ISO 8601, set by the server
    Column("base_date", String(10), nullable=False),      # date of the last bar the forecast used
    Column("base_close", Float, nullable=False),
    Column("predicted_return", Float, nullable=False),    # log return
    Column("interval_low", Float, nullable=False),        # 80% interval, price
    Column("interval_high", Float, nullable=False),
    Column("backtest_skill", Float),                      # backtest snapshot at the time (NOT a live result)
    Column("backtest_verdict", String(64)),
    Column("model", String(64), nullable=False),
    Column("prev_hash", String(64), nullable=False),
    Column("entry_hash", String(64), nullable=False),
    # outcome (filled once, after the horizon has passed)
    Column("status", String(16), nullable=False, default="pending"),  # pending | resolved
    Column("resolved_at", String(32)),
    Column("realized_date", String(10)),
    Column("realized_close", Float),
    Column("realized_return", Float),                     # log return, from the same adjusted series as base
    # outcome seal (second chain); NULL on rows resolved before it existed
    Column("res_seq", Integer),
    Column("res_prev_hash", String(64)),
    Column("res_hash", String(64)),
    # hash rule v2 (rows written from Nov 2026 on); NULL on every earlier row, which keeps the v1 rule untouched
    Column("hash_version", Integer),                      # NULL or 1 = v1 rule, 2 = v2 rule
    Column("model_version", String(64)),                  # model id + code commit that made the prediction
    Column("band_method", String(32)),                    # which 80% band was logged (see trackrecord.BAND_*)
    UniqueConstraint("symbol", "horizon_days", "base_date", name="uq_prediction"),
    Index("uq_predictions_prev_hash", "prev_hash", unique=True),   # a second row can never extend the same parent
    Index("uq_predictions_res_seq", "res_seq", unique=True),       # nor can two outcomes take the same position
)

HASH_FIELDS = ("symbol", "horizon_days", "made_at", "base_date", "base_close", "predicted_return",
               "interval_low", "interval_high", "backtest_skill", "backtest_verdict", "model")
# v2 adds what made the prediction and which band was logged. The payload also starts with the literal tag "v2", so a
# v2 row cannot be passed off as v1 (or the reverse) by editing ``hash_version``: the recomputed hash would differ.
HASH_FIELDS_V2 = HASH_FIELDS + ("model_version", "band_method")
HASH_VERSION_CURRENT = 2
V2_ONLY_FIELDS = ("model_version", "band_method")
RES_FIELDS = ("status", "resolved_at", "realized_date", "realized_close", "realized_return")
# Columns added to an existing table at startup (nullable, no default, no rewrite). Order matters only for the log.
NEW_COLUMNS = {"res_seq": "INTEGER", "res_prev_hash": "VARCHAR(64)", "res_hash": "VARCHAR(64)",
               "hash_version": "INTEGER", "model_version": "VARCHAR(64)", "band_method": "VARCHAR(32)"}
GENESIS = "0" * 64
# Postgres advisory-lock keys: one per chain, so appends/resolutions are serialised across app instances
LOCK_ENTRY_CHAIN = 7_351_001
LOCK_OUTCOME_CHAIN = 7_351_002
MIGRATION_LOCK_TIMEOUT = "5s"
LOCK_MIGRATION = 7_351_000


def plan_widening(live: dict[str, int | None]) -> list[tuple[str, int]]:
    """Columns whose live VARCHAR length is smaller than the model's. Never narrows (so it is idempotent and can't
    truncate data); sha-256 hash columns are 64 in both and are never touched."""
    plan = []
    for col in predictions.columns:
        want = getattr(col.type, "length", None)
        have = live.get(col.name)
        if want and have is not None and have < want:
            plan.append((col.name, want))
    return plan


class StorageUnavailable(ApiError):
    code, status = "STORAGE_UNAVAILABLE", 503

    def __init__(self, message: str = "The prediction log is temporarily unavailable."):
        super().__init__(message, retryable=True, retry_after=30)


class UnknownHashVersion(ValueError):
    """A row claims a hash rule this code does not know: it can never verify."""


def compute_hash(prev_hash: str, row: dict) -> str:
    """Entry hash of a row under the rule its ``hash_version`` names.

    v1 (``hash_version`` NULL/absent or 1; every row written before Nov 2026) is byte-for-byte the original rule:
        sha256(prev_hash + json.dumps([row[f] for f in HASH_FIELDS], separators=(",", ":"), default=str))
    v2 (``hash_version`` 2) prepends the tag and adds the v2 fields:
        sha256(prev_hash + json.dumps(["v2"] + [row[f] for f in HASH_FIELDS_V2], separators=(",", ":"), default=str))
    Both rules chain through ``prev_hash`` the same way, so a v2 row simply extends a v1 chain."""
    version = row.get("hash_version")
    if version is None or version == 1:
        payload = json.dumps([row[k] for k in HASH_FIELDS], separators=(",", ":"), default=str)
    elif version == 2:
        payload = json.dumps(["v2"] + [row[k] for k in HASH_FIELDS_V2], separators=(",", ":"), default=str)
    else:
        raise UnknownHashVersion(f"unknown hash_version {version!r}")
    return hashlib.sha256((prev_hash + payload).encode()).hexdigest()


def _v1_with_v2_fields(row: dict) -> bool:
    """A v1 row's hash does not cover the v2-only fields, so a v1 row that carries any of them was edited after it
    was written (e.g. a band_method planted to move an old row into the conformal period). It fails verification."""
    return (row.get("hash_version") or 1) == 1 and any(row.get(k) is not None for k in V2_ONLY_FIELDS)


CHAIN_ERRORS = {
    "prev_hash_mismatch": "a row does not link to the row before it",
    "entry_hash_mismatch": "a row's contents do not match its hash (edited after it was written)",
    "unknown_hash_version": "a row names a hash rule this code does not know",
    "v1_with_v2_fields": "an old-format (v1) row carries v2-only fields, which its hash does not cover",
    "v1_after_v2": "an old-format (v1) row was written after the log switched to v2",
}


def entry_problem(prev: str, row: dict, seen_v2: bool) -> str | None:
    """Why ``row`` breaks the entry chain (a key of ``CHAIN_ERRORS``), or None if it is fine. ``seen_v2``: an earlier
    row already used the v2 rule. The switch is one-way: once a v2 row exists, every later row must be v2 too."""
    if row["prev_hash"] != prev:
        return "prev_hash_mismatch"
    try:
        if row["entry_hash"] != compute_hash(prev, row):
            return "entry_hash_mismatch"
    except UnknownHashVersion:
        return "unknown_hash_version"
    if _v1_with_v2_fields(row):
        return "v1_with_v2_fields"
    if seen_v2 and (row.get("hash_version") or 1) == 1:
        return "v1_after_v2"
    return None


def compute_res_hash(res_prev: str, entry_hash: str, row: dict) -> str:
    """Seal over an outcome: previous seal + the entry it belongs to + the outcome fields."""
    payload = json.dumps([row[k] for k in RES_FIELDS], separators=(",", ":"), default=str)
    return hashlib.sha256((res_prev + entry_hash + payload).encode()).hexdigest()


def _normalise_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


_URL_CREDS = re.compile(r"://[^/\s@]*@")
_KV_SECRET = re.compile(r"(?i)\b(password|passwd|pwd|sslpassword)\b(\s*[=:]\s*)(\S+)")


def redact(text: str, secrets: list[str]) -> str:
    """Remove anything resembling database credentials from an error message, then collapse and truncate it.

    ``secrets`` are exact strings known to be sensitive (the raw/normalised DATABASE_URL, the password in raw and
    percent-encoded form, the user name). Pattern rules then catch ``scheme://user:pass@host`` and ``password=...``
    forms that a driver may have re-formatted.
    """
    for sec in sorted({x for x in secrets if x}, key=len, reverse=True):
        text = text.replace(sec, "[redacted]")
    text = _URL_CREDS.sub("://[redacted]@", text)
    text = _KV_SECRET.sub(r"\1\2[redacted]", text)
    return re.sub(r"\s+", " ", text).strip()[:300]


@dataclass
class Page:
    items: list[dict]
    total: int


class PredictionStore:
    def __init__(self, url: str):
        self.url = _normalise_url(url)
        self.backend = "postgres" if self.url.startswith("postgresql") else "sqlite"
        if self.backend == "sqlite":
            kwargs: dict = {"connect_args": {"check_same_thread": False}}
        else:
            kwargs = {"pool_pre_ping": True, "connect_args": {"connect_timeout": CONNECT_TIMEOUT_S}}
        self.engine: Engine = create_engine(self.url, **kwargs)
        self._lock = threading.Lock()  # serialises writers so the hash chain stays linear
        self._ready = False
        # Values that must never appear in logs.
        parsed = make_url(self.url)
        pw = parsed.password or ""
        self._secrets = [url, self.url, pw, quote(pw, safe=""), unquote(pw), parsed.username or ""]
        self._host = "file" if self.backend == "sqlite" else (
            f"{parsed.host}:{parsed.port}" if parsed.port else (parsed.host or "unknown"))

    def _fail(self, op: str, exc: BaseException, phase: str | None = None,
              level: int = logging.ERROR) -> StorageUnavailable:
        """Log the cause (class + sanitized message, backend, host; never credentials) and build the public error.
        The public error body is unchanged; the cause is not chained so it can't leak through tracebacks."""
        orig = getattr(exc, "orig", None)
        log_event(log, "storage_error", level, op=op, phase=phase, backend=self.backend, host=self._host,
                  error_class=type(exc).__name__, driver_error_class=type(orig).__name__ if orig else None,
                  message=redact(str(orig or exc), self._secrets))
        return StorageUnavailable()

    def init(self) -> None:
        attempts = CONNECT_ATTEMPTS if self.backend == "postgres" else 1
        for n in range(1, attempts + 1):
            try:
                with self.engine.connect():
                    break
            except SQLAlchemyError as exc:
                last = n == attempts
                err = self._fail("init", exc, phase="connect", level=logging.ERROR if last else logging.WARNING)
                if last:
                    raise err from None
                _sleep(CONNECT_BACKOFF_S[min(n - 1, len(CONNECT_BACKOFF_S) - 1)])
        try:
            metadata.create_all(self.engine)
            if self.backend == "postgres":
                self._migrate_columns()
            self._migrate_seal()
        except SQLAlchemyError as exc:
            raise self._fail("init", exc, phase="query") from None
        self._ready = True

    def _migrate_columns(self) -> None:
        """create_all never alters existing tables. An earlier release created some VARCHAR columns too short
        (e.g. backtest_verdict VARCHAR(16)), so widen any that are smaller than the current model. Idempotent."""
        with self.engine.begin() as conn:
            live = {c["name"]: getattr(c["type"], "length", None) for c in inspect(conn).get_columns("predictions")}
            for name, length in plan_widening(live):
                # identifiers come from our own table definition, never from user input
                conn.execute(text(f'ALTER TABLE predictions ALTER COLUMN "{name}" TYPE VARCHAR({int(length)})'))
                log_event(log, "storage_column_widened", logging.INFO, column=name, length=length, host=self._host)

    def _migrate_seal(self) -> None:
        """Bring an EXISTING ``predictions`` table up to date for the outcome seal and the append guards.
        ``create_all`` never alters or indexes a table that already exists, so this does it explicitly.

        Safe on a live table by construction:
          * only ADDs nullable columns (a metadata-only change on Postgres, no rewrite, no default, no data touched);
          * no row is ever updated, rewritten or re-hashed: existing entry hashes and the entry chain stay valid, and
            rows resolved before this change simply keep NULL seal columns;
          * unique indexes are created only if the data already satisfies them (otherwise skipped with a warning, so
            the app never fails to start because of old data);
          * idempotent (IF NOT EXISTS + inspection), one transaction, a lock timeout so it cannot hang request
            handling behind a long-running query, and an advisory lock so two starting instances do not race.
        """
        pg = self.engine.dialect.name == "postgresql"  # real dialect, not the label (tests fake the label)
        with self.engine.begin() as conn:
            if pg:
                conn.execute(text(f"SET LOCAL lock_timeout = '{MIGRATION_LOCK_TIMEOUT}'"))
                conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": LOCK_MIGRATION})
            have_cols = {c["name"] for c in inspect(conn).get_columns("predictions")}
            for name, sql_type in NEW_COLUMNS.items():  # constants from this module, never user input
                if name not in have_cols:
                    ine = "IF NOT EXISTS " if pg else ""
                    conn.execute(text(f'ALTER TABLE predictions ADD COLUMN {ine}"{name}" {sql_type}'))
                    log_event(log, "storage_column_added", logging.INFO, column=name, host=self._host)
            have_idx = {i["name"] for i in inspect(conn).get_indexes("predictions")}
            for idx_name, col in (("uq_predictions_prev_hash", "prev_hash"), ("uq_predictions_res_seq", "res_seq")):
                if idx_name in have_idx:
                    continue
                dup = conn.execute(text(
                    f'SELECT 1 FROM predictions WHERE "{col}" IS NOT NULL GROUP BY "{col}" HAVING COUNT(*) > 1 LIMIT 1'
                )).first()
                if dup:
                    log_event(log, "storage_index_skipped", logging.WARNING, index=idx_name, reason="duplicate_values",
                              host=self._host)
                    continue
                conn.execute(text(f'CREATE UNIQUE INDEX IF NOT EXISTS {idx_name} ON predictions ("{col}")'))
                log_event(log, "storage_index_created", logging.INFO, index=idx_name, host=self._host)

    def _pg_lock(self, conn, key: int) -> None:
        """Serialise writers across processes/instances (Postgres). SQLite is a single-file database whose own write
        lock plus the unique indexes cover this; the in-process threading lock covers threads."""
        if self.engine.dialect.name == "postgresql":
            conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": key})

    def _ensure(self) -> None:
        if not self._ready:
            self.init()

    # --- writes -----------------------------------------------------------------------------
    def add_prediction(self, rec: dict) -> bool:
        """Insert unless (symbol, horizon, base_date) already exists. Returns True if inserted.

        Safe across instances: on Postgres the whole read-last-hash + insert runs under an advisory lock, and the
        unique index on ``prev_hash`` makes the database itself refuse a forked chain. If that guard ever fires
        (e.g. a writer that bypassed the lock) we simply retry against the new chain tip."""
        self._ensure()
        for attempt in range(3):
            try:
                with self._lock, self.engine.begin() as conn:
                    self._pg_lock(conn, LOCK_ENTRY_CHAIN)
                    dup = conn.execute(select(predictions.c.id).where(
                        predictions.c.symbol == rec["symbol"], predictions.c.horizon_days == rec["horizon_days"],
                        predictions.c.base_date == rec["base_date"])).first()
                    if dup:
                        return False
                    last = conn.execute(
                        select(predictions.c.entry_hash).order_by(predictions.c.id.desc()).limit(1)).first()
                    prev = last[0] if last else GENESIS
                    # new code always writes the current rule, whatever the caller passed: it can never append an
                    # old-format row after a v2 row (which verification rejects as ``v1_after_v2``)
                    row = {**dict.fromkeys(V2_ONLY_FIELDS), **rec, "made_at": rec.get("made_at") or now_iso(),
                           "hash_version": HASH_VERSION_CURRENT}
                    conn.execute(insert(predictions).values(**row, prev_hash=prev,
                                                            entry_hash=compute_hash(prev, row), status="pending"))
                    return True
            except IntegrityError as exc:
                if attempt == 2:
                    raise self._fail("add_prediction", exc, phase="query") from None
                log_event(log, "storage_append_conflict_retry", logging.WARNING, attempt=attempt + 1)
            except SQLAlchemyError as exc:
                raise self._fail("add_prediction", exc, phase="query") from None
        return False  # unreachable

    def symbols_with_base(self, base_date: str, horizon_days: int) -> set[str]:
        """Symbols that already have a row for this (base date, horizon)."""
        self._ensure()
        try:
            with self.engine.connect() as conn:
                rows = conn.execute(select(predictions.c.symbol).where(
                    predictions.c.base_date == base_date, predictions.c.horizon_days == horizon_days)).all()
            return {r[0] for r in rows}
        except SQLAlchemyError as exc:
            raise self._fail("symbols_with_base", exc, phase="query") from None

    def pending(self) -> list[dict]:
        self._ensure()
        try:
            with self.engine.connect() as conn:
                rows = conn.execute(select(predictions).where(predictions.c.status == "pending")
                                    .order_by(predictions.c.id)).mappings().all()
            return [dict(r) for r in rows]
        except SQLAlchemyError as exc:
            raise self._fail("pending", exc, phase="query") from None

    def resolve(self, pred_id: int, realized_date: str, realized_close: float, realized_return: float) -> bool:
        """Fill in the outcome of a pending row (once) and seal it on the outcome chain.
        Never touches prediction fields or the entry hash."""
        self._ensure()
        for attempt in range(3):
            try:
                with self._lock, self.engine.begin() as conn:
                    self._pg_lock(conn, LOCK_OUTCOME_CHAIN)
                    cur = conn.execute(select(predictions).where(
                        predictions.c.id == pred_id, predictions.c.status == "pending")).mappings().first()
                    if cur is None:
                        return False
                    tip = conn.execute(select(predictions.c.res_seq, predictions.c.res_hash)
                                       .where(predictions.c.res_seq.is_not(None))
                                       .order_by(predictions.c.res_seq.desc()).limit(1)).first()
                    seq, res_prev = (tip[0] + 1, tip[1]) if tip else (1, GENESIS)
                    out = {"status": "resolved", "resolved_at": now_iso(), "realized_date": realized_date,
                           "realized_close": realized_close, "realized_return": realized_return}
                    res = conn.execute(
                        update(predictions)
                        .where(predictions.c.id == pred_id, predictions.c.status == "pending")
                        .values(**out, res_seq=seq, res_prev_hash=res_prev,
                                res_hash=compute_res_hash(res_prev, cur["entry_hash"], out)))
                    return res.rowcount == 1
            except IntegrityError as exc:
                if attempt == 2:
                    raise self._fail("resolve", exc, phase="query") from None
                log_event(log, "storage_append_conflict_retry", logging.WARNING, attempt=attempt + 1)
            except SQLAlchemyError as exc:
                raise self._fail("resolve", exc, phase="query") from None
        return False  # unreachable

    # --- reads ------------------------------------------------------------------------------
    def page(self, limit: int, offset: int, symbol: str | None = None, status: str | None = None) -> Page:
        self._ensure()
        try:
            cond = []
            if symbol:
                cond.append(predictions.c.symbol == symbol)
            if status:
                cond.append(predictions.c.status == status)
            with self.engine.connect() as conn:
                total = conn.execute(select(func.count()).select_from(predictions).where(*cond)).scalar_one()
                rows = conn.execute(select(predictions).where(*cond).order_by(predictions.c.id.desc())
                                    .limit(limit).offset(offset)).mappings().all()
            return Page([dict(r) for r in rows], int(total))
        except SQLAlchemyError as exc:
            raise self._fail("page", exc, phase="query") from None

    def all_rows(self) -> list[dict]:
        self._ensure()
        try:
            with self.engine.connect() as conn:
                return [dict(r) for r in conn.execute(select(predictions).order_by(predictions.c.id)).mappings().all()]
        except SQLAlchemyError as exc:
            raise self._fail("all_rows", exc, phase="query") from None

    def verify_report(self, rows: list[dict] | None = None) -> dict:
        """Check both chains. ``chain_ok`` is the original entry-chain check (unchanged, so every row written before
        outcome seals existed still verifies). ``outcomes_ok`` checks the outcome seals of rows that have one;
        resolved rows that predate the seal are counted in ``unsealed_resolved`` (their outcomes are not covered)."""
        rows = self.all_rows() if rows is None else rows
        chain_ok, prev, chain_error, seen_v2 = True, GENESIS, None, False
        for r in rows:
            reason = entry_problem(prev, r, seen_v2)
            if reason:
                chain_ok, chain_error = False, {"reason": reason, "row_id": r.get("id")}
                break
            seen_v2 = seen_v2 or r.get("hash_version") == 2
            prev = r["entry_hash"]
        outcomes_ok, unsealed, res_prev, seq = True, 0, GENESIS, 0
        sealed = sorted((r for r in rows if r.get("res_seq") is not None), key=lambda r: r["res_seq"])
        for r in rows:
            if r["status"] == "resolved" and r.get("res_hash") is None:
                unsealed += 1
            if r["status"] != "resolved" and (r.get("res_hash") is not None or r.get("res_seq") is not None):
                outcomes_ok = False  # a seal on a row that claims to be pending
        for r in sealed:
            seq += 1
            if (r["res_seq"] != seq or r["res_prev_hash"] != res_prev or r["status"] != "resolved"
                    or r["res_hash"] != compute_res_hash(res_prev, r["entry_hash"], r)):
                outcomes_ok = False
                break
            res_prev = r["res_hash"]
        return {"chain_ok": chain_ok, "chain_error": chain_error, "outcomes_ok": outcomes_ok,
                "unsealed_resolved": unsealed, "sealed_resolved": len(sealed)}

    @staticmethod
    def hash_versions(rows: list[dict]) -> dict:
        """How many rows use each hash rule and where the log switched. ``v1_after_v2`` counts v1 rows after the first
        v2 row; any such row makes ``verify_report`` fail (reason ``v1_after_v2``), so this should always be 0."""
        versions = [r.get("hash_version") or 1 for r in rows]
        first_v2 = next((r["id"] for r, v in zip(rows, versions, strict=True) if v == 2), None)
        return {"v1": versions.count(1), "v2": versions.count(2), "first_v2_id": first_v2,
                "v1_after_v2": sum(1 for r, v in zip(rows, versions, strict=True)
                                   if v == 1 and first_v2 is not None and r["id"] > first_v2)}

    def verify_chain(self) -> bool:
        """Entry chain only (kept for compatibility); see ``verify_report`` for outcomes."""
        return self.verify_report()["chain_ok"]

    def close(self) -> None:
        self.engine.dispose()


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
