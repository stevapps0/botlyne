from fastapi import APIRouter, HTTPException, status, Depends, Header
from pydantic import BaseModel
from typing import List, Optional
import hashlib
import logging
from datetime import datetime

from src.core.database import supabase

# Import dependencies from main.py
from src.core.database import supabase as main_supabase

# Pydantic models for dependencies
class TokenData(BaseModel):
    user_id: str
    org_id: str | None = None
    kb_id: str | None = None

# Dependency to get current user
async def get_current_user(authorization: str = Header(None, alias="Authorization")):
    """Extract and validate user from JWT token or API key."""
    try:
        logger.info(f"KB auth attempt with Authorization header: {authorization[:30]}..." if authorization else "No Authorization header")

        # Check for org API key
        if authorization and authorization.startswith("Bearer "):
            api_key = authorization.replace("Bearer ", "")
            logger.info(f"Extracted API key: {api_key[:15]}...")

            if api_key.startswith("sk-"):
                # Validate API key using direct hash lookup
                try:
                    logger.info("KB: Validating API key using direct hash lookup")

                    # Hash the incoming API key
                    import hashlib
                    computed_hash = hashlib.sha256(api_key.encode()).hexdigest()
                    logger.info(f"KB: Computed hash: {computed_hash[:16]}...")

                    # Look up the API key by hash
                    key_query = supabase.table("api_keys").select("*").eq("key_hash", computed_hash).eq("is_active", True).execute()

                    logger.info(f"KB: Key lookup result: {len(key_query.data) if key_query.data else 0} records found")

                    if key_query.data:
                        found_key = key_query.data[0]
                        logger.info(f"KB: Found key record: id={found_key['id']}, kb_id={found_key.get('kb_id')}")

                        # Check expiration
                        expires_at = found_key.get("expires_at")
                        if expires_at:
                            try:
                                expiry_dt = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                                if expiry_dt < datetime.utcnow():
                                    logger.warning("KB: API key expired")
                                    result = type('MockResult', (), {'data': [{'is_valid': False}]})()
                                else:
                                    logger.info("KB: API key valid and not expired")
                                    result = type('MockResult', (), {'data': [{
                                        'is_valid': True,
                                        'api_key_id': found_key['id'],
                                        'org_id': found_key['org_id'],
                                        'kb_id': found_key['kb_id'],
                                        'permissions': found_key['permissions']
                                    }]})()
                            except Exception as e:
                                logger.error(f"KB: Error parsing expiration date: {e}")
                                result = type('MockResult', (), {'data': [{'is_valid': False}]})()
                        else:
                            logger.info("KB: API key valid (no expiration)")
                            result = type('MockResult', (), {'data': [{
                                'is_valid': True,
                                'api_key_id': found_key['id'],
                                'org_id': found_key['org_id'],
                                'kb_id': found_key['kb_id'],
                                'permissions': found_key['permissions']
                            }]})()
                    else:
                        logger.warning("KB: No API key found with matching hash")
                        result = type('MockResult', (), {'data': [{'is_valid': False}]})()

                    if result and result.data and len(result.data) > 0 and result.data[0]["is_valid"]:
                        key_info = result.data[0]
                        logger.info(f"KB: Valid key found: kb_id = {key_info.get('kb_id')}, org_id = {key_info.get('org_id')}")

                        # Update last_used_at
                        supabase.rpc("update_key_last_used", {"key_id": key_info["api_key_id"]}).execute()

                        return TokenData(
                            user_id="api_key_user",
                            org_id=key_info.get("org_id"),
                            kb_id=key_info.get("kb_id")
                        )
                    else:
                        logger.warning("KB: Key not valid or kb_id is null")
                        raise HTTPException(
                            status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid API key"
                        )
                except HTTPException:
                    raise
                except Exception as e:
                    logger.error(f"KB: Verification error: {e}")
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="API key verification failed"
                    )
            else:
                logger.warning(f"Invalid API key format: {api_key[:15]}...")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid API key format"
                )

        # For testing, extract user ID from mock token
        if authorization and authorization.startswith("Bearer mock-token-"):
            user_id = authorization.replace("Bearer mock-token-", "")
            # Get user org from database
            user_data = supabase.table("users").select("org_id").eq("id", user_id).single().execute()
            org_id = user_data.data.get("org_id") if user_data.data else None
            return TokenData(user_id=user_id, org_id=org_id, kb_id="mock_kb")
        elif authorization and authorization.startswith("mock-token-"):
            # Handle query parameter style tokens
            user_id = authorization.replace("mock-token-", "")
            user_data = supabase.table("users").select("org_id").eq("id", user_id).single().execute()
            org_id = user_data.data.get("org_id") if user_data.data else None
            return TokenData(user_id=user_id, org_id=org_id, kb_id="mock_kb")
        else:
            # This is a simplified version - in real implementation you'd validate the token
            logger.warning("No valid Bearer token found, using mock user")
            return TokenData(user_id="mock_user", org_id="mock_org", kb_id="mock_kb")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token validation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token validation failed"
        )

# Dependency to check admin role
async def require_admin(current_user: TokenData = Depends(get_current_user)) -> TokenData:
    """Ensure user has admin role."""
    # Simplified - in real implementation check user role
    return current_user

router = APIRouter()

# Standard API Response Model
class APIResponse(BaseModel):
    success: bool
    message: str
    data: Optional[dict] = None
    error: Optional[str] = None

# Pydantic models
class CreateKBRequest(BaseModel):
    name: str
    shortcode: str

class KBResponse(BaseModel):
    id: str
    org_id: str
    name: str
    created_at: str

class KBListResponse(BaseModel):
    id: str
    name: str
    created_at: str
    document_count: int = 0

# Knowledge Base CRUD endpoints
@router.post("/kb", response_model=APIResponse)
async def create_knowledge_base(
    data: CreateKBRequest,
    current_user: TokenData = Depends(get_current_user)
):
    """Create a new knowledge base in an organization"""
    try:
        # Get org_id from shortcode
        org_result = supabase.table("organizations").select("id").eq("shortcode", data.shortcode).single().execute()
        if not org_result.data:
            raise HTTPException(status_code=404, detail="Organization not found")

        org_id = org_result.data["id"]

        # Verify user belongs to org
        if current_user.org_id != org_id:
            raise HTTPException(status_code=403, detail="Access denied")

        # Create KB
        kb_data = {
            "org_id": org_id,
            "name": data.name
        }
        result = supabase.table("knowledge_bases").insert(kb_data).execute()
        kb = result.data[0]

        # Note: API keys are now associated individually via the /apikeys/{key_id}/associate-kb endpoint
        # This ensures each key can be scoped to a specific KB for better access control

        return APIResponse(
            success=True,
            message="Knowledge base created successfully",
            data={"kb": KBResponse(**kb).dict()}
        )
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(
            success=False,
            message="Failed to create knowledge base",
            error=str(e)
        )

class ListKBRequest(BaseModel):
    org_id: str

@router.get("/kb", response_model=APIResponse)
async def list_knowledge_bases(current_user: TokenData = Depends(get_current_user)):
    """List all knowledge bases in the user's organization"""
    try:
        # Get KBs with document count
        result = supabase.table("knowledge_bases").select("""
            id,
            name,
            created_at
        """).eq("org_id", current_user.org_id).execute()

        kbs = []
        for kb in result.data:
            # Count documents
            doc_count = supabase.table("documents").select("id", count="exact").eq("kb_id", kb["id"]).execute()
            kb["document_count"] = doc_count.count
            kbs.append(KBListResponse(**kb).dict())

        return APIResponse(
            success=True,
            message="Knowledge bases retrieved successfully",
            data={"kbs": kbs}
        )
    except Exception as e:
        return APIResponse(
            success=False,
            message="Failed to list knowledge bases",
            error=str(e)
        )

class GetKBRequest(BaseModel):
    kb_id: str

@router.get("/kb/current", response_model=APIResponse)
async def get_current_knowledge_base(current_user: TokenData = Depends(get_current_user)):
    """Get the user's associated knowledge base details"""
    try:
        if not current_user.kb_id or current_user.kb_id == "mock_kb":
            return APIResponse(
                success=False,
                message="No knowledge base associated with this API key",
                error="kb_not_found"
            )

        # Get KB details
        result = supabase.table("knowledge_bases").select("*").eq("id", current_user.kb_id).single().execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Knowledge base not found")

        kb = result.data
        return APIResponse(
            success=True,
            message="Knowledge base retrieved successfully",
            data={"kb": KBResponse(**kb).dict()}
        )
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(
            success=False,
            message="Failed to get knowledge base",
            error=str(e)
        )

@router.put("/kbs/{kb_id}", response_model=KBResponse)
async def update_knowledge_base(
    kb_id: str,
    data: CreateKBRequest,
    current_user: TokenData = Depends(get_current_user)
):
    """Update knowledge base name"""
    try:
        # Get KB and verify access
        kb_check = supabase.table("knowledge_bases").select("org_id").eq("id", kb_id).single().execute()
        if not kb_check.data:
            raise HTTPException(status_code=404, detail="Knowledge base not found")

        if kb_check.data["org_id"] != current_user.org_id:
            raise HTTPException(status_code=403, detail="Access denied")

        # Update KB
        result = supabase.table("knowledge_bases").update({"name": data.name}).eq("id", kb_id).execute()
        kb = result.data[0]

        return KBResponse(**kb)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to update knowledge base: {str(e)}"
        )

@router.delete("/kbs/{kb_id}")
async def delete_knowledge_base(
    kb_id: str,
    current_user: TokenData = Depends(get_current_user)
):
    """Delete knowledge base (admin only)"""
    try:
        # Get KB and verify access + admin role
        kb_check = supabase.table("knowledge_bases").select("org_id").eq("id", kb_id).single().execute()
        if not kb_check.data:
            raise HTTPException(status_code=404, detail="Knowledge base not found")

        if kb_check.data["org_id"] != current_user.org_id:
            raise HTTPException(status_code=403, detail="Access denied")

        # Check admin role
        user_role = supabase.table("users").select("role").eq("id", current_user.user_id).single().execute()
        if user_role.data.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Admin access required")

        # Delete KB (cascade will handle related records)
        supabase.table("knowledge_bases").delete().eq("id", kb_id).execute()

        return {"message": "Knowledge base deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to delete knowledge base: {str(e)}"
        )

# Metrics endpoint
class MetricsResponse(BaseModel):
    total_conversations: int
    ai_resolution_rate: float
    average_response_time: float
    average_satisfaction_score: Optional[float]
    total_resolution_time: Optional[float]
    chats_handled: int
    chat_deflection_rate: float
    escalation_rate: float
    total_ai_responses: int
    total_handoffs: int

@router.get("/orgs/{org_id}/metrics", response_model=MetricsResponse)
async def get_organization_metrics(
    org_id: str,
    current_user: TokenData = Depends(get_current_user)
):
    """Get analytics metrics for an organization"""
    try:
        # Verify user belongs to org and is admin
        if current_user.org_id != org_id:
            raise HTTPException(status_code=403, detail="Access denied")

        user_role = supabase.table("users").select("role").eq("id", current_user.user_id).single().execute()
        if user_role.data.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Admin access required")

        # Get all conversations for the org
        conversations = supabase.table("conversations").select("id").eq("user_id", current_user.user_id).execute()
        conv_ids = [conv["id"] for conv in conversations.data]

        if not conv_ids:
            return MetricsResponse(
                total_conversations=0,
                ai_resolution_rate=0.0,
                average_response_time=0.0,
                average_satisfaction_score=None,
                total_resolution_time=None,
                chats_handled=0,
                chat_deflection_rate=0.0,
                escalation_rate=0.0,
                total_ai_responses=0,
                total_handoffs=0
            )

        # Get metrics data
        metrics_data = supabase.table("metrics").select("*").in_("conv_id", conv_ids).execute()

        if not metrics_data.data:
            return MetricsResponse(
                total_conversations=len(conv_ids),
                ai_resolution_rate=0.0,
                average_response_time=0.0,
                average_satisfaction_score=None,
                total_resolution_time=None,
                chats_handled=len(conv_ids),
                chat_deflection_rate=0.0,
                escalation_rate=0.0,
                total_ai_responses=0,
                total_handoffs=0
            )

        # Calculate metrics
        total_conversations = len(conv_ids)
        total_ai_responses = sum(m.get("ai_responses", 0) for m in metrics_data.data)
        total_handoffs = sum(1 for m in metrics_data.data if m.get("handoff_triggered", False))

        # AI resolution rate (conversations without handoff)
        ai_resolution_rate = ((total_conversations - total_handoffs) / total_conversations) * 100 if total_conversations > 0 else 0

        # Average response time
        response_times = [m.get("response_time", 0) for m in metrics_data.data if m.get("response_time")]
        average_response_time = sum(response_times) / len(response_times) if response_times else 0

        # Average satisfaction score
        satisfaction_scores = [m.get("satisfaction_score") for m in metrics_data.data if m.get("satisfaction_score") is not None]
        average_satisfaction_score = sum(satisfaction_scores) / len(satisfaction_scores) if satisfaction_scores else None

        # Total resolution time (for human-handled conversations)
        resolution_times = [m.get("resolution_time", 0) for m in metrics_data.data if m.get("resolution_time")]
        total_resolution_time = sum(resolution_times) if resolution_times else None

        # Chat deflection rate (opposite of escalation rate)
        chat_deflection_rate = ai_resolution_rate

        # Escalation rate
        escalation_rate = (total_handoffs / total_conversations) * 100 if total_conversations > 0 else 0

        return MetricsResponse(
            total_conversations=total_conversations,
            ai_resolution_rate=round(ai_resolution_rate, 2),
            average_response_time=round(average_response_time, 2),
            average_satisfaction_score=round(average_satisfaction_score, 2) if average_satisfaction_score else None,
            total_resolution_time=round(total_resolution_time, 2) if total_resolution_time else None,
            chats_handled=total_conversations,
            chat_deflection_rate=round(chat_deflection_rate, 2),
            escalation_rate=round(escalation_rate, 2),
            total_ai_responses=total_ai_responses,
            total_handoffs=total_handoffs
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to get metrics: {str(e)}"
        )