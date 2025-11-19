"""Reusable retry utilities for external service calls."""
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
    RetryCallState
)
import httpx
import smtplib
import logging
from typing import Callable

logger = logging.getLogger(__name__)


def retry_http_request(max_attempts: int = 3):
    """
    Retry decorator for HTTP requests on transient failures.
    
    Retries on:
    - Connection errors (network issues)
    - Timeout errors
    - 5xx server errors
    
    Args:
        max_attempts: Maximum number of retry attempts (default: 3)
    
    Returns:
        Tenacity retry decorator
    """
    def should_retry_http(exception: BaseException) -> bool:
        """Check if HTTP exception should trigger retry"""
        if isinstance(exception, httpx.HTTPStatusError):
            # Only retry on 5xx server errors, not client errors (4xx)
            return exception.response.status_code >= 500
        return isinstance(exception, (httpx.ConnectError, httpx.TimeoutException))
    
    return retry(
        retry=should_retry_http,
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        before_sleep=before_sleep_log(logger, logging.WARNING)
    )


def retry_smtp_operation(max_attempts: int = 2):
    """
    Retry decorator for SMTP operations on connection errors.
    
    Retries on:
    - SMTP connection errors
    - Server disconnections
    - Timeout errors
    
    Does NOT retry on:
    - Authentication errors (configuration issue)
    
    Args:
        max_attempts: Maximum number of retry attempts (default: 2)
    
    Returns:
        Tenacity retry decorator
    """
    def should_retry_smtp(exception: BaseException) -> bool:
        """Check if SMTP exception should trigger retry"""
        # Don't retry authentication errors
        if isinstance(exception, smtplib.SMTPAuthenticationError):
            return False
        # Retry connection-related errors
        return isinstance(exception, (
            smtplib.SMTPConnectError,
            smtplib.SMTPServerDisconnected,
            ConnectionError,
            TimeoutError
        ))
    
    return retry(
        retry=should_retry_smtp,
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=5, max=15),
        before_sleep=before_sleep_log(logger, logging.WARNING)
    )


def retry_ai_request(max_attempts: int = 3):
    """
    Retry decorator for AI API calls on overload/rate limit errors.
    
    Uses exponential backoff to handle temporary service unavailability.
    
    Args:
        max_attempts: Maximum number of retry attempts (default: 3)
    
    Returns:
        Tenacity retry decorator
    """
    def log_retry_attempt(retry_state: RetryCallState):
        """Custom logging for AI retry attempts"""
        exception = retry_state.outcome.exception()
        logger.warning(
            f"AI request failed (attempt {retry_state.attempt_number}/{max_attempts}), "
            f"retrying in {retry_state.next_action.sleep:.1f}s... Error: {exception}"
        )
    
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        before_sleep=log_retry_attempt,
        reraise=True
    )
