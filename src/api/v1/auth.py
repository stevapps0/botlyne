from fastapi import APIRouter, HTTPException, status, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field
from typing import List
import logging
import uuid
import secrets
import hashlib
from datetime import datetime, timedelta

from src.core.config import settings
from src.core.database import supabase
from src.core.auth import get_current_user, require_admin
from src.core.auth_utils import TokenData
from src.archive.transform import vectorize_and_chunk
from src.archive.load import load_to_supabase

logger = logging.getLogger(__name__)

router = APIRouter()


def hash_api_key(key: str) -> str:
    """Hash API key for storage."""
    return hashlib.sha256(key.encode()).hexdigest()

def generate_api_key() -> str:
    """Generate a secure random API key."""
    return "sk-" + secrets.token_urlsafe(32)

# Pydantic models for org/user management
class CreateOrgRequest(BaseModel):
    name: str
    description: str | None = None
    team_size: int | None = None

class OrgResponse(BaseModel):
    id: str
    name: str
    created_at: str
    updated_at: str
    description: str | None = None
    team_size: int | None = None
    shortcode: str | None = None

class AddUserRequest(BaseModel):
    email: EmailStr
    role: str = "member"  # admin or member

class InviteUserRequest(BaseModel):
    email: EmailStr
    role: str = "member"

class UserResponse(BaseModel):
    id: str
    org_id: str
    role: str
    created_at: str
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None

class UserInfo(BaseModel):
    id: str
    email: str
    org_id: str | None
    role: str | None
    kb_id: str | None

# Request/Response Models
class CompleteOnboardingRequest(BaseModel):
    organization_name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)
    team_size: int | None = Field(None, ge=1, le=10000)


# Additional endpoints

@router.get("/auth/user", response_model=UserInfo)
async def get_user(current_user: TokenData = Depends(get_current_user)):
    """Get current user info with org/role/kb"""
    try:
        # Get user details from our table
        user_data = supabase.table("users").select("*").eq("id", current_user.user_id).single().execute()

        return UserInfo(
            id=current_user.user_id,
            email=user_data.data.get("email") if user_data.data else "",
            org_id=user_data.data.get("org_id") if user_data.data else current_user.org_id,
            role=user_data.data.get("role") if user_data.data else None,
            kb_id=current_user.kb_id
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token or user not found"
        )

# Organization management endpoints
@router.post("/orgs", response_model=OrgResponse)
async def create_organization(data: CreateOrgRequest):
    """Create a new organization"""
    try:
        # Generate 6-character hex shortcode
        shortcode = secrets.token_hex(3)  # 6 characters

        # Create org
        org_data = {
            "name": data.name,
            "description": data.description,
            "team_size": data.team_size,
            "shortcode": shortcode
        }
        org_result = supabase.table("organizations").insert(org_data).execute()
        org = org_result.data[0]

        return OrgResponse(**org)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to create organization: {str(e)}"
        )

@router.get("/orgs/{org_id}", response_model=OrgResponse)
async def get_organization(org_id: str, current_user: TokenData = Depends(get_current_user)):
    """Get organization details"""
    try:
        result = supabase.table("organizations").select("*").eq("id", org_id).single().execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Organization not found")
        return OrgResponse(**result.data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to get organization: {str(e)}"
        )

@router.get("/orgs/{org_id}/users", response_model=List[UserResponse])
async def list_org_users(org_id: str, current_user: TokenData = Depends(get_current_user)):
    """List all users in an organization"""
    try:
        result = supabase.table("users").select("id, org_id, role, created_at, email, first_name, last_name").eq("org_id", org_id).execute()
        return [UserResponse(**user) for user in result.data]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to list users: {str(e)}"
        )

@router.post("/orgs/{org_id}/users", response_model=UserResponse)
async def add_user_to_org(org_id: str, data: AddUserRequest, current_user: TokenData = Depends(require_admin)):
    """Add a user to an organization (admin only)"""
    try:
        # Verify the inviting user is admin of the target org
        if current_user.org_id != org_id:
            raise HTTPException(status_code=403, detail="You can only invite users to your own organization")

        # For now, assume user_id is provided (in real implementation, search by email or something)
        # This is a placeholder - in production, you'd look up user by email
        user_id = data.email  # Placeholder - should be actual user ID lookup

        # Check if user exists and is not already in an org
        existing = supabase.table("users").select("org_id").eq("id", user_id).single().execute()
        if existing.data and existing.data.get("org_id"):
            raise HTTPException(status_code=400, detail="User already belongs to an organization")

        # Add or update user in org
        user_data = {
            "id": user_id,
            "org_id": org_id,
            "role": data.role
        }
        if existing.data:
            # Update existing user
            result = supabase.table("users").update(user_data).eq("id", user_id).execute()
        else:
            # Insert new user (this assumes user exists in auth.users)
            result = supabase.table("users").insert(user_data).execute()

        return UserResponse(**result.data[0])
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to add user: {str(e)}"
        )

@router.delete("/orgs/{org_id}/users/{user_id}")
async def remove_user_from_org(org_id: str, user_id: str):
    """Remove a user from an organization (admin only)"""
    try:
        # Verify user belongs to org
        user_check = supabase.table("users").select("org_id").eq("id", user_id).single().execute()
        if not user_check.data or user_check.data["org_id"] != org_id:
            raise HTTPException(status_code=404, detail="User not found in organization")

        # Remove user
        supabase.table("users").delete().eq("id", user_id).execute()
        return {"message": "User removed from organization"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to remove user: {str(e)}"
        )

@router.post("/orgs/{org_id}/invites")
async def invite_user_to_org(org_id: str, data: InviteUserRequest, current_user: TokenData = Depends(require_admin)):
    """Send invitation to a user to join the organization (admin only)"""
    try:
        # Verify admin belongs to org
        if current_user.org_id != org_id:
            raise HTTPException(status_code=403, detail="You can only invite users to your own organization")

        # Check if user already exists and belongs to an org
        existing_user = supabase.table("users").select("org_id").eq("email", data.email).single().execute()
        if existing_user.data and existing_user.data.get("org_id"):
            raise HTTPException(status_code=400, detail="User already belongs to an organization")

        # Create invitation
        invite_id = str(uuid.uuid4())
        invite_data = {
            "id": invite_id,
            "org_id": org_id,
            "email": data.email,
            "role": data.role,
            "invited_by": current_user.user_id,
            "expires_at": (datetime.utcnow() + timedelta(days=7)).isoformat()  # 7 days expiry
        }
        supabase.table("invitations").insert(invite_data).execute()

        # Send invitation email
        invite_link = f"{settings.FRONTEND_URL}/accept-invite/{invite_id}"
        try:
            email_data = {
                "to": data.email,
                "subject": f"Invitation to join {current_user.org_id} organization",
                "invite_link": invite_link,
                "org_id": org_id,
                "role": data.role
            }
            supabase.rpc('send_invite_email', email_data).execute()
        except Exception as e:
            logger.error(f"Failed to send invite email: {e}")
            # Don't fail the invite if email fails

        return {"message": "Invitation sent successfully", "invite_id": invite_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to send invitation: {str(e)}"
        )

@router.post("/accept-invite/{invite_id}")
async def accept_invitation(invite_id: str):
    """Accept an invitation and sign up/sign in"""
    try:
        # Get invitation
        invite = supabase.table("invitations").select("*").eq("id", invite_id).single().execute()
        if not invite.data:
            raise HTTPException(status_code=404, detail="Invitation not found")

        invite_data = invite.data
        if datetime.fromisoformat(invite_data["expires_at"].replace('Z', '+00:00')) < datetime.utcnow():
            raise HTTPException(status_code=400, detail="Invitation has expired")

        # Redirect to signup with invite context
        signup_url = f"{settings.FRONTEND_URL}/signup?invite={invite_id}"
        return {"redirect_url": signup_url, "org_id": invite_data["org_id"], "role": invite_data["role"]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to accept invitation: {str(e)}"
        )

@router.post("/orgs/{org_id}/leave")
async def leave_organization(org_id: str, current_user: TokenData = Depends(get_current_user)):
    """Allow a user to leave their organization"""
    try:
        # Verify user belongs to org
        if current_user.org_id != org_id:
            raise HTTPException(status_code=403, detail="You don't belong to this organization")

        # Check if user is admin
        user_data = supabase.table("users").select("role").eq("id", current_user.user_id).single().execute()
        is_admin = user_data.data and user_data.data.get("role") == "admin"

        if is_admin:
            # Check if there are other admins
            other_admins = supabase.table("users").select("id").eq("org_id", org_id).eq("role", "admin").neq("id", current_user.user_id).execute()
            if not other_admins.data or len(other_admins.data) == 0:
                raise HTTPException(status_code=400, detail="Cannot leave organization: you are the only admin. Transfer admin role first or delete the organization.")

        # Remove user from org (set org_id to null)
        supabase.table("users").update({"org_id": None}).eq("id", current_user.user_id).execute()

        # Optionally deactivate API keys (or transfer them)
        # For now, leave them active but they may not work without org context

        return {"message": "Successfully left the organization"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to leave organization: {str(e)}"
        )


@router.get("/onboarding")
async def get_onboarding_content():
    """Get onboarding welcome content for new users"""
    return {
        "title": "Welcome to Your Knowledge Base!",
        "content": """
Welcome to your new knowledge base! Here's how to get started:

## Getting Started

1. **Upload Documents**: Start by uploading your first documents. We support PDF, TXT, DOCX, and HTML files.

2. **Ask Questions**: Once documents are uploaded, you can ask questions about your content using natural language.

3. **API Access**: Use your API key to integrate with other applications.

## Your API Key

Your default API key has been created and associated with your knowledge base. You can manage API keys in your settings.

## Next Steps

- Upload some documents to your knowledge base
- Try asking a question about your uploaded content
- Explore the API documentation at /docs

Welcome aboard!
        """,
        "steps": [
            {
                "title": "Upload Your First Document",
                "description": "Add documents to your knowledge base to start asking questions.",
                "action": "upload"
            },
            {
                "title": "Ask a Question",
                "description": "Test your knowledge base by asking questions about your documents.",
                "action": "query"
            },
            {
                "title": "Explore API",
                "description": "Check out the API documentation and try integrating with other tools.",
                "action": "api"
            }
        ]
    }




# Knowledge Base management endpoints
class CreateKBRequest(BaseModel):
    name: str
    description: str = ""

class KBResponse(BaseModel):
    id: str
    org_id: str
    name: str
    description: str
    created_at: str


@router.post("/kb", response_model=KBResponse)
async def create_knowledge_base(
    data: CreateKBRequest,
    current_user: TokenData = Depends(get_current_user)
):
    """Create a new knowledge base in user's organization"""
    try:
        if not current_user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only authenticated users can create KBs"
            )
        
        if not current_user.org_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User must belong to organization"
            )
        
        kb_id = str(uuid.uuid4())
        kb_result = supabase.table("knowledge_bases").insert({
            "id": kb_id,
            "org_id": current_user.org_id,
            "name": data.name,
            "description": data.description,
        }).execute()
        
        logger.info(f"KB created: {kb_id} for org {current_user.org_id}")
        
        return KBResponse(**kb_result.data[0])
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"KB creation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to create KB: {str(e)}"
        )


@router.get("/kb/{kb_id}", response_model=KBResponse)
async def get_knowledge_base(kb_id: str, current_user: TokenData = Depends(get_current_user)):
    """Get knowledge base details"""
    try:
        result = supabase.table("knowledge_bases").select("*").eq("id", kb_id).single().execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Knowledge base not found")
        return KBResponse(**result.data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to get KB: {str(e)}"
        )


@router.get("/orgs/{org_id}/kb")
async def list_org_knowledge_bases(org_id: str, current_user: TokenData = Depends(get_current_user)):
    """List all knowledge bases in organization"""
    try:
        result = supabase.table("knowledge_bases").select("*").eq("org_id", org_id).execute()
        return [KBResponse(**kb) for kb in result.data]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to list KBs: {str(e)}"
        )
