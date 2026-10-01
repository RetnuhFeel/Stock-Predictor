import json
import logging

import pytest

from app import config, main
from app.observability import JsonFormatter, new_request_id, request_id_var, scrub, scrub_route


@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_TOKEN", "s3cret-token")
    return {"Authorization": "Bearer s3cret-token"}


def test_request_id_header_generated_and_echoed(client):
    r = client.get("/health")
    assert len(r.headers["x-request-id"]) >= 8
    r = client.get("/api/quote/AAPL", headers={"X-Request-ID": "abc-12345678"})
    assert r.headers["x-request-id"] == "abc-12345678"
    r = client.get("/health", headers={"X-Request-ID": "bad id\r\n<script>"})
    assert r.headers["x-request-id"] != "bad id\r\n<script>"
    assert new_request_id("short") != "short"


def test_stats_disabled_by_default(client):
    assert client.get("/api/_stats").status_code == 404


def test_stats_requires_token(client, admin):
    assert client.get("/api/_stats").status_code == 401
    assert client.get("/api/_stats", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/_stats", headers=admin).status_code == 200


def test_stats_aggregates_without_pii(client, admin):
    client.get("/api/quote/AAPL?x=secret-query")
    client.get("/api/quote/MSFT")
    client.get("/api/quote/FAIL")
    client.get("/api/quote/A$B")
    snap = client.get("/api/_stats", headers=admin).json()
    assert snap["by_route"]["GET /api/quote/{symbol}"] == 4  # templates, not symbols
    assert snap["by_error_code"] == {"DATA_UNAVAILABLE": 1, "INVALID_SYMBOL": 1}
    assert snap["by_status"]["2xx"] == 2 and snap["by_status"]["4xx"] == 1 and snap["by_status"]["5xx"] == 1
    text = json.dumps(snap)
    for forbidden in ("AAPL", "MSFT", "secret-query", "testclient", "127.0.0.1"):
        assert forbidden not in text


def test_access_log_is_json_and_has_no_pii(client, caplog):
    logger = logging.getLogger("stock-api")
    logger.propagate = True
    with caplog.at_level(logging.INFO, logger="stock-api"):
        client.get("/api/quote/AAPL?token=abc", headers={"User-Agent": "UA-SECRET"})
    rec = next(r for r in caplog.records if r.getMessage() == "request")
    line = json.loads(JsonFormatter().format(rec))
    assert line["route"] == "/api/quote/{symbol}" and line["status"] == 200 and "request_id" in line
    blob = json.dumps(line)
    for forbidden in ("AAPL", "token=abc", "UA-SECRET", "testclient"):
        assert forbidden not in blob


def test_client_error_endpoint_off_by_default(client):
    assert client.post("/api/_client-error", json={"message": "x"}).status_code == 404


@pytest.fixture
def reports_on(monkeypatch):
    monkeypatch.setattr(config, "CLIENT_ERROR_LOGGING", True)


def test_client_error_logged_sanitised(client, reports_on, caplog, admin):
    logger = logging.getLogger("stock-api")
    logger.propagate = True
    payload = {"message": "Boom for bob@example.com at https://app.test/x?token=SECRET#frag",
               "stack": "Error\n at f (https://app.test/_next/a.js?v=1:1:1)", "route": "/?email=a@b.co",
               "cookie": "ignored", "extra": "ignored"}
    with caplog.at_level(logging.ERROR, logger="stock-api"):
        r = client.post("/api/_client-error", json=payload)
    assert r.status_code == 204
    rec = next(r for r in caplog.records if r.getMessage() == "client_error")
    ctx = rec.ctx
    blob = json.dumps(ctx)
    assert "bob@example.com" not in blob and "SECRET" not in blob and "?v=1" not in blob and "a@b.co" not in blob
    assert ctx["route"] == "/" and set(ctx) == {"route", "message", "stack", "fingerprint"}
    assert client.get("/api/_stats", headers=admin).json()["client_errors_reported"] == 1


def test_client_error_size_and_shape_limits(client, reports_on):
    big = client.post("/api/_client-error", content=b"{" + b" " * 5000 + b"}")
    assert big.status_code == 413 and big.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert client.post("/api/_client-error", content=b"not json").status_code == 422
    assert client.post("/api/_client-error", content=b"[1,2]").status_code == 422


def test_client_error_rate_limited(client, reports_on, monkeypatch):
    monkeypatch.setattr(config, "CLIENT_ERROR_RATE_PER_MIN", 2)
    codes = [client.post("/api/_client-error", json={"message": "m"}).status_code for _ in range(4)]
    assert codes == [204, 204, 429, 429]


def test_cors_headers_on_rate_limited_and_post(client, monkeypatch, reports_on):
    origin = config.CORS_ORIGINS[0]
    pre = client.options("/api/_client-error", headers={"Origin": origin, "Access-Control-Request-Method": "POST",
                                                        "Access-Control-Request-Headers": "content-type"})
    assert pre.status_code == 200 and pre.headers["access-control-allow-origin"] == origin
    monkeypatch.setattr(config, "RATE_LIMIT_PER_MIN", 1)
    client.get("/api/quote/AAPL")
    limited = client.get("/api/quote/AAPL", headers={"Origin": origin})
    assert limited.status_code == 429 and limited.headers["access-control-allow-origin"] == origin
    assert main  # keep import used


def test_unhandled_exception_is_structured_500(client, fake):
    from fastapi.testclient import TestClient

    fake.fail_with = RuntimeError("kaboom with /secret/path")
    r = TestClient(main.app, raise_server_exceptions=False).get("/api/quote/AAPL")
    assert r.status_code == 500 and r.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "kaboom" not in r.text and r.headers["x-request-id"]


def test_scrub_helpers():
    assert scrub("see https://a.b/c?d=1#e and x@y.com", 100) == "see https://a.b/c and [email]"
    assert scrub("a" * 500, 10) == "a" * 10
    assert scrub_route("/path?x=1") == "/path" and scrub_route("javascript:x") == "/"
    assert request_id_var.get() == "-"
