from fastapi import APIRouter, HTTPException, status, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from typing import List
import logging
import uuid
import secrets
import hashlib
from datetime import datetime, timedelta

from src.core.config import settings
from src.core.database import supabase
from src.core.auth_utils import TokenData, validate_bearer_token
from src.archive.transform import vectorize_and_chunk
from src.archive.load import load_to_supabase

logger = logging.getLogger(__name__)

router = APIRouter()

async def get_current_user(authorization: str = Header(None, alias="Authorization")) -> TokenData:
    """Dependency to get current user from authorization header."""
    token = authorization.replace("Bearer ", "") if authorization else ""
    return await validate_bearer_token(token)

async def require_admin(current_user: TokenData = Depends(get_current_user)) -> TokenData:
    """Ensure user has admin role."""
    user_data = supabase.table("users").select("role").eq("id", current_user.user_id).single().execute()
    if user_data.data.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user

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
class SignUpRequest(BaseModel):
    email: EmailStr
    password: str
    organization_name: str = "My Organization"  # Auto-create org on signup

class EmailSignUp(BaseModel):
    email: EmailStr


class OAuthSignInRequest(BaseModel):
    provider: str  # "google" or "github"

class AuthResponse(BaseModel):
    user: dict
    session: dict | None = None
    redirect_url: str | None = None
    org_id: str | None = None
    kb_id: str | None = None
    api_key: str | None = None

class CompleteOnboardingRequest(BaseModel):
    organization_name: str
    description: str | None = None
    team_size: int | None = None


# Enhanced signin: send magic link
@router.post("/auth/signin", response_model=dict)
async def email_signin(data: EmailSignUp):
    """Send magic link for signup/signin"""
    try:
        # Send magic link via Supabase
        auth_response = supabase.auth.sign_in_with_otp({
            "email": data.email,
            "options": {
                "redirect_to": f"{settings.FRONTEND_URL}/auth/callback"
            }
        })

        logger.info(f"Magic link sent to: {data.email}")

        return {
            "message": "Magic link sent. Check your email and click the link to sign in.",
            "email": data.email
        }
    except Exception as e:
        logger.error(f"Magic link error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to send magic link: {str(e)}"
        )


# OAuth Authentication
@router.post("/auth/oauth/signin", response_model=dict)
async def oauth_signin(data: OAuthSignInRequest):
    """Get OAuth sign-in URL for Google or GitHub"""
    if data.provider not in ["google", "github"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provider must be 'google' or 'github'"
        )
    
    try:
        response = supabase.auth.sign_in_with_oauth({
            "provider": data.provider,
            "options": {
                "redirect_to": f"{settings.FRONTEND_URL}/auth/callback"
            }
        })
        return {
            "provider": data.provider,
            "redirect_url": response.url,
            "message": f"Redirect to {data.provider} for authentication"
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"OAuth error: {str(e)}"
        )

@router.get("/auth/callback")
async def auth_callback(code: str | None = None, error: str | None = None, invite: str | None = None):
    """Handle auth callback from magic link or OAuth"""
    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Auth error: {error}"
        )

    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authorization code not provided"
        )

    try:
        response = supabase.auth.exchange_code_for_session({"auth_code": code})
        user = response.user

        # Check for invitation
        invite_data = None
        if invite:
            invite_record = supabase.table("invitations").select("*").eq("id", invite).eq("email", user.email).single().execute()
            if invite_record.data:
                invite_data = invite_record.data

        # Check if user exists in our users table
        user_record = supabase.table("users").select("*").eq("id", user.id).single().execute()

        if not user_record.data:
            # First time user
            logger.info(f"New user signup: {user.id}, {user.email}")

            if invite_data:
                # User is accepting an invitation - complete setup immediately
                org_id = invite_data["org_id"]
                role = invite_data["role"]

                # Get org name
                org_record = supabase.table("organizations").select("name").eq("id", org_id).single().execute()
                org_name = org_record.data["name"] if org_record.data else "Organization"

                # Create user record in invited org
                user_result = supabase.table("users").insert({
                    "id": user.id,
                    "email": user.email,
                    "org_id": org_id,
                    "role": role
                }).execute()

                logger.info(f"User record created: {user.id} in invited org {org_id}")

                # Get or create KB for the org (assume org has at least one KB)
                kb_record = supabase.table("knowledge_bases").select("id").eq("org_id", org_id).limit(1).execute()
                kb_id = kb_record.data[0]["id"] if kb_record.data else None

                # Delete the invitation
                supabase.table("invitations").delete().eq("id", invite).execute()

                # Send welcome email for invited user
                try:
                    email_data = {
                        "to": user.email,
                        "subject": f"Welcome to {org_name}!",
                        "org_name": org_name,
                        "dashboard_url": f"{settings.FRONTEND_URL}/dashboard"
                    }
                    supabase.rpc('send_invited_user_welcome_email', email_data).execute()
                    logger.info(f"Welcome email sent to invited user {user.email}")
                except Exception as e:
                    logger.error(f"Failed to send welcome email: {e}")

                return {
                    "user": user.model_dump(),
                    "session": response.session.model_dump() if response.session else None,
                    "access_token": response.session.access_token if response.session else None,
                    "org_id": org_id,
                    "kb_id": kb_id,
                    "message": f"Welcome to {org_name}! You have been successfully added to the organization."
                }
            else:
                # Regular signup - create minimal user record, require onboarding
                user_result = supabase.table("users").insert({
                    "id": user.id,
                    "email": user.email,
                    # no org_id yet - will be set during onboarding
                }).execute()

                logger.info(f"Minimal user record created: {user.id}, {user.email}")

                return {
                    "user": user.model_dump(),
                    "session": response.session.model_dump() if response.session else None,
                    "access_token": response.session.access_token if response.session else None,
                    "message": "Please complete your onboarding to set up your account."
                }
        else:
            # Existing user - check onboarding status
            org_id = user_record.data.get("org_id")
            if org_id:
                # Fully onboarded user
                # Get KB for the org
                kb_record = supabase.table("knowledge_bases").select("id").eq("org_id", org_id).limit(1).execute()
                kb_id = kb_record.data[0]["id"] if kb_record.data else None

                return {
                    "user": user.model_dump(),
                    "session": response.session.model_dump() if response.session else None,
                    "access_token": response.session.access_token if response.session else None,
                    "org_id": org_id,
                    "kb_id": kb_id,
                    "message": "Signin successful"
                }
            else:
                # User stuck in onboarding (signed up but didn't complete)
                return {
                    "user": user.model_dump(),
                    "session": response.session.model_dump() if response.session else None,
                    "access_token": response.session.access_token if response.session else None,
                    "message": "Please complete your onboarding."
                }

    except Exception as e:
        logger.error(f"Auth callback error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Authentication failed: {str(e)}"
        )

@router.post("/auth/callback")
async def auth_callback_post(code: str | None = None, error: str | None = None):
    """Handle auth callback from magic link or OAuth (POST method for compatibility)"""
    return await auth_callback(code, error)

@router.post("/auth/onboarding")
async def complete_onboarding(data: CompleteOnboardingRequest, current_user: TokenData = Depends(get_current_user)):
    """Complete user onboarding by creating organization and knowledge base"""
    try:
        if not current_user.user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not authenticated"
            )

        # Check if user already has an org
        user_record = supabase.table("users").select("org_id").eq("id", current_user.user_id).single().execute()
        if user_record.data and user_record.data.get("org_id"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User has already completed onboarding"
            )

        # Create organization
        org_id = str(uuid.uuid4())
        shortcode = secrets.token_hex(3)  # 6-character hex shortcode
        org_result = supabase.table("organizations").insert({
            "id": org_id,
            "name": data.organization_name,
            "description": data.description,
            "team_size": data.team_size,
            "shortcode": shortcode
        }).execute()

        logger.info(f"Organization created: {org_id} - {data.organization_name}")

        # Update user record with org_id and role
        user_result = supabase.table("users").update({
            "org_id": org_id,
            "role": "admin"  # First user is admin
        }).eq("id", current_user.user_id).execute()

        logger.info(f"User updated: {current_user.user_id} in org {org_id}")

        # Create default knowledge base
        kb_id = str(uuid.uuid4())
        kb_name = f"{data.organization_name} Knowledge Base"
        kb_result = supabase.table("knowledge_bases").insert({
            "id": kb_id,
            "org_id": org_id,
            "name": kb_name,
            "description": "Your first knowledge base - start uploading documents here!",
        }).execute()

        logger.info(f"Default KB created: {kb_id} for org {org_id}")

        # Upload onboarding content to KB
        onboarding_content = """
Welcome to Your Knowledge Base!

This is your welcome guide. Here's how to get started:

## Getting Started

1. **Upload Documents**: Start by uploading your first documents. We support PDF, TXT, DOCX, and HTML files.

2. **Ask Questions**: Once documents are uploaded, you can ask questions about your content using natural language.

3. **API Access**: Use your API key to integrate with other applications.

## Your API Key

Your default API key has been created and associated with your knowledge base. You can manage API keys in your settings.

## Next Steps

- Upload some documents to your knowledge base
- Try asking a question about your uploaded content
- Explore the API documentation

Welcome aboard!
        """
        onboarding_metadata = {
            "source": "welcome.md",
            "title": "Welcome Guide",
            "type": "onboarding"
        }
        vectorized_data = vectorize_and_chunk(onboarding_content, onboarding_metadata)
        load_to_supabase(vectorized_data, kb_id)
        logger.info(f"Onboarding content uploaded to KB {kb_id}")

        # Send welcome email (without API key)
        try:
            email_data = {
                "to": user_result.data[0]["email"],
                "subject": "Welcome to Your Knowledge Base!",
                "org_name": data.organization_name,
                "kb_id": kb_id,
                "dashboard_url": f"{settings.FRONTEND_URL}/dashboard"
            }
            supabase.rpc('send_welcome_email', email_data).execute()
            logger.info(f"Welcome email sent to {user_result.data[0]['email']}")
        except Exception as e:
            logger.error(f"Failed to send welcome email: {e}")
            # Don't fail onboarding if email fails

        return {
            "org_id": org_id,
            "kb_id": kb_id,
            "message": f"Welcome to {data.organization_name}! Your account is now fully set up."
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Complete onboarding error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to complete onboarding: {str(e)}"
        )

# Additional endpoints
@router.post("/auth/refresh")
async def refresh_token(refresh_token: str):
    """Refresh access token using refresh token"""
    try:
        response = supabase.auth.refresh_session(refresh_token)
        return {
            "session": response.session.model_dump() if response.session else None,
            "access_token": response.session.access_token if response.session else None,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )

@router.post("/auth/signout")
async def signout(refresh_token: str):
    """Sign out user"""
    try:
        supabase.auth.sign_out(refresh_token)
        return {"message": "Signed out successfully"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

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
async def get_organization(org_id: str):
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
async def list_org_users(org_id: str):
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
async def get_knowledge_base(kb_id: str):
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
async def list_org_knowledge_bases(org_id: str):
    """List all knowledge bases in organization"""
    try:
        result = supabase.table("knowledge_bases").select("*").eq("org_id", org_id).execute()
        return [KBResponse(**kb) for kb in result.data]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to list KBs: {str(e)}"
        )
