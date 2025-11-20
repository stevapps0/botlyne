"""Webhook security middleware with HMAC signature validation, rate limiting, and IP whitelisting."""
import hashlib
import hmac
import time
import json
import ipaddress
from typing import Optional, List, Dict, Any
from fastapi import Request, HTTPException, status, Response
from starlette.middleware.base import BaseHTTPMiddleware
import logging
from datetime import datetime, timedelta

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    redis = None
    REDIS_AVAILABLE = False

# Type alias for Redis client
RedisClient = None
if REDIS_AVAILABLE:
    RedisClient = redis.Redis

from src.core.config import settings
from src.core.database import supabase

logger = logging.getLogger(__name__)


class WebhookSecurityMiddleware(BaseHTTPMiddleware):
    """Middleware for webhook security including signature validation, rate limiting, and IP filtering."""
    
    def __init__(self, app, redis_client: Optional[RedisClient] = None):
        super().__init__(app)
        self.redis_client = redis_client
        self.rate_limit_cache = {}  # Fallback if Redis not available
        
    async def dispatch(self, request: Request, call_next):
        """Process request through webhook security middleware."""
        # Only apply to webhook endpoints
        if not request.url.path.startswith("/api/v1/integrations/webhook/"):
            return await call_next(request)
        
        start_time = time.time()
        
        try:
            # Extract integration ID from path
            path_parts = request.url.path.split("/")
            if len(path_parts) < 5:
                logger.warning(f"Invalid webhook path: {request.url.path}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid webhook endpoint"
                )
            
            integration_id = path_parts[-1]
            
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
        """Extract client IP from request headers."""
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
    
    async def _extract_request_data(self, request: Request) -> tuple:
        """Extract timestamp, body, and signature from request."""
        body = await request.body()
        timestamp = request.headers.get("x-timestamp")
        signature = request.headers.get("x-signature")
        
        return timestamp, body, signature
    
    async def _validate_integration(self, integration_id: str):
        """Validate that the integration exists and is active."""
        try:
            result = supabase.table("integrations").select("id", "status", "org_id").eq("id", integration_id).single().execute()
            
            if not result.data:
                logger.warning(f"Webhook received for non-existent integration: {integration_id}")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Integration not found"
                )
            
            if result.data["status"] != "active":
                logger.warning(f"Webhook received for inactive integration: {integration_id}")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Integration is not active"
                )
                
        except Exception as e:
            logger.error(f"Integration validation failed: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Integration validation failed"
            )
    
    async def _validate_ip_whitelist(self, integration_id: str, client_ip: str):
        """Validate client IP against whitelist for the integration."""
        try:
            # Get integration configs
            result = supabase.table("integration_configs").select("value").eq("integration_id", integration_id).eq("key", "allowed_ips").single().execute()
            
            if not result.data:
                return  # No IP whitelist configured, allow all IPs
            
            allowed_ips_str = result.data["value"]
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
    
    async def _validate_signature(self, integration_id: str, timestamp: str, body: bytes, signature: str):
        """Validate HMAC signature of the request."""
        try:
            # Get webhook secret from integration configs
            result = supabase.table("integration_configs").select("value").eq("integration_id", integration_id).eq("key", "webhook_secret").single().execute()
            
            if not result.data:
                logger.warning(f"No webhook secret configured for integration {integration_id}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Webhook secret not configured"
                )
            
            webhook_secret = result.data["value"]
            
            # Validate timestamp (prevent replay attacks)
            if not timestamp:
                logger.warning("Missing timestamp header")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Missing timestamp"
                )
            
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
            
            # Validate signature
            if not signature:
                logger.warning("Missing signature header")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Missing signature"
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
    
    async def _validate_rate_limit(self, integration_id: str, client_ip: str):
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
    
    async def _log_webhook_access(self, integration_id: str, client_ip: str, endpoint: str):
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
                "status": "logged"
            }).execute()
            
        except Exception as e:
            logger.error(f"Failed to log webhook access: {str(e)}")


class WebhookSecurityConfig:
    """Configuration for webhook security settings."""
    
    def __init__(self):
        # Rate limiting defaults
        self.default_rate_limit = 60  # requests per minute
        self.rate_limit_window = 60   # seconds
        
        # Signature validation
        self.timestamp_tolerance = 300  # 5 minutes
        
        # Redis configuration for rate limiting
        self.redis_url = settings.REDIS_URL if hasattr(settings, 'REDIS_URL') else None
        
        # IP whitelisting
        self.default_allowed_ips = []  # Empty list means allow all IPs


# Global security config instance
webhook_security_config = WebhookSecurityConfig()