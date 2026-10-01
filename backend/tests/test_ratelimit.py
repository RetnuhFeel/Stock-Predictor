"""Rate limiter: trustworthy client key, bounded memory."""
import pytest

from app import config, main
from app.ratelimit import MAX_KEY_LEN, SWEEP_BATCH, RateLimiter, client_key


# ---------- key derivation
def test_spoofed_leftmost_xff_cannot_pick_the_bucket():
    # client sent "1.1.1.1" itself; the trusted proxy appended the real peer it saw (9.9.9.9)
    assert client_key("10.0.0.1", "1.1.1.1, 9.9.9.9", True, 1) == "9.9.9.9"
    # rotating the forged part does not change the key
    keys = {client_key("10.0.0.1", f"{i}.2.3.4, 9.9.9.9", True, 1) for i in range(50)}
    assert keys == {"9.9.9.9"}


def test_two_hops_takes_second_from_right():
    assert client_key("10.0.0.1", "6.6.6.6, 9.9.9.9, 172.70.1.1", True, 2) == "9.9.9.9"
    assert client_key("10.0.0.1", "9.9.9.9, 172.70.1.1", True, 2) == "9.9.9.9"


def test_fewer_entries_than_hops_falls_back_to_peer():
    assert client_key("10.0.0.1", "9.9.9.9", True, 2) == "10.0.0.1"
    assert client_key("10.0.0.1", None, True, 1) == "10.0.0.1"


def test_without_trust_proxy_header_is_ignored_and_proxy_is_shared_bucket():
    assert client_key("10.0.0.1", "1.1.1.1, 9.9.9.9", False, 1) == "10.0.0.1"
    # everyone behind the proxy shares the proxy's peer address, which is why TRUST_PROXY exists
    assert client_key("10.0.0.1", "3.3.3.3", False, 1) == client_key("10.0.0.1", "4.4.4.4", False, 1)


def test_invalid_or_hostile_entry_falls_back_to_peer():
    for bad in ("not-an-ip", "", "9.9.9.9:80", "x" * 5000, "<script>", "999.1.1.1"):
        assert client_key("10.0.0.1", f"1.1.1.1, {bad}", True, 1) == "10.0.0.1"


def test_ipv6_grouped_by_slash_64_and_v4_mapped_normalised():
    a = client_key("p", "2001:db8:1:2:aaaa::1", True, 1)
    b = client_key("p", "2001:db8:1:2:bbbb:cccc::9", True, 1)
    c = client_key("p", "2001:db8:1:3::1", True, 1)
    assert a == b and a != c and a.endswith("/64")
    assert client_key("p", "::ffff:9.9.9.9", True, 1) == "9.9.9.9"


def test_key_length_is_capped():
    assert len(client_key("y" * 500, None, False, 1)) <= MAX_KEY_LEN
    lim = RateLimiter(100)
    lim.hit("api", "z" * 10_000, 5, 0.0)
    assert all(len(k) <= len("api:") + MAX_KEY_LEN for k in lim._hits)


# ---------- limiter behaviour and memory bound
def test_limit_and_window_slide():
    lim = RateLimiter(10)
    assert [lim.hit("api", "a", 3, t) for t in (0, 1, 2)] == [None, None, None]
    retry = lim.hit("api", "a", 3, 3)
    assert retry is not None and 1 <= retry <= 60
    assert lim.hit("api", "b", 3, 3) is None  # other client unaffected
    assert lim.hit("api", "a", 3, 61) is None  # window slid
    assert lim.hit("heavy", "a", 1, 0) is None and lim.hit("heavy", "a", 1, 1) is not None  # separate buckets


def test_key_table_is_hard_capped_and_overflow_still_limits():
    cap = 50
    lim = RateLimiter(cap)
    for i in range(10_000):  # many distinct clients inside one window
        lim.hit("api", f"10.{i // 256}.{i % 256}.1", 5, 1.0)
    assert len(lim) <= cap + 1  # + the shared overflow key
    # clients that arrive when the table is full share ONE bucket, so a flood cannot get unlimited requests
    results = [lim.hit("api", f"192.168.{i}.1", 5, 2.0) for i in range(100)]
    assert sum(r is None for r in results) <= 5
    assert any(r is not None for r in results)
    # a client already in the table keeps its own bucket
    assert lim.hit("api", "10.0.0.1", 5, 3.0) is None


def test_expired_keys_are_purged_by_last_seen_in_bounded_steps():
    lim = RateLimiter(100_000)
    for i in range(1000):
        lim.hit("api", f"k{i}", 5, 0.0)
    assert len(lim) == 1000
    before = len(lim)
    lim.hit("api", "fresh", 5, 1000.0)  # everything else is long expired
    removed = before + 1 - len(lim)
    assert 0 < removed <= SWEEP_BATCH  # one call does a bounded amount of work, not a full scan
    for _ in range(40):
        lim.hit("api", "fresh", 5, 1000.0)
    assert len(lim) == 1  # repeated calls drain the rest


def test_a_busy_old_key_is_not_purged_while_active():
    lim = RateLimiter(100)
    lim.hit("api", "busy", 100, 0.0)
    for i in range(1, 200):
        lim.hit("api", "busy", 100, float(i % 50))  # last seen recently relative to now below
    lim.hit("api", "busy", 100, 59.0)
    assert "api:busy" in lim._hits


# ---------- wired into the app
def test_app_limits_by_trusted_hop_not_by_forged_header(client, monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_PER_MIN", 3)
    monkeypatch.setattr(config, "TRUST_PROXY", True)
    monkeypatch.setattr(config, "TRUSTED_PROXY_HOPS", 1)
    statuses = [client.get("/api/search?q=a", headers={"X-Forwarded-For": f"{i}.1.1.1, 9.9.9.9"}).status_code
                for i in range(6)]
    assert statuses[:3] == [200, 200, 200] and set(statuses[3:]) == {429}
    # a different real client (different right-most hop) has its own budget
    assert client.get("/api/search?q=a", headers={"X-Forwarded-For": "1.1.1.1, 8.8.8.8"}).status_code == 200


def test_app_shared_bucket_without_trust_proxy(client, monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_PER_MIN", 2)
    monkeypatch.setattr(config, "TRUST_PROXY", False)
    codes = [client.get("/api/search?q=a", headers={"X-Forwarded-For": f"{i}.1.1.1"}).status_code for i in range(4)]
    assert codes == [200, 200, 429, 429]


def test_config_defaults():
    assert config.TRUSTED_PROXY_HOPS >= 1 and config.RATE_LIMIT_MAX_KEYS >= 1000
    assert isinstance(main.limiter, RateLimiter) and main.limiter.max_keys == config.RATE_LIMIT_MAX_KEYS


@pytest.mark.parametrize("n", [0])
def test_hits_with_zero_limit_dont_crash(n):
    assert RateLimiter(5).hit("api", "a", n, 0.0) is not None
