"""Database connection and Supabase client initialization."""
from supabase import create_client, Client

from .config import settings

# Initialize Supabase client with application settings
supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)

# Export for use in other modules
__all__ = ["supabase"]