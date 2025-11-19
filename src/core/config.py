"""Application configuration settings."""
import os
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Settings:
    """Application settings loaded from environment variables."""

    # Supabase Configuration
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "http://127.0.0.1:54321")
    SUPABASE_ANON_KEY: str = os.getenv("SUPABASE_ANON_KEY", "sb_publishable_ACJWlzQHlZjBrEguHvfOxg_3BJgxAaH")

    # AI Configuration
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
    
    # Scraping Service Configuration (local service)
    SCRAPING_SERVICE_URL: str = os.getenv("SCRAPING_SERVICE_URL", "http://localhost:3001")
    SCRAPING_API_KEY: str = os.getenv("SCRAPING_API_KEY", "")

    # Email Configuration (for human handoff)
    SMTP_SERVER: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str = os.getenv("SMTP_USERNAME", "")
    SMTP_PASS: str = os.getenv("SMTP_PASSWORD", "")
    SUPPORT_EMAIL: str = os.getenv("SMTP_FROM_EMAIL", "support@company.com")

    # File Processing Configuration
    MAX_FILE_SIZE: int = int(os.getenv("MAX_FILE_SIZE", str(50 * 1024 * 1024)))  # 50MB default
    MAX_PARALLEL_TASKS: int = int(os.getenv("MAX_PARALLEL_TASKS", "10"))

    # Timeout Configuration
    AI_REQUEST_TIMEOUT: int = int(os.getenv("AI_REQUEST_TIMEOUT", "60"))  # 60 seconds
    AI_MAX_RETRIES: int = int(os.getenv("AI_MAX_RETRIES", "3"))
    SMTP_TIMEOUT: int = int(os.getenv("SMTP_TIMEOUT", "10"))
    WEB_SCRAPING_TIMEOUT: int = int(os.getenv("WEB_SCRAPING_TIMEOUT", "30"))

    # Query Processing Configuration
    MAX_MESSAGE_LENGTH: int = int(os.getenv("MAX_MESSAGE_LENGTH", "2000"))
    MAX_USER_ID_LENGTH: int = int(os.getenv("MAX_USER_ID_LENGTH", "100"))
    MAX_KB_ID_LENGTH: int = int(os.getenv("MAX_KB_ID_LENGTH", "50"))
    MAX_CONVERSATION_ID_LENGTH: int = int(os.getenv("MAX_CONVERSATION_ID_LENGTH", "50"))
    CACHE_TTL_SECONDS: int = int(os.getenv("CACHE_TTL_SECONDS", "300"))  # 5 minutes
    MAX_CONTEXT_LENGTH: int = int(os.getenv("MAX_CONTEXT_LENGTH", "8000"))  # ~2000 tokens
    SIMILARITY_THRESHOLD: float = float(os.getenv("SIMILARITY_THRESHOLD", "0.3"))
    MAX_SOURCES_COUNT: int = int(os.getenv("MAX_SOURCES_COUNT", "3"))
    MAX_TICKET_LENGTH: int = int(os.getenv("MAX_TICKET_LENGTH", "6"))

    # Scraping Service Configuration
    SCRAPING_SERVICE_URL: str = os.getenv("SCRAPING_SERVICE_URL", "http://localhost:3001")

    # Frontend Configuration
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:8081")

    # API Configuration
    API_BASE_URL: str = os.getenv("API_BASE_URL", "http://localhost:8000")


# Global settings instance
settings = Settings()