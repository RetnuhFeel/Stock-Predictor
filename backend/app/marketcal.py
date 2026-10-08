"""NYSE trading calendar (full-day closures), so forecast dates and "how old is the data" skip market holidays.

Rules (https://www.nyse.com/markets/hours-calendars): New Year's Day, Martin Luther King Jr. Day (3rd Mon Jan),
Washington's Birthday (3rd Mon Feb), Good Friday, Memorial Day (last Mon May), Juneteenth (from 2022), Independence
Day, Labor Day (1st Mon Sep), Thanksgiving (4th Thu Nov), Christmas. A holiday on a Saturday is observed the Friday
before and on a Sunday the Monday after, except that New Year's Day on a Saturday is NOT observed on the Friday.
Early closes (13:00) are still trading days. A few one-off closures are listed in ``SPECIAL_CLOSURES``.

This is a best-effort local table, not an official feed: if the exchange announces an unscheduled closure that is not
listed here, dates after it are off by one day until it is added.
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import cache

import numpy as np
import pandas as pd

SPECIAL_CLOSURES = {
    date(2018, 12, 5),   # National Day of Mourning: President G.H.W. Bush
    date(2025, 1, 9),    # National Day of Mourning: President Carter
}
FIRST_YEAR, LAST_YEAR = 2015, 2040


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """n-th (1-based) given weekday (Mon=0) of a month; n=-1 means the last one."""
    if n > 0:
        first = date(year, month, 1)
        return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))
    last = (date(year + (month == 12), month % 12 + 1, 1)) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _easter(year: int) -> date:
    """Western Easter Sunday (anonymous Gregorian algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    el = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * el) // 451
    month, day = divmod(h + el - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _observed(d: date, saturday_to_friday: bool = True) -> date | None:
    if d.weekday() == 5:
        return d - timedelta(days=1) if saturday_to_friday else None
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


@cache
def holidays_for(year: int) -> frozenset[date]:
    out: set[date | None] = {
        _observed(date(year, 1, 1), saturday_to_friday=False),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _easter(year) - timedelta(days=2),
        _nth_weekday(year, 5, 0, -1),
        _observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4),
        _observed(date(year, 12, 25)),
    }
    if year >= 2022:
        out.add(_observed(date(year, 6, 19)))
    # a following year's New Year's Day observed on Dec 31 never happens (Saturday case excluded above)
    return frozenset(d for d in out if d is not None and d.year == year)


@cache
def all_holidays() -> tuple[date, ...]:
    hs: set[date] = set(SPECIAL_CLOSURES)
    for y in range(FIRST_YEAR, LAST_YEAR + 1):
        hs |= holidays_for(y)
    return tuple(sorted(hs))


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in set(all_holidays())


def previous_trading_day(d: date) -> date:
    """The last trading day strictly before ``d``."""
    d -= timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


def market_offset() -> pd.offsets.CustomBusinessDay:
    """pandas offset that steps over weekends and NYSE holidays (``ts - market_offset() * n`` etc.)."""
    return pd.offsets.CustomBusinessDay(holidays=[np.datetime64(d) for d in all_holidays()])


def trading_days_after(last: pd.Timestamp, n: int) -> pd.DatetimeIndex:
    """The next ``n`` trading days strictly after ``last``."""
    return pd.date_range(last, periods=n + 1, freq=market_offset())[1:]


def trading_days_between(start: date, end: date) -> int:
    """Number of trading days in [start, end): the "business-day lag" used for data freshness."""
    return int(np.busday_count(start, end, holidays=[np.datetime64(d) for d in all_holidays()]))
