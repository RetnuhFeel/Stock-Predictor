"""News, compare, horizon validation."""
from app import config, main
from app.errors import DataUnavailable
from app.providers.yahoo import parse_news


def test_news_ok_and_conventions(client):
    r = client.get("/api/news/aapl")
    body = r.json()
    assert r.status_code == 200 and body["symbol"] == "AAPL"
    assert set(body["items"][0]) == {"headline", "source", "url", "published_at"}  # link-out fields only
    assert "not a trading signal" in body["note"]
    assert body["stale"] is False and body["fetched_at"].endswith("Z") and body["warnings"] == []


def test_news_failure_and_stale(client, fake):
    client.get("/api/news/AAPL")
    main.cache._data = {k: (0, v[1], v[2]) for k, v in main.cache._data.items()}
    fake.fail_news = DataUnavailable("down", retryable=True)
    body = client.get("/api/news/AAPL").json()
    assert body["stale"] is True and body["warnings"][0]["code"] == "STALE_DATA" and body["items"]
    main.cache.clear()
    r = client.get("/api/news/AAPL")
    assert r.status_code == 502 and r.json()["error"]["code"] == "DATA_UNAVAILABLE"


def test_news_empty_for_provider_without_feed(client, fake):
    fake.news = lambda s: []
    assert client.get("/api/news/AAPL").json()["items"] == []


def test_news_invalid_symbol(client):
    assert client.get("/api/news/A$B").json()["error"]["code"] == "INVALID_SYMBOL"


def test_parse_news_formats():
    new = {"content": {"title": "T1", "pubDate": "2026-09-30T10:00:00Z", "provider": {"displayName": "IBD"},
                       "canonicalUrl": {"url": "https://x.com/1"}, "body": "<p>never returned</p>"}}
    old = {"title": "T2", "publisher": "Reuters", "link": "https://x.com/2", "providerPublishTime": 1790000000}
    bad = [{"content": {"title": "no url", "pubDate": "2026-01-01T00:00:00Z"}},
           {"content": {"title": "js", "pubDate": "x", "canonicalUrl": {"url": "javascript:alert(1)"}}}, "junk", None]
    items = parse_news([new, old, *bad])
    assert [i["headline"] for i in items] == ["T2", "T1"] or [i["headline"] for i in items] == ["T1", "T2"]
    assert all(i["url"].startswith("https://") for i in items) and len(items) == 2
    assert all("body" not in i for i in items)


def test_compare(client):
    r = client.get("/api/compare?symbols=aapl,msft,nvda&range=3mo")
    body = r.json()
    assert r.status_code == 200 and [s["symbol"] for s in body["series"]] == ["AAPL", "MSFT", "NVDA"]
    assert all(len(s["points"]) == len(body["dates"]) for s in body["series"])
    assert all(abs(s["points"][0]) < 1e-9 for s in body["series"])  # normalised: all start at 0%
    assert "stale" in body and body["failed"] == []


def test_compare_partial_failure_and_validation(client):
    body = client.get("/api/compare?symbols=AAPL,FAIL,MSFT").json()
    assert [s["symbol"] for s in body["series"]] == ["AAPL", "MSFT"] and body["failed"][0]["symbol"] == "FAIL"
    assert client.get("/api/compare?symbols=AAPL,FAIL").json()["error"]["code"] == "DATA_UNAVAILABLE"
    for bad in ["AAPL", "AAPL,AAPL", "A,B,C,D,E,F", "AAPL,A$B"]:
        r = client.get(f"/api/compare?symbols={bad}")
        assert r.status_code in (400, 422) and "code" in r.json()["error"], bad
    assert client.get("/api/compare?symbols=AAPL,MSFT&range=9y").json()["error"]["code"] == "INVALID_RANGE"


def test_forecast_per_horizon_backtest(client):
    outs = {h: client.get(f"/api/forecast/AAPL?horizon={h}").json() for h in (5, 20, 40)}
    for h, o in outs.items():
        bt = o["backtest"]
        assert o["horizon_days"] == h and bt["horizon_days"] == h
        assert bt["embargo_days"] >= h  # no label overlap between train and test
        assert f"{h}-day embargo" in bt["method"] and bt["n_independent_tests"] == bt["n_test_points"] // h
        assert len(o["path"]) == h and o["disclaimer"]
    # longer horizon -> fewer independent tests -> flagged small sample before shorter ones
    assert outs[40]["backtest"]["n_independent_tests"] < outs[5]["backtest"]["n_independent_tests"]
    # intervals widen with horizon (relative to price)
    w = {h: (o["interval_80"]["high"] - o["interval_80"]["low"]) / o["last_close"] for h, o in outs.items()}
    assert w[5] < w[20] < w[40]


def test_horizon_validation(client):
    for h in (0, config.MAX_HORIZON + 1, -3):
        assert client.get(f"/api/forecast/AAPL?horizon={h}").status_code == 422
    assert client.get("/api/forecast/AAPL?horizon=abc").json()["error"]["code"] == "INVALID_REQUEST"
    assert client.get(f"/api/forecast/AAPL?horizon={config.MAX_HORIZON}").status_code == 200
