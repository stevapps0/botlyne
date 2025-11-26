"""Retry mechanisms with exponential backoff and circuit breaker patterns."""
import asyncio
import time
import logging
from typing import Callable, Any, Optional, Dict, List
from enum import Enum
from dataclasses import dataclass
from functools import wraps

from src.core.config import settings

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Blocking requests
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class RetryConfig:
    """Configuration for retry mechanisms."""
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True
    exceptions: tuple = (Exception,)


class CircuitBreaker:
    """Circuit breaker implementation for resilience."""
    
    def __init__(
        self,
        failure_threshold: int = None,
        timeout: int = None,
        expected_exception: tuple = (Exception,)
    ):
        self.failure_threshold = failure_threshold or settings.CIRCUIT_BREAKER_FAILURE_THRESHOLD
        self.timeout = timeout or settings.CIRCUIT_BREAKER_TIMEOUT
        self.expected_exception = expected_exception
        
        self.failure_count = 0
        self.last_failure_time = None
        self.state = CircuitState.CLOSED
        
    async def __aenter__(self):
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type in self.expected_exception:
            self.record_failure()
        else:
            self.record_success()
    
    def record_failure(self):
        """Record a failure and update circuit state."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning(f"Circuit breaker opened after {self.failure_count} failures")
    
    def record_success(self):
        """Record a success and update circuit state."""
        self.failure_count = 0
        self.state = CircuitState.CLOSED
    
    def can_execute(self) -> bool:
        """Check if the circuit allows execution."""
        if self.state == CircuitState.CLOSED:
            return True
        elif self.state == CircuitState.OPEN:
            # Check if timeout has elapsed
            if time.time() - self.last_failure_time >= self.timeout:
                self.state = CircuitState.HALF_OPEN
                logger.info("Circuit breaker moving to half-open state")
                return True
            return False
        else:  # HALF_OPEN
            return True
    
    def call(self, func: Callable, *args, **kwargs) -> Any:
        """Call function with circuit breaker protection."""
        if not self.can_execute():
            raise CircuitBreakerOpenError("Circuit breaker is open")
        
        try:
            result = func(*args, **kwargs)
            if asyncio.iscoroutine(result):
                # Handle async functions
                async def wrapped():
                    try:
                        return await result
                    except self.expected_exception:
                        self.record_failure()
                        raise
                    else:
                        self.record_success()
                return wrapped()
            else:
                # Handle sync functions
                try:
                    return result
                except self.expected_exception:
                    self.record_failure()
                    raise
                else:
                    self.record_success()
        except self.expected_exception:
            self.record_failure()
            raise


class CircuitBreakerOpenError(Exception):
    """Exception raised when circuit breaker is open."""
    pass


def with_circuit_breaker(
    failure_threshold: int = None,
    timeout: int = None,
    expected_exception: tuple = (Exception,)
):
    """Decorator to add circuit breaker protection to functions."""
    def decorator(func):
        breaker = CircuitBreaker(failure_threshold, timeout, expected_exception)
        
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            async with breaker:
                return await func(*args, **kwargs)
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            with breaker:
                return func(*args, **kwargs)
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    
    return decorator


async def retry_with_backoff(
    func: Callable,
    *args,
    config: RetryConfig = None,
    **kwargs
) -> Any:
    """Execute function with exponential backoff retry."""
    if config is None:
        config = RetryConfig()
    
    last_exception = None
    
    for attempt in range(config.max_attempts):
        try:
            result = func(*args, **kwargs)
            if asyncio.iscoroutine(result):
                return await result
            else:
                return result
                
        except config.exceptions as e:
            last_exception = e
            
            if attempt == config.max_attempts - 1:
                # Last attempt failed
                logger.error(f"All {config.max_attempts} retry attempts failed. Last exception: {str(e)}")
                raise e
            
            # Calculate delay with exponential backoff
            delay = min(
                config.base_delay * (config.exponential_base ** attempt),
                config.max_delay
            )
            
            # Add jitter to avoid thundering herd
            if config.jitter:
                import random
                delay *= (0.5 + random.random() * 0.5)
            
            logger.warning(f"Attempt {attempt + 1}/{config.max_attempts} failed: {str(e)}. Retrying in {delay:.2f}s")
            await asyncio.sleep(delay)
    
    # This should never be reached, but for safety
    if last_exception:
        raise last_exception


def retry_async(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    exponential_base: float = 2.0,
    max_delay: float = 60.0,
    jitter: bool = True,
    exceptions: tuple = (Exception,)
):
    """Decorator for async functions with retry and backoff."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            config = RetryConfig(
                max_attempts=max_attempts,
                base_delay=base_delay,
                exponential_base=exponential_base,
                max_delay=max_delay,
                jitter=jitter,
                exceptions=exceptions
            )
            
            return await retry_with_backoff(func, *args, config=config, **kwargs)
        
        return wrapper
    return decorator


def retry_sync(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    exponential_base: float = 2.0,
    max_delay: float = 60.0,
    jitter: bool = True,
    exceptions: tuple = (Exception,)
):
    """Decorator for sync functions with retry and backoff."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            config = RetryConfig(
                max_attempts=max_attempts,
                base_delay=base_delay,
                exponential_base=exponential_base,
                max_delay=max_delay,
                jitter=jitter,
                exceptions=exceptions
            )
            
            last_exception = None
            
            for attempt in range(config.max_attempts):
                try:
                    return func(*args, **kwargs)
                    
                except config.exceptions as e:
                    last_exception = e
                    
                    if attempt == config.max_attempts - 1:
                        # Last attempt failed
                        logger.error(f"All {config.max_attempts} retry attempts failed. Last exception: {str(e)}")
                        raise e
                    
                    # Calculate delay with exponential backoff
                    delay = min(
                        config.base_delay * (config.exponential_base ** attempt),
                        config.max_delay
                    )
                    
                    # Add jitter to avoid thundering herd
                    if config.jitter:
                        import random
                        delay *= (0.5 + random.random() * 0.5)
                    
                    logger.warning(f"Attempt {attempt + 1}/{config.max_attempts} failed: {str(e)}. Retrying in {delay:.2f}s")
                    time.sleep(delay)
            
            # This should never be reached, but for safety
            if last_exception:
                raise last_exception
        
        return wrapper
    return decorator


class ResilienceManager:
    """Manager for multiple resilience patterns."""
    
    def __init__(self):
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        self.metrics: Dict[str, Dict[str, Any]] = {}
    
    def get_circuit_breaker(self, name: str, **kwargs) -> CircuitBreaker:
        """Get or create a circuit breaker by name."""
        if name not in self.circuit_breakers:
            self.circuit_breakers[name] = CircuitBreaker(**kwargs)
        return self.circuit_breakers[name]
    
    def record_success(self, operation: str):
        """Record a successful operation."""
        if operation not in self.metrics:
            self.metrics[operation] = {"successes": 0, "failures": 0, "retries": 0}
        
        self.metrics[operation]["successes"] += 1
    
    def record_failure(self, operation: str):
        """Record a failed operation."""
        if operation not in self.metrics:
            self.metrics[operation] = {"successes": 0, "failures": 0, "retries": 0}
        
        self.metrics[operation]["failures"] += 1
    
    def record_retry(self, operation: str):
        """Record a retry attempt."""
        if operation not in self.metrics:
            self.metrics[operation] = {"successes": 0, "failures": 0, "retries": 0}
        
        self.metrics[operation]["retries"] += 1
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get health status of all circuit breakers and metrics."""
        status = {
            "circuit_breakers": {},
            "metrics": self.metrics,
            "overall_health": "healthy"
        }
        
        for name, breaker in self.circuit_breakers.items():
            status["circuit_breakers"][name] = {
                "state": breaker.state.value,
                "failure_count": breaker.failure_count,
                "last_failure_time": breaker.last_failure_time
            }
        
        # Determine overall health
        critical_failures = 0
        for metrics in self.metrics.values():
            if metrics["failures"] > metrics["successes"] * 0.5:  # More than 50% failure rate
                critical_failures += 1
        
        if critical_failures > len(self.metrics) * 0.3:  # More than 30% of services failing
            status["overall_health"] = "unhealthy"
        elif critical_failures > 0:
            status["overall_health"] = "degraded"
        
        return status


# Global resilience manager instance
resilience_manager = ResilienceManager()


def retry_smtp_operation(
    max_attempts: int = 3,
    base_delay: float = 2.0,
    exponential_base: float = 2.0,
    max_delay: float = 30.0,
    jitter: bool = True,
    exceptions: tuple = (Exception,)
):
    """
    Decorator specifically for SMTP operations with exponential backoff.

    This is a specialized version of retry_async designed for email operations
    with sensible defaults for handling SMTP connection issues and rate limits.

    Args:
        max_attempts: Maximum number of retry attempts (default: 3)
        base_delay: Base delay in seconds before first retry (default: 2.0)
        exponential_base: Base for exponential backoff multiplier (default: 2.0)
        max_delay: Maximum delay between retries in seconds (default: 30.0)
        jitter: Whether to add random jitter to delays (default: True)
        exceptions: Tuple of exceptions to retry on (default: all exceptions)

    Returns:
        Decorator function that can be applied to async functions

    Example:
        @retry_smtp_operation(max_attempts=2)
        async def my_email_function():
            return await send_email()
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            config = RetryConfig(
                max_attempts=max_attempts,
                base_delay=base_delay,
                exponential_base=exponential_base,
                max_delay=max_delay,
                jitter=jitter,
                exceptions=exceptions
            )

            # Add specific handling for common SMTP errors
            smtp_specific_exceptions = (
                Exception,  # Base exception
            )

            # Import specific SMTP-related exceptions if available
            try:
                import smtplib
                smtp_specific_exceptions = (
                    smtplib.SMTPException,
                    smtplib.SMTPConnectError,
                    smtplib.SMTPHeloError,
                    smtplib.SMTPAuthenticationError,
                    smtplib.SMTPRecipientsRefused,
                    smtplib.SMTPDataError,
                    smtplib.SMTPNotSupportedError,
                    ConnectionError,
                    TimeoutError,
                    OSError,
                    Exception
                )
            except ImportError:
                # If smtplib not available, use generic exceptions
                pass

            # Update config with SMTP-specific exceptions
            config.exceptions = smtp_specific_exceptions

            return await retry_with_backoff(func, *args, config=config, **kwargs)

        return wrapper
    return decorator


def retry_http_request(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    exponential_base: float = 2.0,
    max_delay: float = 30.0,
    jitter: bool = True,
    exceptions: tuple = (Exception,)
):
    """
    Decorator specifically for HTTP request retry with exponential backoff.

    This is a specialized version of retry_async designed for HTTP requests
    with sensible defaults for handling network issues, timeouts, and HTTP errors.

    Args:
        max_attempts: Maximum number of retry attempts (default: 3)
        base_delay: Base delay in seconds before first retry (default: 1.0)
        exponential_base: Base for exponential backoff multiplier (default: 2.0)
        max_delay: Maximum delay between retries in seconds (default: 30.0)
        jitter: Whether to add random jitter to delays (default: True)
        exceptions: Tuple of exceptions to retry on (default: all exceptions)

    Returns:
        Decorator function that can be applied to async functions

    Example:
        @retry_http_request(max_attempts=5)
        async def my_http_function():
            return await make_http_request()
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            config = RetryConfig(
                max_attempts=max_attempts,
                base_delay=base_delay,
                exponential_base=exponential_base,
                max_delay=max_delay,
                jitter=jitter,
                exceptions=exceptions
            )

            # Add specific handling for common HTTP errors
            http_specific_exceptions = (
                Exception,  # Base exception
            )

            # Import specific HTTP-related exceptions if available
            try:
                import aiohttp
                http_specific_exceptions = (
                    aiohttp.ClientError,
                    aiohttp.ClientConnectionError,
                    aiohttp.ClientTimeout,
                    aiohttp.ClientResponseError,
                    aiohttp.ServerTimeoutError,
                    Exception
                )
            except ImportError:
                # If aiohttp not available, try requests
                try:
                    import requests.exceptions
                    http_specific_exceptions = (
                        requests.exceptions.ConnectionError,
                        requests.exceptions.Timeout,
                        requests.exceptions.HTTPError,
                        requests.exceptions.RequestException,
                        Exception
                    )
                except ImportError:
                    # If neither available, use generic exceptions
                    pass

            # Update config with HTTP-specific exceptions
            config.exceptions = http_specific_exceptions

            return await retry_with_backoff(func, *args, config=config, **kwargs)

        return wrapper
    return decorator


def retry_ai_request(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    exponential_base: float = 2.0,
    max_delay: float = 60.0,
    jitter: bool = True,
    exceptions: tuple = (Exception,)
):
    """
    Decorator specifically for AI request retry with exponential backoff.

    This is a specialized version of retry_async designed for AI API calls
    with sensible defaults for handling rate limits and transient failures.

    Args:
        max_attempts: Maximum number of retry attempts (default: 3)
        base_delay: Base delay in seconds before first retry (default: 1.0)
        exponential_base: Base for exponential backoff multiplier (default: 2.0)
        max_delay: Maximum delay between retries in seconds (default: 60.0)
        jitter: Whether to add random jitter to delays (default: True)
        exceptions: Tuple of exceptions to retry on (default: all exceptions)

    Returns:
        Decorator function that can be applied to async functions

    Example:
        @retry_ai_request(max_attempts=5)
        async def my_ai_function():
            return await some_ai_call()
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            config = RetryConfig(
                max_attempts=max_attempts,
                base_delay=base_delay,
                exponential_base=exponential_base,
                max_delay=max_delay,
                jitter=jitter,
                exceptions=exceptions
            )

            # Add specific handling for common AI API errors
            ai_specific_exceptions = (
                Exception,  # Base exception
            )

            # Import specific AI-related exceptions if available
            try:
                from requests.exceptions import (
                    ConnectionError,
                    Timeout,
                    HTTPError,
                    RequestException
                )
                ai_specific_exceptions = (
                    ConnectionError,
                    Timeout,
                    HTTPError,
                    RequestException,
                    Exception
                )
            except ImportError:
                # If requests not available, use generic exceptions
                pass

            # Update config with AI-specific exceptions
            config.exceptions = ai_specific_exceptions

            return await retry_with_backoff(func, *args, config=config, **kwargs)

        return wrapper
    return decorator
