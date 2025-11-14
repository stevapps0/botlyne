"""Centralized authentication service."""
import logging
from datetime import datetime
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from .database import supabase, sha256_hex as hash_api_key
from .auth_utils import TokenData

logger = logging.getLogger(__name__)

# Security scheme
security = HTTPBearer()


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
            # Validate API key (hash for security)
            key_data = supabase.table("api_keys").select("org_id, permissions, is_active, expires_at").eq("key_hash", hash_api_key(token)).single().execute()

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
            supabase.table("api_keys").update({"last_used_at": "now"}).eq("key_hash", hash_api_key(token)).execute()

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


async def require_admin(current_user: TokenData = Depends(get_current_user)) -> TokenData:
    """Ensure user has admin role."""
    user_data = supabase.table("users").select("role").eq("id", current_user.user_id).single().execute()
    if user_data.data.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user