"""Comprehensive error handling and logging system for production readiness."""
import logging
import json
import traceback
from datetime import datetime
from typing import Dict, Any, Optional, List
import uuid
from contextlib import contextmanager
from functools import wraps

from src.core.database import supabase
from src.core.config import settings


class StructuredLogger:
    """Structured logging for better observability."""
    
    def __init__(self, name: str = None):
        self.logger = logging.getLogger(name or __name__)
        self.logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
        
        # Ensure handlers exist
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
    
    def _log_structured(
        self, 
        level: str, 
        message: str, 
        extra: Optional[Dict[str, Any]] = None,
        exception: Optional[Exception] = None
    ):
        """Log with structured data."""
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": level,
            "message": message,
            "service": "botlyne",
            "version": "1.0.0"
        }
        
        if extra:
            log_data.update(extra)
        
        if exception:
            log_data["exception"] = {
                "type": type(exception).__name__,
                "message": str(exception),
                "traceback": traceback.format_exc()
            }
        
        # Log as JSON for structured logging
        log_message = json.dumps(log_data, default=str)
        
        if level.upper() == "ERROR":
            self.logger.error(log_message)
        elif level.upper() == "WARNING":
            self.logger.warning(log_message)
        elif level.upper() == "INFO":
            self.logger.info(log_message)
        elif level.upper() == "DEBUG":
            self.logger.debug(log_message)
    
    def error(self, message: str, extra: Optional[Dict[str, Any]] = None, exception: Optional[Exception] = None):
        """Log error message."""
        self._log_structured("ERROR", message, extra, exception)
    
    def warning(self, message: str, extra: Optional[Dict[str, Any]] = None, exception: Optional[Exception] = None):
        """Log warning message."""
        self._log_structured("WARNING", message, extra, exception)
    
    def info(self, message: str, extra: Optional[Dict[str, Any]] = None):
        """Log info message."""
        self._log_structured("INFO", message, extra)
    
    def debug(self, message: str, extra: Optional[Dict[str, Any]] = None):
        """Log debug message."""
        self._log_structured("DEBUG", message, extra)


class ErrorTracker:
    """Track and store errors in the database for monitoring."""
    
    def __init__(self):
        self.structured_logger = StructuredLogger("error_tracker")
    
    def record_error(
        self,
        error: Exception,
        context: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        org_id: Optional[str] = None,
        endpoint: Optional[str] = None,
        request_id: Optional[str] = None
    ):
        """Record an error in the database."""
        try:
            error_data = {
                "id": str(uuid.uuid4()),
                "error_type": type(error).__name__,
                "error_message": str(error),
                "traceback": traceback.format_exc(),
                "context": context or {},
                "user_id": user_id,
                "org_id": org_id,
                "endpoint": endpoint,
                "request_id": request_id,
                "timestamp": datetime.utcnow().isoformat(),
                "severity": self._determine_severity(error, context),
                "status": "open"
            }
            
            # Store in audit_logs table for now
            supabase.table("audit_logs").insert({
                "table_name": "error_tracking",
                "record_id": error_data["id"],
                "operation": "ERROR",
                "new_values": error_data,
                "timestamp": datetime.utcnow().isoformat()
            }).execute()
            
            # Also log with structured logger
            self.structured_logger.error(
                f"Error recorded: {type(error).__name__}",
                extra={
                    "error_id": error_data["id"],
                    "error_type": error_data["error_type"],
                    "context": context,
                    "endpoint": endpoint,
                    "request_id": request_id
                },
                exception=error
            )
            
        except Exception as e:
            # If error tracking fails, log it but don't crash
            self.structured_logger.error(
                "Failed to record error",
                extra={"tracking_error": str(e), "original_error": str(error)}
            )
    
    def _determine_severity(self, error: Exception, context: Optional[Dict[str, Any]]) -> str:
        """Determine error severity based on error type and context."""
        error_name = type(error).__name__
        
        # Critical errors
        if error_name in ["DatabaseError", "ConnectionError", "TimeoutError"]:
            return "critical"
        
        # High severity errors
        if error_name in ["AuthenticationError", "AuthorizationError", "ValidationError"]:
            return "high"
        
        # Check context for priority indicators
        if context:
            if context.get("priority") == "urgent":
                return "high"
            if context.get("status_code", 200) >= 500:
                return "high"
        
        return "medium"


class GracefulDegradation:
    """Handle graceful degradation for service failures."""
    
    def __init__(self):
        self.degraded_services = set()
        self.fallback_strategies = {}
    
    def register_fallback(self, service_name: str, fallback_func: callable):
        """Register a fallback strategy for a service."""
        self.fallback_strategies[service_name] = fallback_func
    
    def mark_service_degraded(self, service_name: str, reason: str):
        """Mark a service as degraded."""
        self.degraded_services.add(service_name)
        
        # Log the degradation
        structured_logger = StructuredLogger("graceful_degradation")
        structured_logger.warning(
            f"Service marked as degraded: {service_name}",
            extra={"service": service_name, "reason": reason}
        )
    
    def mark_service_recovered(self, service_name: str):
        """Mark a service as recovered."""
        self.degraded_services.discard(service_name)
        
        # Log the recovery
        structured_logger = StructuredLogger("graceful_degradation")
        structured_logger.info(
            f"Service recovered: {service_name}",
            extra={"service": service_name}
        )
    
    async def execute_with_fallback(self, service_name: str, primary_func: callable, *args, **kwargs):
        """Execute function with fallback on failure."""
        if service_name in self.degraded_services:
            # Service is degraded, try fallback
            if service_name in self.fallback_strategies:
                structured_logger = StructuredLogger("graceful_degradation")
                structured_logger.info(
                    f"Using fallback for degraded service: {service_name}",
                    extra={"service": service_name}
                )
                return await self.fallback_strategies[service_name](*args, **kwargs)
            else:
                raise ServiceUnavailableError(f"Service {service_name} is degraded and no fallback available")
        
        try:
            result = await primary_func(*args, **kwargs)
            
            # If service was previously degraded, mark as recovered
            if service_name in self.degraded_services:
                self.mark_service_recovered(service_name)
            
            return result
            
        except Exception as e:
            # Mark service as degraded
            self.mark_service_degraded(service_name, str(e))
            
            # Try fallback
            if service_name in self.fallback_strategies:
                try:
                    structured_logger = StructuredLogger("graceful_degradation")
                    structured_logger.warning(
                        f"Primary failed, using fallback for: {service_name}",
                        extra={"service": service_name, "error": str(e)}
                    )
                    return await self.fallback_strategies[service_name](*args, **kwargs)
                except Exception as fallback_error:
                    structured_logger.error(
                        f"Fallback also failed for: {service_name}",
                        extra={"service": service_name, "primary_error": str(e), "fallback_error": str(fallback_error)}
                    )
                    raise ServiceUnavailableError(f"Both primary and fallback failed for service {service_name}")
            else:
                raise ServiceUnavailableError(f"Service {service_name} failed and no fallback available")


class ServiceUnavailableError(Exception):
    """Exception raised when a service is unavailable."""
    pass


def error_handler(
    log_errors: bool = True,
    track_errors: bool = True,
    context_provider: callable = None,
    re_raise: bool = True
):
    """Decorator for comprehensive error handling."""
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            error_tracker = ErrorTracker()
            structured_logger = StructuredLogger(func.__module__)
            
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                # Get context
                context = {}
                if context_provider:
                    try:
                        context = context_provider(*args, **kwargs)
                    except:
                        pass
                
                # Log error
                if log_errors:
                    structured_logger.error(
                        f"Error in {func.__name__}",
                        extra={
                            "function": func.__name__,
                            "args": str(args)[:500],  # Truncate long args
                            "context": context
                        },
                        exception=e
                    )
                
                # Track error
                if track_errors:
                    error_tracker.record_error(
                        error=e,
                        context=context,
                        endpoint=context.get("endpoint"),
                        request_id=context.get("request_id")
                    )
                
                if re_raise:
                    raise
                
                return None
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            error_tracker = ErrorTracker()
            structured_logger = StructuredLogger(func.__module__)
            
            try:
                return func(*args, **kwargs)
            except Exception as e:
                # Get context
                context = {}
                if context_provider:
                    try:
                        context = context_provider(*args, **kwargs)
                    except:
                        pass
                
                # Log error
                if log_errors:
                    structured_logger.error(
                        f"Error in {func.__name__}",
                        extra={
                            "function": func.__name__,
                            "args": str(args)[:500],  # Truncate long args
                            "context": context
                        },
                        exception=e
                    )
                
                # Track error
                if track_errors:
                    error_tracker.record_error(
                        error=e,
                        context=context,
                        endpoint=context.get("endpoint"),
                        request_id=context.get("request_id")
                    )
                
                if re_raise:
                    raise
                
                return None
        
        return async_wrapper if hasattr(func, '__code__') and func.__code__.co_flags & 0x80 else sync_wrapper
    
    return decorator


@contextmanager
def error_context(error_tracker: ErrorTracker, context: Dict[str, Any]):
    """Context manager for error handling."""
    try:
        yield
    except Exception as e:
        error_tracker.record_error(error=e, context=context)
        raise


# Global instances
structured_logger = StructuredLogger("botlyne")
error_tracker = ErrorTracker()
graceful_degradation = GracefulDegradation()