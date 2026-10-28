from sportscanner.crawlers.parsers.core.fetch_failures import FetchFailure
from sportscanner.scheduler.providers import FetchOutcome


def test_fetched_zero_slots_is_success():
    outcome = FetchOutcome(slots=[], failures=[])
    assert outcome.ok
    assert outcome.error_message is None
    assert outcome.retryable is False


def test_failed_fetch_is_not_success_even_with_zero_slots():
    outcome = FetchOutcome(
        slots=[],
        failures=[
            FetchFailure("HTTP 429", status=429, retryable=True, retry_after_seconds=30)
        ],
    )
    assert not outcome.ok
    assert outcome.retryable is True
    assert outcome.retry_after_seconds == 30
    assert "429" in outcome.error_message


def test_outcome_uses_max_retry_after():
    outcome = FetchOutcome(
        slots=[],
        failures=[
            FetchFailure(
                "HTTP 429", status=429, retryable=True, retry_after_seconds=10
            ),
            FetchFailure(
                "HTTP 429", status=429, retryable=True, retry_after_seconds=90
            ),
        ],
    )
    assert outcome.retry_after_seconds == 90
