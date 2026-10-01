"""Prediction-log storage: a thin abstraction over SQLAlchemy Core (SQLite by default, Postgres via DATABASE_URL).

Rules the code enforces (so the "pre-registered" claim is as strong as software alone can make it):
  * a prediction row is inserted once per (symbol, horizon, base_date) and its prediction fields are never updated;
  * only the outcome fields of a still-pending row can be filled in, once;
  * each row carries a hash chained to the previous row, so edits to old predictions are detectable.
This is tamper-*evidence*, not tamper-proofing: whoever controls the database could rebuild the chain.
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import (
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    create_engine,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from .errors import ApiError

metadata = MetaData()
predictions = Table(
    "predictions", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("symbol", String(16), nullable=False),
    Column("horizon_days", Integer, nullable=False),
    Column("made_at", String(24), nullable=False),        # UTC ISO 8601, set by the server
    Column("base_date", String(10), nullable=False),      # date of the last bar the forecast used
    Column("base_close", Float, nullable=False),
    Column("predicted_return", Float, nullable=False),    # log return
    Column("interval_low", Float, nullable=False),        # 80% interval, price
    Column("interval_high", Float, nullable=False),
    Column("backtest_skill", Float),                      # backtest snapshot at the time (NOT a live result)
    Column("backtest_verdict", String(16)),
    Column("model", String(32), nullable=False),
    Column("prev_hash", String(64), nullable=False),
    Column("entry_hash", String(64), nullable=False),
    # outcome (filled once, after the horizon has passed)
    Column("status", String(12), nullable=False, default="pending"),  # pending | resolved
    Column("resolved_at", String(24)),
    Column("realized_date", String(10)),
    Column("realized_close", Float),
    Column("realized_return", Float),                     # log return, from the same adjusted series as base
    UniqueConstraint("symbol", "horizon_days", "base_date", name="uq_prediction"),
)

HASH_FIELDS = ("symbol", "horizon_days", "made_at", "base_date", "base_close", "predicted_return",
               "interval_low", "interval_high", "backtest_skill", "backtest_verdict", "model")
GENESIS = "0" * 64


class StorageUnavailable(ApiError):
    code, status = "STORAGE_UNAVAILABLE", 503

    def __init__(self, message: str = "The prediction log is temporarily unavailable."):
        super().__init__(message, retryable=True, retry_after=30)


def compute_hash(prev_hash: str, row: dict) -> str:
    payload = json.dumps([row[k] for k in HASH_FIELDS], separators=(",", ":"), default=str)
    return hashlib.sha256((prev_hash + payload).encode()).hexdigest()


def _normalise_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


@dataclass
class Page:
    items: list[dict]
    total: int


class PredictionStore:
    def __init__(self, url: str):
        self.url = _normalise_url(url)
        self.backend = "postgres" if self.url.startswith("postgresql") else "sqlite"
        kwargs = {"connect_args": {"check_same_thread": False}} if self.backend == "sqlite" else {"pool_pre_ping": True}
        self.engine: Engine = create_engine(self.url, **kwargs)
        self._lock = threading.Lock()  # serialises writers so the hash chain stays linear
        self._ready = False

    def init(self) -> None:
        try:
            metadata.create_all(self.engine)
            self._ready = True
        except SQLAlchemyError as exc:
            raise StorageUnavailable() from exc

    def _ensure(self) -> None:
        if not self._ready:
            self.init()

    # --- writes -----------------------------------------------------------------------------
    def add_prediction(self, rec: dict) -> bool:
        """Insert unless (symbol, horizon, base_date) already exists. Returns True if inserted."""
        self._ensure()
        try:
            with self._lock, self.engine.begin() as conn:
                dup = conn.execute(select(predictions.c.id).where(
                    predictions.c.symbol == rec["symbol"], predictions.c.horizon_days == rec["horizon_days"],
                    predictions.c.base_date == rec["base_date"])).first()
                if dup:
                    return False
                last = conn.execute(select(predictions.c.entry_hash).order_by(predictions.c.id.desc()).limit(1)).first()
                prev = last[0] if last else GENESIS
                row = {**rec, "made_at": rec.get("made_at") or now_iso()}
                conn.execute(insert(predictions).values(**row, prev_hash=prev, entry_hash=compute_hash(prev, row),
                                                        status="pending"))
                return True
        except SQLAlchemyError as exc:
            raise StorageUnavailable() from exc

    def pending(self) -> list[dict]:
        self._ensure()
        try:
            with self.engine.connect() as conn:
                rows = conn.execute(select(predictions).where(predictions.c.status == "pending")
                                    .order_by(predictions.c.id)).mappings().all()
            return [dict(r) for r in rows]
        except SQLAlchemyError as exc:
            raise StorageUnavailable() from exc

    def resolve(self, pred_id: int, realized_date: str, realized_close: float, realized_return: float) -> bool:
        """Fill in the outcome of a pending row (once). Never touches prediction fields."""
        self._ensure()
        try:
            with self._lock, self.engine.begin() as conn:
                res = conn.execute(
                    update(predictions)
                    .where(predictions.c.id == pred_id, predictions.c.status == "pending")
                    .values(status="resolved", resolved_at=now_iso(), realized_date=realized_date,
                            realized_close=realized_close, realized_return=realized_return))
                return res.rowcount == 1
        except SQLAlchemyError as exc:
            raise StorageUnavailable() from exc

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
            raise StorageUnavailable() from exc

    def all_rows(self) -> list[dict]:
        self._ensure()
        try:
            with self.engine.connect() as conn:
                return [dict(r) for r in conn.execute(select(predictions).order_by(predictions.c.id)).mappings().all()]
        except SQLAlchemyError as exc:
            raise StorageUnavailable() from exc

    def verify_chain(self) -> bool:
        prev = GENESIS
        for r in self.all_rows():
            if r["prev_hash"] != prev or r["entry_hash"] != compute_hash(prev, r):
                return False
            prev = r["entry_hash"]
        return True

    def close(self) -> None:
        self.engine.dispose()


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
