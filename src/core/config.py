"""Application configuration settings."""
import os
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Settings:
    """Application settings loaded from environment variables."""

    # Supabase Configuration
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_ANON_KEY: str = os.getenv("SUPABASE_ANON_KEY", "")

    # AI Configuration
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
    OPENLYNE_API_KEY: str = os.getenv("OPENLYNE_API_KEY", "")

    # Email Configuration (for human handoff)
    SMTP_SERVER: str = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASS: str = os.getenv("SMTP_PASS", "")
    SUPPORT_EMAIL: str = os.getenv("SUPPORT_EMAIL", "support@company.com")

    # File Processing Configuration
    MAX_FILE_SIZE: int = int(os.getenv("MAX_FILE_SIZE", str(50 * 1024 * 1024)))  # 50MB default
    MAX_PARALLEL_TASKS: int = int(os.getenv("MAX_PARALLEL_TASKS", "10"))

    # Optional OAuth Redirect URLs
    GOOGLE_REDIRECT_URL: str = os.getenv("GOOGLE_REDIRECT_URL", "http://localhost:3000/auth/callback")
    GITHUB_REDIRECT_URL: str = os.getenv("GITHUB_REDIRECT_URL", "http://localhost:3000/auth/callback")


    def __init__(self) -> None:
        """Validate required settings on initialization."""
        if not self.SUPABASE_URL or not self.SUPABASE_ANON_KEY:
            # Use default local Supabase if not set
            self.SUPABASE_URL = "http://127.0.0.1:54321"
            self.SUPABASE_ANON_KEY = "sb_publishable_ACJWlzQHlZjBrEguHvfOxg_3BJgxAaH"


# Global settings instance
settings = Settings()