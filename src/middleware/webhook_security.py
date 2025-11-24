"""Webhook security middleware with HMAC signature validation, rate limiting, and IP whitelisting."""
import hashlib
import hmac
import time
import ipaddress
from typing import Optional, Dict, Any, Union
from dataclasses import dataclass, field
from fastapi import Request, HTTPException, status, Response
from starlette.middleware.base import BaseHTTPMiddleware
import logging
from datetime import datetime, timedelta

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
    RedisClient = redis.Redis
except ImportError:
    REDIS_AVAILABLE = False
    RedisClient = None

from src.core.config import settings
from src.core.database import supabase

logger = logging.getLogger(__name__)


@dataclass
class WebhookSecurityConfig:
    """Configuration for webhook security settings."""
    default_rate_limit: int = 60  # requests per minute
    rate_limit_window: int = 60   # seconds
    timestamp_tolerance: int = 300  # 5 minutes
    redis_url: Optional[str] = field(default_factory=lambda: getattr(settings, 'REDIS_URL', None))
    default_allowed_ips: list[str] = field(default_factory=list)


class WebhookSecurityMiddleware(BaseHTTPMiddleware):
    """Middleware for webhook security including signature validation, rate limiting, and IP filtering."""

    def __init__(
        self,
        app,
        redis_client: Optional[RedisClient] = None,
        config: Optional[WebhookSecurityConfig] = None
    ) -> None:
        super().__init__(app)
        self.redis_client = redis_client
        self.config = config or WebhookSecurityConfig()
        self.rate_limit_cache: dict[str, int] = {}  # Fallback if Redis not available
        
    async def dispatch(self, request: Request, call_next) -> Union[Response, Any]:
        """Process request through webhook security middleware."""
        # Only apply to webhook endpoints
        if not request.url.path.startswith("/api/v1/integrations/webhook/"):
            return await call_next(request)
        
        start_time = time.time()
        
        try:
            # Extract integration ID from path - find the UUID in the path
            path_parts = request.url.path.split("/")
            integration_id = None
            for part in path_parts:
                # UUID pattern: 8-4-4-4-12 hex digits
                if len(part) == 36 and part.count('-') == 4:
                    try:
                        # Validate it's a proper UUID
                        import uuid
                        uuid.UUID(part)
                        integration_id = part
                        break
                    except ValueError:
                        continue

            if not integration_id:
                logger.warning(f"Could not extract integration ID from path: {request.url.path}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid webhook endpoint"
                )
            
            # Get client IP
            client_ip = self._get_client_ip(request)
            
            # Get request timestamp and body for signature validation
            timestamp, body, signature = await self._extract_request_data(request)
            
            # Security validations
            await self._validate_integration(integration_id)
            await self._validate_ip_whitelist(integration_id, client_ip)
            await self._validate_signature(integration_id, timestamp, body, signature)
            await self._validate_rate_limit(integration_id, client_ip)
            
            # Log webhook access
            await self._log_webhook_access(integration_id, client_ip, request.url.path)
            
            response = await call_next(request)
            
            # Log successful processing
            processing_time = time.time() - start_time
            logger.info(f"Webhook processed successfully: {integration_id} ({processing_time:.3f}s)")
            
            return response
            
        except HTTPException:
            raise
        except Exception as e:
            processing_time = time.time() - start_time
            logger.error(f"Webhook processing error: {str(e)} ({processing_time:.3f}s)")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal server error"
            )
    
    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP from request headers with modern pattern matching."""
        # Check for forwarded headers first
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip
        
        # Fallback to client host
        if hasattr(request.client, "host"):
            return request.client.host
        
        return "unknown"
    
    async def _extract_request_data(self, request: Request) -> tuple[Optional[str], bytes, Optional[str]]:
        """Extract timestamp, body, and signature from request."""
        body = await request.body()
        timestamp = request.headers.get("x-timestamp")
        signature = request.headers.get("x-signature")
        
        return timestamp, body, signature
    
    async def _validate_integration(self, integration_id: str) -> None:
        """Validate that the integration exists and is active."""
        try:
            result = supabase.table("integrations").select("id", "status", "org_id").eq("id", integration_id).execute()

            if not result.data:
                logger.warning(f"Webhook received for non-existent integration: {integration_id}")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Integration not found"
                )

            integration = result.data[0]
            if integration["status"] != "active":
                logger.warning(f"Webhook received for inactive integration: {integration_id} (status: {integration['status']})")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Integration is not active"
                )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Integration validation failed: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Integration validation failed"
            )
    
    async def _validate_ip_whitelist(self, integration_id: str, client_ip: str) -> None:
        """Validate client IP against whitelist for the integration."""
        try:
            # Get integration configs
            result = supabase.table("integration_configs").select("value").eq("integration_id", integration_id).eq("key", "allowed_ips").single().execute()
            
            if not result.data:
                return  # No IP whitelist configured, allow all IPs

            allowed_ips_str = result.data.get("value")
            if not allowed_ips_str:
                return
            
            # Parse allowed IPs
            allowed_ips = [ip.strip() for ip in allowed_ips_str.split(",")]
            
            # Check if IP matches any allowed pattern
            client_ip_obj = ipaddress.ip_address(client_ip)
            ip_allowed = False
            
            for allowed_ip in allowed_ips:
                try:
                    if "/" in allowed_ip:  # CIDR notation
                        network = ipaddress.ip_network(allowed_ip, strict=False)
                        if client_ip_obj in network:
                            ip_allowed = True
                            break
                    else:  # Single IP
                        if client_ip == allowed_ip:
                            ip_allowed = True
                            break
                except ValueError:
                    logger.warning(f"Invalid IP pattern in whitelist: {allowed_ip}")
                    continue
            
            if not ip_allowed:
                logger.warning(f"IP {client_ip} not whitelisted for integration {integration_id}")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Client IP not whitelisted"
                )
                
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"IP whitelist validation failed: {str(e)}")
            # Don't fail the request on whitelist validation errors
            return
    
    async def _validate_signature(self, integration_id: str, timestamp: Optional[str], body: bytes, signature: Optional[str]) -> None:
        """Validate HMAC signature of the request (optional for Evolution API)."""
        try:
            # Get webhook secret from integration configs
            result = supabase.table("integration_configs").select("value").eq("integration_id", integration_id).eq("key", "webhook_secret").single().execute()

            # If no webhook secret configured OR required headers missing, skip validation
            if not result.data or not timestamp or not signature:
                logger.info(f"Skipping signature validation for integration {integration_id} (no secret or missing headers)")
                return

            webhook_secret = result.data["value"]

            # Validate timestamp (prevent replay attacks)
            try:
                request_time = float(timestamp)
                current_time = time.time()
                time_diff = abs(current_time - request_time)

                # Allow 5 minute clock skew
                if time_diff > 300:
                    logger.warning(f"Request timestamp too old: {timestamp}")
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Request timestamp too old"
                    )
            except ValueError:
                logger.warning(f"Invalid timestamp format: {timestamp}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid timestamp format"
                )

            # Compute expected signature
            payload = f"{timestamp}.{body.decode('utf-8')}"
            expected_signature = hmac.new(
                webhook_secret.encode('utf-8'),
                payload.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()

            # Use constant time comparison to prevent timing attacks
            if not hmac.compare_digest(signature, expected_signature):
                logger.warning(f"Invalid signature for integration {integration_id}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid signature"
                )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Signature validation failed: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Signature validation failed"
            )
    
    async def _validate_rate_limit(self, integration_id: str, client_ip: str) -> None:
        """Validate rate limiting for the integration and IP."""
        try:
            # Rate limiting configuration
            requests_per_minute = 60  # Default: 60 requests per minute per IP
            
            # Get custom rate limit from integration config if available
            try:
                result = supabase.table("integration_configs").select("value").eq("integration_id", integration_id).eq("key", "rate_limit_per_minute").single().execute()
                if result.data:
                    requests_per_minute = int(result.data["value"])
            except:
                pass  # Use default rate limit
            
            # Create rate limit key
            rate_limit_key = f"webhook_rate_limit:{integration_id}:{client_ip}"
            
            # Use Redis if available, otherwise use in-memory cache
            if self.redis_client:
                current_requests = await self.redis_client.get(rate_limit_key)
                if current_requests is None:
                    # First request in this minute
                    await self.redis_client.setex(rate_limit_key, 60, 1)
                else:
                    requests_count = int(current_requests)
                    if requests_count >= requests_per_minute:
                        logger.warning(f"Rate limit exceeded for {client_ip} on integration {integration_id}")
                        raise HTTPException(
                            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail="Rate limit exceeded"
                        )
                    await self.redis_client.incr(rate_limit_key)
            else:
                # Fallback to in-memory cache
                current_time = int(time.time())
                minute_window = current_time // 60
                cache_key = f"{rate_limit_key}:{minute_window}"
                
                if cache_key not in self.rate_limit_cache:
                    self.rate_limit_cache[cache_key] = 0
                
                if self.rate_limit_cache[cache_key] >= requests_per_minute:
                    logger.warning(f"Rate limit exceeded for {client_ip} on integration {integration_id}")
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail="Rate limit exceeded"
                    )
                
                self.rate_limit_cache[cache_key] += 1
                
                # Clean up old entries
                keys_to_delete = [k for k in self.rate_limit_cache.keys() if int(k.split(":")[-1]) < minute_window - 1]
                for key in keys_to_delete:
                    del self.rate_limit_cache[key]
                
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Rate limit validation failed: {str(e)}")
            # Don't fail the request on rate limiting errors
            return
    
    async def _log_webhook_access(self, integration_id: str, client_ip: str, endpoint: str) -> None:
        """Log webhook access for monitoring."""
        try:
            log_entry = {
                "integration_id": integration_id,
                "client_ip": client_ip,
                "endpoint": endpoint,
                "timestamp": datetime.utcnow().isoformat(),
                "access_type": "webhook_request"
            }
            
            # Store in database for audit trail
            supabase.table("integration_events").insert({
                "integration_id": integration_id,
                "event_type": "webhook_access",
                "payload": log_entry,
                "status": "processed"
            }).execute()
            
        except Exception as e:
            logger.error(f"Failed to log webhook access: {str(e)}")


# Global security config instance
webhook_security_config = WebhookSecurityConfig()