"""Integration schemas for external services like WhatsApp."""
from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Dict, List, Optional, Any
from datetime import datetime
import uuid


class IntegrationConfig(BaseModel):
    """Schema for integration configuration key-value pairs."""
    model_config = ConfigDict(frozen=True)

    key: str = Field(..., description="Configuration key")
    value: str = Field(..., description="Configuration value")
    is_secret: bool = Field(False, description="Whether this config contains sensitive data")


class IntegrationCreate(BaseModel):
    """Schema for creating a new integration."""
    model_config = ConfigDict(extra='forbid')

    type: str = Field(..., description="Integration type (whatsapp, email, api, etc.)", min_length=1, max_length=50)
    name: str = Field(..., description="Human-readable name for the integration", min_length=1, max_length=100)
    kb_id: Optional[str] = Field(None, description="Linked knowledge base ID, null for org default")
    configs: Dict[str, str] = Field(default_factory=dict, description="Integration-specific configurations")

    @field_validator('type')
    @classmethod
    def validate_integration_type(cls, v: str) -> str:
        allowed_types = {'whatsapp', 'webchat', 'email', 'api'}
        if v not in allowed_types:
            raise ValueError(f'Integration type must be one of: {", ".join(allowed_types)}')
        return v


class IntegrationResponse(BaseModel):
    """Schema for integration response."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: str
    type: str
    name: str
    status: str
    kb_id: Optional[str]
    configs: List[IntegrationConfig]
    created_at: datetime
    updated_at: datetime


class IntegrationEvent(BaseModel):
    """Schema for integration events (webhooks, messages)."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    integration_id: str
    event_type: str
    payload: Dict[str, Any]
    status: str
    created_at: datetime


class WhatsAppWebhookPayload(BaseModel):
    """Schema for WhatsApp webhook payload from Evolution API."""
    model_config = ConfigDict(extra='allow')  # Allow additional fields from Evolution API

    instance: str = Field(..., description="Evolution API instance name")
    apikey: Optional[str] = Field(None, description="API key for the instance (may be null)")
    message: Optional[Dict[str, Any]] = Field(None, description="Message data if present")
    # Other fields like contact, chat, etc. can be added as needed

    @field_validator('instance')
    @classmethod
    def validate_instance_name(cls, v: str) -> str:
        if not v or len(v.strip()) == 0:
            raise ValueError('Instance name cannot be empty')
        return v.strip()


class WhatsAppMessageSend(BaseModel):
    """Schema for sending WhatsApp messages."""
    model_config = ConfigDict(extra='forbid')

    number: str = Field(..., description="Recipient phone number", pattern=r'^\+?\d{10,15}$')
    message: str = Field(..., description="Message text to send", min_length=1, max_length=4096)

    @field_validator('number')
    @classmethod
    def normalize_phone_number(cls, v: str) -> str:
        """Normalize phone number to international format."""
        # Remove all non-digit characters except +
        cleaned = ''.join(c for c in v if c.isdigit() or c == '+')

        # Ensure it starts with +
        if not cleaned.startswith('+'):
            # Assume country code if not provided (this is a simple example)
            if len(cleaned) == 10:  # US format
                cleaned = '+1' + cleaned
            else:
                cleaned = '+' + cleaned

        return cleaned