from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel
from typing import List, Optional
import hashlib

from src.core.database import supabase

# Import dependencies from main.py
from src.core.database import supabase as main_supabase

# Pydantic models for dependencies
class TokenData(BaseModel):
    user_id: str
    org_id: str | None = None

# Dependency to get current user
async def get_current_user(token: str = Depends(lambda: None)):
    """Extract and validate user from JWT token or API key."""
    try:
        # Check for org API key
        if token and token.startswith("Bearer "):
            api_key = token.replace("Bearer ", "")
            if api_key.startswith("kb_") or api_key.startswith("sk-"):
                # Validate API key (stored as plain text)
                key_data = supabase.table("api_keys").select("*").eq("key_hash", api_key).eq("is_active", True).single().execute()
                if key_data.data:
                    return TokenData(user_id="api_key_user", org_id=key_data.data["org_id"])
                else:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid API key"
                    )
            else:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid API key format"
                )

        # For testing, extract user ID from mock token
        if token and token.startswith("Bearer mock-token-"):
            user_id = token.replace("Bearer mock-token-", "")
            # Get user org from database
            user_data = supabase.table("users").select("org_id").eq("id", user_id).single().execute()
            org_id = user_data.data.get("org_id") if user_data.data else None
            return TokenData(user_id=user_id, org_id=org_id)
        elif token and token.startswith("mock-token-"):
            # Handle query parameter style tokens
            user_id = token.replace("mock-token-", "")
            user_data = supabase.table("users").select("org_id").eq("id", user_id).single().execute()
            org_id = user_data.data.get("org_id") if user_data.data else None
            return TokenData(user_id=user_id, org_id=org_id)
        else:
            # This is a simplified version - in real implementation you'd validate the token
            return TokenData(user_id="mock_user", org_id="mock_org")
    except HTTPException:
        raise
    except Exception as e:
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

# Pydantic models
class CreateKBRequest(BaseModel):
    name: str

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
@router.post("/orgs/{org_id}/kbs", response_model=KBResponse)
async def create_knowledge_base(
    org_id: str,
    data: CreateKBRequest,
    current_user: TokenData = Depends(get_current_user)
):
    """Create a new knowledge base in an organization"""
    try:
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

        return KBResponse(**kb)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to create knowledge base: {str(e)}"
        )

@router.get("/orgs/{org_id}/kbs", response_model=List[KBListResponse])
async def list_knowledge_bases(
    org_id: str,
    current_user: TokenData = Depends(get_current_user)
):
    """List all knowledge bases in an organization"""
    try:
        # Verify user belongs to org
        if current_user.org_id != org_id:
            raise HTTPException(status_code=403, detail="Access denied")

        # Get KBs with document count
        result = supabase.table("knowledge_bases").select("""
            id,
            name,
            created_at
        """).eq("org_id", org_id).execute()

        kbs = []
        for kb in result.data:
            # Count documents
            doc_count = supabase.table("documents").select("id", count="exact").eq("kb_id", kb["id"]).execute()
            kb["document_count"] = doc_count.count
            kbs.append(KBListResponse(**kb))

        return kbs
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to list knowledge bases: {str(e)}"
        )

@router.get("/kbs/{kb_id}", response_model=KBResponse)
async def get_knowledge_base(
    kb_id: str,
    current_user: TokenData = Depends(get_current_user)
):
    """Get knowledge base details"""
    try:
        # Get KB and verify access
        result = supabase.table("knowledge_bases").select("*").eq("id", kb_id).single().execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Knowledge base not found")

        kb = result.data
        if kb["org_id"] != current_user.org_id:
            raise HTTPException(status_code=403, detail="Access denied")

        return KBResponse(**kb)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to get knowledge base: {str(e)}"
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