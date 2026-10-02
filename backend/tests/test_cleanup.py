"""Second cleanup pass: constant prices, NaN volume, symbol parsing, hidden routes, token length, compare deadline,
market calendar."""
import json as _json
import shutil as _shutil
import subprocess as _subprocess
import threading
import time
from datetime import date
from pathlib import Path as _Path

import numpy as np
import pandas as pd
import pytest

from app import config, main
from app.errors import InsufficientData
from app.forecast import forecast, ratio
from app.marketcal import holidays_for, is_trading_day, trading_days_after, trading_days_between
from app.models import compare_models
from app.spikes import spike_forecast
from app.symbols import normalize_symbol
from app.volatility import forecast_volatility

from .conftest import FakeProvider, synthetic_prices


# ---------- constant / degenerate prices: a clear 422, never a ZeroDivision 500
@pytest.fixture(scope="module")
def flat():
    return pd.Series(100.0, index=synthetic_prices(900).index)


@pytest.mark.parametrize("fn", [lambda s: forecast(s, 5), lambda s: forecast(s, 256), lambda s: compare_models(s, 5),
                                lambda s: forecast_volatility(s, 5)])
def test_constant_price_is_insufficient_data_not_a_crash(flat, fn):
    with pytest.raises(InsufficientData, match="constant"):
        fn(flat)


def test_spike_forecast_on_constant_price(flat):
    with pytest.raises(InsufficientData):
        spike_forecast(flat, 5, {"last_close": 100, "path": [], "predicted_return": 0})


def test_flat_stock_endpoints_return_422(client, fake):
    flat = pd.Series(100.0, index=synthetic_prices(900).index)
    fake.history = lambda symbol, period: pd.DataFrame(
        {"Open": flat, "High": flat, "Low": flat, "Close": flat, "Volume": 0.0}).tail(900)
    for ep in ("forecast", "compare-models", "volatility", "spikes"):
        r = client.get(f"/api/{ep}/FLAT?horizon=5")
        assert r.status_code == 422 and r.json()["error"]["code"] == "INSUFFICIENT_DATA", (ep, r.text[:120])


def test_ratio_never_divides_by_zero():
    assert ratio(1.0, 0.0) == 1.0 and ratio(3.0, 2.0) == 1.5


def test_quote_ignores_zero_bars(client, fake):
    df = synthetic_prices(10)
    df.iloc[-2, df.columns.get_loc("Close")] = 0.0
    fake.history = lambda symbol, period: df
    r = client.get("/api/quote/AAPL")
    assert r.status_code == 200 and np.isfinite(r.json()["change_percent"])


# ---------- NaN volume
def test_history_with_nan_volume_is_not_a_500(client, fake):
    df = synthetic_prices(60)
    df["Volume"] = np.nan
    df.iloc[3, df.columns.get_loc("Volume")] = np.inf
    fake.history = lambda symbol, period: df
    r = client.get("/api/history/AAPL?range=1mo")
    assert r.status_code == 200 and all(p["volume"] == 0 for p in r.json()["points"])


# ---------- symbols
@pytest.mark.parametrize("bad", ["AAPL\nX", "A B", "", "-AAPL", "A" * 16, "AAPL;", "é", "AAPL\x00", "A/../B"])
def test_symbol_rejects_junk(bad):
    from app.errors import InvalidSymbol
    with pytest.raises(InvalidSymbol):
        normalize_symbol(bad)


def test_symbol_regex_is_matched_in_full():
    from app.symbols import SYMBOL_RE
    assert SYMBOL_RE.fullmatch("AAPL") and not SYMBOL_RE.fullmatch("AAPL\n")


def test_symbol_accepts_real_forms():
    assert normalize_symbol(" brk-b ") == "BRK-B" and normalize_symbol("^gspc") == "^GSPC"
    assert normalize_symbol("eurusd=x") == "EURUSD=X" and normalize_symbol("BF.B") == "BF.B"


# ---------- internal routes are not advertised
def test_openapi_hides_underscore_routes(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert not [p for p in paths if "/_" in p], paths.keys()
    assert "/api/forecast/{symbol}" in paths
    assert client.get("/api/_stats").status_code == 404  # still routed (disabled unless configured)


# ---------- token minimum length
def test_short_tokens_are_ignored_and_warned_without_the_value(monkeypatch):
    import importlib

    monkeypatch.setenv("ADMIN_TOKEN", "short")
    monkeypatch.setenv("LOG_TASK_TOKEN", "x" * 40)
    try:
        importlib.reload(config)
        assert config.ADMIN_TOKEN == "" and config.LOG_TASK_TOKEN == "x" * 40
        assert len(config.TOKEN_WARNINGS) == 1 and config.TOKEN_WARNINGS[0].startswith("ADMIN_TOKEN is shorter")
        assert "short" not in config.TOKEN_WARNINGS[0].replace("shorter", "")  # the value itself is never echoed
    finally:
        monkeypatch.undo()
        importlib.reload(config)


# ---------- /api/compare deadline
class SlowOne(FakeProvider):
    def history(self, symbol, period):
        if symbol == "SLOW":
            time.sleep(1.5)
        return super().history(symbol, period)


def test_compare_returns_partial_result_at_the_deadline(client, monkeypatch):
    monkeypatch.setattr(config, "COMPARE_DEADLINE_S", 0.3)
    main.app.dependency_overrides[main.get_provider] = lambda: SlowOne()
    t0 = time.perf_counter()
    r = client.get("/api/compare?symbols=AAPL,SLOW,MSFT")
    assert time.perf_counter() - t0 < 1.2  # did not wait for the slow symbol
    body = r.json()
    assert r.status_code == 200 and [s["symbol"] for s in body["series"]] == ["AAPL", "MSFT"]
    assert body["failed"][0]["symbol"] == "SLOW" and body["failed"][0]["code"] == "UPSTREAM_TIMEOUT"


def test_compare_all_slow_is_a_structured_timeout(client, monkeypatch):
    monkeypatch.setattr(config, "COMPARE_DEADLINE_S", 0.2)

    class AllSlow(FakeProvider):
        def history(self, symbol, period):
            time.sleep(1.0)
            return super().history(symbol, period)
    main.app.dependency_overrides[main.get_provider] = lambda: AllSlow()
    r = client.get("/api/compare?symbols=AAPL,MSFT")
    assert r.status_code == 504 and r.json()["error"]["code"] == "UPSTREAM_TIMEOUT"


def test_compare_symbols_are_fetched_in_parallel(client):
    seen, lock = [], threading.Lock()

    class P(FakeProvider):
        def history(self, symbol, period):
            with lock:
                seen.append(threading.current_thread().name)
            time.sleep(0.3)
            return super().history(symbol, period)
    main.app.dependency_overrides[main.get_provider] = lambda: P()
    t0 = time.perf_counter()
    assert client.get("/api/compare?symbols=AAPL,MSFT,NVDA,AMD").status_code == 200
    assert time.perf_counter() - t0 < 0.9  # 4 x 0.3 s sequentially would be 1.2 s
    assert len(set(seen)) > 1


# ---------- market calendar
def test_holidays_2026_and_observed_rules():
    h = {str(d) for d in holidays_for(2026)}
    assert h == {"2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03",
                 "2026-09-07", "2026-11-26", "2026-12-25"}  # July 4 is a Saturday -> observed Friday July 3
    assert date(2027, 12, 31) not in holidays_for(2027) and date(2028, 1, 1) not in holidays_for(2027)
    assert date(2022, 12, 26) in holidays_for(2022)  # Christmas on Sunday -> Monday
    assert date(2021, 6, 18) not in holidays_for(2021)  # Juneteenth only from 2022
    assert date(2025, 4, 18) in holidays_for(2025) and date(2024, 3, 29) in holidays_for(2024)  # Good Friday


def test_trading_days_skip_holidays():
    assert not is_trading_day(date(2026, 11, 26)) and is_trading_day(date(2026, 11, 27))
    nxt = trading_days_after(pd.Timestamp("2026-11-24"), 3)
    assert [d.strftime("%Y-%m-%d") for d in nxt] == ["2026-11-25", "2026-11-27", "2026-11-30"]  # Thanksgiving skipped
    assert trading_days_between(date(2026, 11, 25), date(2026, 11, 27)) == 1


def test_forecast_path_dates_skip_holidays_and_weekends():
    close = synthetic_prices(900, end=pd.Timestamp("2026-11-24"))["Close"]
    path = forecast(close, 5)["path"]
    got = [p["date"] for p in path]
    assert got == ["2026-11-25", "2026-11-27", "2026-11-30", "2026-12-01", "2026-12-02"]


def test_freshness_does_not_count_a_holiday_as_a_missing_bar(monkeypatch):
    from app import freshness
    monkeypatch.setattr(freshness, "today_ny", lambda: date(2026, 11, 27))  # Friday after Thanksgiving
    out = freshness.describe(date(2026, 11, 25), time.time(), False)  # Wednesday's bar is the latest possible
    assert out["is_delayed"] is False


# ---------- repo files: the prediction-log workflow check, workflow/Blueprint syntax ----------
_ROOT = _Path(__file__).resolve().parents[2]
_CHECK = _ROOT / ".github" / "scripts" / "check-prediction-log-result.sh"


def _run_check(tmp_path, payload):
    f = tmp_path / "out.json"
    f.write_text(payload if isinstance(payload, str) else _json.dumps(payload))
    return _subprocess.run(["bash", str(_CHECK), str(f)], capture_output=True, text=True).returncode


@pytest.mark.skipif(_shutil.which("jq") is None or _shutil.which("bash") is None, reason="needs bash and jq")
@pytest.mark.parametrize("payload,expected", [
    ({"logged": ["SPY"], "skipped": []}, 0),
    ({"logged": [], "skipped": [{"symbol": "SPY", "reason": "ALREADY_LOGGED"}]}, 0),
    ({"logged": ["SPY"], "skipped": [{"symbol": "AAPL", "reason": "PARTIAL_BAR"}]}, 0),  # warning only
    ({"logged": [], "skipped": [{"symbol": "SPY", "reason": "DATA_UNAVAILABLE"}]}, 1),
    ({"logged": [], "skipped": [{"symbol": "SPY", "reason": "STALE_DATA"},
                                {"symbol": "A", "reason": "ALREADY_LOGGED"}]}, 0),
    ({"logged": [], "skipped": []}, 1),
    ("<html>bad gateway</html>", 1),
    ({"unexpected": True}, 1),
])
def test_prediction_log_workflow_check(tmp_path, payload, expected):
    assert _run_check(tmp_path, payload) == expected


def test_workflows_and_blueprint_are_valid_yaml_and_safe():
    yaml = pytest.importorskip("yaml")
    for p in (_ROOT / ".github" / "workflows").glob("*.yml"):
        assert isinstance(yaml.safe_load(p.read_text()), dict), p.name
    bp = yaml.safe_load((_ROOT / "render.yaml").read_text())
    names = {s["name"] for s in bp["services"]}
    assert names == {"stock-predictor-api", "stock-predictor-web"}
    api = next(s for s in bp["services"] if s["name"] == "stock-predictor-api")
    env = {e["key"]: e for e in api["envVars"]}
    assert env["TRUST_PROXY"]["value"] == "true" and env["TRUSTED_PROXY_HOPS"]["value"] == "1"
    for secret in ("DATABASE_URL", "LOG_TASK_TOKEN", "ADMIN_TOKEN"):
        assert env[secret].get("sync") is False and "value" not in env[secret]  # secrets are never in the file
