from app import config


def test_quote(client):
    r = client.get("/api/quote/aapl")
    assert r.status_code == 200
    body = r.json()
    assert body["symbol"] == "AAPL" and body["price"] > 0


def test_history_and_range_validation(client):
    r = client.get("/api/history/AAPL?range=3mo")
    assert r.status_code == 200 and len(r.json()["points"]) == 63
    bad = client.get("/api/history/AAPL?range=99y")
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "INVALID_RANGE"


def test_forecast_has_disclaimer_and_backtest(client):
    r = client.get("/api/forecast/AAPL?horizon=7")
    assert r.status_code == 200
    body = r.json()
    assert body["disclaimer"] and "not financial advice" in body["disclaimer"].lower()
    assert {"model", "naive_baseline", "skill_vs_baseline"} <= set(body["backtest"])


def test_forecast_horizon_bounds(client):
    r = client.get("/api/forecast/AAPL?horizon=0")
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_REQUEST"
    assert client.get(f"/api/forecast/AAPL?horizon={config.MAX_HORIZON + 1}").status_code == 422


def test_invalid_symbol(client):
    for bad in ["A$B", "THIS-IS-WAY-TOO-LONG-SYMBOL", "%20"]:
        r = client.get(f"/api/quote/{bad}")
        assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_SYMBOL"


def test_upstream_failure_is_clear_error(client):
    r = client.get("/api/quote/FAIL")
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "DATA_UNAVAILABLE" and r.json()["error"]["message"]


def test_caching(client, fake):
    client.get("/api/history/AAPL?range=1y")
    client.get("/api/history/AAPL?range=1y")
    assert fake.calls == 1


def test_rate_limit(client, monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_PER_MIN", 3)
    codes = [client.get("/api/quote/AAPL").status_code for _ in range(5)]
    assert codes[:3] == [200] * 3 and codes[3:] == [429, 429]
    r = client.get("/api/quote/AAPL")
    assert r.json()["error"]["code"] == "RATE_LIMITED" and r.headers["retry-after"]


def test_cors_header(client):
    r = client.get("/health", headers={"Origin": config.CORS_ORIGINS[0]})
    assert r.headers.get("access-control-allow-origin") == config.CORS_ORIGINS[0]


def test_search(client):
    assert client.get("/api/search?q=app").json()["results"][0]["symbol"] == "AAPL"
