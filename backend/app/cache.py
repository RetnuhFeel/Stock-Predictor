"""Thread-safe in-memory TTL cache: single-flight loads, LRU eviction, stale-if-error fallback."""
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .errors import UpstreamError

FOLLOWER_WAIT_S = 150  # a follower never waits longer than this for another request's load, then loads itself


@dataclass
class Fetched:
    value: Any
    fetched_at: float  # unix time the value was produced
    stale: bool  # True when an expired value was served because refreshing failed


class _Flight:
    """One in-progress load of a key; concurrent requests for the same key wait on it instead of repeating it."""

    __slots__ = ("done", "value", "fetched_at", "error")

    def __init__(self) -> None:
        self.done = threading.Event()
        self.value: Any = None
        self.fetched_at = 0.0
        self.error: BaseException | None = None


class TTLCache:
    """key -> (expires, fetched_at, value) in ``_data``, ordered least recently used first.

    * Single-flight: while one request loads a key, others asking for the same key wait and share the result (or the
      error), so a cold page that fires several requests for the same symbol makes one provider call.
    * Eviction: at capacity, entries that are expired AND past their stale-if-error window are dropped first; if
      still full, the least recently used entry goes. Entries that can still be served as stale-if-error fallback are
      never dropped just because something new was inserted (only by the hard cap, least recently used first).
    """

    def __init__(self, max_items: int = 512):
        self._data: dict[Any, tuple[float, float, Any]] = {}
        self._keep: dict[Any, float] = {}  # key -> stale_max_age the entry was stored with
        self._flights: dict[Any, _Flight] = {}
        self._lock = threading.Lock()
        self._max = max_items

    def __len__(self) -> int:
        return len(self._data)

    def _touch(self, key: Any) -> None:
        item = self._data.pop(key, None)
        if item is not None:
            self._data[key] = item  # reinsert: now the most recently used

    def _store(self, key: Any, ttl: float, now: float, value: Any, stale_max_age: float) -> None:
        if key not in self._data and len(self._data) >= self._max:
            dead = [k for k, (exp, fa, _) in self._data.items() if exp <= now and now - fa > self._keep.get(k, 0)]
            for k in dead:
                self._data.pop(k, None)
                self._keep.pop(k, None)
            while len(self._data) >= self._max:
                oldest = next(iter(self._data))
                self._data.pop(oldest)
                self._keep.pop(oldest, None)
        self._data.pop(key, None)
        self._data[key] = (now + ttl, now, value)
        self._keep[key] = stale_max_age

    def fetch(self, key: Any, ttl: float, factory: Callable[[], Any], stale_max_age: float = 0) -> Fetched:
        """Return a fresh cached value, else call ``factory`` (once per key at a time).

        If ``factory`` fails with an upstream error and an expired entry younger than ``stale_max_age`` seconds
        exists, that entry is returned with ``stale=True``.
        """
        now = time.time()
        with self._lock:
            hit = self._data.get(key)
            if hit and hit[0] > now:
                self._touch(key)
                return Fetched(hit[2], hit[1], False)
            flight = self._flights.get(key)
            leader = flight is None
            if leader:
                flight = self._flights[key] = _Flight()
        assert flight is not None

        if not leader:
            if flight.done.wait(FOLLOWER_WAIT_S):
                if flight.error is None:
                    return Fetched(flight.value, flight.fetched_at, False)
                if isinstance(flight.error, UpstreamError) and hit and now - hit[1] <= stale_max_age:
                    return Fetched(hit[2], hit[1], True)
                raise flight.error
            return self._load(key, ttl, factory, stale_max_age, hit, now)  # leader hung: go alone
        return self._load(key, ttl, factory, stale_max_age, hit, now, flight=flight)

    def _load(self, key, ttl, factory, stale_max_age, hit, now, *, flight: _Flight | None = None):
        try:
            value = factory()  # outside the lock: network calls can be slow
        except BaseException as exc:
            if flight is not None:
                flight.error = exc
            if isinstance(exc, UpstreamError) and hit and now - hit[1] <= stale_max_age:
                return Fetched(hit[2], hit[1], True)
            raise
        else:
            done = time.time()
            with self._lock:
                self._store(key, ttl, done, value, stale_max_age)
            if flight is not None:
                flight.value, flight.fetched_at = value, done
            return Fetched(value, done, False)
        finally:
            if flight is not None:
                with self._lock:
                    self._flights.pop(key, None)
                flight.done.set()

    def clear_prefix(self, prefix: str) -> None:
        """Drop entries whose key is a tuple starting with ``prefix``."""
        with self._lock:
            for k in [k for k in self._data if isinstance(k, tuple) and k and k[0] == prefix]:
                self._data.pop(k, None)
                self._keep.pop(k, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._keep.clear()
