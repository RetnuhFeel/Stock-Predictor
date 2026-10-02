"""Public model report card endpoint."""
from app import config, main
from app.errors import DataUnavailable


def test_report_shape_and_conventions(client, monkeypatch):
    monkeypatch.setattr(config, "REPORT_SYMBOLS", ["SPY", "AAPL"])
    r = client.get("/api/model-report")
    body = r.json()
    assert r.status_code == 200 and body["horizon_days"] == 5
    assert [x["symbol"] for x in body["rows"]] == ["SPY", "AAPL"] and body["failed"] == []
    row = body["rows"][0]
    assert row["verdict"] in {"better", "inconclusive", "not_better"}
    assert len(row["skill_ci_90"]) == 2 and row["n_test_points"] > row["n_independent_tests"] >= 1
    assert body["summary"]["total"] == 2
    assert sum(body["summary"][k] for k in ("better", "inconclusive", "not_better")) == 2
    assert body["stale"] is False and body["fetched_at"].endswith("Z") and body["disclaimer"]
    assert "embargo" in body["method"]
    assert row["range_tested"] is True and 0.6 < row["range_coverage"] < 0.95 and row["range_independent_tests"] >= 8


def test_report_is_cached_and_bounded(client, fake, monkeypatch):
    monkeypatch.setattr(config, "REPORT_SYMBOLS", ["SPY", "AAPL"])
    client.get("/api/model-report")
    calls = fake.calls
    client.get("/api/model-report")
    assert fake.calls == calls  # second request served entirely from cache
    # the report shares the forecast cache: a normal forecast for a report symbol makes no new provider call
    client.get("/api/forecast/SPY?horizon=5")
    assert fake.calls == calls


def test_report_partial_failure_and_total_failure(client, fake, monkeypatch):
    monkeypatch.setattr(config, "REPORT_SYMBOLS", ["SPY", "FAIL", "AAPL"])
    body = client.get("/api/model-report").json()
    assert [x["symbol"] for x in body["rows"]] == ["SPY", "AAPL"]
    assert body["failed"][0]["symbol"] == "FAIL" and body["failed"][0]["code"] == "DATA_UNAVAILABLE"
    main.cache.clear()
    fake.fail_with = DataUnavailable("down", retryable=True)
    r = client.get("/api/model-report")
    assert r.status_code == 502 and r.json()["error"]["code"] == "DATA_UNAVAILABLE"


def test_report_served_stale_when_provider_fails(client, fake, monkeypatch):
    monkeypatch.setattr(config, "REPORT_SYMBOLS", ["SPY"])
    client.get("/api/model-report")
    main.cache._data = {k: (0, v[1], v[2]) for k, v in main.cache._data.items()}  # expire everything
    fake.fail_with = DataUnavailable("down", retryable=True)
    body = client.get("/api/model-report").json()
    assert body["stale"] is True and body["warnings"][0]["code"] == "STALE_DATA" and body["rows"]


def test_report_has_stricter_rate_limit(client, monkeypatch):
    monkeypatch.setattr(config, "REPORT_SYMBOLS", ["SPY"])
    monkeypatch.setattr(config, "MODEL_REPORT_RATE_PER_MIN", 2)
    codes = [client.get("/api/model-report").status_code for _ in range(4)]
    assert codes == [200, 200, 429, 429]
    assert client.get("/api/quote/AAPL").status_code == 200  # other routes unaffected


def test_report_symbols_are_fixed_and_not_user_input(client):
    assert config.REPORT_SYMBOLS == ["SPY", "AAPL", "MSFT", "NVDA", "TSLA"] and config.REPORT_HORIZON == 5
    # query params are ignored: no way to widen the workload
    r = client.get("/api/model-report?symbols=A,B,C,D,E,F,G&horizon=60")
    assert r.status_code == 200 and r.json()["horizon_days"] == 5
