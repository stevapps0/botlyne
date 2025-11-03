"""User CRUD operations."""
from typing import List, Optional
from supabase import Client

from app.core.database import supabase


def get_user_by_id(user_id: str) -> Optional[dict]:
    """Get user by ID."""
    result = supabase.table("users").select("*").eq("id", user_id).single().execute()
    return result.data


def get_users_by_org(org_id: str) -> List[dict]:
    """Get all users in an organization."""
    result = supabase.table("users").select("*").eq("org_id", org_id).execute()
    return result.data or []


def create_user(user_data: dict) -> dict:
    """Create a new user."""
    result = supabase.table("users").insert(user_data).execute()
    return result.data[0]


def update_user_role(user_id: str, role: str) -> dict:
    """Update user role."""
    result = supabase.table("users").update({"role": role}).eq("id", user_id).execute()
    return result.data[0]


def delete_user(user_id: str) -> None:
    """Delete a user."""
    supabase.table("users").delete().eq("id", user_id).execute()


def get_org_by_id(org_id: str) -> Optional[dict]:
    """Get organization by ID."""
    result = supabase.table("organizations").select("*").eq("id", org_id).single().execute()
    return result.data


def create_org(org_data: dict) -> dict:
    """Create a new organization."""
    result = supabase.table("organizations").insert(org_data).execute()
    return result.data[0]


def update_org(org_id: str, org_data: dict) -> dict:
    """Update organization."""
    result = supabase.table("organizations").update(org_data).eq("id", org_id).execute()
    return result.data[0]