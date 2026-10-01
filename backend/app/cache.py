"""Tiny thread-safe in-memory TTL cache with optional stale-if-error fallback."""
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .errors import UpstreamError


@dataclass
class Fetched:
    value: Any
    fetched_at: float  # unix time the value was produced
    stale: bool  # True when an expired value was served because refreshing failed


class TTLCache:
    def __init__(self, max_items: int = 512):
        self._data: dict[Any, tuple[float, float, Any]] = {}  # key -> (expires, fetched_at, value)
        self._lock = threading.Lock()
        self._max = max_items

    def fetch(self, key: Any, ttl: float, factory: Callable[[], Any], stale_max_age: float = 0) -> Fetched:
        """Return a fresh cached value, else call ``factory``.

        If ``factory`` fails with an upstream error and an expired entry younger than
        ``stale_max_age`` seconds exists, that entry is returned with ``stale=True``.
        """
        now = time.time()
        with self._lock:
            hit = self._data.get(key)
            if hit and hit[0] > now:
                return Fetched(hit[2], hit[1], False)
        try:
            value = factory()  # outside the lock: network calls can be slow; duplicate work is acceptable
        except UpstreamError:
            if hit and now - hit[1] <= stale_max_age:
                return Fetched(hit[2], hit[1], True)
            raise
        with self._lock:
            if len(self._data) >= self._max:
                for k in [k for k, (exp, fa, _) in self._data.items() if exp <= now and now - fa > stale_max_age]:
                    self._data.pop(k, None)
                if len(self._data) >= self._max:
                    self._data.pop(min(self._data, key=lambda k: self._data[k][1]), None)
            self._data[key] = (now + ttl, now, value)
        return Fetched(value, now, False)

    def get_or_set(self, key: Any, ttl: float, factory: Callable[[], Any]) -> Any:
        return self.fetch(key, ttl, factory).value

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
