"""Tiny thread-safe in-memory TTL cache."""
import threading
import time
from collections.abc import Callable
from typing import Any


class TTLCache:
    def __init__(self, max_items: int = 512):
        self._data: dict[Any, tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self._max = max_items

    def get_or_set(self, key: Any, ttl: float, factory: Callable[[], Any]) -> Any:
        now = time.monotonic()
        with self._lock:
            hit = self._data.get(key)
            if hit and hit[0] > now:
                return hit[1]
        value = factory()  # outside the lock: network calls can be slow; duplicate work is acceptable
        with self._lock:
            if len(self._data) >= self._max:
                # drop expired entries, then the oldest if still full
                for k in [k for k, (exp, _) in self._data.items() if exp <= now]:
                    self._data.pop(k, None)
                if len(self._data) >= self._max:
                    self._data.pop(min(self._data, key=lambda k: self._data[k][0]), None)
            self._data[key] = (now + ttl, value)
        return value
