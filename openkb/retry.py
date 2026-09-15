"""Exponential backoff retry utilities for LLM completions.

Protects against Vertex AI / OpenAI / Anthropic rate limits (HTTP 429 Resource
Exhausted) and transient service errors (HTTP 500/503/timeouts) with jittered
exponential backoff.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import sys
import time
from typing import Any, Callable, Coroutine, TypeVar

logger = logging.getLogger("openkb.retry")

T = TypeVar("T")

DEFAULT_MAX_RETRIES = int(os.getenv("OPENKB_LLM_MAX_RETRIES", "5"))
DEFAULT_INITIAL_DELAY = float(os.getenv("OPENKB_LLM_RETRY_INITIAL_DELAY", "2.0"))
DEFAULT_MAX_DELAY = float(os.getenv("OPENKB_LLM_RETRY_MAX_DELAY", "60.0"))
DEFAULT_BACKOFF_FACTOR = float(os.getenv("OPENKB_LLM_RETRY_BACKOFF", "2.0"))


def is_retryable_error(exc: BaseException) -> bool:
    """Return True if ``exc`` is a transient or rate-limit LLM error."""
    exc_name = type(exc).__name__
    exc_str = str(exc).lower()

    # Direct LiteLLM exception types
    if exc_name in (
        "RateLimitError",
        "APIConnectionError",
        "ServiceUnavailableError",
        "InternalServerError",
        "Timeout",
        "APIError",
    ):
        return True

    # Check status code attributes
    status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status_code in (429, 500, 502, 503, 504, 529):
        return True

    # String pattern matching for Vertex AI / Cloud errors
    retry_patterns = (
        "resource_exhausted",
        "resource exhausted",
        "ratelimit",
        "rate limit",
        "too many requests",
        "429",
        "503",
        "service unavailable",
        "connection reset",
        "connection closed",
        "server disconnected",
        "timeout",
        "timed out",
    )
    return any(p in exc_str for p in retry_patterns)


def _extract_retry_after(exc: BaseException) -> float | None:
    """Try to extract a Retry-After duration in seconds from exception headers/text."""
    # Check headers if attached to response/exc
    response = getattr(exc, "response", None)
    if response is not None and hasattr(response, "headers"):
        retry_after = response.headers.get("retry-after") or response.headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass

    # Regex search in error string
    m = re.search(r"retry\s+after\s+(\d+(?:\.\d+)?)\s*s", str(exc), re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass

    return None


def calculate_backoff(
    attempt: int,
    exc: BaseException | None = None,
    initial_delay: float = DEFAULT_INITIAL_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
) -> float:
    """Calculate exponential backoff duration with full jitter."""
    if exc is not None:
        explicit_wait = _extract_retry_after(exc)
        if explicit_wait is not None and explicit_wait > 0:
            return min(explicit_wait + random.uniform(0.5, 1.5), max_delay)

    raw_delay = initial_delay * (backoff_factor ** attempt)
    # Add random jitter between 0.5s and 1.5s
    jitter = random.uniform(0.5, 1.5)
    return min(raw_delay + jitter, max_delay)


def call_with_retry(
    fn: Callable[..., T],
    *args: Any,
    step_name: str = "LLM call",
    max_retries: int = DEFAULT_MAX_RETRIES,
    initial_delay: float = DEFAULT_INITIAL_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    **kwargs: Any,
) -> T:
    """Execute synchronous ``fn(*args, **kwargs)`` with exponential backoff on retryable errors."""
    attempt = 0
    while True:
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            if not is_retryable_error(exc) or attempt >= max_retries:
                raise

            delay = calculate_backoff(
                attempt,
                exc=exc,
                initial_delay=initial_delay,
                max_delay=max_delay,
                backoff_factor=backoff_factor,
            )
            attempt += 1
            logger.warning(
                "Rate limit / transient error on [%s] (attempt %d/%d): %s. Retrying in %.1fs...",
                step_name,
                attempt,
                max_retries,
                exc,
                delay,
            )
            sys.stdout.write(
                f"    [Retry {attempt}/{max_retries}] ⏳ Rate limit on {step_name}; waiting {delay:.1f}s...\n"
            )
            sys.stdout.flush()
            time.sleep(delay)


async def acall_with_retry(
    coro_fn: Callable[..., Coroutine[Any, Any, T]],
    *args: Any,
    step_name: str = "LLM async call",
    max_retries: int = DEFAULT_MAX_RETRIES,
    initial_delay: float = DEFAULT_INITIAL_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    **kwargs: Any,
) -> T:
    """Execute asynchronous ``coro_fn(*args, **kwargs)`` with exponential backoff on retryable errors."""
    attempt = 0
    while True:
        try:
            return await coro_fn(*args, **kwargs)
        except Exception as exc:
            if not is_retryable_error(exc) or attempt >= max_retries:
                raise

            delay = calculate_backoff(
                attempt,
                exc=exc,
                initial_delay=initial_delay,
                max_delay=max_delay,
                backoff_factor=backoff_factor,
            )
            attempt += 1
            logger.warning(
                "Rate limit / transient error on [%s] (attempt %d/%d): %s. Retrying in %.1fs...",
                step_name,
                attempt,
                max_retries,
                exc,
                delay,
            )
            sys.stdout.write(
                f"    [Retry {attempt}/{max_retries}] ⏳ Rate limit on {step_name}; waiting {delay:.1f}s...\n"
            )
            sys.stdout.flush()
            await asyncio.sleep(delay)
