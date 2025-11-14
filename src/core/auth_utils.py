"""JWT and API key validation utilities."""
from fastapi import HTTPException, status
from pydantic import BaseModel
import logging
from datetime import datetime

from src.core.database import supabase

logger = logging.getLogger(__name__)


class TokenData(BaseModel):
    """Token data extracted from JWT or API key."""
    user_id: str | None = None
    org_id: str | None = None
    kb_id: str | None = None
    api_key_id: str | None = None
    email: str | None = None


async def validate_bearer_token(token: str) -> TokenData:
    """
    Validate bearer token - tries JWT first, then API key.
    
    Args:
        token: Bearer token (JWT from Supabase or API key with sk-/kb_ prefix)
        
    Returns:
        TokenData with extracted user/org/kb info
        
    Raises:
        HTTPException if token is invalid
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No token provided"
        )

    # Check if it's an API key (has sk- or kb_ prefix)
    is_api_key = token.startswith("sk-") or token.startswith("ol-secret-")
    
    # Try JWT first if not an API key
    if not is_api_key:
        try:
            logger.info(f"Attempting JWT validation for token: {token[:20]}...")
            try:
                user = supabase.auth.get_user(token)
                logger.info(f"Supabase get_user result: user={user}")
                logger.info(f"Full user object: {user}")
                actual_user = user.user if hasattr(user, 'user') else user
                user_id = actual_user.id if hasattr(actual_user, 'id') else None
                user_email = actual_user.email if hasattr(actual_user, 'email') else None
                logger.info(f"Extracted user_id={user_id}, email={user_email}")
            except Exception as get_user_e:
                logger.error(f"supabase.auth.get_user failed: {get_user_e}")
                raise

            if actual_user and user_id:
                logger.info(f"JWT validated for user: {user_id}")

                # Get org_id from users table
                org_id = None
                kb_id = None
                try:
                    logger.info(f"Looking up user {user_id} in local users table")
                    user_record = supabase.table("users").select("org_id").eq("id", user_id).single().execute()
                    org_id = user_record.data.get("org_id") if user_record.data else None
                    logger.info(f"User record found: org_id={org_id}")

                    # Get default kb_id for the org
                    if org_id:
                        kb_result = supabase.table("knowledge_bases").select("id").eq("org_id", org_id).limit(1).execute()
                        kb_id = kb_result.data[0]["id"] if kb_result.data else None
                        logger.info(f"KB lookup result: kb_id={kb_id}")
                except Exception as e:
                    logger.warning(f"User {user_id} not found in local users table: {e}")

                logger.info(f"Returning TokenData: user_id={user_id}, org_id={org_id}, kb_id={kb_id}")
                return TokenData(
                    user_id=user_id,
                    org_id=org_id,
                    kb_id=kb_id,
                    email=user_email
                )
        except Exception as e:
            logger.debug(f"JWT validation failed: {e}")
            # If JWT fails and it doesn't look like an API key, it's invalid
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid JWT token"
            )

    # Validate API key
    logger.info(f"Validating API key: {token[:15]}...")
    try:
        result = supabase.rpc("verify_api_key", {"p_plain_key": token}).execute()
        
        if result.data and len(result.data) > 0:
            key_info = result.data[0]
            logger.info(f"API key validated for org: {key_info.get('org_id')}")
            
            # Update last_used_at
            try:
                supabase.rpc("update_key_last_used", {"key_id": key_info.get("id")}).execute()
            except Exception:
                pass
            
            return TokenData(
                user_id=None,
                org_id=key_info.get('org_id'),
                kb_id=key_info.get('kb_id'),
                api_key_id=key_info.get('id')
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"API key validation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )
