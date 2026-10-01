"""Structured API errors with stable, machine-readable codes.

Wire format (all non-2xx responses from /api/*):
    {"error": {"code": "DATA_UNAVAILABLE", "message": "...", "retryable": true, "retry_after": 12}}

Codes are part of the public contract: add new ones, don't rename existing ones.
(STALE_DATA is not an HTTP error: it appears in a response's ``warnings`` list.)
"""
from __future__ import annotations


class ApiError(Exception):
    code = "INTERNAL_ERROR"
    status = 500

    def __init__(self, message: str, *, retryable: bool = False, retry_after: int | None = None):
        super().__init__(message)
        self.message, self.retryable, self.retry_after = message, retryable, retry_after

    def body(self) -> dict:
        err: dict = {"code": self.code, "message": self.message, "retryable": self.retryable}
        if self.retry_after is not None:
            err["retry_after"] = self.retry_after
        return {"error": err}


class InvalidSymbol(ApiError):
    code, status = "INVALID_SYMBOL", 400


class InvalidRange(ApiError):
    code, status = "INVALID_RANGE", 400


class InsufficientData(ApiError):
    """Not enough price history to run the forecast/backtest."""
    code, status = "INSUFFICIENT_DATA", 422


class UpstreamError(ApiError):
    """Base for failures of the market-data provider; the cache may serve older data instead."""


class DataUnavailable(UpstreamError):
    code, status = "DATA_UNAVAILABLE", 502


class RateLimited(UpstreamError):
    code, status = "RATE_LIMITED", 429

    def __init__(self, message: str, *, retry_after: int | None = 30):
        super().__init__(message, retryable=True, retry_after=retry_after)


class UpstreamTimeout(UpstreamError):
    code, status = "UPSTREAM_TIMEOUT", 504

    def __init__(self, message: str = "The market-data provider took too long to respond."):
        super().__init__(message, retryable=True)
