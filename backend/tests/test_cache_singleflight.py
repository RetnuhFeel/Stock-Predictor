"""Caching: single-flight loads, search isolation, LRU eviction that spares stale-if-error entries."""
import threading
import time

from app import main
from app.cache import TTLCache
from app.errors import DataUnavailable

from .conftest import FakeProvider, synthetic_prices


class SlowProvider(FakeProvider):
    def __init__(self, delay=0.4):
        super().__init__()
        self.delay = delay
        self.lock = threading.Lock()
        self.by_symbol: dict[str, int] = {}

    def history(self, symbol, period):
        with self.lock:
            self.calls += 1
            self.by_symbol[symbol] = self.by_symbol.get(symbol, 0) + 1
        time.sleep(self.delay)
        return synthetic_prices(900).tail({"5y": 900, "1mo": 21, "6mo": 126, "1y": 252, "2y": 504}.get(period, 900))


def burst(client, urls):
    out = [None] * len(urls)

    def go(i, u):
        out[i] = client.get(u)
    ts = [threading.Thread(target=go, args=(i, u)) for i, u in enumerate(urls)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return out


def test_cold_page_load_makes_one_provider_call(client):
    slow = SlowProvider()
    main.app.dependency_overrides[main.get_provider] = lambda: slow
    urls = [f"/api/{ep}/AAPL?horizon=5" for ep in ("forecast", "volatility", "compare-models")] + [
        "/api/timeline/AAPL", "/api/forecast/AAPL?horizon=5", "/api/volatility/AAPL?horizon=5",
        "/api/compare-models/AAPL?horizon=5", "/api/timeline/AAPL"]
    res = burst(client, urls)
    assert [r.status_code for r in res] == [200] * len(urls), [r.text[:100] for r in res if r.status_code != 200]
    assert slow.by_symbol == {"AAPL": 1}, slow.by_symbol  # was 8 before single-flight


def test_ttlcache_single_flight_shares_result_and_runs_factory_once():
    c = TTLCache()
    n = {"v": 0}

    def factory():
        n["v"] += 1
        time.sleep(0.2)
        return object()
    out = []
    ts = [threading.Thread(target=lambda: out.append(c.fetch("k", 60, factory).value)) for _ in range(10)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert n["v"] == 1 and len({id(o) for o in out}) == 1 and len(out) == 10
    assert c._flights == {}  # nothing left behind


def test_followers_share_the_leaders_error_and_inflight_is_cleaned_up():
    c = TTLCache()
    n = {"v": 0}

    def factory():
        n["v"] += 1
        time.sleep(0.2)
        raise DataUnavailable("down")
    errs = []

    def go():
        try:
            c.fetch("k", 60, factory)
        except DataUnavailable as e:
            errs.append(e)
    ts = [threading.Thread(target=go) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert n["v"] == 1 and len(errs) == 6 and c._flights == {}
    assert c.fetch("k", 60, lambda: 7).value == 7  # a failure is not cached: next call retries


def test_followers_get_stale_value_when_leader_fails():
    c = TTLCache()
    c.fetch("k", 60, lambda: "old", stale_max_age=1000)
    c._data["k"] = (0, c._data["k"][1], "old")  # expire
    gate = threading.Event()

    def bad():
        gate.wait(1)
        raise DataUnavailable("down")
    got = []
    ts = [threading.Thread(target=lambda: got.append(c.fetch("k", 60, bad, stale_max_age=1000))) for _ in range(4)]
    [t.start() for t in ts]
    time.sleep(0.1)
    gate.set()
    [t.join() for t in ts]
    assert len(got) == 4 and all(g.value == "old" and g.stale for g in got)


def test_leader_exception_that_is_not_upstream_still_releases_followers():
    c = TTLCache()

    def bad():
        time.sleep(0.1)
        raise ValueError("bug")
    res = []

    def go():
        try:
            c.fetch("k", 60, bad)
        except ValueError:
            res.append("err")
    ts = [threading.Thread(target=go) for _ in range(3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert res == ["err"] * 3 and c._flights == {}


def test_concurrent_cold_trending_requests_share_one_download(client, monkeypatch):
    from .test_trending import BatchProvider
    p = BatchProvider({"NVDA": 6.0})
    orig = p.batch_history

    def slow_batch(symbols, period):
        time.sleep(0.3)
        return orig(symbols, period)
    p.batch_history = slow_batch
    main.app.dependency_overrides[main.get_provider] = lambda: p
    res = burst(client, ["/api/trending"] * 5)
    assert [r.status_code for r in res] == [200] * 5
    assert p.batch_calls == 1  # was 5 sequential downloads


# ---------- eviction
def test_search_flood_cannot_evict_history(client, fake):
    assert client.get("/api/forecast/AAPL?horizon=5").status_code == 200
    calls = fake.calls
    for i in range(main.search_cache._max * 3):
        client.get(f"/api/search?q=term{i}")
    assert len(main.search_cache) <= main.search_cache._max
    assert len(main.cache) < 20
    assert client.get("/api/forecast/AAPL?horizon=5").status_code == 200
    assert fake.calls == calls  # still served from the history cache, no new provider call


def test_lru_evicts_least_recently_used_not_oldest_inserted():
    c = TTLCache(max_items=3)
    for k in "abc":
        c.fetch(k, 60, lambda k=k: k)
    c.fetch("a", 60, lambda: "x")  # touch a: now b is least recently used
    c.fetch("d", 60, lambda: "d")
    assert set(k for k in c._data) == {"a", "c", "d"} and len(c) == 3


def test_stale_if_error_entries_survive_insert_pressure_and_expired_ones_go_first():
    c = TTLCache(max_items=4)
    c.fetch("keep1", 1, lambda: 1, stale_max_age=3600)
    c.fetch("keep2", 1, lambda: 2, stale_max_age=3600)
    c.fetch("gone", 1, lambda: 3, stale_max_age=0)
    c.fetch("fresh", 600, lambda: 4)
    for k in ("keep1", "keep2", "gone"):  # all expired; keep* still inside their stale window
        e, fa, v = c._data[k]
        c._data[k] = (0, fa, v)
    c.fetch("new", 600, lambda: 5)  # at capacity: the expired entry with no stale window must be the one dropped
    assert "gone" not in c._data and {"keep1", "keep2", "fresh", "new"} <= set(c._data)
    # and a stale entry is still usable as fallback after the insert
    r = c.fetch("keep1", 60, lambda: (_ for _ in ()).throw(DataUnavailable("down")), stale_max_age=3600)
    assert r.stale and r.value == 1


def test_hard_cap_holds_even_when_everything_is_stale_protected():
    c = TTLCache(max_items=5)
    for i in range(50):
        c.fetch(i, 600, lambda i=i: i, stale_max_age=3600)
    assert len(c) == 5 and len(c._keep) == 5


def test_clear_prefix_and_clear_keep_side_tables_consistent():
    c = TTLCache()
    c.fetch(("plog", 1), 60, lambda: 1, stale_max_age=5)
    c.fetch(("x", 1), 60, lambda: 1, stale_max_age=5)
    c.clear_prefix("plog")
    assert set(c._keep) == set(c._data) == {("x", 1)}
    c.clear()
    assert not c._data and not c._keep
