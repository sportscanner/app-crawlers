"""Opt-in fetch outcome tracking for the scheduler.

The existing crawlers intentionally swallow transient fetch errors so one bad
venue cannot fail a whole sport's pipeline run. The scheduler needs a stricter
signal: "this venue/date genuinely had zero slots" and "this venue/date could
not be fetched" must not be treated the same. This module is a no-op unless a
`track_fetch_failures()` context is active, so the current GitHub Actions
pipeline is unchanged.

Crawler code only records at the point it already knows the outcome (an HTTP
status, a connection failure, or a swallowed task exception). The scheduler
reads the tracker after the fetch and decides whether to write results or
release the claim for a retry.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Iterator, Mapping, Optional


@dataclass(frozen=True)
class FetchFailure:
    message: str
    status: Optional[int] = None
    retryable: bool = False
    retry_after_seconds: Optional[float] = None


@dataclass
class FetchFailureTracker:
    failures: list[FetchFailure] = field(default_factory=list)
    responses: int = 0

    def record_failure(
        self,
        message: str,
        *,
        status: Optional[int] = None,
        retryable: bool = False,
        retry_after_seconds: Optional[float] = None,
    ) -> None:
        self.failures.append(
            FetchFailure(
                message=message,
                status=status,
                retryable=retryable,
                retry_after_seconds=retry_after_seconds,
            )
        )

    def record_response(self) -> None:
        self.responses += 1

    @property
    def ok(self) -> bool:
        return not self.failures


_tracker: ContextVar[Optional[FetchFailureTracker]] = ContextVar(
    "sportscanner_fetch_failure_tracker", default=None
)


@contextmanager
def track_fetch_failures(tracker: FetchFailureTracker) -> Iterator[FetchFailureTracker]:
    token = _tracker.set(tracker)
    try:
        yield tracker
    finally:
        _tracker.reset(token)


def current_tracker() -> Optional[FetchFailureTracker]:
    return _tracker.get()


def record_failure(
    message: str,
    *,
    status: Optional[int] = None,
    retryable: bool = False,
    retry_after_seconds: Optional[float] = None,
) -> None:
    tracker = _tracker.get()
    if tracker is not None:
        tracker.record_failure(
            message,
            status=status,
            retryable=retryable,
            retry_after_seconds=retry_after_seconds,
        )


def record_response() -> None:
    tracker = _tracker.get()
    if tracker is not None:
        tracker.record_response()


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        return None
    return max(0.0, (when - datetime.now(when.tzinfo)).total_seconds())


def record_http_status(
    status: int,
    *,
    headers: Optional[Mapping[str, str]] = None,
    message: str = "",
) -> None:
    """Classify one HTTP response for the scheduler.

    Expected 4xx answers (for example Better's "activity not offered" 422) are
    a successful fetch with no data, not a failure. 403 and 429 are WAF/rate
    limits, and 5xx is an upstream fault; all three are retryable.
    """
    tracker = _tracker.get()
    if tracker is None:
        return
    if status in (403, 429) or status >= 500:
        retry_after = _parse_retry_after((headers or {}).get("Retry-After"))
        tracker.record_failure(
            message or f"HTTP {status}",
            status=status,
            retryable=True,
            retry_after_seconds=retry_after,
        )
    else:
        tracker.record_response()
