"""Database connection and Supabase client initialization."""
import hashlib
from datetime import datetime
from supabase import create_client, Client

from .config import settings

# Initialize Supabase client with application settings
supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)

def sha256_hex(s: str) -> str:
    # ensure the same encoding and hex format as Postgres: lowercase hex
    return hashlib.sha256(s.encode('utf-8')).hexdigest()

def verify_key_by_hash(plain_key: str):
    h = sha256_hex(plain_key)
    # Query for expires_at IS NULL
    result1 = supabase.table("api_keys").select("id, org_id, permissions, is_active, kb_id").eq("key_hash", h).eq("is_active", True).is_("expires_at", "null").execute()
    if result1.data:
        row = result1.data[0]
        supabase.table("api_keys").update({"last_used_at": "now"}).eq("key_hash", h).execute()
        return row
    # Query for expires_at > NOW()
    result2 = supabase.table("api_keys").select("id, org_id, permissions, is_active, kb_id").eq("key_hash", h).eq("is_active", True).gt("expires_at", datetime.utcnow()).execute()
    if result2.data:
        row = result2.data[0]
        supabase.table("api_keys").update({"last_used_at": "now"}).eq("key_hash", h).execute()
        return row
    return None

async def verify_api_key_db(plain_key: str):
    """
    Calls the Postgres function verify_api_key(p_plain_key TEXT)
    and returns the first matching row, or None.
    """
    # Supabase RPC = call Postgres function
    res = supabase.rpc("verify_api_key", {"p_plain_key": plain_key}).execute()

    if res.error:
        print("Supabase RPC Error:", res.error)
        return None
    if not res.data:
        return None
    return res.data[0]  # first matching record

# Export for use in other modules
__all__ = ["supabase", "sha256_hex", "verify_key_by_hash", "verify_api_key_db"]