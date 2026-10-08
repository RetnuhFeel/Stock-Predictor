"""Describe how fresh a response's data is, in a provider-independent way."""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .marketcal import is_trading_day, previous_trading_day, trading_days_between

STALE_AFTER_BUSINESS_DAYS = 5  # a full week with no new bar suggests a problem (or a long closure)


def today_ny() -> date:
    return datetime.now(ZoneInfo("America/New_York")).date()


def _stale_warning(message: str) -> dict:
    return {"code": "STALE_DATA", "message": f"Data may be outdated: {message}."}


def describe_fetch(fetched_at: float, served_from_stale_cache: bool, data_as_of: str | None = None) -> dict:
    """Freshness fields for data that has no daily-bar date (e.g. news)."""
    warnings = []
    if served_from_stale_cache:
        warnings.append(_stale_warning("the data provider is currently failing, so the last good copy is shown"))
    return {
        "data_as_of": data_as_of,
        "fetched_at": datetime.fromtimestamp(fetched_at, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "is_delayed": False,
        "stale": served_from_stale_cache,
        "warnings": warnings,
    }


def describe(last_bar: date, fetched_at: float, served_from_stale_cache: bool) -> dict:
    """Freshness fields to merge into a response.

    data_as_of   date of the latest daily bar
    fetched_at   when we obtained it from the provider (UTC, ISO 8601)
    is_delayed   latest bar is 2+ business days old (normal data lags by at most one)
    stale        old data: served from an expired cache because the provider failed,
                 or no new bar for a full business week
    warnings     machine-readable notes, e.g. {"code": "STALE_DATA", ...}
    """
    lag = trading_days_between(last_bar, today_ny())
    stale = served_from_stale_cache or lag >= STALE_AFTER_BUSINESS_DAYS
    out = describe_fetch(fetched_at, served_from_stale_cache, last_bar.isoformat())
    out["is_delayed"] = lag >= 2
    out["stale"] = stale
    if stale and not served_from_stale_cache:
        out["warnings"] = [_stale_warning(f"the latest price bar is {lag} business days old")]
    return out


# --- market clock (used to refuse partial intraday bars) ---------------------------------------------------
MARKET_OPEN_NY = time(9, 30)
MARKET_CLOSE_NY = time(16, 0)
CLOSE_BUFFER = timedelta(minutes=10)  # providers publish the final daily bar a little after the bell


def now_ny() -> datetime:
    return datetime.now(ZoneInfo("America/New_York"))


def bar_is_final(bar_date: date, now: datetime | None = None) -> bool:
    """False if ``bar_date`` is today (New York) and the regular session has not closed yet, because providers
    return a partial, still-changing bar for the current day while the market is open. Conservative on early-close
    days (waits until 16:10 ET). Future dates are never final."""
    now = now or now_ny()
    if bar_date < now.date():
        return True
    if bar_date > now.date():
        return False
    if now.weekday() >= 5:  # a bar dated on a weekend cannot be a live session
        return True
    return now >= datetime.combine(now.date(), MARKET_CLOSE_NY, tzinfo=now.tzinfo) + CLOSE_BUFFER


def _after_close(now: datetime) -> bool:
    return now >= datetime.combine(now.date(), MARKET_CLOSE_NY, tzinfo=now.tzinfo) + CLOSE_BUFFER


def expected_base_session(now: datetime | None = None) -> date:
    """The session whose close the prediction log should be using right now (New York time).

    On a trading day after the close (+ ``CLOSE_BUFFER``) that is today; at any other time (before the close, the
    morning before the open, weekends, holidays) it is the previous trading day. Early-close days are treated like
    normal days (conservative: today's bar only counts after 16:10)."""
    now = now or now_ny()
    if is_trading_day(now.date()) and _after_close(now):
        return now.date()
    return previous_trading_day(now.date())


def session_in_progress(now: datetime | None = None) -> bool:
    """True from the open until the close (+ buffer) on a trading day. Then the outcome window of the previous
    session's close has already started, so logging that close as a new prediction would use hindsight."""
    now = now or now_ny()
    if not is_trading_day(now.date()):
        return False
    return datetime.combine(now.date(), MARKET_OPEN_NY, tzinfo=now.tzinfo) <= now and not _after_close(now)
