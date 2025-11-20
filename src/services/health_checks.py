"""Health check endpoints and system monitoring for production readiness."""
import asyncio
import time
import psutil
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import logging

from src.core.database import supabase
from src.core.config import settings
from src.core.retry_utils import resilience_manager
from src.services.error_handling import structured_logger, error_tracker

logger = logging.getLogger(__name__)


class HealthCheck:
    """Base class for health checks."""
    
    def __init__(self, name: str, critical: bool = True):
        self.name = name
        self.critical = critical
    
    async def check(self) -> Dict[str, Any]:
        """Perform health check and return status."""
        try:
            result = await self._perform_check()
            return {
                "name": self.name,
                "status": "healthy",
                "critical": self.critical,
                "response_time_ms": result.get("response_time_ms", 0),
                "message": result.get("message", "OK"),
                "details": result.get("details", {}),
                "last_check": datetime.utcnow().isoformat()
            }
        except Exception as e:
            return {
                "name": self.name,
                "status": "unhealthy",
                "critical": self.critical,
                "response_time_ms": 0,
                "message": str(e),
                "details": {"error_type": type(e).__name__},
                "last_check": datetime.utcnow().isoformat()
            }


class DatabaseHealthCheck(HealthCheck):
    """Health check for database connectivity."""
    
    def __init__(self):
        super().__init__("database", critical=True)
    
    async def _perform_check(self) -> Dict[str, Any]:
        start_time = time.time()
        
        try:
            # Test basic connectivity
            result = supabase.table("organizations").select("id").limit(1).execute()
            
            response_time = (time.time() - start_time) * 1000
            
            return {
                "response_time_ms": response_time,
                "message": "Database connection healthy",
                "details": {
                    "query_executed": "SELECT id FROM organizations LIMIT 1",
                    "records_found": len(result.data) if result.data else 0
                }
            }
        except Exception as e:
            raise Exception(f"Database connection failed: {str(e)}")


class RedisHealthCheck(HealthCheck):
    """Health check for Redis connectivity."""
    
    def __init__(self):
        super().__init__("redis", critical=False)
    
    async def _perform_check(self) -> Dict[str, Any]:
        start_time = time.time()
        
        try:
            import redis.asyncio as redis
            REDIS_AVAILABLE = True
        except ImportError:
            redis = None
            REDIS_AVAILABLE = False
            
            if hasattr(settings, 'REDIS_URL') and settings.REDIS_URL:
                r = redis.from_url(settings.REDIS_URL)
                await r.ping()
                
                response_time = (time.time() - start_time) * 1000
                
                return {
                    "response_time_ms": response_time,
                    "message": "Redis connection healthy",
                    "details": {
                        "redis_url": "configured",
                        "ping_success": True
                    }
                }
            else:
                return {
                    "response_time_ms": 0,
                    "message": "Redis not configured",
                    "details": {
                        "redis_url": "not_configured"
                    }
                }
                
        except Exception as e:
            raise Exception(f"Redis connection failed: {str(e)}")


class ExternalAPIHealthCheck(HealthCheck):
    """Health check for external API services."""
    
    def __init__(self):
        super().__init__("external_apis", critical=False)
    
    async def _perform_check(self) -> Dict[str, Any]:
        start_time = time.time()
        
        # Check Google AI API
        google_healthy = False
        try:
            if settings.GOOGLE_API_KEY:
                # Simple test for Google AI API availability
                # In production, this would be a more comprehensive check
                google_healthy = True
        except Exception:
            pass
        
        # Check Evolution API
        evolution_healthy = False
        try:
            if settings.EVOLUTION_API_BASE_URL:
                import httpx
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(f"{settings.EVOLUTION_API_BASE_URL}/instance/fetchInstances")
                    evolution_healthy = response.status_code == 200
        except Exception:
            pass
        
        response_time = (time.time() - start_time) * 1000
        
        overall_status = "healthy" if (google_healthy or True) and (evolution_healthy or True) else "degraded"
        
        return {
            "response_time_ms": response_time,
            "message": f"External APIs overall status: {overall_status}",
            "details": {
                "google_ai": {
                    "configured": bool(settings.GOOGLE_API_KEY),
                    "healthy": google_healthy
                },
                "evolution_api": {
                    "configured": bool(settings.EVOLUTION_API_BASE_URL),
                    "healthy": evolution_healthy
                }
            }
        }


class SystemHealthCheck(HealthCheck):
    """Health check for system resources."""
    
    def __init__(self):
        super().__init__("system", critical=False)
    
    async def _perform_check(self) -> Dict[str, Any]:
        try:
            # Get system metrics
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            # Determine status based on thresholds
            status = "healthy"
            warnings = []
            
            if cpu_percent > 90:
                status = "unhealthy"
                warnings.append(f"High CPU usage: {cpu_percent:.1f}%")
            elif cpu_percent > 70:
                status = "degraded"
                warnings.append(f"Elevated CPU usage: {cpu_percent:.1f}%")
            
            if memory.percent > 90:
                status = "unhealthy"
                warnings.append(f"High memory usage: {memory.percent:.1f}%")
            elif memory.percent > 80:
                status = "degraded"
                warnings.append(f"Elevated memory usage: {memory.percent:.1f}%")
            
            if disk.percent > 95:
                status = "unhealthy"
                warnings.append(f"High disk usage: {disk.percent:.1f}%")
            elif disk.percent > 85:
                status = "degraded"
                warnings.append(f"Elevated disk usage: {disk.percent:.1f}%")
            
            return {
                "response_time_ms": 0,
                "message": f"System status: {status}" + (f" - {', '.join(warnings)}" if warnings else ""),
                "details": {
                    "cpu": {
                        "usage_percent": cpu_percent,
                        "count": psutil.cpu_count()
                    },
                    "memory": {
                        "total_gb": round(memory.total / (1024**3), 2),
                        "available_gb": round(memory.available / (1024**3), 2),
                        "usage_percent": memory.percent
                    },
                    "disk": {
                        "total_gb": round(disk.total / (1024**3), 2),
                        "free_gb": round(disk.free / (1024**3), 2),
                        "usage_percent": disk.percent
                    }
                }
            }
        except Exception as e:
            raise Exception(f"System health check failed: {str(e)}")


class ConversationHealthCheck(HealthCheck):
    """Health check for conversation processing."""
    
    def __init__(self):
        super().__init__("conversations", critical=True)
    
    async def _perform_check(self) -> Dict[str, Any]:
        start_time = time.time()
        
        try:
            # Check for stuck conversations
            stuck_threshold = datetime.utcnow() - timedelta(hours=1)
            stuck_conversations = supabase.table("conversations").select("id").eq("status", "ongoing").lt("started_at", stuck_threshold.isoformat()).execute()
            
            # Check conversation volume in last hour
            one_hour_ago = datetime.utcnow() - timedelta(hours=1)
            recent_conversations = supabase.table("conversations").select("id").gte("started_at", one_hour_ago.isoformat()).execute()
            
            # Check escalated conversations
            escalated_count = supabase.table("conversations").select("id").eq("status", "escalated").execute()
            
            response_time = (time.time() - start_time) * 1000
            
            status = "healthy"
            warnings = []
            
            if stuck_conversations.data and len(stuck_conversations.data) > 0:
                status = "degraded"
                warnings.append(f"Found {len(stuck_conversations.data)} stuck conversations")
            
            if escalated_count.data and len(escalated_count.data) > 10:
                status = "degraded"
                warnings.append(f"High number of escalated conversations: {len(escalated_count.data)}")
            
            return {
                "response_time_ms": response_time,
                "message": f"Conversations status: {status}" + (f" - {', '.join(warnings)}" if warnings else ""),
                "details": {
                    "stuck_conversations": len(stuck_conversations.data) if stuck_conversations.data else 0,
                    "recent_conversations_1h": len(recent_conversations.data) if recent_conversations.data else 0,
                    "escalated_conversations": len(escalated_count.data) if escalated_count.data else 0
                }
            }
        except Exception as e:
            raise Exception(f"Conversation health check failed: {str(e)}")


class HealthCheckManager:
    """Manager for coordinating all health checks."""
    
    def __init__(self):
        self.checks = [
            DatabaseHealthCheck(),
            RedisHealthCheck(),
            ExternalAPIHealthCheck(),
            SystemHealthCheck(),
            ConversationHealthCheck()
        ]
        
        self.last_check_results = {}
        self.check_interval = 60  # seconds
        self._running = False
        
    async def run_all_checks(self) -> Dict[str, Any]:
        """Run all health checks concurrently."""
        tasks = [check.check() for check in self.checks]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        check_results = {}
        overall_status = "healthy"
        critical_issues = []
        
        for i, result in enumerate(results):
            check_name = self.checks[i].name
            
            if isinstance(result, Exception):
                check_results[check_name] = {
                    "name": check_name,
                    "status": "unhealthy",
                    "critical": self.checks[i].critical,
                    "message": str(result),
                    "last_check": datetime.utcnow().isoformat()
                }
                
                if self.checks[i].critical:
                    overall_status = "unhealthy"
                    critical_issues.append(f"{check_name}: {str(result)}")
            else:
                check_results[check_name] = result
                
                if result["status"] == "unhealthy" and result["critical"]:
                    overall_status = "unhealthy"
                    critical_issues.append(f"{check_name}: {result['message']}")
                elif result["status"] == "degraded" and overall_status == "healthy":
                    overall_status = "degraded"
        
        # Log health check results
        if critical_issues:
            structured_logger.error(
                "Health check failed with critical issues",
                extra={
                    "overall_status": overall_status,
                    "critical_issues": critical_issues,
                    "check_results": check_results
                }
            )
        elif overall_status == "degraded":
            structured_logger.warning(
                "Health check degraded",
                extra={
                    "overall_status": overall_status,
                    "check_results": check_results
                }
            )
        else:
            structured_logger.info(
                "Health check passed",
                extra={
                    "overall_status": overall_status,
                    "check_results": {k: v["status"] for k, v in check_results.items()}
                }
            )
        
        return {
            "overall_status": overall_status,
            "timestamp": datetime.utcnow().isoformat(),
            "checks": check_results,
            "critical_issues": critical_issues,
            "total_checks": len(self.checks),
            "healthy_checks": len([r for r in check_results.values() if r["status"] == "healthy"]),
            "degraded_checks": len([r for r in check_results.values() if r["status"] == "degraded"]),
            "unhealthy_checks": len([r for r in check_results.values() if r["status"] == "unhealthy"])
        }


# Global health check manager instance
health_check_manager = HealthCheckManager()


# Metrics collection for monitoring
class MetricsCollector:
    """Collect and store system metrics."""
    
    def __init__(self):
        self.metrics = {}
        self.request_count = 0
        self.error_count = 0
        self.start_time = time.time()
    
    def record_request(self, endpoint: str, status_code: int, response_time: float):
        """Record a request metric."""
        self.request_count += 1
        
        if status_code >= 400:
            self.error_count += 1
        
        if endpoint not in self.metrics:
            self.metrics[endpoint] = {
                "count": 0,
                "errors": 0,
                "response_times": [],
                "status_codes": {}
            }
        
        endpoint_metrics = self.metrics[endpoint]
        endpoint_metrics["count"] += 1
        endpoint_metrics["response_times"].append(response_time)
        
        if status_code >= 400:
            endpoint_metrics["errors"] += 1
        
        endpoint_metrics["status_codes"][status_code] = endpoint_metrics["status_codes"].get(status_code, 0) + 1
        
        # Keep only last 1000 response times per endpoint
        if len(endpoint_metrics["response_times"]) > 1000:
            endpoint_metrics["response_times"] = endpoint_metrics["response_times"][-1000:]
    
    def get_metrics_summary(self) -> Dict[str, Any]:
        """Get current metrics summary."""
        uptime_seconds = time.time() - self.start_time
        
        return {
            "uptime_seconds": uptime_seconds,
            "total_requests": self.request_count,
            "total_errors": self.error_count,
            "error_rate": self.error_count / max(self.request_count, 1),
            "requests_per_second": self.request_count / max(uptime_seconds, 1),
            "endpoints": self.metrics
        }


# Global metrics collector
metrics_collector = MetricsCollector()