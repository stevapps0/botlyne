"""Main FastAPI application entry point."""
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from datetime import datetime

from src.api.v1 import auth, kb, query, upload, apikeys, integrations
from src.core.database import supabase
from src.core.auth import get_current_user, require_admin, security

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager."""
    # Startup
    logger.info("Starting Knowledge Base AI API")
    yield
    # Shutdown
    logger.info("Shutting down Knowledge Base AI API")


# Initialize FastAPI application
app = FastAPI(
    title="Knowledge Base AI API",
    version="1.0.0",
    description="Multi-tenant knowledge base with AI agent and human handoff",
    lifespan=lifespan
)

# CORS middleware - TODO: Configure for production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8081"],  # Specific origins for security
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health check endpoint
@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "message": "Knowledge Base AI API is running"
    }


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