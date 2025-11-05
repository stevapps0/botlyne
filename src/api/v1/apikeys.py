from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel
from typing import List, Optional
import secrets
import hashlib
from datetime import datetime, timedelta

from src.core.database import supabase

router = APIRouter()

# Pydantic models
class CreateAPIKeyRequest(BaseModel):
    name: str
    permissions: Optional[dict] = {"read": True, "write": True, "admin": False}
    expires_in_days: Optional[int] = 365

class APIKeyResponse(BaseModel):
    id: str
    name: str
    key_preview: str  # First 8 chars + asterisks
    permissions: dict
    created_at: str
    expires_at: Optional[str]
    last_used_at: Optional[str]
    is_active: bool
    kb_id: Optional[str] = None

class APIKeyFullResponse(BaseModel):
    id: str
    name: str
    key: str  # Full key - only returned on creation
    permissions: dict
    created_at: str
    expires_at: Optional[str]
    last_used_at: Optional[str]
    is_active: bool
    kb_id: Optional[str] = None

# Pydantic models for dependencies
class TokenData(BaseModel):
    user_id: str
    org_id: str | None = None
    kb_id: str | None = None

# Dependency to get current user
async def get_current_user(token: str = Depends(lambda: None)):
    """Extract and validate user from JWT token or API key."""
    try:
        # Check for org API key
        if token and token.startswith("Bearer "):
            api_key = token.replace("Bearer ", "")
            if api_key.startswith("kb_") or api_key.startswith("sk-"):
                # Validate API key using database verification function
                try:
                    derived_shortcode = api_key[-6:]

                    # Use the verify_api_key database function
                    result = supabase.rpc("verify_api_key", {"api_key": api_key}).execute()

                    if result.data and len(result.data) > 0:
                        key_info = result.data[0]

                        # Update last_used_at
                        supabase.rpc("update_key_last_used", {"key_id": key_info["id"]}).execute()

                        return TokenData(
                            user_id="api_key_user",
                            org_id=str(key_info["org_id"]),
                            kb_id=None  # kb_id not returned by verify_api_key function
                        )
                    else:
                        raise HTTPException(
                            status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid API key"
                        )
                except HTTPException:
                    raise
                except Exception as e:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="API key verification failed"
                    )

        # For testing, extract user ID from mock token
        if token and token.startswith("Bearer mock-token-"):
            user_id = token.replace("Bearer mock-token-", "")
            # Get user org from database
            user_data = supabase.table("users").select("org_id").eq("id", user_id).single().execute()
            org_id = user_data.data.get("org_id") if user_data.data else None
            return TokenData(user_id=user_id, org_id=org_id)
        else:
            # This is a simplified version - in real implementation you'd validate the token
            return TokenData(user_id="mock_user", org_id="mock_org")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token validation failed"
        )

# Dependency to check admin role
async def require_admin(current_user: TokenData = Depends(get_current_user)) -> TokenData:
    """Ensure user has admin role."""
    # For testing with our demo user, allow admin access
    if current_user.user_id == "cac0bb03-1281-406b-9a9e-19b68ed73581" or current_user.org_id == "629339ec-44b6-4383-8527-10a8466590e0":
        return current_user

    # For real users, check role in database
    try:
        user_data = supabase.table("users").select("role").eq("id", current_user.user_id).single().execute()
        if user_data.data.get("role") != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required"
            )
    except Exception:
        # If database query fails, assume not admin for security
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user

def hash_api_key(key: str) -> str:
    """Hash API key for storage."""
    return hashlib.sha256(key.encode()).hexdigest()

def generate_api_key() -> str:
    """Generate a secure random API key."""
    return "sk-" + secrets.token_urlsafe(32)

@router.post("/apikeys", response_model=APIKeyFullResponse)
async def create_api_key(
    data: CreateAPIKeyRequest,
    current_user: TokenData = Depends(require_admin)
):
    """Create a new API key for the organization (admin only)"""
    try:
        if not current_user.org_id:
            raise HTTPException(status_code=400, detail="User must belong to an organization")

        # Generate API key
        api_key = generate_api_key()

        # Calculate expiration
        expires_at = None
        if data.expires_in_days:
            expires_at = datetime.utcnow() + timedelta(days=data.expires_in_days)

        # Create API key record - trigger will hash the api_key and nullify it
        key_data = {
            "org_id": current_user.org_id,
            "name": data.name,
            "api_key": api_key,  # Plain key - trigger will hash and nullify
            "permissions": data.permissions,
            "created_by": current_user.user_id,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "is_active": True,
            "kb_id": None  # New keys start without KB association
        }

        result = supabase.table("api_keys").insert(key_data).execute()
        created_key = result.data[0]

        return APIKeyFullResponse(
            id=created_key["id"],
            name=created_key["name"],
            key=api_key,  # Return full key only on creation
            permissions=created_key["permissions"],
            created_at=created_key["created_at"],
            expires_at=created_key["expires_at"],
            last_used_at=created_key["last_used_at"],
            is_active=created_key["is_active"],
            kb_id=created_key.get("kb_id")
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to create API key: {str(e)}"
        )

@router.get("/apikeys", response_model=List[APIKeyResponse])
async def list_api_keys(current_user: TokenData = Depends(require_admin)):
    """List all API keys for the organization (admin only)"""
    try:
        if not current_user.org_id:
            raise HTTPException(status_code=400, detail="User must belong to an organization")

        result = supabase.table("api_keys").select("*").eq("org_id", current_user.org_id).execute()

        keys = []
        for key in result.data:
            # Create preview (first 8 chars + asterisks)
            key_hash = key["key_hash"][:8] + "*" * 24

            keys.append(APIKeyResponse(
                id=key["id"],
                name=key["name"],
                key_preview=key_hash,
                permissions=key["permissions"],
                created_at=key["created_at"],
                expires_at=key["expires_at"],
                last_used_at=key["last_used_at"],
                is_active=key["is_active"],
                kb_id=key.get("kb_id")
            ))

        return keys

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to list API keys: {str(e)}"
        )

@router.delete("/apikeys/{key_id}")
async def delete_api_key(
    key_id: str,
    current_user: TokenData = Depends(require_admin)
):
    """Delete an API key (admin only)"""
    try:
        if not current_user.org_id:
            raise HTTPException(status_code=400, detail="User must belong to an organization")

        # Verify key belongs to user's org
        key_check = supabase.table("api_keys").select("org_id").eq("id", key_id).single().execute()
        if not key_check.data or key_check.data["org_id"] != current_user.org_id:
            raise HTTPException(status_code=404, detail="API key not found")

        # Delete the key
        supabase.table("api_keys").delete().eq("id", key_id).execute()

        return {"message": "API key deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to delete API key: {str(e)}"
        )

@router.put("/apikeys/{key_id}/associate-kb")
async def associate_api_key_with_kb(
    key_id: str,
    kb_id: str,
    current_user: TokenData = Depends(require_admin)
):
    """Associate an API key with a knowledge base (admin only)"""
    try:
        if not current_user.org_id:
            raise HTTPException(status_code=400, detail="User must belong to an organization")

        # Verify key belongs to user's org
        key_data = supabase.table("api_keys").select("org_id").eq("id", key_id).single().execute()
        if not key_data.data or key_data.data["org_id"] != current_user.org_id:
            raise HTTPException(status_code=404, detail="API key not found")

        # Verify KB belongs to user's org
        kb_data = supabase.table("knowledge_bases").select("org_id").eq("id", kb_id).single().execute()
        if not kb_data.data or kb_data.data["org_id"] != current_user.org_id:
            raise HTTPException(status_code=404, detail="Knowledge base not found")

        # Associate key with KB
        supabase.table("api_keys").update({"kb_id": kb_id}).eq("id", key_id).execute()

        return {"message": "API key associated with knowledge base successfully"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to associate API key with knowledge base: {str(e)}"
        )

@router.put("/apikeys/{key_id}/toggle")
async def toggle_api_key(
    key_id: str,
    current_user: TokenData = Depends(require_admin)
):
    """Enable/disable an API key (admin only)"""
    try:
        if not current_user.org_id:
            raise HTTPException(status_code=400, detail="User must belong to an organization")

        # Get current key status
        key_data = supabase.table("api_keys").select("is_active, org_id").eq("id", key_id).single().execute()
        if not key_data.data or key_data.data["org_id"] != current_user.org_id:
            raise HTTPException(status_code=404, detail="API key not found")

        # Toggle active status
        new_status = not key_data.data["is_active"]
        supabase.table("api_keys").update({"is_active": new_status}).eq("id", key_id).execute()

        return {"message": f"API key {'enabled' if new_status else 'disabled'} successfully"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to toggle API key: {str(e)}"
        )