"""Document CRUD operations."""
from typing import List, Optional
from supabase import Client

from src.core.database import supabase


def get_documents_by_kb(kb_id: str) -> List[dict]:
    """Get all documents in a knowledge base."""
    result = supabase.table("documents").select("*").eq("kb_id", kb_id).execute()
    return result.data or []


def create_document(doc_data: dict) -> dict:
    """Create a new document."""
    result = supabase.table("documents").insert(doc_data).execute()
    return result.data[0]


def search_similar_documents(kb_id: str, query_embedding: List[float], limit: int = 5) -> List[dict]:
    """Search for similar documents using vector similarity."""
    result = supabase.rpc(
        "match_documents",
        {
            "query_embedding": query_embedding,
            "kb_id": kb_id,
            "match_count": limit
        }
    ).execute()
    return result.data or []


def create_file(file_data: dict) -> dict:
    """Create a new file record."""
    result = supabase.table("files").insert(file_data).execute()
    return result.data[0]


def get_files_by_kb(kb_id: str) -> List[dict]:
    """Get all files in a knowledge base."""
    result = supabase.table("files").select("*").eq("kb_id", kb_id).execute()
    return result.data or []


def create_conversation(conv_data: dict) -> dict:
    """Create a new conversation."""
    result = supabase.table("conversations").insert(conv_data).execute()
    return result.data[0]


def get_conversation(conv_id: str) -> Optional[dict]:
    """Get conversation by ID."""
    result = supabase.table("conversations").select("*").eq("id", conv_id).single().execute()
    return result.data


def get_user_conversations(user_id: str) -> List[dict]:
    """Get all conversations for a user."""
    result = supabase.table("conversations").select("*").eq("user_id", user_id).order("started_at", desc=True).execute()
    return result.data or []


def create_message(msg_data: dict) -> dict:
    """Create a new message."""
    result = supabase.table("messages").insert(msg_data).execute()
    return result.data[0]


def get_conversation_messages(conv_id: str) -> List[dict]:
    """Get all messages in a conversation."""
    result = supabase.table("messages").select("*").eq("conv_id", conv_id).order("timestamp").execute()
    return result.data or []


def create_metrics(metrics_data: dict) -> dict:
    """Create metrics record."""
    result = supabase.table("metrics").insert(metrics_data).execute()
    return result.data[0]


def update_conversation_status(conv_id: str, status: str, resolved_at: Optional[str] = None) -> dict:
    """Update conversation status."""
    update_data = {"status": status}
    if resolved_at:
        update_data["resolved_at"] = resolved_at
    
    result = supabase.table("conversations").update(update_data).eq("id", conv_id).execute()
    return result.data[0]