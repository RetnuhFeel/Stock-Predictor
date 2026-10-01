import httpx
import pytest

from app.errors import DataUnavailable, RateLimited, UpstreamTimeout
from app.providers import create_provider
from app.providers.twelvedata import TwelveDataProvider
from app.providers.yahoo import YahooProvider, _translate

TS_OK = {"meta": {"symbol": "AAPL"}, "status": "ok", "values": [
    {"datetime": "2026-09-30", "open": "10.0", "high": "11", "low": "9", "close": "10.5", "volume": "1000"},
    {"datetime": "2026-09-29", "open": "9.0", "high": "10", "low": "8", "close": "9.5", "volume": "900"},
]}


def td(handler) -> TwelveDataProvider:
    client = httpx.Client(base_url="https://api.twelvedata.com", transport=httpx.MockTransport(handler))
    return TwelveDataProvider("secret-key", client=client)


def test_factory_selection(monkeypatch):
    assert isinstance(create_provider("yfinance"), YahooProvider)
    monkeypatch.setenv("TWELVEDATA_API_KEY", "k")
    assert isinstance(create_provider("TwelveData"), TwelveDataProvider)
    with pytest.raises(ValueError, match="Unknown DATA_PROVIDER"):
        create_provider("nope")
    monkeypatch.delenv("TWELVEDATA_API_KEY")
    with pytest.raises(ValueError, match="TWELVEDATA_API_KEY"):
        create_provider("twelvedata")


def test_twelvedata_history_parsing_and_auth_header():
    seen = {}

    def handler(req: httpx.Request):
        seen["auth"], seen["url"] = req.headers.get("authorization"), str(req.url)
        return httpx.Response(200, json=TS_OK)

    df = td(handler).history("BRK-B", "1mo")
    assert seen["auth"] == "apikey secret-key" and "secret-key" not in seen["url"]  # key never in the URL
    assert "symbol=BRK.B" in seen["url"] and "interval=1day" in seen["url"]
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert df.index.is_monotonic_increasing and df["Close"].tolist() == [9.5, 10.5]


def test_twelvedata_quote_derived_from_bars():
    q = td(lambda r: httpx.Response(200, json=TS_OK)).quote("AAPL")
    assert q["price"] == 10.5 and q["previous_close"] == 9.5 and str(q["as_of"]) == "2026-09-30"


@pytest.mark.parametrize("response,exc", [
    (httpx.Response(200, json={"code": 429, "message": "limit", "status": "error"}), RateLimited),
    (httpx.Response(429, json={"code": 429, "message": "limit", "status": "error"},
                    headers={"Retry-After": "9"}), RateLimited),
    (httpx.Response(200, json={"code": 400, "message": "symbol not found", "status": "error"}), DataUnavailable),
    (httpx.Response(200, json={"code": 401, "message": "bad key", "status": "error"}), DataUnavailable),
    (httpx.Response(500, text="boom"), DataUnavailable),
    (httpx.Response(200, json={"status": "ok", "values": []}), DataUnavailable),
])
def test_twelvedata_errors_are_typed(response, exc, monkeypatch):
    monkeypatch.setattr("app.providers.base.config.UPSTREAM_RETRIES", 0)
    with pytest.raises(exc):
        td(lambda r: response).history("AAPL", "1mo")


def test_twelvedata_credential_errors_do_not_leak_details():
    with pytest.raises(DataUnavailable) as e:
        body = {"code": 401, "message": "bad key secret-key", "status": "error"}
        td(lambda r: httpx.Response(200, json=body)).history("A", "1mo")
    assert "secret-key" not in e.value.message and e.value.retryable is False


def test_twelvedata_timeout_maps_and_retries(monkeypatch):
    monkeypatch.setattr("app.providers.base.time.sleep", lambda s: None)
    calls = []

    def handler(req):
        calls.append(1)
        raise httpx.ReadTimeout("slow", request=req)

    with pytest.raises(UpstreamTimeout):
        td(handler).history("AAPL", "1mo")
    assert len(calls) == 1 + 2  # default UPSTREAM_RETRIES = 2


def test_twelvedata_search():
    body = {"data": [{"symbol": "aapl", "instrument_name": "Apple Inc", "exchange": "NASDAQ"}], "status": "ok"}
    assert td(lambda r: httpx.Response(200, json=body)).search("apple") == [
        {"symbol": "AAPL", "name": "Apple Inc", "exchange": "NASDAQ"}]


def test_yahoo_exception_translation():
    class YFRateLimitError(Exception): ...
    class ReadTimeout(Exception): ...
    assert isinstance(_translate(YFRateLimitError("x"), "A"), RateLimited)
    assert isinstance(_translate(Exception("Too Many Requests. Rate limited"), "A"), RateLimited)
    assert isinstance(_translate(ReadTimeout("x"), "A"), UpstreamTimeout)
    assert isinstance(_translate(RuntimeError("weird"), "A"), DataUnavailable)


def test_yahoo_empty_frame_is_data_unavailable(monkeypatch):
    import pandas as pd
    p = YahooProvider()
    monkeypatch.setattr(p, "_download", lambda s, per: pd.DataFrame())
    with pytest.raises(DataUnavailable):
        p.history("ZZZZ", "1mo")
