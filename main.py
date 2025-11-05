"""Main FastAPI application entry point."""
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from datetime import datetime

from src.api.v1 import auth, kb, query, upload, apikeys
from src.core.database import supabase

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# Pydantic models
class TokenData(BaseModel):
    """User token data model."""
    user_id: str
    org_id: str | None = None


# Security
security = HTTPBearer()


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

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Dependency to get current user (supports both JWT and API keys)
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> TokenData:
    """Extract and validate user from JWT token or API key."""
    try:
        token = credentials.credentials if credentials else None

        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required"
            )

        # Check if it's an API key (starts with "kb_" or "sk-")
        if token.startswith("kb_") or token.startswith("sk-"):
            # Validate API key (stored as plain text)
            key_data = supabase.table("api_keys").select("org_id, permissions, is_active, expires_at").eq("key_hash", token).single().execute()

            if not key_data.data:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid API key"
                )

            key_info = key_data.data
            if not key_info["is_active"]:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="API key is disabled"
                )

            if key_info["expires_at"] and datetime.fromisoformat(key_info["expires_at"].replace('Z', '+00:00')) < datetime.utcnow():
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="API key has expired"
                )

            # Update last_used_at
            supabase.table("api_keys").update({"last_used_at": "now"}).eq("key_hash", token).execute()

            return TokenData(user_id="api_key_user", org_id=key_info["org_id"])

        else:
            # Validate JWT token with Supabase
            response = supabase.auth.get_user(token)
            user = response.user

            if not user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token"
                )

            # Get org_id from users table
            user_data = supabase.table("users").select("org_id").eq("id", user.id).single().execute()
            org_id = user_data.data.get("org_id") if user_data.data else None

            return TokenData(user_id=user.id, org_id=org_id)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Authentication error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed"
        )


# Dependency to check admin role
async def require_admin(current_user: TokenData = Depends(get_current_user)) -> TokenData:
    """Ensure user has admin role."""
    user_data = supabase.table("users").select("role").eq("id", current_user.user_id).single().execute()
    if user_data.data.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)