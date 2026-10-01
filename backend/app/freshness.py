"""Describe how fresh a response's data is, in a provider-independent way."""
from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import numpy as np

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
    lag = int(np.busday_count(last_bar, today_ny()))
    stale = served_from_stale_cache or lag >= STALE_AFTER_BUSINESS_DAYS
    out = describe_fetch(fetched_at, served_from_stale_cache, last_bar.isoformat())
    out["is_delayed"] = lag >= 2
    out["stale"] = stale
    if stale and not served_from_stale_cache:
        out["warnings"] = [_stale_warning(f"the latest price bar is {lag} business days old")]
    return out
