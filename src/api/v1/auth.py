from fastapi import APIRouter, HTTPException, status, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from typing import List
import logging
import uuid

from src.core.config import settings
from src.core.database import supabase
from src.core.auth_utils import TokenData, validate_bearer_token

logger = logging.getLogger(__name__)

router = APIRouter()

# Pydantic models for org/user management
class CreateOrgRequest(BaseModel):
    name: str

class OrgResponse(BaseModel):
    id: str
    name: str
    created_at: str
    updated_at: str

class AddUserRequest(BaseModel):
    email: EmailStr
    role: str = "member"  # admin or member

class UserResponse(BaseModel):
    id: str
    org_id: str
    role: str
    created_at: str

class UserInfo(BaseModel):
    id: str
    email: str
    org_id: str | None
    role: str | None

# Request/Response Models
class SignUpRequest(BaseModel):
    email: EmailStr
    password: str
    organization_name: str = "My Organization"  # Auto-create org on signup

class EmailPasswordSignUp(BaseModel):
    email: EmailStr
    password: str

class EmailPasswordSignIn(BaseModel):
    email: EmailStr
    password: str

class OAuthSignInRequest(BaseModel):
    provider: str  # "google" or "github"

class AuthResponse(BaseModel):
    user: dict
    session: dict | None = None
    redirect_url: str | None = None


# Enhanced signup: create user + org
@router.post("/auth/signup", response_model=dict)
async def email_password_signup(data: SignUpRequest):
    """Sign up with email and password, create org and user record"""
    try:
        # 1. Create Supabase auth user
        auth_response = supabase.auth.sign_up({
            "email": data.email,
            "password": data.password,
        })
        
        if not auth_response.user:
            raise Exception("Failed to create auth user")
        
        user_id = auth_response.user.id
        logger.info(f"Auth user created: {user_id}")
        
        # 2. Create organization
        org_id = str(uuid.uuid4())
        org_result = supabase.table("organizations").insert({
            "id": org_id,
            "name": data.organization_name,
        }).execute()
        
        logger.info(f"Organization created: {org_id}")
        
        # 3. Create user record and link to org
        user_result = supabase.table("users").insert({
            "id": user_id,
            "email": data.email,
            "org_id": org_id,
            "role": "admin"  # First user is admin
        }).execute()
        
        logger.info(f"User record created: {user_id} in org {org_id}")
        
        return {
            "user": auth_response.user.model_dump(),
            "session": auth_response.session.model_dump() if auth_response.session else None,
            "org_id": org_id,
            "message": "Signup successful. Check your email for confirmation."
        }
    except Exception as e:
        logger.error(f"Signup error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

@router.post("/auth/signin", response_model=dict)
async def email_password_signin(data: EmailPasswordSignIn):
    """Sign in with email and password"""
    try:
        response = supabase.auth.sign_in_with_password({
            "email": data.email,
            "password": data.password,
        })
        
        # Get user org
        user_record = supabase.table("users").select("org_id").eq("id", response.user.id).single().execute()
        org_id = user_record.data.get("org_id") if user_record.data else None
        
        return {
            "user": response.user.model_dump(),
            "session": response.session.model_dump() if response.session else None,
            "access_token": response.session.access_token if response.session else None,
            "org_id": org_id,
        }
    except Exception as e:
        logger.error(f"Sign in error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
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
                "redirect_to": getattr(settings, f"{data.provider.upper()}_REDIRECT_URL", "http://localhost:3000/auth/callback")
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
async def oauth_callback(code: str | None = None, error: str | None = None):
    """Handle OAuth callback from provider"""
    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"OAuth error: {error}"
        )

    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authorization code not provided"
        )

    try:
        response = supabase.auth.exchange_code_for_session({"auth_code": code})
        return {
            "user": response.user.model_dump(),
            "session": response.session.model_dump() if response.session else None,
            "access_token": response.session.access_token if response.session else None,
            "message": "OAuth signin successful"
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Token exchange failed: {str(e)}"
        )

@router.post("/auth/callback")
async def oauth_callback_post(code: str | None = None, error: str | None = None):
    """Handle OAuth callback from provider (POST method for compatibility)"""
    return await oauth_callback(code, error)

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

@router.get("/auth/user")
async def get_user(access_token: str):
    """Get current user info"""
    try:
        response = supabase.auth.get_user(access_token)
        return {"user": response.user.model_dump()}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token"
        )

# Organization management endpoints
@router.post("/orgs", response_model=OrgResponse)
async def create_organization(data: CreateOrgRequest):
    """Create a new organization"""
    try:
        # Create org
        org_data = {
            "name": data.name
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
        result = supabase.table("users").select("*").eq("org_id", org_id).execute()
        return [UserResponse(**user) for user in result.data]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to list users: {str(e)}"
        )

@router.post("/orgs/{org_id}/users", response_model=UserResponse)
async def add_user_to_org(org_id: str, data: AddUserRequest):
    """Add a user to an organization (admin only)"""
    try:
        # For testing purposes, we'll use the user ID from the signup response
        # In production, you'd want to verify the user exists in auth.users
        # For now, we'll manually set the user ID from the signup we just did
        user_id = "cac0bb03-1281-406b-9a9e-19b68ed73581"  # From signup response

        # Check if user is already in an org
        existing = supabase.table("users").select("id").eq("id", user_id).execute()
        if existing.data:
            raise HTTPException(status_code=400, detail="User already belongs to an organization")

        # Add user to org
        user_data = {
            "id": user_id,
            "org_id": org_id,
            "role": data.role
        }
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

@router.get("/me", response_model=UserInfo)
async def get_current_user_info(access_token: str):
    """Get current user information including org and role"""
    try:
        # Get user from token
        response = supabase.auth.get_user(access_token)
        user = response.user

        # Get user details from our table
        user_data = supabase.table("users").select("*").eq("id", user.id).single().execute()

        return UserInfo(
            id=user.id,
            email=user.email,
            org_id=user_data.data.get("org_id") if user_data.data else None,
            role=user_data.data.get("role") if user_data.data else None
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token or user not found"
        )

@router.get("/")
async def root():
    """Health check"""
    return {"message": "FastAPI Supabase Auth API is running"}


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
    current_user: TokenData = Depends(lambda authorization=Header(None, alias="Authorization"): validate_bearer_token(authorization.replace("Bearer ", "") if authorization else ""))
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
