"""Knowledge base CRUD operations."""
from typing import List, Optional
from supabase import Client

from app.core.database import supabase


def get_kb_by_id(kb_id: str) -> Optional[dict]:
    """Get knowledge base by ID."""
    result = supabase.table("knowledge_bases").select("*").eq("id", kb_id).single().execute()
    return result.data


def get_kbs_by_org(org_id: str) -> List[dict]:
    """Get all knowledge bases in an organization."""
    result = supabase.table("knowledge_bases").select("*").eq("org_id", org_id).execute()
    return result.data or []


def create_kb(kb_data: dict) -> dict:
    """Create a new knowledge base."""
    result = supabase.table("knowledge_bases").insert(kb_data).execute()
    return result.data[0]


def update_kb(kb_id: str, kb_data: dict) -> dict:
    """Update knowledge base."""
    result = supabase.table("knowledge_bases").update(kb_data).eq("id", kb_id).execute()
    return result.data[0]


def delete_kb(kb_id: str) -> None:
    """Delete a knowledge base."""
    supabase.table("knowledge_bases").delete().eq("id", kb_id).execute()