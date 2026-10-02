"""In-memory sliding-window rate limiter with a trustworthy client key and bounded memory.

Client key (see ``client_key``):
  * ``TRUST_PROXY`` off (default): the socket peer address. Behind a reverse proxy that is the proxy's address, so
    every visitor then shares one bucket. Turn TRUST_PROXY on behind a proxy.
  * ``TRUST_PROXY`` on: the entry ``TRUSTED_PROXY_HOPS`` positions from the RIGHT of X-Forwarded-For. Proxies append;
    only the right-most entries were written by infrastructure we trust, everything to the left is client-supplied
    and ignored, so a client cannot choose its own bucket by sending a forged header.
  * Anything that is not a valid IP, or a header with fewer entries than hops, falls back to the socket peer.
  * IPv6 addresses are grouped by /64 (one subscriber typically controls a whole /64), so rotating addresses inside
    it does not buy more requests.

Memory is bounded three ways: keys are expired by last-seen time from the front of an ordered map (amortised O(1),
at most ``SWEEP_BATCH`` per call, no full scan under the lock); key length is capped; and the number of keys has a
hard cap. At the cap, *new* clients share one overflow bucket with the same per-minute limit (existing clients are
unaffected), so flooding with unique clients can neither grow memory nor reset anyone's counter.
"""
from __future__ import annotations

import ipaddress
import threading
from collections import OrderedDict, deque

WINDOW_S = 60
MAX_KEY_LEN = 64
SWEEP_BATCH = 64
OVERFLOW_KEY = "overflow"


def _normalise_ip(raw: str) -> str | None:
    raw = raw.strip()
    if not raw or len(raw) > 45:
        return None
    try:
        ip = ipaddress.ip_address(raw.split("%", 1)[0])
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped:
            return str(ip.ipv4_mapped)
        return str(ipaddress.ip_network(f"{ip}/64", strict=False).network_address) + "/64"
    return str(ip)


def client_key(peer: str | None, forwarded_for: str | None, trust_proxy: bool, hops: int) -> str:
    fallback = (peer or "unknown")[:MAX_KEY_LEN]
    if not trust_proxy or not forwarded_for:
        return fallback
    parts = [x.strip() for x in forwarded_for.split(",")]  # keep empty entries: positions must not shift
    if hops < 1 or len(parts) < hops:
        return fallback
    return _normalise_ip(parts[-hops]) or fallback


class RateLimiter:
    def __init__(self, max_keys: int = 10_000):
        self.max_keys = max(max_keys, 2)
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()  # least recently seen first
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._hits)

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()

    def _sweep(self, now: float) -> None:
        """Drop keys whose newest hit is outside the window, oldest-seen first, a bounded number per call."""
        for _ in range(SWEEP_BATCH):
            if not self._hits:
                return
            key = next(iter(self._hits))
            q = self._hits[key]
            if q and q[-1] > now - WINDOW_S:
                return  # the least recently seen key is still active, so every other key is too
            del self._hits[key]

    def hit(self, bucket: str, cid: str, limit: int, now: float) -> int | None:
        """Record a request; return seconds to wait if ``cid`` is over ``limit`` per minute in ``bucket``, else None."""
        key = f"{bucket}:{cid[:MAX_KEY_LEN]}"
        with self._lock:
            self._sweep(now)
            if key not in self._hits and len(self._hits) >= self.max_keys:
                key = f"{bucket}:{OVERFLOW_KEY}"  # table full: unseen clients share one bucket
            q = self._hits.get(key)
            if q is None:
                q = self._hits[key] = deque()
            else:
                self._hits.move_to_end(key)
            while q and q[0] <= now - WINDOW_S:
                q.popleft()
            if len(q) >= limit:
                return max(int(WINDOW_S - (now - q[0])) + 1, 1) if q else WINDOW_S
            q.append(now)
        return None
