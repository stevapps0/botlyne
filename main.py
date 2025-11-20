"""Main FastAPI application entry point."""
import logging
from contextlib import asynccontextmanager
from typing import Optional

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    redis = None
    REDIS_AVAILABLE = False

from fastapi import Depends, FastAPI, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from datetime import datetime

from src.api.v1 import auth, kb, query, upload, apikeys, integrations
from src.core.database import supabase
from src.core.auth import get_current_user, require_admin, security
from src.core.config import settings
from src.middleware.webhook_security import WebhookSecurityMiddleware
from src.services.error_handling import structured_logger

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# Global Redis client for webhook rate limiting
redis_client = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager."""
    global redis_client
    
    # Startup
    logger.info("Starting Knowledge Base AI API")
    
    # Initialize Redis for rate limiting if available
    try:
        redis_url = getattr(settings, 'REDIS_URL', None)
        if redis_url:
            redis_client = redis.from_url(redis_url)
            await redis_client.ping()
            logger.info("Redis connection established for rate limiting")
        else:
            logger.info("Redis not configured, using in-memory rate limiting")
    except Exception as e:
        logger.warning(f"Redis connection failed: {e}. Using in-memory rate limiting.")
        redis_client = None
    
    yield
    
    # Shutdown
    logger.info("Shutting down Knowledge Base AI API")
    
    # Close Redis connection
    if redis_client:
        await redis_client.close()


# Initialize FastAPI application
app = FastAPI(
    title="Knowledge Base AI API",
    version="1.0.0",
    description="Multi-tenant knowledge base with AI agent and human handoff",
    lifespan=lifespan
)

# Add webhook security middleware
app.add_middleware(WebhookSecurityMiddleware, redis_client=redis_client)

# CORS middleware - TODO: Configure for production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8081"],  # Specific origins for security
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Exception handler for validation errors
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Log validation errors with request details."""
    try:
        body = await request.body()
        logger.error(f"Validation error on {request.url.path}: {exc.errors()}, body: {body.decode('utf-8', errors='ignore')}")
    except Exception as log_error:
        logger.error(f"Failed to log validation error: {log_error}, errors: {exc.errors()}")

    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()},
    )


# Health check endpoint
@app.get("/health")
async def health_check() -> dict:
    """Basic health check endpoint."""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "message": "Knowledge Base AI API is running"
    }

# Comprehensive health check endpoint
@app.get("/health/detailed")
async def detailed_health_check():
    """Detailed health check with all service checks."""
    from src.services.health_checks import health_check_manager
    
    try:
        health_status = await health_check_manager.run_all_checks()
        return health_status
    except Exception as e:
        structured_logger.error("Health check failed", exception=e)
        return {
            "overall_status": "unhealthy",
            "timestamp": datetime.utcnow().isoformat(),
            "error": str(e),
            "checks": {},
            "critical_issues": [f"Health check system error: {str(e)}"]
        }

# Metrics endpoint
@app.get("/metrics")
async def get_metrics():
    """Get system metrics."""
    from src.services.health_checks import metrics_collector
    
    try:
        return metrics_collector.get_metrics_summary()
    except Exception as e:
        structured_logger.error("Failed to get metrics", exception=e)
        return {"error": str(e)}


# Root endpoint
@app.get("/")
async def root() -> dict:
    """API information endpoint."""
    return {
        "name": "Knowledge Base AI API",
        "version": "1.0.0",
        "description": "Multi-tenant knowledge base with AI agent",
        "docs": "/docs",
        "health": "/health"
    }


# Include API route modules
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(auth.router, prefix="", tags=["Authentication"])  # Also mount at root for /auth/callback
app.include_router(kb.router, prefix="/api/v1", tags=["Knowledge Bases"])
app.include_router(upload.router, prefix="/api/v1", tags=["Uploads"])
app.include_router(query.router, prefix="/api/v1", tags=["Querying"])
app.include_router(apikeys.router, prefix="/api/v1", tags=["API Keys"])
app.include_router(integrations.router, prefix="/api/v1", tags=["Integrations"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)