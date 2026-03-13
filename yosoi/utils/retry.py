"""Standardized retry logic for Yosoi.

Provides a centralized way to create retry configurations using tenacity.
"""

from collections.abc import Callable
from typing import Any

import logfire
from tenacity import (
    AsyncRetrying,
    BaseRetrying,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


def _build_retry_kwargs(
    max_attempts: int = 3,
    wait_min: float = 1.0,
    wait_max: float = 10.0,
    wait_multiplier: float = 1.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    log_callback: Callable[[Any], None] | None = None,
    reraise: bool = True,
) -> dict[str, Any]:
    return {
        'stop': stop_after_attempt(max_attempts),
        'wait': wait_exponential(multiplier=wait_multiplier, min=wait_min, max=wait_max),
        'retry': retry_if_exception_type(exceptions),
        'before_sleep': log_callback,
        'reraise': reraise,
    }


def get_retryer(
    max_attempts: int = 3,
    wait_min: float = 1.0,
    wait_max: float = 10.0,
    wait_multiplier: float = 1.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    log_callback: Callable[[Any], None] | None = None,
    reraise: bool = True,
) -> BaseRetrying:
    """Create a standardized tenacity Retrying object for synchronous code.

    Args:
        max_attempts: Maximum number of retry attempts.
        wait_min: Minimum wait time between retries in seconds.
        wait_max: Maximum wait time between retries in seconds.
        wait_multiplier: Multiplier for exponential backoff.
        exceptions: Tuple of exception types to retry on.
        log_callback: Optional callback function for before_sleep logging.
                      Receives the retry state.
        reraise: Whether to reraise the exception after all retries fail.

    Returns:
        A configured tenacity.Retrying object.

    """
    return Retrying(
        **_build_retry_kwargs(
            max_attempts,
            wait_min,
            wait_max,
            wait_multiplier,
            exceptions,
            log_callback,
            reraise,
        )
    )


def get_async_retryer(
    max_attempts: int = 3,
    wait_min: float = 1.0,
    wait_max: float = 10.0,
    wait_multiplier: float = 1.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    log_callback: Callable[[Any], None] | None = None,
    reraise: bool = True,
) -> AsyncRetrying:
    """Create a standardized tenacity AsyncRetrying object for async code.

    Uses asyncio.sleep between retries instead of time.sleep,
    avoiding event-loop blocking.

    Args:
        max_attempts: Maximum number of retry attempts.
        wait_min: Minimum wait time between retries in seconds.
        wait_max: Maximum wait time between retries in seconds.
        wait_multiplier: Multiplier for exponential backoff.
        exceptions: Tuple of exception types to retry on.
        log_callback: Optional callback function for before_sleep logging.
                      Receives the retry state.
        reraise: Whether to reraise the exception after all retries fail.

    Returns:
        A configured tenacity.AsyncRetrying object.

    """
    return AsyncRetrying(
        **_build_retry_kwargs(
            max_attempts,
            wait_min,
            wait_max,
            wait_multiplier,
            exceptions,
            log_callback,
            reraise,
        )
    )


def log_retry(retry_state: Any) -> None:
    """Default logging callback for retries.

    Logs a warning with logfire.

    Args:
        retry_state: The tenacity retry state object.

    """
    exception = retry_state.outcome.exception()
    attempt = retry_state.attempt_number
    logfire.warn('Retrying operation', attempt=attempt, error=str(exception) if exception else 'Unknown error')
