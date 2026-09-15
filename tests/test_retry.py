"""Unit tests for exponential backoff and rate limit retry mechanism."""

import asyncio
import pytest
from unittest.mock import MagicMock

from openkb.retry import (
    is_retryable_error,
    calculate_backoff,
    call_with_retry,
    acall_with_retry,
)


class FakeRateLimitError(Exception):
    def __init__(self, message="Resource exhausted 429"):
        super().__init__(message)
        self.status_code = 429


class FakeFatalError(Exception):
    def __init__(self, message="Invalid API key"):
        super().__init__(message)
        self.status_code = 401


def test_is_retryable_error():
    assert is_retryable_error(FakeRateLimitError())
    assert is_retryable_error(Exception("vertex_aiException - RESOURCE_EXHAUSTED 429"))
    assert is_retryable_error(Exception("Service Unavailable 503"))
    assert is_retryable_error(Exception("Server connection reset by peer"))
    assert not is_retryable_error(FakeFatalError())
    assert not is_retryable_error(ValueError("Invalid syntax"))


def test_calculate_backoff():
    d0 = calculate_backoff(0, initial_delay=2.0, max_delay=60.0)
    assert 2.0 <= d0 <= 4.0

    d1 = calculate_backoff(1, initial_delay=2.0, max_delay=60.0)
    assert 4.0 <= d1 <= 6.0

    d_capped = calculate_backoff(10, initial_delay=2.0, max_delay=30.0)
    assert d_capped <= 30.0


def test_call_with_retry_succeeds_first_try():
    fn = MagicMock(return_value="ok")
    res = call_with_retry(fn, 123, key="val", initial_delay=0.01)
    assert res == "ok"
    assert fn.call_count == 1
    fn.assert_called_once_with(123, key="val")


def test_call_with_retry_recovers_after_rate_limits():
    attempts = 0

    def flaky():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise FakeRateLimitError("RESOURCE_EXHAUSTED 429")
        return "success"

    res = call_with_retry(flaky, initial_delay=0.01, max_retries=5)
    assert res == "success"
    assert attempts == 3


def test_call_with_retry_raises_non_retryable_immediately():
    attempts = 0

    def fatal():
        nonlocal attempts
        attempts += 1
        raise FakeFatalError("401 Unauthorized")

    with pytest.raises(FakeFatalError):
        call_with_retry(fatal, initial_delay=0.01, max_retries=5)

    assert attempts == 1


@pytest.mark.asyncio
async def test_acall_with_retry_recovers_after_rate_limits():
    attempts = 0

    async def aflaky():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise FakeRateLimitError("Resource exhausted 429")
        return "async_success"

    res = await acall_with_retry(aflaky, initial_delay=0.01, max_retries=5)
    assert res == "async_success"
    assert attempts == 3

