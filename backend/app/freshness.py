"""Describe how fresh a response's data is, in a provider-independent way."""
from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import numpy as np

STALE_AFTER_BUSINESS_DAYS = 5  # a full week with no new bar suggests a problem (or a long closure)


def today_ny() -> date:
    return datetime.now(ZoneInfo("America/New_York")).date()


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
    warnings = []
    if stale:
        why = "the data provider is currently failing, so the last good copy is shown" if served_from_stale_cache \
            else f"the latest price bar is {lag} business days old"
        warnings.append({"code": "STALE_DATA", "message": f"Data may be outdated: {why}."})
    return {
        "data_as_of": last_bar.isoformat(),
        "fetched_at": datetime.fromtimestamp(fetched_at, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "is_delayed": lag >= 2,
        "stale": stale,
        "warnings": warnings,
    }
