"""Authentication and user management schemas."""
from pydantic import BaseModel, EmailStr
from typing import Optional


class EmailPasswordSignUp(BaseModel):
    """Schema for user signup request."""
    email: EmailStr
    password: str


class EmailPasswordSignIn(BaseModel):
    """Schema for user signin request."""
    email: EmailStr
    password: str


class OAuthSignInRequest(BaseModel):
    """Schema for OAuth signin request."""
    provider: str  # "google" or "github"


class AuthResponse(BaseModel):
    """Schema for authentication response."""
    user: dict
    session: Optional[dict] = None
    redirect_url: Optional[str] = None


class CreateOrgRequest(BaseModel):
    """Schema for organization creation request."""
    name: str


class OrgResponse(BaseModel):
    """Schema for organization response."""
    id: str
    name: str
    created_at: str
    updated_at: str


class AddUserRequest(BaseModel):
    """Schema for adding user to organization request."""
    email: EmailStr
    role: str = "member"  # admin or member


class UserResponse(BaseModel):
    """Schema for user response."""
    id: str
    org_id: str
    role: str
    created_at: str


class UserInfo(BaseModel):
    """Schema for user information response."""
    id: str
    email: str
    org_id: Optional[str] = None
    role: Optional[str] = None